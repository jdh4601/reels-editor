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
    plan = {'version':timing.VERSION,'signature':timing.signature(doc,segments,1), 'words':words,
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
    assert 'atrim=10.0:14.0,asetpts=PTS-STARTPTS[rawa0]' in graph
    assert 'concat=n=1:v=0:a=1,atempo=1.2' in graph


@pytest.mark.parametrize('fade',[0,.04])
def test_render_audio_matches_timing_audio_despite_video_focus_splits(tmp_path,fade):
    import wave
    from array import array
    from dataclasses import replace
    from reels_editor.speaker_focus import FocusPoint, FocusSlice
    from reels_editor.style import load_style
    from reels_editor import edl
    source=tmp_path/'source.mkv'
    render._ffmpeg(['-f','lavfi','-i','testsrc2=s=320x180:r=24:d=2.095',
        '-f','lavfi','-i','sine=frequency=900:sample_rate=48000:duration=2.095',
        '-c:v','libx264','-c:a','pcm_s16le',str(source)])
    segments={'segments':[{'id':'a','text':'a','source_start_us':0,'source_end_us':2_000_000},
                          {'id':'b','text':'b','source_start_us':2_000_000,'source_end_us':2_095_000}]}
    doc={'cuts':[{'seg_ids':['a','b']}],'audio_fade_out_s':fade}
    reference=timing.extract_audio(source,tmp_path/'timing.wav',doc=doc,segments=segments,speed=1.15)
    style=replace(load_style(Path(__file__).resolve().parents[1]/'reels_editor/resources/styles/default.yaml'),
                  canvas=(320,568),top_bar=44,bottom_bar=44)
    slices=[FocusSlice(0,0,.7,FocusPoint()),FocusSlice(0,.7,2,FocusPoint(x=0)),
            FocusSlice(1,2,2.095,FocusPoint(x=1))]
    graph=render.build_base_filter(edl.ordered_segments(doc,segments),
        1.15,style,(320,180),focus_slices=slices,audio_fade_out_s=fade)
    graph+='[a]loudnorm=I=-14:TP=-1.5:LRA=11[aout]'
    output=tmp_path/'render.mkv'
    render._ffmpeg(['-i',str(source),'-filter_complex',graph,'-map','[v]','-map','[aout]',
        '-c:v','libx264','-c:a','pcm_s16le','-ac','1','-ar','16000',str(output)])
    actual=timing.extract_audio(output,tmp_path/'final.wav')
    def samples(path):
        with wave.open(str(path)) as w:return array('h',w.readframes(w.getnframes()))
    expected,observed=samples(reference),samples(actual)
    assert len(observed)==len(expected)
    assert max(abs(a-b) for a,b in zip(expected,observed)) <= 1
    assert any(abs(x)>500 for x in observed[-800:])


def test_previous_audio_recipe_cannot_reuse_a_timing_plan():
    doc,segments,plan=fixture()
    plan['version']=timing.VERSION-1
    with pytest.raises(ValueError,match="earlier script"):
        timing.plan_groups(plan,doc,segments,1)


def test_translation_only_repair_retains_measured_final_audio(monkeypatch,tmp_path):
    doc,segments,plan=fixture()
    feedback={'signature':timing.signature(doc,segments,1),
              'audio_signature':timing.audio_signature(doc,segments,1),
              'audio_reference':{'words':plan['words'],'audio_sha256':'actual-final'}}
    doc['subtitle_translations']['s1']='먼저 고객에게 필요한 제품을 만드세요.'
    assert feedback['signature'] != timing.signature(doc,segments,1)
    assert feedback['audio_signature'] == timing.audio_signature(doc,segments,1)
    monkeypatch.setattr(timing,'extract_audio',lambda *_a,**_k:pytest.fail('translation did not change audio'))
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path,
        runner=lambda _:json.dumps({'captions':[{'text':doc['subtitle_translations']['s1'],
                                                'start_word':0,'end_word':3}]}),feedback=feedback)
    assert result['caption_timing']['audio_sha256']=='actual-final'
    doc['source_trim_us']={'s1':{'start':100000}}
    assert feedback['audio_signature'] != timing.audio_signature(doc,segments,1)


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
    with pytest.raises(ValueError,match="valid word-time"):
        timing.validate_words({'words':words[:1]},2)


def test_short_acknowledgement_can_share_a_readable_caption_with_a_complete_sentence():
    doc, segments, plan = fixture()
    doc['subtitle_translations']['s1'] = '네. 먼저 고객층을 만드세요.'
    plan['signature'] = timing.signature(doc, segments, 1)
    plan['captions'] = [{'text': '네. 먼저 고객층을 만드세요.', 'start_word': 0, 'end_word': 3}]
    assert timing.plan_groups(plan, doc, segments, 1) == [[.2, 3.4, '네. 먼저 고객층을 만드세요.']]
    plan['captions'] = [{'text': '네.', 'start_word': 0, 'end_word': 0},
                        {'text': '먼저 고객층을 만드세요.', 'start_word': 1, 'end_word': 3}]
    plan['words'][0]['end'] = .4
    with pytest.raises(ValueError, match="displayed for 0.20 seconds"):
        timing.plan_groups(plan, doc, segments, 1)


def test_combining_sentence_tail_and_next_incomplete_clause_is_still_rejected():
    doc, segments, plan = fixture()
    text = '고객은 제품을 원합니다. 다음 주제는'
    doc['subtitle_translations']['s1'] = text
    plan['signature'] = timing.signature(doc, segments, 1)
    plan['captions'] = [{'text': text, 'start_word': 0, 'end_word': 3}]
    with pytest.raises(ValueError, match="end of one sentence with the start of another"):
        timing.plan_groups(plan, doc, segments, 1)


def test_audio_identity_survives_downloaded_bundle_coordinate_remapping():
    doc, segments, _ = fixture()
    bundle = deepcopy(segments)
    row = bundle['segments'][0]
    row.update(original_source_start_us=row['source_start_us'],
               original_source_end_us=row['source_end_us'],
               source_start_us=250_000, source_end_us=4_250_000)
    assert timing.signature(doc, bundle, 1) == timing.signature(doc, segments, 1)
    doc['source_trim_us'] = {'s1': {'start': 100_000, 'end': 200_000}}
    assert timing.signature(doc, bundle, 1) == timing.signature(doc, segments, 1)
    assert timing.signature(doc, bundle, 1.2) != timing.signature(doc, segments, 1)


def test_negation_meaning_unit_cannot_be_split_across_screens():
    doc, segments, plan = fixture()
    text = '저희 판단을 고집하지 않아요.'
    doc['subtitle_translations']['s1'] = text
    doc['caption_keep_together'] = [text]
    plan['signature'] = timing.signature(doc, segments, 1)
    plan['captions'] = [{'text':'저희 판단을','start_word':0,'end_word':1},
                        {'text':'고집하지 않아요.','start_word':2,'end_word':3}]
    with pytest.raises(ValueError, match="protected meaning units"):
        timing.plan_groups(plan, doc, segments, 1)
    plan['captions'] = [{'text':text,'start_word':0,'end_word':3}]
    assert timing.plan_groups(plan, doc, segments, 1) == [[.2,3.4,text]]


def test_valid_saved_timing_is_reused_only_without_new_feedback(monkeypatch,tmp_path):
    doc,segments,plan=fixture();doc['caption_timing']=plan
    monkeypatch.setattr(timing,'extract_audio',lambda *_a,**_k:pytest.fail('valid timing should be retained'))
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path,
        runner=lambda _:pytest.fail('do not regenerate an unchanged approved timing plan'))
    assert result==doc and result is not doc
    actual=deepcopy(plan['words']);actual[0]['start']=.3
    feedback={'signature':timing.signature(doc,segments,1),
        'audio_reference':{'words':actual,'audio_sha256':'actual-final-audio'}}
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path/'new',
        runner=lambda _:json.dumps({'captions':plan['captions']}),feedback=feedback)
    assert result['caption_timing']['words'][0]['start']==.3


def test_saved_timing_still_prepares_required_hook_effect(monkeypatch,tmp_path):
    from reels_editor import hook_effects
    doc,segments,plan=fixture();doc['caption_timing']=plan
    monkeypatch.setattr(timing,'extract_audio',lambda *_a,**_k:pytest.fail('reuse measured timing'))
    calls=[]
    def prepare(result,source,speed,work,**kwargs):
        calls.append((source,speed,work))
        result['hook_effect']={'prepared':True}
        return result
    monkeypatch.setattr(hook_effects,'prepare',prepare)
    result=timing.prepare_caption_timing(tmp_path/'source.mp4',doc,segments,1,tmp_path,runner=None)
    assert result['hook_effect']=={'prepared':True}
    assert calls==[(segments,1,tmp_path/'hook')]
    assert 'hook_effect' not in doc


@pytest.fixture(autouse=True)
def isolate_optional_effect_tests(monkeypatch):
    from reels_editor import hook_effects
    monkeypatch.setattr(hook_effects, "DEFAULT_SOUND", None)
