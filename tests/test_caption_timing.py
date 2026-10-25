from copy import deepcopy
import json
from pathlib import Path

import pytest

from reels_editor import caption_timing as timing, render


def fixture():
    segments = {'transcript_language': 'en', 'segments': [
        {'id':'s1', 'text':'Customers want better products.', 'source_start_us':10_000_000, 'source_end_us':14_000_000}]}
    doc = {'cuts':[{'seg_ids':['s1']}], 'subtitle_translations':{'s1':'고객은 더 나은 제품을 원합니다.'}}
    words = [dict(word=w, start=a, end=b, probability=.99) for w,a,b in [
        ('Customers',.2,1),('want',1,1.5),('better',1.8,2.4),('products.',2.4,3.4)]]
    plan = {'version':1,'signature':timing.signature(doc,segments,1), 'words':words,
            'captions':[{'text':'고객은 더 나은','start_word':0,'end_word':2},
                        {'text':'제품을 원합니다.','start_word':3,'end_word':3}]}
    return doc, segments, plan


def test_captions_use_measured_words_and_do_not_allocate_time_by_character_count():
    doc, segments, plan = fixture()
    groups = timing.plan_groups(plan, doc, segments, 1)
    assert groups == [[.2,2.4,'고객은 더 나은'],[2.4,3.4,'제품을 원합니다.']]
    doc['caption_timing'] = plan
    assert render.caption_groups(doc,segments,1) == [[.2,2.4,'고객은 더 나은'],[2.4,3.4,'제품을 원합니다']]


@pytest.mark.parametrize('mutation', ['word_gap','duplicate','fabricate','omit','stale','too_fast','nan'])
def test_rejects_unverified_or_stale_timing(mutation):
    doc, segments, plan = fixture()
    if mutation == 'word_gap': plan['captions'][1]['start_word'] = 4
    if mutation == 'duplicate': plan['captions'][1]['start_word'] = 2
    if mutation == 'fabricate': plan['captions'][1]['text'] = '없는 말을 추가합니다.'
    if mutation == 'omit': plan['captions'].pop()
    if mutation == 'stale': doc['subtitle_translations']['s1'] = '다른 번역입니다.'
    if mutation == 'too_fast': plan['words'][-1]['end'] = 2.5
    if mutation == 'nan': plan['words'][0]['start'] = float('nan')
    with pytest.raises(ValueError): timing.plan_groups(plan, doc, segments, 1)


def test_real_audio_filter_uses_edl_order_speed_and_local_source_time(monkeypatch,tmp_path):
    doc,segments,_ = fixture()
    calls=[]
    monkeypatch.setattr(timing,'_run_ffmpeg',lambda args:calls.append(args))
    timing.extract_audio(tmp_path/'source.mp4',tmp_path/'audio.wav',doc=doc,segments=segments,speed=1.2)
    graph=calls[0][calls[0].index('-filter_complex')+1]
    assert 'atrim=10.0:14.0,asetpts=PTS-STARTPTS,atempo=1.2' in graph
    assert 'concat=n=1:v=0:a=1' in graph


def test_timing_validation_feeds_back_and_keeps_original_translation(monkeypatch,tmp_path):
    doc,segments,plan=fixture()
    original=deepcopy(doc)
    monkeypatch.setattr(timing,'extract_audio',lambda *_a,**_k:tmp_path/'audio.wav')
    monkeypatch.setattr(timing,'transcribe_audio',lambda *_a,**_k:{'words':plan['words'],'audio_sha256':'audio'})
    prompts=[]
    def runner(prompt):
        prompts.append(prompt)
        return json.dumps({'captions': [] if len(prompts)==1 else plan['captions']})
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path,runner=runner)
    assert '이전 계획 오류' in prompts[1]
    assert doc==original
    assert result['subtitle_translations']==doc['subtitle_translations']
    assert timing.plan_groups(result['caption_timing'],result,segments,1)[0][0]==.2


def test_srt_and_renderer_share_the_same_measured_groups(tmp_path):
    from reels_editor.export import write_srt
    doc,segments,plan=fixture();doc['caption_timing']=plan
    groups=render.caption_groups(doc,segments,1)
    text=write_srt(groups,tmp_path/'reel.srt').read_text()
    assert '00:00:00,200 --> 00:00:02,400' in text
    assert '00:00:02,400 --> 00:00:03,400' in text


def test_timing_repair_uses_the_actual_final_audio_when_edl_is_unchanged(monkeypatch,tmp_path):
    doc,segments,plan=fixture()
    monkeypatch.setattr(timing,'extract_audio',lambda *_a,**_k:pytest.fail('must reuse final audio anchors'))
    actual=deepcopy(plan['words']);actual[0]['start']=.3
    feedback={'signature':timing.signature(doc,segments,1),
              'audio_reference':{'words':actual,'audio_sha256':'final-audio'}}
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path,
        runner=lambda _:json.dumps({'captions':plan['captions']}),feedback=feedback)
    assert result['caption_timing']['words'][0]['start']==.3
    assert result['caption_timing']['audio_sha256']=='final-audio'


def test_zero_duration_asr_token_is_preserved_as_point_without_inventing_duration():
    words=[{'word':'So','start':.4,'end':.4,'probability':.97},
           {'word':'build','start':.6,'end':1.2,'probability':.99}]
    clean=timing.validate_words({'words':words},2)
    assert clean[0]['start']==clean[0]['end']==.4
    assert clean[0]['timing_kind']=='point'
    assert clean[1]['timing_kind']=='interval'
    with pytest.raises(ValueError,match='유효한 단어 시간'):
        timing.validate_words({'words':words[:1]},2)
