"""Standalone language, packaging and fail-closed QA regressions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import ImageFont

from reels_editor import candidate_analyzer, caption_timing, hook_effects, quality_review, storyteller
from reels_editor.config import AppConfig, load_config, save_config
from reels_editor.desktop.server import CreateJobRequest, create_app
from reels_editor.jobs import Job, JobService, JobStore, Status
from reels_editor.languages import language_instruction, translation_required
from reels_editor.opening_hook import opening_hook_errors, restore_opening_hook_evidence
from reels_editor.style import load_style
from reels_editor.jobs.service import DEFAULT_STYLE, JobServiceError
from test_job_service import Calls, _deps, _run_ready, _approved
from test_desktop_api import FakeService, _static


@pytest.mark.parametrize('language', ['ko', 'en', 'zh'])
def test_language_survives_config_api_and_job_roundtrip(tmp_path, language):
    path = tmp_path / 'config.yaml'
    save_config(AppConfig(output_language=language), path)
    assert load_config(path).output_language == language
    store = JobStore(tmp_path / 'jobs')
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(static_dir=_static(tmp_path), media_dir=tmp_path,
                     job_service=service, session_token='secret', config_path=path)
    response = TestClient(app).post('/api/jobs?token=secret', json={
        'youtube_url': 'https://youtu.be/abcdefghijk', 'output_language': language})
    assert response.status_code == 200
    assert response.json()['output_language'] == language
    assert Job.from_dict(job.to_dict()).output_language == language
    assert CreateJobRequest.model_validate({'output_language': language}).output_language == language


def test_unknown_language_is_rejected_and_old_jobs_default_to_korean(tmp_path):
    assert Job.from_dict({'id': 'legacy'}).output_language == 'ko'
    with pytest.raises(ValueError):
        save_config(AppConfig(output_language='xx'), tmp_path/'config.yaml')
    with pytest.raises(ValueError):
        CreateJobRequest.model_validate({'output_language': 'xx'})


@pytest.mark.parametrize('source,target,required', [
    ('en', 'ko', True), ('ko', 'en', True), ('en', 'en', False),
    ('zh-Hans', 'zh', False), ('zh', 'ko', True), ('ko', 'zh', True)])
def test_translation_contract_covers_both_directions(source, target, required):
    segments = {'transcript_language': source, 'output_language': target,
                'segments': [{'id': 'a', 'text': 'Source.', 'source_start_us': 0, 'source_end_us': 1_000_000}]}
    assert translation_required(segments) is required
    doc = {'cuts': [{'seg_ids': ['a']}], 'subtitle_translations': {}}
    assert bool(storyteller.validate_subtitle_translations(doc, segments)) is required
    doc['subtitle_translations'] = {'a': 'Translated.'}
    assert not storyteller.validate_subtitle_translations(doc, segments)
    assert f'({target})' in storyteller.build_prompt(segments, 30, None)
    assert 'EVERY selected seg_id' in storyteller.build_prompt(segments, 30, None) if required else True


@pytest.mark.parametrize('target', ['ko', 'en', 'zh'])
def test_language_is_preserved_in_generation_render_and_retry(tmp_path, target):
    captured = []
    base = _deps(tmp_path, Calls())
    def analyze(segments, *args, **kwargs):
        captured.append(('analysis', segments['output_language']))
        return base.analyze_candidates(segments, *args, **kwargs)
    def prepare(video, doc, segments, *args, **kwargs):
        captured.append(('timing', segments['output_language']))
        return doc
    def review(video, doc, segments, *args, **kwargs):
        captured.append(('review', segments['output_language']))
        return _approved(video)
    service = JobService(store=JobStore(tmp_path/'jobs'), config=AppConfig(output_language=target),
                         deps=replace(base, analyze_candidates=analyze, prepare_caption_timing=prepare,
                                      review_render_output=review))
    try:
        job = _run_ready(service, candidate_count=1)
        assert job.status is Status.READY
        assert {kind for kind, language in captured if language == target} == {'analysis', 'timing', 'review'}
        doc = json.loads(Path(job.storylines[0].segments_path).read_text())
        assert doc['output_language'] == target
        service.retry_storyline(job.id, job.storylines[0].id)
        assert all(language == target for _, language in captured)
    finally:
        service.shutdown()


@pytest.mark.parametrize('mutation', ['missing', 'uncertain', 'machine', 'hash', 'version', 'evidence'])
def test_incomplete_or_stale_approval_cannot_export(tmp_path, mutation):
    video = tmp_path/'video.mp4'; video.write_bytes(b'final video')
    report = _approved(video)
    if mutation == 'missing': report['checks'].pop('hook_whoosh')
    if mutation == 'uncertain': report['checks']['translation']['verdict'] = 'uncertain'
    if mutation == 'machine': report['machine_issues'] = [{'kind': 'timing'}]
    if mutation == 'hash': video.write_bytes(b'changed')
    if mutation == 'version': report['review_version'] = -1
    if mutation == 'evidence': report['checks']['framing']['evidence'] = ''
    with pytest.raises(ValueError): quality_review.require_approved_video(video, report)


def test_changed_video_cannot_export_even_if_job_says_ready(tmp_path):
    service = JobService(store=JobStore(tmp_path/'jobs'), deps=_deps(tmp_path, Calls()))
    try:
        job = _run_ready(service, candidate_count=1)
        story = job.storylines[0]
        Path(story.active_variant_path).write_bytes(b'unreviewed replacement')
        with pytest.raises(JobServiceError, match='bytes differ'):
            service.export_many(job.id, tmp_path/'exports', storyline_ids=[story.id])
        assert not list((tmp_path/'exports').glob('*.mp4'))
    finally: service.shutdown()


def test_edited_title_is_reviewed_again_and_failure_preserves_old_approval(tmp_path):
    base = _deps(tmp_path, Calls())
    service = JobService(store=JobStore(tmp_path/'jobs'), deps=base)
    try:
        job = _run_ready(service, candidate_count=1)
        story = job.storylines[0]
        original = Path(story.edl_path).read_bytes()
        calls = []
        def refuse(video, *args, **kwargs):
            calls.append(video)
            return {'passed': False}
        service.deps = replace(base, review_render_output=refuse)
        with pytest.raises(JobServiceError):
            service.update_storyline_title(job.id, story.id, '다시 생각하게 만드는 질문의 힘')
        assert len(calls) == 1
        latest = service.store.load(job.id).storylines[0]
        assert latest.active_variant_path == story.active_variant_path
        assert Path(story.edl_path).read_bytes() == original
        quality_review.require_approved_video(Path(latest.active_variant_path),
            json.loads(original)['quality_review'])
    finally: service.shutdown()


def test_opening_quote_requires_consecutive_source_evidence():
    from reels_editor.jobs import ContentCandidate
    source = {'segments': [{'id': 'a', 'text': 'We learned', 'source_start_us': 0},
                           {'id': 'b', 'text': 'by practicing.', 'source_start_us': 1}]}
    candidate = ContentCandidate('c', 'story', 'The Real Price of Learning',
        'Opening hook: “We learned by practicing.” A complete lesson.', 'Practice.', ['a'])
    # Both localized protocol headings and exact source quotation are supported.
    restore_opening_hook_evidence([candidate], source)
    assert candidate.segment_ids == ['a', 'b']
    assert not opening_hook_errors([candidate], source)
    candidate.summary = 'Opening hook: “We became perfect.”'
    assert opening_hook_errors([candidate], source)


def test_bundled_resources_need_no_sibling_repo_or_private_font():
    style = load_style(DEFAULT_STYLE)
    assert style.watermark_image is None and not style.watermark_text
    assert style.title_font.is_file() and (style.title_font.parent/'OFL.txt').is_file()
    font = ImageFont.truetype(str(style.sub_font), 34)
    for text in ['한국어 자막', 'English captions', '中文字幕']:
        assert font.getmask(text).getbbox()
    assert hook_effects.DEFAULT_SOUND.is_file()
    assert storyteller.PROMPT_PATH.is_file()
    assert candidate_analyzer.PROMPT_PATH.is_file()


@pytest.mark.parametrize('language,title', [
    ('ko', '오래 연습해도 실력이 늘지 않는 이유'),
    ('en', 'Why Practice Needs a Plan'),
    ('zh', '为什么每天练习仍然没有明显进步')])
def test_thumbnail_and_video_hide_logo_and_episode_in_each_language(tmp_path, monkeypatch, language, title):
    from PIL import Image, ImageDraw
    from reels_editor import render, thumbnail
    style = replace(load_style(DEFAULT_STYLE), output_language=language).for_episode(42)
    calls = []
    original = ImageDraw.ImageDraw.text
    def record(self, xy, text, **kwargs):
        calls.append(str(text))
        return original(self, xy, text, **kwargs)
    monkeypatch.setattr(ImageDraw.ImageDraw, 'text', record)
    cover = thumbnail.compose_thumbnail(Image.new('RGB', style.canvas, 'gray'), title, style)
    cover.save(tmp_path/f'{language}.jpg')
    assert any(part in title for part in calls if part)
    assert not any('Episode' in text or '에피소드' in text or '42' in text for text in calls)
    watermark = Image.open(render.render_watermark_png(style, tmp_path/'watermark.png'))
    assert watermark.getbbox() is None


def test_failed_subtitle_review_preserves_playable_state_and_can_retry(tmp_path):
    base = _deps(tmp_path, Calls())
    service = JobService(store=JobStore(tmp_path/'jobs'), deps=base)
    try:
        job = _run_ready(service, candidate_count=1)
        story = job.storylines[0]
        doc_before = Path(story.edl_path).read_bytes()
        service.deps = replace(base, review_render_output=lambda *a, **k: {'passed': False})
        with pytest.raises(JobServiceError):
            service.select_variant(job.id, story.id, subtitles_on=False)
        saved = service.store.load(job.id).storylines[0]
        assert saved.status is Status.READY and saved.subtitles_on
        assert saved.active_variant_path == story.active_variant_path
        assert Path(saved.edl_path).read_bytes() == doc_before
        service.deps = base
        retried = service.retry_storyline(job.id, story.id)
        assert retried.storylines[0].status is Status.READY
    finally: service.shutdown()


def test_chinese_opening_quote_matches_exact_characters_across_cues_without_spaces():
    from reels_editor.jobs import ContentCandidate
    source = {'segments': [{'id': 'a', 'text': '每天练习'}, {'id': 'b', 'text': '需要明确目标。'}]}
    candidate = ContentCandidate('c', 'principle', '为什么每天练习仍然没有明显进步',
        '开场钩子: “每天练习需要明确目标。”', '设定目标。', ['a'])
    restore_opening_hook_evidence([candidate], source)
    assert candidate.segment_ids == ['a', 'b']
    assert not opening_hook_errors([candidate], source)
    candidate.summary = '开场钩子: “每天练习保证成功。”'
    assert opening_hook_errors([candidate], source)


def test_english_is_default_for_new_jobs_without_rewriting_legacy_language(tmp_path):
    assert AppConfig().output_language == 'en'
    assert load_config(tmp_path/'missing.yaml').output_language == 'en'
    assert CreateJobRequest().output_language == 'en'
    assert JobStore(tmp_path/'jobs').create_job().output_language == 'en'
    assert Job.from_dict({'id': 'legacy'}).output_language == 'ko'
    assert Job.from_dict({'id': 'chinese', 'output_language': 'zh'}).output_language == 'zh'


def test_empty_workspace_uses_english_interface_labels():
    from reels_editor.desktop.server import _snapshot_from_job, _placeholder_storyline
    snapshot = _snapshot_from_job(None)
    assert snapshot['source_label'] == 'No YouTube link'
    placeholder = _placeholder_storyline(0)
    assert placeholder['label'] == 'Reel 1'
    assert placeholder['hook'] == 'Pending'
    assert placeholder['title'] == 'Title pending'
    assert not any('\uac00' <= char <= '\ud7a3' for char in placeholder['summary'])
