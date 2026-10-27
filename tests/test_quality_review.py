from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from reels_editor import caption_timing, quality_review as quality
from test_caption_timing import fixture


def passed():
    return {'checks':{key:{'verdict':'pass','evidence':'제공된 시간·원문·프레임을 확인함'}
                      for key in quality.CHECKS},'issues':[]}


def test_hook_timing_has_stricter_threshold_than_body():
    _,_,plan=fixture()
    actual={'words':deepcopy(plan['words']),'duration_s':4}
    actual['words'][0]['start']+=.26
    issues=quality.timing_diagnostics(plan,actual)
    assert issues[0]['kind']=='timing'
    assert '0.260' in issues[0]['evidence']
    for w in plan['words']: w['start']+=6;w['end']+=6
    actual={'words':deepcopy(plan['words']),'duration_s':10}
    # The initial-silence guard still flags an empty hook; the body drift itself
    # is within the looser 400ms threshold.
    actual['words'][0]['start']+=.26
    assert not any(i['kind']=='timing' for i in quality.timing_diagnostics(plan,actual))


@pytest.mark.parametrize('change',['missing_check','no_evidence','uncertain_without_issue','nan_time','unknown_kind'])
def test_opus_must_provide_complete_grounded_review(change):
    review=passed()
    if change=='missing_check': review['checks'].pop('hook_audio')
    if change=='no_evidence': review['checks']['hook_audio']['evidence']=''
    if change=='uncertain_without_issue': review['checks']['hook_audio']['verdict']='uncertain'
    if change in {'nan_time','unknown_kind'}:
        review['issues']=[dict(kind='unknown' if change=='unknown_kind' else 'timing',
            start_s=float('nan') if change=='nan_time' else 0,end_s=1,evidence='근거',correction='수정')]
    with pytest.raises(ValueError):quality.parse_review(json.dumps(review),4)


def setup_review(monkeypatch,tmp_path):
    doc,segments,plan=fixture();doc['caption_timing']=plan
    video=tmp_path/'final.mp4';video.write_bytes(b'exact final mp4')
    groups=caption_timing.plan_groups(plan,doc,segments,1)
    assets=SimpleNamespace(groups=groups,total_s=4)
    monkeypatch.setattr(quality,'extract_audio',lambda *_a,**_k:tmp_path/'final.wav')
    actual={'words':deepcopy(plan['words']),'duration_s':4}
    monkeypatch.setattr(quality,'transcribe_audio',lambda *_a,**_k:actual)
    monkeypatch.setattr(quality,'audio_metrics',lambda *_a,**_k:{
        'hook_rms_dbfs':-20,'hook_peak_dbfs':-5,'clipped_sample_ratio':0})
    monkeypatch.setattr(quality,'make_sheets',lambda *_a,**_k:([tmp_path/'sheet.jpg'],[.2,1,3]))
    monkeypatch.setattr(quality,'source_hook_sheet',lambda *_a,**_k:tmp_path/'source.jpg')
    monkeypatch.setattr(quality,'tail_audio_evidence',lambda *_a,**_k:None)
    monkeypatch.setattr(quality,'recheck_audio_evidence',lambda *_a,**_k:[])
    return video,doc,segments,assets,actual


def test_review_attaches_exact_mp4_hash_and_does_not_let_opus_override_measured_errors(monkeypatch,tmp_path):
    video,doc,segments,assets,actual=setup_review(monkeypatch,tmp_path)
    actual['words'][0]['start']+=.8
    def reviewer(prompt,images):
        assert 'final_audio' in prompt and 'hook_window_s' in prompt
        assert images==[tmp_path/'sheet.jpg',tmp_path/'source.jpg']
        return json.dumps(passed())
    result=quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',reviewer=reviewer)
    assert not result['passed']
    assert result['machine_issues'][0]['kind']=='timing'
    assert result['video_sha256']==caption_timing.file_hash(video)
    assert (tmp_path/'review/review.json').is_file()


def test_modified_mp4_cannot_inherit_an_old_review(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    def reviewer(*_args):
        video.write_bytes(b'different mp4')
        return json.dumps(passed())
    with pytest.raises(ValueError,match="video changed during review"):
        quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',reviewer=reviewer)


def test_review_includes_whole_question_beyond_one_adjacent_cue(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    reference={'segments':[
        dict(id='question',text='How did you build this community?',source_start_us=0,source_end_us=2_000_000),
        dict(id='continued',text='And what advice',source_start_us=2_000_000,source_end_us=8_000_000),
        dict(id='fragment',text='for founders?',source_start_us=8_000_000,source_end_us=10_000_000),
        *segments['segments']]}
    quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',
        reviewer=lambda *_a:json.dumps(passed()),reference_segments=reference)
    evidence=json.loads((tmp_path/'review/evidence.json').read_text())
    assert evidence['source_context'][0]['id']=='question'


def test_review_separates_bundle_handle_from_trim_inside_original_cue(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    segments['original_video_path']='/original.mp4'
    segments['segments'][0].update(original_source_start_us=100_000_000,
                                   original_source_end_us=104_000_000)
    doc['caption_timing']['signature'] = caption_timing.signature(doc, segments, 1)
    quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',
                                 reviewer=lambda *_a:json.dumps(passed()))
    evidence=json.loads((tmp_path/'review/evidence.json').read_text())
    row=evidence['source_to_reel_timeline'][0]
    assert row['source_coordinates']=='packed_bundle'
    assert row['source_start_s']==row['cue_source_start_s']==10
    assert row['trim_from_cue_start_s']==row['trim_from_cue_end_s']==0
    assert (row['original_video_start_s'],row['original_video_end_s'])==(100,104)


def test_renderer_cannot_silently_fall_back_to_old_char_based_timing(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    assets.groups[0][0]=0
    with pytest.raises(ValueError,match="Rendered captions"):
        quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review')


def test_codex_repair_cannot_invent_source_ids_or_change_speaker(tmp_path):
    doc,segments,_=fixture();doc['speaker']={'name':'원래 화자'}
    original=deepcopy(doc)
    bad={'cuts':[{'seg_ids':['invented']}],'subtitle_translations':doc['subtitle_translations']}
    with pytest.raises(ValueError,match="Automatic review repair failed"):
        quality.repair_document(doc,segments,runner=lambda _:json.dumps(bad),feedback={},speed=1,maximum_s=5,work=tmp_path)
    good={'cuts':doc['cuts'],'subtitle_translations':doc['subtitle_translations'],'speaker':{'name':'조작'}}
    result=quality.repair_document(doc,segments,runner=lambda _:json.dumps(good),feedback={},speed=1,maximum_s=5,work=tmp_path)
    assert result['speaker']==original['speaker']
    assert doc==original


def test_opus_receives_image_bytes_and_has_no_mutation_tools(monkeypatch,tmp_path):
    from reels_editor.llm import run_opus_review
    image=tmp_path/'sheet.jpg';image.write_bytes(b'actual screenshot')
    def run(args,**kwargs):
        assert args[args.index('--model')+1]=='opus'
        assert args[args.index('--tools')+1]==''
        assert '--strict-mcp-config' in args and '--no-session-persistence' in args
        content=json.loads(kwargs['input'])['message']['content']
        assert content[-1]['type']=='image'
        import base64
        assert base64.b64decode(content[-1]['source']['data'])==b'actual screenshot'
        return SimpleNamespace(returncode=0,stderr='',stdout=json.dumps({'type':'result','result':'{"checks":{}}'})+'\n')
    monkeypatch.setattr(quality.processes,'run',run)
    assert run_opus_review("Review",[image])=='{"checks":{}}'


def test_edge_trim_uses_only_measured_words_and_stays_inside_source_segment():
    doc,segments,plan=fixture();doc['caption_timing']=plan
    result=deepcopy(doc)
    feedback={'signature':plan['signature'],'audio_reference':{'words':plan['words']}}
    quality.apply_edge_trim(result,doc,segments,1,{'start_word':0,'end_word':3},feedback)
    from reels_editor.edl import ordered_segments
    ordered=ordered_segments(result,segments)
    assert ordered[0]['source_start_us']==10_120_000  # measured 200ms minus 80ms headroom
    assert ordered[0]['source_end_us']==13_550_000  # measured 3.4s plus 150ms tailroom
    assert result['source_trim_us']['s1']=={'start':120_000,'end':450_000}
    with pytest.raises(ValueError,match='timing evidence'):
        quality.apply_edge_trim(result,doc,segments,1,{'start_word':0,'end_word':3},{})


def test_unknown_crop_direction_or_source_boundary_is_rejected():
    from reels_editor.edl import validate_edl
    doc,segments,_=fixture()
    doc['focus_overrides']={'s1':'guess'}
    assert any('speaker-crop' in e for e in validate_edl(doc,segments))
    doc.pop('focus_overrides')
    doc['source_trim_us']={'s1':{'start':-100000,'end':0}}
    assert any('original segment' in e for e in validate_edl(doc,segments))


def test_edge_trim_can_use_old_audio_anchors_after_removing_earlier_cuts():
    doc, segments, plan = fixture()
    source = segments['segments'][0]
    segments['segments'] += [
        {**source, 'id': 's2', 'source_start_us': 30_000_000, 'source_end_us': 34_000_000},
        {**source, 'id': 's3', 'source_start_us': 50_000_000, 'source_end_us': 54_000_000}]
    doc['cuts'] = [{'seg_ids': ['s1', 's2', 's3']}]
    plan['signature'] = caption_timing.signature(doc, segments, 1)
    doc['caption_timing'] = plan
    result = deepcopy(doc)
    result['cuts'] = [{'seg_ids': ['s3']}]
    feedback = {'signature': plan['signature'], 'audio_reference': {
        'words': [{'word': 'third', 'start': 8.5, 'end': 9.5}]}}
    quality.apply_edge_trim(result, doc, segments, 1, {'start_word': 0, 'end_word': 0}, feedback)
    assert result['cuts'] == [{'seg_ids': ['s3']}]
    assert result['source_trim_us'] == {'s3': {'start': 420_000, 'end': 2_350_000}}
    for ids in [['s3', 's1'], ['unmeasured']]:
        result['cuts'] = [{'seg_ids': ids}]
        with pytest.raises(ValueError, match='Remove edge_trim'):
            quality.apply_edge_trim(result, doc, segments, 1, {'start_word': 0, 'end_word': 0}, feedback)


def test_partial_translation_repair_preserves_unmodified_subtitles(tmp_path):
    doc,segments,_=fixture()
    patch={'cuts':doc['cuts'],'subtitle_translations':{}}
    result=quality.repair_document(doc,segments,runner=lambda _:json.dumps(patch),
        feedback={},speed=1,maximum_s=5,work=tmp_path)
    assert result['subtitle_translations']==doc['subtitle_translations']


def test_later_translation_repair_keeps_previous_caption_layout_fix(tmp_path):
    doc,segments,_=fixture()
    doc['render_adjustments']={'sub_y_frac':.9,'sub_size':32}
    result=quality.repair_document(doc,segments,runner=lambda _:json.dumps({'cuts':doc['cuts']}),
        feedback={'issues':[{'kind':'translation'}]},speed=1,maximum_s=5,work=tmp_path)
    assert result['render_adjustments']==doc['render_adjustments']


def test_timing_verdict_can_repair_korean_clause_order(tmp_path):
    doc,segments,plan=fixture()
    segments['segments'][0]['text']='It was not surprising that we chose a fatherhood brand.'
    doc['subtitle_translations']['s1']='아빠들을 위한 브랜드를 택한 건 놀랍지 않았어요.'
    doc['caption_timing']=plan
    corrected='놀랍지 않았어요. 아빠들을 위한 브랜드를 택한 건요.'
    prompts=[]
    def repair(prompt):
        prompts.append(prompt)
        return json.dumps({'cuts':doc['cuts'],'subtitle_translations':{'s1':corrected}})
    result=quality.repair_document(doc,segments,runner=repair,
        feedback={'issues':[{'kind':'timing','start_s':0,'end_s':4,
            'evidence':'한국어 절 순서 때문에 뜻이 미리 나타남','correction':'발화 순서에 맞춰 번역 절을 재배치하라'}]},
        speed=1,maximum_s=None,work=tmp_path)
    assert len(prompts)==1 and '점진 번역' in prompts[0]
    assert result['cuts']==doc['cuts']
    assert result['subtitle_translations']['s1']==corrected
    assert 'caption_timing' not in result


def test_silent_hook_cannot_pass_even_if_opus_says_pass(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    monkeypatch.setattr(quality,'audio_metrics',lambda *_a:{
        'hook_rms_dbfs':-80,'hook_peak_dbfs':-60,'clipped_sample_ratio':0})
    result=quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',
        reviewer=lambda *_a:json.dumps(passed()))
    assert not result['passed']
    assert any(issue['kind']=='audio' for issue in result['machine_issues'])


def test_repair_without_duration_cap_keeps_complete_longer_source(tmp_path):
    doc, segments, _ = fixture()
    segments['segments'][0]['source_end_us'] = 90_000_000
    patch = {'cuts': doc['cuts']}
    result = quality.repair_document(doc, segments, runner=lambda _: json.dumps(patch),
        feedback={}, speed=1, maximum_s=None, work=tmp_path)
    assert result['cuts'] == doc['cuts']
    from reels_editor.edl import estimate_duration_s
    assert estimate_duration_s(result, segments, 1) > 50


def test_trim_uses_verified_audio_even_when_timing_plan_failed_validation():
    doc, segments, plan = fixture()
    doc['caption_timing'] = {'signature': 'stale-plan-before-the-cuts-changed'}
    result = deepcopy(doc)
    feedback = {'signature': caption_timing.signature(doc, segments, 1),
                'audio_reference': {'words': plan['words']}}
    quality.apply_edge_trim(result, doc, segments, 1,
                            {'start_word': 0, 'end_word': 3}, feedback)
    assert result['source_trim_us']['s1'] == {'start': 120_000, 'end': 450_000}
    with pytest.raises(ValueError, match='timing evidence'):
        quality.apply_edge_trim(deepcopy(doc), doc, segments, 1,
            {'start_word': 0, 'end_word': 3}, {**feedback, 'signature': 'different-audio'})


def test_audio_repair_can_restore_source_instead_of_trimming_more(tmp_path):
    doc, segments, _ = fixture()
    doc['source_trim_us'] = {'s1': {'start': 200_000, 'end': 300_000}}
    patch = {'cuts': doc['cuts'], 'restore_trim': ['start']}
    feedback = {'issues':[{'kind':'audio','evidence':'First syllable might be clipped'}]}
    result = quality.repair_document(doc, segments, runner=lambda _:json.dumps(patch),
        feedback=feedback, speed=1, maximum_s=None, work=tmp_path)
    assert result['source_trim_us'] == {'s1': {'start':0,'end':300_000}}
    assert doc['source_trim_us']['s1']['start'] == 200_000
    with pytest.raises(ValueError, match="review evidence"):
        quality.repair_document(doc, segments, runner=lambda _:json.dumps(patch),
            feedback={}, speed=1, maximum_s=None, work=tmp_path/'unsupported')


def test_repair_protects_actual_negative_phrase_and_rejects_invented_unit(tmp_path):
    doc, segments, _ = fixture()
    text = '저희 판단을 고집하지 않아요.'
    patch = {'cuts':doc['cuts'],'subtitle_translations':{'s1':text},'caption_keep_together':[text]}
    result = quality.repair_document(doc, segments, runner=lambda _:json.dumps(patch),
        feedback={'issues':[{'kind':'translation'}]}, speed=1, maximum_s=None, work=tmp_path)
    assert result['caption_keep_together'] == [text]
    patch['caption_keep_together'] = ['원문에 없는 부정입니다.']
    with pytest.raises(ValueError, match="actual translation"):
        quality.repair_document(doc, segments, runner=lambda _:json.dumps(patch),
            feedback={}, speed=1, maximum_s=None, work=tmp_path/'invalid')


def test_boundary_probe_compares_uncut_source_word_and_measured_quiet_gap(monkeypatch,tmp_path):
    import wave
    audio = tmp_path/'source.wav'
    with wave.open(str(audio),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000*3*2)
    monkeypatch.setattr(quality,'extract_audio',lambda *_a,**_k:audio)
    source_words=[{'word':'thinking.','start':.1,'end':.8,'probability':.99},
                  {'word':'Hats','start':1.45,'end':1.8,'probability':.998}]
    monkeypatch.setattr(quality,'transcribe_audio',lambda *_a,**_k:{'audio_sha256':'source-hash','words':source_words})
    doc,segments,_=fixture();segments['video_path']=str(audio)
    doc['source_trim_us']={'s1':{'start':1_000_000}}
    actual={'words':[{'word':'hats','start':0,'end':.4,'probability':.485}]}
    result=quality.boundary_audio_evidence(audio,doc,segments,1,actual,tmp_path/'probe')
    assert result['cut_between_measured_words']
    assert result['first_retained_source_word']['probability']==.998
    assert all(b['rms_dbfs'] < -100 for b in result['source_waveform_20ms_bins'])


@pytest.mark.parametrize('trim,between',[(1_000_000,True),(500_000,False)])
def test_ending_probe_uses_original_speed_and_exposes_next_sentence(monkeypatch,tmp_path,trim,between):
    import wave
    audio=tmp_path/'source.wav'
    with wave.open(str(audio),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000*4*2)
    def extract(_video,_out,*,doc,segments,speed):
        assert speed==1
        assert segments['segments'][0]['source_start_us']==10_000_000
        return audio
    monkeypatch.setattr(quality,'extract_audio',extract)
    source_words=[{'word':'thing.','start':2.6,'end':2.9,'probability':.99},
                  {'word':'We','start':3.2,'end':3.7,'probability':.99}]
    monkeypatch.setattr(quality,'transcribe_audio',lambda *_a,**_k:{'audio_sha256':'source-hash','words':source_words})
    doc,segments,_=fixture();doc['source_trim_us']={'s1':{'end':trim}}
    result=quality.ending_audio_evidence(audio,doc,segments,
        {'words':[{'word':'thing.','start':0,'end':.2,'probability':.99}]},tmp_path/'probe')
    assert result['cut_between_measured_words']==between
    assert result['following_source_word']['word']=='We'
    assert result['source_context_speed']==1


def test_tail_probe_uses_actual_final_samples_and_reports_absolute_times(monkeypatch,tmp_path):
    import wave
    audio=tmp_path/'final.wav'
    with wave.open(str(audio),'wb') as w:
        w.setnchannels(1);w.setsampwidth(2);w.setframerate(16000);w.writeframes(b'\0'*16000*10*2)
    def transcribe(tail,language,work):
        with wave.open(str(tail)) as w:assert w.getnframes()==8*16000
        return {'words':[{'word':'We','start':7.7,'end':7.9}], 'audio_sha256':'tail'}
    monkeypatch.setattr(quality,'transcribe_audio',transcribe)
    result=quality.tail_audio_evidence(audio,'en',tmp_path/'probe')
    assert result['words'][0]['start']==9.7
    assert result['timeline_offset_s']==2
    assert result['parent_audio_sha256']==caption_timing.file_hash(audio)


def test_edge_padding_cannot_keep_next_phrase_only_detected_in_final_tail():
    doc,segments,plan=fixture();doc['caption_timing']=plan
    actual={'words':deepcopy(plan['words'])}
    tail=deepcopy(actual)
    tail['words'].append({'word':'We','start':3.44,'end':3.6,'probability':.99})
    feedback={'signature':caption_timing.signature(doc,segments,1),
              'audio_reference':actual,'audio_tail_reference':tail}
    result=deepcopy(doc)
    quality.apply_edge_trim(result,doc,segments,1,{'start_word':0,'end_word':3},feedback)
    assert result['source_trim_us']['s1']['end']==580_000


def test_repair_can_shorten_measured_end_padding_and_apply_bounded_fade(tmp_path):
    doc,segments,plan=fixture()
    feedback={'signature':caption_timing.signature(doc,segments,1),
              'audio_reference':{'words':plan['words']},'issues':[{'kind':'cut'}]}
    patch={'cuts':doc['cuts'],'edge_trim':{'start_word':0,'end_word':3,'end_pad_s':.02},
           'audio_fade_out_s':.04}
    result=quality.repair_document(doc,segments,runner=lambda _:json.dumps(patch),
        feedback=feedback,speed=1,maximum_s=None,work=tmp_path)
    assert result['source_trim_us']['s1']['end']==580_000
    assert result['audio_fade_out_s']==.04
    patch['audio_fade_out_s']=.5
    with pytest.raises(ValueError,match="at most 0.06 seconds"):
        quality.repair_document(doc,segments,runner=lambda _:json.dumps(patch),
            feedback=feedback,speed=1,maximum_s=None,work=tmp_path/'invalid')


def measured_reference():
    words=[dict(word=w,start=a,end=b,probability=.99) for w,a,b in
           [('we',0,.2),('talk',.2,.4),('every',1.2,1.5),('day',1.5,1.8)]]
    full={'audio_sha256':'same-final-audio','duration_s':2,'words':words}
    supplement={'audio_sha256':'actual-chunk','parent_audio_sha256':'same-final-audio',
        'timeline_offset_s':0,'duration_s':2,'words':words[:2]+[
            dict(word='to',start=.4,end=.7,probability=.99),
            dict(word='dads',start=.7,end=1,probability=.99)]+words[2:],
        'waveform_20ms_bins':[{'start_s':at,'rms_dbfs':-20} for at in [.4,.5,.7,.9]]}
    return full,supplement


def test_missing_boundary_words_are_recovered_from_same_final_samples():
    full,supplement=measured_reference()
    result=quality.recover_measured_words(full,[supplement])
    assert [w['word'] for w in result['words']]==['we','talk','to','dads','every','day']
    assert len(full['words'])==4
    plan={'words':supplement['words'],'captions':[{'text':'아빠들과 대화해요.','start_word':0,'end_word':3},
                                                {'text':'매일요.','start_word':4,'end_word':5}]}
    assert quality.timing_diagnostics(plan,full)
    assert quality.timing_diagnostics(plan,result)==[]
    assert result['supplemental_word_sources'][0]['audio_sha256']=='actual-chunk'


@pytest.mark.parametrize('problem',['different_audio','uncertain_word','silence','unaligned'])
def test_word_recovery_requires_actual_audio_confidence_voice_and_time_anchors(problem):
    full,supplement=measured_reference();supplement=deepcopy(supplement)
    if problem=='different_audio':supplement['parent_audio_sha256']='different'
    if problem=='uncertain_word':supplement['words'][2]['probability']=.3
    if problem=='silence':supplement['waveform_20ms_bins']=[]
    if problem=='unaligned':
        for w in supplement['words']:w['start']+=.5;w['end']+=.5
    result=quality.recover_measured_words(full,[supplement])
    assert result['words']==full['words']


def test_second_pass_cannot_remove_a_real_following_phrase():
    full,supplement=measured_reference()
    full['words'].append(dict(word='Next',start=1.8,end=2,probability=.99))
    result=quality.recover_measured_words(full,[supplement])
    assert result['words'][-1]['word']=='Next'


@pytest.fixture(autouse=True)
def isolate_optional_effect_tests(monkeypatch):
    from reels_editor import hook_effects
    monkeypatch.setattr(hook_effects, "DEFAULT_SOUND", None)
