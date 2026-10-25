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
    return video,doc,segments,assets,actual


def test_review_attaches_exact_mp4_hash_and_does_not_let_opus_override_measured_errors(monkeypatch,tmp_path):
    video,doc,segments,assets,actual=setup_review(monkeypatch,tmp_path)
    actual['words'][0]['start']+=.3
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
    with pytest.raises(ValueError,match='검수 중 영상'):
        quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',reviewer=reviewer)


def test_review_separates_bundle_handle_from_trim_inside_original_cue(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    segments['original_video_path']='/original.mp4'
    segments['segments'][0].update(original_source_start_us=100_000_000,
                                   original_source_end_us=104_000_000)
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
    with pytest.raises(ValueError,match='렌더 자막'):
        quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review')


def test_codex_repair_cannot_invent_source_ids_or_change_speaker(tmp_path):
    doc,segments,_=fixture();doc['speaker']={'name':'원래 화자'}
    original=deepcopy(doc)
    bad={'cuts':[{'seg_ids':['invented']}],'subtitle_translations':doc['subtitle_translations']}
    with pytest.raises(ValueError,match='자동 수정 실패'):
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
    assert run_opus_review('검수',[image])=='{"checks":{}}'


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
    with pytest.raises(ValueError,match='시간 근거'):
        quality.apply_edge_trim(result,doc,segments,1,{'start_word':0,'end_word':3},{})


def test_unknown_crop_direction_or_source_boundary_is_rejected():
    from reels_editor.edl import validate_edl
    doc,segments,_=fixture()
    doc['focus_overrides']={'s1':'guess'}
    assert any('크롭' in e for e in validate_edl(doc,segments))
    doc.pop('focus_overrides')
    doc['source_trim_us']={'s1':{'start':-100000,'end':0}}
    assert any('원문 구간' in e for e in validate_edl(doc,segments))


def test_edge_trim_can_use_old_audio_anchors_after_removing_earlier_cuts():
    doc, segments, plan = fixture()
    source = segments['segments'][0]
    segments['segments'] += [
        {**source, 'id': 's2', 'source_start_us': 30_000_000, 'source_end_us': 34_000_000},
        {**source, 'id': 's3', 'source_start_us': 50_000_000, 'source_end_us': 54_000_000}]
    doc['cuts'] = [{'seg_ids': ['s1', 's2', 's3']}]
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
        with pytest.raises(ValueError, match='edge_trim 키를 삭제'):
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


def test_silent_hook_cannot_pass_even_if_opus_says_pass(monkeypatch,tmp_path):
    video,doc,segments,assets,_=setup_review(monkeypatch,tmp_path)
    monkeypatch.setattr(quality,'audio_metrics',lambda *_a:{
        'hook_rms_dbfs':-80,'hook_peak_dbfs':-60,'clipped_sample_ratio':0})
    result=quality.review_render_output(video,doc,segments,assets,1,'제목',tmp_path/'review',
        reviewer=lambda *_a:json.dumps(passed()))
    assert not result['passed']
    assert any(issue['kind']=='audio' for issue in result['machine_issues'])
