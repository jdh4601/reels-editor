"""Cost controls must not waive material defects or approve stale video bytes."""
from copy import deepcopy
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from reels_editor import caption_timing, hook_effects, processes, quality_review
from reels_editor.review_policy import compact_evidence
from test_quality_review import setup_review as base_setup_review, passed


def setup_review(monkeypatch, tmp_path):
    monkeypatch.setattr(hook_effects, "DEFAULT_SOUND", None)
    return base_setup_review(monkeypatch, tmp_path)


def test_minor_findings_finish_without_repair_but_keep_original_observations(monkeypatch, tmp_path):
    video, doc, segments, assets, _ = setup_review(monkeypatch, tmp_path)
    review = passed()
    review['checks']['framing'] = {'verdict': 'fail', 'evidence': 'ear edge slightly cropped'}
    review['issues'] = [dict(kind='layout', severity='minor', start_s=0, end_s=1,
                            evidence='ear edge slightly cropped', correction='optional crop')]
    result = quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'review',
                                                reviewer=lambda *_: json.dumps(review))
    assert result['passed'] is True and result['issues'] == []
    assert result['warnings'][0]['severity'] == 'minor'
    assert result['advisory_checks']['framing']['verdict'] == 'fail'
    quality_review.require_approved_video(video, result, effect_required=False)
    video.write_bytes(b'changed bytes')
    with pytest.raises(ValueError, match='Video bytes differ'):
        quality_review.require_approved_video(video, result, effect_required=False)


def test_major_translation_error_still_blocks_even_with_minor_warnings(monkeypatch, tmp_path):
    video, doc, segments, assets, _ = setup_review(monkeypatch, tmp_path)
    review = passed()
    review['issues'] = [dict(kind='translation', severity='major', start_s=0, end_s=1,
                            evidence='negative translated as positive', correction='restore negation')]
    result = quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'review',
                                                reviewer=lambda *_: json.dumps(review))
    assert result['passed'] is False and result['issues'][0]['severity'] == 'major'


def test_small_measured_drift_warns_while_silent_audio_still_blocks(monkeypatch, tmp_path):
    video, doc, segments, assets, actual = setup_review(monkeypatch, tmp_path)
    actual['words'][0]['start'] += .3
    result = quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'review',
                                                reviewer=lambda *_: json.dumps(passed()))
    assert result['passed'] is True and result['warnings'][0]['kind'] == 'timing'
    monkeypatch.setattr(quality_review, 'audio_metrics', lambda *_: {
        'hook_rms_dbfs': -80, 'hook_peak_dbfs': -60, 'clipped_sample_ratio': 0})
    result = quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'silent',
                                                reviewer=lambda *_: json.dumps(passed()))
    assert result['passed'] is False


def test_malformed_expensive_review_is_not_sent_twice(monkeypatch, tmp_path):
    video, doc, segments, assets, _ = setup_review(monkeypatch, tmp_path)
    calls = []
    def malformed(*_):
        calls.append(1)
        return '{}'
    with pytest.raises(RuntimeError, match='response validation'):
        quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'review', reviewer=malformed)
    assert len(calls) == 1


def test_compaction_removes_duplicate_words_but_preserves_original_evidence():
    words = [{'word': str(i), 'start': i/10, 'end': (i+1)/10, 'probability': .9} for i in range(200)]
    evidence = {'doc': {'cuts': [{'seg_ids': ['s1']}], 'caption_timing': {'words': words}},
                'final_audio': {'words': words}, 'final_audio_full_pass': {'words': words},
                'rendered_captions': [[0, 20, 'complete translated meaning']],
                'source_context': [{'id': 's1', 'text': 'complete source meaning', 'source_start_us': 0, 'source_end_us': 20000000}],
                'audio_signal_metrics': {'bins': [{'start_s': i/50, 'rms_dbfs': -i} for i in range(100)]}}
    original = deepcopy(evidence)
    compact = compact_evidence(evidence)
    assert evidence == original
    assert len(json.dumps(compact)) < len(json.dumps(evidence)) / 2
    assert compact['final_audio']['words'] == words
    assert compact['source_context'][0]['text'] == 'complete source meaning'
    assert compact['rendered_captions'] == evidence['rendered_captions']


def test_frame_budget_keeps_opening_body_and_last_frame():
    times = [i/10 for i in range(800)]
    sampled = quality_review.sample_review_times(times, 80)
    assert len(sampled) <= 16 and sampled == sorted(set(sampled))
    assert sampled[0] == 0 and sampled[-1] == 79.9
    assert sum(t < 5 for t in sampled) == 8
    assert any(35 < t < 50 for t in sampled)
    assert len(quality_review.sample_review_times([i/100 for i in range(40)], 1)) <= 16


@pytest.mark.parametrize('response', [
    subprocess.CompletedProcess(['claude'], 1, "You've hit your session limit · resets 4:10am", ''),
    subprocess.CompletedProcess(['claude'], 0, json.dumps({'type': 'result', 'is_error': True,
        'result': "You've hit your session limit"}), ''),
    subprocess.CompletedProcess(['codex'], 1, '', 'ERROR: 429 Too Many Requests'),
])
def test_limit_blocks_queued_other_clips_and_other_providers(monkeypatch, response):
    registry = processes.ProcessRegistry()
    entered, release = Event(), Event()
    calls = []
    def fake_run(args, **_):
        calls.append(args)
        entered.set()
        assert release.wait(3)
        return response
    monkeypatch.setattr(processes, '_run', fake_run)
    def request(provider):
        with processes.use_process_registry(registry):
            with pytest.raises(processes.AIUsageLimitError, match='남은 AI 호출'):
                processes.run([provider, '-p'], text=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(request, 'claude')
        assert entered.wait(3)
        queued = pool.submit(request, 'codex')
        release.set()
        first.result(timeout=3)
        queued.result(timeout=3)
    assert len(calls) == 1
    # Rendering and file checks are still allowed; this is not cancellation.
    assert not registry.cancelled


def test_successful_source_mentioning_quota_does_not_trip_circuit(monkeypatch):
    registry = processes.ProcessRegistry()
    monkeypatch.setattr(processes, '_run', lambda *_, **__: subprocess.CompletedProcess(
        ['claude'], 0, 'The speaker says 429 and quota exceeded.', ''))
    with processes.use_process_registry(registry):
        processes.run(['claude', '-p'])
        processes.run(['codex', 'exec'])


def test_layout_repair_reuses_valid_timing_and_hook(monkeypatch, tmp_path):
    from test_hook_effects import prepared
    doc, segments = prepared(monkeypatch, tmp_path/'plan')
    calls = []
    def no_new_call(prompt):
        calls.append(prompt)
        raise AssertionError('unchanged timing and hook must be reused')
    feedback = {'issues': [{'kind': 'layout', 'evidence': 'caption placement'}]}
    result = caption_timing.prepare_caption_timing(tmp_path/'video.mp4', doc, segments, 1,
        tmp_path/'timing', runner=no_new_call, feedback=feedback)
    assert result['caption_timing'] == doc['caption_timing']
    assert result['hook_effect'] == doc['hook_effect'] and calls == []


def test_minor_crop_cannot_waive_unexplained_failed_translation_check():
    from reels_editor.review_policy import prioritize_review
    review = passed()
    review['checks']['translation']['verdict'] = 'fail'
    review['issues'] = [dict(kind='layout', severity='minor')]
    result = prioritize_review(review)
    assert result['checks']['translation']['verdict'] == 'fail'


def test_timing_invalid_plan_gets_only_one_retry(monkeypatch, tmp_path):
    from test_caption_timing import fixture
    doc, segments, plan = fixture()
    calls = []
    monkeypatch.setattr(hook_effects, 'DEFAULT_SOUND', None)
    monkeypatch.setattr(caption_timing, 'extract_audio', lambda *_, **__: tmp_path/'audio.wav')
    monkeypatch.setattr(caption_timing, 'transcribe_audio', lambda *_, **__: {
        'words': plan['words'], 'audio_sha256': 'hash', 'duration_s': 4})
    def malformed(_):
        calls.append(1)
        return '{"captions": []}'
    with pytest.raises(caption_timing.CaptionTimingError):
        caption_timing.prepare_caption_timing(tmp_path/'video.mp4', doc, segments, 1,
            tmp_path/'timing', runner=malformed)
    assert len(calls) == 2


def test_repair_keeps_valid_timing_when_only_layout_changed(tmp_path):
    from test_caption_timing import fixture
    doc, segments, plan = fixture()
    doc['caption_timing'] = plan
    result = quality_review.repair_document(doc, segments, speed=1, maximum_s=None,
        work=tmp_path, feedback={'issues': [{'kind': 'layout', 'evidence': 'caption overlaps face'}]},
        runner=lambda _: json.dumps({'cuts': doc['cuts'], 'render_adjustments': {'sub_y_frac': .9}}))
    assert result['caption_timing'] == plan
    assert result['render_adjustments']['sub_y_frac'] == .9


def test_echoed_source_cannot_trip_limit_when_actual_error_is_authentication():
    response = subprocess.CompletedProcess(['codex'], 1, 'user\nWe discuss 429 errors and quota exceeded.',
        'user\nWe discuss quota exceeded.\nERROR: authentication failed')
    assert processes._limit_diagnostic(response) == ''


def test_existing_strict_approval_remains_exportable_without_new_ai_call(monkeypatch, tmp_path):
    video, doc, segments, assets, _ = setup_review(monkeypatch, tmp_path)
    result = quality_review.review_render_output(video, doc, segments, assets, 1, 'title', tmp_path/'review',
                                                reviewer=lambda *_: json.dumps(passed()))
    result['review_version'] = 6
    quality_review.require_approved_video(video, result, effect_required=False)


def test_actual_contact_sheets_respect_frame_budget_and_repair_focus(monkeypatch, tmp_path):
    from PIL import Image
    def frame(args, **_):
        Image.new('RGB', (540, 320), 'white').save(args[-1])
        return subprocess.CompletedProcess(args, 0, '', '')
    monkeypatch.setattr(quality_review.processes, 'run', frame)
    groups = [[i, i+.8, f'caption {i}'] for i in range(80)]
    sheets, times = quality_review.make_sheets(tmp_path/'video.mp4', groups, 80, tmp_path)
    assert len(times) == 16 and len(sheets) == 4
    assert all(sheet.is_file() for sheet in sheets)
    focused = tmp_path/'focused'
    focused.mkdir()
    _, times = quality_review.make_sheets(tmp_path/'video.mp4', groups, 80, focused, focus_ranges=[(20, 22)])
    assert times and all(t < .3 or t > 79.7 or 19.7 <= t <= 22.3 for t in times)
    from test_caption_timing import fixture
    doc, segments, _ = fixture()
    segments['video_path'] = str(tmp_path/'video.mp4')
    quality_review.source_hook_sheet(doc, segments, 1, tmp_path, extra_times=[i/10 for i in range(35)])
    assert len(list(tmp_path.glob('source-hook-*.jpg'))) == 4
