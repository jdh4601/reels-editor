from __future__ import annotations

import subprocess
import sys
import threading
import time
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from reels_editor.jobs import Job, JobService, JobServiceDeps, JobServiceError, JobStore, Status, Storyline
from reels_editor import processes
from reels_editor.render import RenderAssets
from reels_editor.storyteller import StorylineResult
from reels_editor.style import StylePreset
from reels_editor.config import AppConfig
from reels_editor.voice_isolation import IsolationResult
from reels_editor.youtube import YouTubeSource


@dataclass
class Calls:
    base: int = 0
    overlay: int = 0
    generate: int = 0
    durations: list[int] = field(default_factory=list)
    storyline_counts: list[int] = field(default_factory=list)
    speeds: list[float] = field(default_factory=list)
    providers: list[str] = field(default_factory=list)
    max_active_base: int = 0
    active_base: int = 0
    base_version: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)


def _style(tmp_path: Path) -> StylePreset:
    font = tmp_path / "font.ttf"
    font.write_bytes(b"font")
    return StylePreset(
        canvas=(1080, 1920),
        top_bar=220,
        bottom_bar=160,
        title_font=font,
        title_size=64,
        title_color="#ffffff",
        title_highlight="#ffcc00",
        title_max_lines=2,
        sub_font=font,
        sub_size=42,
        sub_color="#ffffff",
        sub_highlight="#ffcc00",
        sub_box_alpha=180,
        sub_y_frac=0.85,
        watermark_text="@reels",
        watermark_font=font,
        watermark_size=28,
        speed=1.2,
    )


def _segments(video: Path) -> dict[str, Any]:
    return {
        "video_path": str(video),
        "segments": [
            {
                "id": "seg1",
                "text": "대표 인터뷰입니다",
                "source_start_us": 0,
                "source_end_us": 1_000_000,
            }
        ],
    }


def _doc(prefix: str) -> dict[str, Any]:
    return {
        "title_candidates": [
            {"text": f"{prefix} 제목 1", "keyword": "제목"},
            {"text": f"{prefix} 제목 2", "keyword": "제목"},
            {"text": f"{prefix} 제목 3", "keyword": "제목"},
        ],
        "subtitle_keywords": ["대표"],
        "cuts": [{"beat": "hook", "seg_ids": ["seg1"]}],
    }


def _deps(tmp_path: Path, calls: Calls, results: list[StorylineResult] | None = None) -> JobServiceDeps:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source")
    style = _style(tmp_path)
    generated = results or [
        StorylineResult(0, "정면승부형", _doc("A")),
        StorylineResult(1, "반전형", _doc("B")),
        StorylineResult(2, "감정선형", _doc("C")),
    ]

    def render_base(_video, _segments, _doc, _style, work_dir: Path, _speed, **_kwargs):
        with calls.lock:
            calls.active_base += 1
            calls.max_active_base = max(calls.max_active_base, calls.active_base)
        time.sleep(0.01)
        with calls.lock:
            calls.base += 1
            calls.base_version += 1
            base_version = calls.base_version
        work_dir.mkdir(parents=True, exist_ok=True)
        base = work_dir / "base.mp4"
        wm = work_dir / "wm.png"
        sub = work_dir / "subs" / "s000.png"
        sub.parent.mkdir(parents=True, exist_ok=True)
        base.write_text(f"base-v{base_version}", encoding="utf-8")
        wm.write_bytes(b"wm")
        sub.write_bytes(b"sub")
        with calls.lock:
            calls.active_base -= 1
        return RenderAssets(base=base, wm_png=wm, sub_pngs=[sub], groups=[[0.0, 1.0, "자막"]], work=work_dir, keywords=["자막"])

    def render_overlay(_assets, *, title_text: str, out_path: Path, subtitles_enabled: bool, **_kwargs):
        calls.overlay += 1
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(f"{Path(_assets.base).read_text(encoding='utf-8')}:{title_text}:{subtitles_enabled}".encode())
        return out_path

    def write_outputs(work: Path, doc: dict[str, Any], segments: dict[str, Any]) -> None:
        work.mkdir(parents=True, exist_ok=True)
        (work / "edl.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
        (work / "segments.json").write_text(__import__("json").dumps(segments), encoding="utf-8")

    return JobServiceDeps(
        find_project=lambda name: tmp_path / name,
        load_project=lambda _path: {"draft": True},
        build_segments=lambda _draft: _segments(video),
        generate_many=lambda _segments, count, duration_s, **_kwargs: _count_generate(
            calls,
            generated[:count],
            duration_s,
            count,
            _kwargs["speed"],
        ),
        build_runner=lambda cfg: _capture_provider(calls, cfg.provider),
        load_style=lambda _path: style,
        render_base_and_assets=render_base,
        render_overlay_variant=render_overlay,
        write_outputs=write_outputs,
        write_srt=lambda _groups, path: path.write_text("srt", encoding="utf-8") or path,
    )


def _capture_provider(calls: Calls, provider: str):
    calls.providers.append(provider)
    return lambda prompt: prompt


def _count_generate(
    calls: Calls,
    results: list[StorylineResult],
    duration_s: int,
    storyline_count: int,
    speed: float,
) -> list[StorylineResult]:
    calls.generate += 1
    calls.durations.append(duration_s)
    calls.storyline_counts.append(storyline_count)
    calls.speeds.append(speed)
    return results


def test_job_service_marks_partial_success_as_failed_and_limits_base_parallelism(tmp_path: Path) -> None:
    calls = Calls()
    results = [
        StorylineResult(0, "정면승부형", _doc("A")),
        StorylineResult(1, "반전형", None, "LLM failed"),
        StorylineResult(2, "감정선형", _doc("C")),
    ]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = service.run_job_sync("김현지대표인터뷰")

    assert job.status is Status.FAILED
    assert job.phase == "partial-failure"
    assert job.error == "대표 영상 2/3개만 준비되었습니다."
    assert [story.status for story in job.storylines] == [Status.READY, Status.FAILED, Status.READY]
    assert calls.generate == 1
    assert calls.base == 2
    assert calls.overlay == 2
    assert calls.max_active_base <= 2
    assert job.selected_storyline_id == "s1"
    assert not (Path(job.work_dir or "") / "s1" / "cuts").exists()


def test_job_service_uses_duration_stored_on_each_job(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))

    job = service.run_job_sync("김현지대표인터뷰", duration_s=60)

    assert job.duration_s == 60
    assert calls.durations == [60]


def test_job_service_validates_storyline_length_with_configured_playback_speed(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        config=AppConfig(provider="codex-cli", style={"speed": 1.45}),
    )

    service.run_job_sync("김현지대표인터뷰", duration_s=60)

    assert calls.speeds == [1.45]


def test_youtube_job_downloads_source_and_reuses_existing_storyline_pipeline(tmp_path: Path) -> None:
    calls = Calls()
    deps = _deps(tmp_path, calls)
    video = tmp_path / "youtube-source.mp4"
    video.write_bytes(b"youtube")
    transcript = tmp_path / "source.ko.json3"
    transcript.write_text("{}", encoding="utf-8")
    download_args: dict[str, Any] = {}

    def download(url: str, output_dir: Path, **kwargs: Any) -> YouTubeSource:
        download_args.update({"url": url, "output_dir": output_dir, **kwargs})
        kwargs["progress_cb"](0.5)
        return YouTubeSource(
            video_path=video,
            segments=_segments(video),
            title="1시간 창업가 인터뷰",
            video_id="abc123",
            source_url=url,
            transcript_path=transcript,
            transcript_language="ko",
            transcript_kind="automatic",
        )

    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=replace(deps, download_youtube_source=download),
    )

    job = service.run_youtube_job_sync(
        "https://www.youtube.com/watch?v=abc123",
        duration_s=60,
    )

    assert job.status is Status.READY
    assert job.source_type == "youtube"
    assert job.source_url == "https://www.youtube.com/watch?v=abc123"
    assert job.project_path is None
    assert job.project_name == "1시간 창업가 인터뷰"
    assert job.input_path == str(video)
    assert job.transcript_language == "ko"
    assert job.transcript_kind == "automatic"
    assert download_args["output_dir"] == tmp_path / "jobs" / job.id / "source"
    assert calls.durations == [60]
    assert calls.base == 3


def test_youtube_job_reuses_complete_prior_download_for_same_video_id(tmp_path: Path) -> None:
    calls = Calls()
    deps = _deps(tmp_path, calls)
    store = JobStore(tmp_path / "jobs")
    prior = store.create_job(
        source_type="youtube",
        source_url="https://www.youtube.com/watch?v=abc123&si=old",
        project_name="이전 작업 제목",
    )
    source_dir = store.job_dir(prior.id) / "source"
    source_dir.mkdir(parents=True)
    video = source_dir / "source.mp4"
    video.write_bytes(b"cached-video")
    (source_dir / "source.en-orig.json3").write_text("{}", encoding="utf-8")
    cached_segments = _segments(video)
    cached_segments.update({
        "transcript_language": "en-orig",
        "transcript_kind": "automatic",
    })
    (source_dir / "segments.json").write_text(json.dumps(cached_segments), encoding="utf-8")
    (source_dir / "source.info.json").write_text(json.dumps({
        "id": "abc123",
        "title": "캐시된 창업가 인터뷰",
    }), encoding="utf-8")

    def unexpected_download(*_args: Any, **_kwargs: Any) -> YouTubeSource:
        raise AssertionError("complete cached source must skip YouTube download")

    service = JobService(
        store=store,
        deps=replace(deps, download_youtube_source=unexpected_download),
    )

    job = service.run_youtube_job_sync("https://youtu.be/abc123?si=new")

    assert job.status is Status.READY
    assert job.project_name == "캐시된 창업가 인터뷰"
    assert job.input_path == str(video)
    assert job.transcript_language == "en-orig"
    assert job.transcript_kind == "automatic"
    assert calls.generate == 1
    assert calls.base == 3


def test_job_service_uses_storyline_count_and_provider_stored_on_each_job(tmp_path: Path) -> None:
    calls = Calls()
    results = [StorylineResult(index, f"관점 {index + 1}", _doc(str(index + 1))) for index in range(10)]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = service.run_job_sync(
        "김현지대표인터뷰",
        n_storylines=10,
        provider="claude-cli",
    )

    assert job.n_storylines == 10
    assert job.provider == "claude-cli"
    assert len(job.storylines) == 10
    assert calls.storyline_counts == [10]
    assert calls.providers == ["claude-cli"]


def test_job_service_reports_detailed_progress_during_rendering(tmp_path: Path) -> None:
    calls = Calls()
    entered_render = threading.Event()
    release_render = threading.Event()
    deps = _deps(tmp_path, calls, [StorylineResult(0, "정면승부형", _doc("A"))])
    render_base = deps.render_base_and_assets

    def blocking_render_base(*args, **kwargs):
        entered_render.set()
        release_render.wait(3)
        return render_base(*args, **kwargs)

    deps = JobServiceDeps(**{**deps.__dict__, "render_base_and_assets": blocking_render_base})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_job("김현지대표인터뷰", n_storylines=1)

    try:
        assert entered_render.wait(2)
        current = service.store.load(job.id)
        assert current.phase == "rendering"
        assert current.progress > 0.28
        assert "스토리라인 1" in (current.message or "")
        assert "세로 영상" in (current.message or "")
    finally:
        release_render.set()

    deadline = time.time() + 3
    while service.store.load(job.id).status is not Status.READY and time.time() < deadline:
        time.sleep(0.02)
    assert service.store.load(job.id).status is Status.READY


def test_job_service_all_fail_does_not_render(tmp_path: Path) -> None:
    calls = Calls()
    results = [
        StorylineResult(0, "정면승부형", None, "bad"),
        StorylineResult(1, "반전형", None, "bad"),
        StorylineResult(2, "감정선형", None, "bad"),
    ]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = service.run_job_sync("김현지대표인터뷰")

    assert job.status is Status.FAILED
    assert calls.base == 0
    assert calls.overlay == 0


def test_selection_change_rerenders_overlay_only_and_exports_one_selected(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    before = (calls.generate, calls.base, calls.overlay)

    selected_story_change = service.select_variant(job.id, "s1", title_index=1, subtitles_on=False)
    selected_story = next(item for item in selected_story_change.storylines if item.id == "s1")
    active_selected_variant = selected_story.variants[-1]

    assert selected_story_change.selected_storyline_id == "s1"
    assert selected_story_change.export.selected_variant_id == active_selected_variant.id
    assert active_selected_variant.selected is True
    assert (calls.generate, calls.base) == before[:2]

    selected = service.select_variant(job.id, "s2", title_index=2, subtitles_on=False)

    assert (calls.generate, calls.base) == before[:2]
    assert calls.overlay == before[2] + 2
    story = next(item for item in selected.storylines if item.id == "s2")
    assert story.selected_title_index == 2
    assert story.subtitles_on is False
    assert selected.selected_storyline_id == "s1"
    assert sum(variant.selected for item in selected.storylines for variant in item.variants) == 1

    selected = service.select_variant(
        job.id,
        "s2",
        title_index=2,
        subtitles_on=False,
        selected_for_export=True,
    )
    story = next(item for item in selected.storylines if item.id == "s2")
    assert selected.selected_storyline_id == "s2"
    assert sum(variant.selected for item in selected.storylines for variant in item.variants) == 1

    destination = tmp_path / "exported.mp4"
    exported = service.export_selected(selected.id, destination, storyline_id="s2")

    assert destination.read_bytes() == Path(story.variants[-1].path or "").read_bytes()
    assert destination.is_file()
    assert (tmp_path / "exported.mp4.manifest.json").is_file()
    assert exported.export.status is Status.READY
    assert exported.export.output_path == str(destination)


def test_export_reconciles_requested_subtitle_variant_before_copy(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    before = calls.overlay
    destination = tmp_path / "exported-nosub.mp4"

    exported = service.export_selected(job.id, destination, storyline_id="s1", subtitles_on=False)

    assert calls.overlay == before + 1
    assert b":False" in destination.read_bytes()
    assert exported.export.status is Status.READY
    assert exported.export.selected_storyline_id == "s1"


def test_batch_export_writes_each_selected_storyline_to_one_folder(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    destination = tmp_path / "exports"

    exported = service.export_many(
        job.id,
        destination,
        storyline_ids=["s1", "s3"],
        subtitles_on=False,
    )

    assert sorted(path.name for path in destination.glob("storyline-*.mp4")) == [
        "storyline-1.mp4",
        "storyline-3.mp4",
    ]
    assert sorted(path.name for path in destination.glob("*.manifest.json")) == [
        "storyline-1.mp4.manifest.json",
        "storyline-3.mp4.manifest.json",
    ]
    assert all(b":False" in path.read_bytes() for path in destination.glob("storyline-*.mp4"))
    assert exported.export.output_path == str(destination)


def test_export_applies_voice_isolator_once_and_records_manifest(tmp_path: Path) -> None:
    calls = Calls()
    enhanced_sources: list[Path] = []

    def enhance(source: Path, output: Path, *, cache_dir: Path, api_key: str) -> IsolationResult:
        assert api_key == "xi-test-key"
        assert cache_dir.name == ".voice-isolation"
        enhanced_sources.append(source)
        output.write_bytes(b"voice-isolated")
        return IsolationResult(output, cache_hit=False, audio_hash="abc123")

    deps = replace(
        _deps(tmp_path, calls),
        enhance_export_video=enhance,
        resolve_voice_isolation_key=lambda: "xi-test-key",
    )
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=deps,
        config=AppConfig(provider="codex-cli", voice_isolation=False),
    )
    job = service.run_job_sync("김현지대표인터뷰", voice_isolation=True)
    destination = tmp_path / "isolated.mp4"

    service.export_selected(job.id, destination, storyline_id="s1")

    assert destination.read_bytes() == b"voice-isolated"
    assert len(enhanced_sources) == 1
    manifest = json.loads((tmp_path / "isolated.mp4.manifest.json").read_text(encoding="utf-8"))
    assert manifest["voice_isolation"] is True
    assert manifest["speech_enhancement"] is True
    assert manifest["voice_isolation_cache_hit"] is False
    assert manifest["voice_isolation_audio_hash"] == "abc123"


def test_export_requires_elevenlabs_key_when_voice_isolation_enabled(tmp_path: Path) -> None:
    deps = replace(
        _deps(tmp_path, Calls()),
        resolve_voice_isolation_key=lambda: None,
    )
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=deps,
        config=AppConfig(provider="codex-cli", voice_isolation=False),
    )
    job = service.run_job_sync("김현지대표인터뷰", voice_isolation=True)

    with pytest.raises(JobServiceError, match="ElevenLabs API key"):
        service.export_selected(job.id, tmp_path / "missing-key.mp4", storyline_id="s1")


def test_export_keeps_job_voice_isolation_choice_after_global_setting_changes(tmp_path: Path) -> None:
    enhanced_sources: list[Path] = []

    def enhance(source: Path, output: Path, *, cache_dir: Path, api_key: str) -> IsolationResult:
        enhanced_sources.append(source)
        output.write_bytes(b"unexpected")
        return IsolationResult(output, cache_hit=False, audio_hash="unused")

    deps = replace(
        _deps(tmp_path, Calls()),
        enhance_export_video=enhance,
        resolve_voice_isolation_key=lambda: "xi-test-key",
    )
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=deps,
        config=AppConfig(provider="codex-cli", voice_isolation=False),
    )
    job = service.run_job_sync("김현지대표인터뷰", voice_isolation=False)
    service.config = replace(service.config, voice_isolation=True)
    destination = tmp_path / "original-audio.mp4"

    service.export_selected(job.id, destination, storyline_id="s1")

    assert enhanced_sources == []
    manifest = json.loads((tmp_path / "original-audio.mp4.manifest.json").read_text(encoding="utf-8"))
    assert manifest["voice_isolation"] is False
    assert manifest["speech_enhancement"] is False


def test_batch_export_rejects_empty_selection(tmp_path: Path) -> None:
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, Calls()))
    job = service.run_job_sync("김현지대표인터뷰")

    with pytest.raises(JobServiceError, match="at least one"):
        service.export_many(job.id, tmp_path / "exports", storyline_ids=[])


def test_export_rejects_unselected_storyline_request(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")

    with pytest.raises(JobServiceError, match="not selected"):
        service.export_selected(job.id, tmp_path / "wrong.mp4", storyline_id="s2")


def test_stale_overlay_request_is_suppressed(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    story = next(item for item in job.storylines if item.id == "s1")
    story.render_request_id = 9
    job = service.store.save(job)

    service._render_selection(job.id, "s1", request_id=8)

    after = service.store.load(job.id)
    story_after = next(item for item in after.storylines if item.id == "s1")
    assert story_after.render_request_id == 9
    assert story_after.selected_title_index == 0
    assert len(story_after.variants) == len(story.variants)


def test_retry_invalidates_old_overlay_cache_for_same_title_choice(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    alternate = service.select_variant(job.id, "s1", title_index=1, subtitles_on=False)
    story = next(item for item in alternate.storylines if item.id == "s1")
    old_variant_path = Path(story.active_variant_path or "")
    old_payload = old_variant_path.read_text(encoding="utf-8")

    assert old_payload.startswith("base-v")

    retried = service.retry_storyline(job.id, "s1")
    retry_story = next(item for item in retried.storylines if item.id == "s1")
    retry_overlay_count = calls.overlay
    retry_base_count = calls.base

    rerendered = service.select_variant(retried.id, "s1", title_index=1, subtitles_on=False)
    rerendered_story = next(item for item in rerendered.storylines if item.id == "s1")
    new_variant_path = Path(rerendered_story.active_variant_path or "")
    new_payload = new_variant_path.read_text(encoding="utf-8")

    assert calls.base == retry_base_count
    assert calls.overlay == retry_overlay_count + 1
    assert retry_story.variants[0].path != str(old_variant_path)
    assert new_payload.startswith("base-v")
    assert new_payload != old_payload
    assert not old_variant_path.exists()


def test_retry_recovers_failed_generation_with_structural_smart_quote(tmp_path: Path) -> None:
    calls = Calls()
    store = JobStore(tmp_path / "jobs")
    service = JobService(store=store, deps=_deps(tmp_path, calls))
    cached_source_dir = store.job_dir("cached-source-job") / "source"
    cached_source_dir.mkdir(parents=True)
    video = cached_source_dir / "source.mp4"
    video.write_bytes(b"cached-video")
    job = Job(
        id="recover-job",
        source_type="youtube",
        input_path=str(video),
        duration_s=30,
        n_storylines=1,
        status=Status.FAILED,
        phase="partial-failure",
        storylines=[Storyline(
            id="s1",
            index=0,
            angle_name="정면승부형",
            status=Status.FAILED,
            error="JSON parse failed",
        )],
    )
    store.save(job)
    segments = _segments(video)
    (cached_source_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
    malformed = json.dumps(_doc("복구"), ensure_ascii=False).replace(
        '"복구 제목 1"', '“복구 제목 1"', 1
    )
    (store.job_dir(job.id) / "llm_raw_s1.txt").write_text(malformed, encoding="utf-8")

    recovered = service.retry_storyline(job.id, "s1")
    story = recovered.storylines[0]

    assert recovered.status is Status.READY
    assert story.status is Status.READY
    assert story.title_candidates[0] == "복구 제목 1"
    assert story.edl_path is not None


def test_cancel_marks_active_job_and_blocks_second_active_job(tmp_path: Path) -> None:
    calls = Calls()

    def slow_generate(*_args, **_kwargs):
        time.sleep(0.2)
        return [StorylineResult(0, "정면승부형", _doc("A"))]

    deps = _deps(tmp_path, calls)
    deps = JobServiceDeps(**{**deps.__dict__, "generate_many": slow_generate})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_job("김현지대표인터뷰")

    with pytest.raises(JobServiceError):
        service.start_job("다른프로젝트")

    cancelled = service.cancel(job.id)
    time.sleep(0.25)

    assert cancelled.status is Status.CANCELLED
    assert service.store.load(job.id).status is Status.CANCELLED


def test_cancelled_job_cannot_resume_after_new_job_replaces_active_slot(tmp_path: Path) -> None:
    calls = Calls()
    release_generate = threading.Event()
    entered_generate = threading.Event()

    def slow_generate(*_args, **_kwargs):
        entered_generate.set()
        release_generate.wait(2)
        return [StorylineResult(0, "정면승부형", _doc("A"))]

    deps = _deps(tmp_path, calls)
    deps = JobServiceDeps(**{**deps.__dict__, "generate_many": slow_generate})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job_a = service.start_job("A")
    assert entered_generate.wait(2)
    cancelled_a = service.cancel(job_a.id)

    with pytest.raises(JobServiceError):
        service.start_job("B")

    release_generate.set()
    time.sleep(0.25)

    job_b = service.start_job("B")
    time.sleep(0.25)

    assert cancelled_a.status is Status.CANCELLED
    assert service.store.load(job_a.id).status is Status.CANCELLED
    assert service.store.load(job_b.id).status is Status.FAILED
    assert service.store.load(job_b.id).phase == "partial-failure"
    assert service.store.load(job_b.id).project_name == "B"


def test_cancel_terminates_runner_process_spawned_inside_generation_thread(tmp_path: Path) -> None:
    calls = Calls()
    pid_file = tmp_path / "runner.pid"

    def threaded_generate_many(*_args, runner, **_kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner, "prompt")
            try:
                future.result()
            except RuntimeError as exc:
                return [StorylineResult(0, "정면승부형", None, str(exc))]
        return [StorylineResult(0, "정면승부형", _doc("A"))]

    def build_runner(_cfg):
        def runner(_prompt: str) -> str:
            completed = processes.run(
                [
                    sys.executable,
                    "-c",
                    "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)",
                    str(pid_file),
                ],
                capture_output=True,
                text=True,
            )
            return completed.stdout

        return runner

    deps = _deps(tmp_path, calls)
    deps = JobServiceDeps(**{**deps.__dict__, "generate_many": threaded_generate_many, "build_runner": build_runner})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_job("김현지대표인터뷰")

    deadline = time.time() + 5
    while not pid_file.is_file() and time.time() < deadline:
        time.sleep(0.02)
    assert pid_file.is_file()
    pid = int(pid_file.read_text(encoding="utf-8"))

    service.cancel(job.id)

    deadline = time.time() + 3
    while time.time() < deadline:
        probe = subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True)
        if probe.returncode != 0:
            break
        time.sleep(0.05)
    assert subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True).returncode != 0


def test_cancel_terminates_overlay_process_and_blocks_new_job_until_done(tmp_path: Path) -> None:
    calls = Calls()
    pid_file = tmp_path / "overlay.pid"
    slow_overlay = threading.Event()
    deps = _deps(tmp_path, calls)
    original_overlay = deps.render_overlay_variant

    def render_overlay(assets, *, title_text: str, out_path: Path, subtitles_enabled: bool, **kwargs):
        if slow_overlay.is_set():
            processes.run(
                [
                    sys.executable,
                    "-c",
                    "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)",
                    str(pid_file),
                ],
                capture_output=True,
                text=True,
            )
        return original_overlay(
            assets,
            title_text=title_text,
            out_path=out_path,
            subtitles_enabled=subtitles_enabled,
            **kwargs,
        )

    deps = replace(deps, render_overlay_variant=render_overlay)
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.run_job_sync("김현지대표인터뷰")
    slow_overlay.set()
    errors: list[BaseException] = []
    thread = threading.Thread(
        target=lambda: _capture_exception(
            errors,
            service.select_variant,
            job.id,
            "s1",
            title_index=1,
            subtitles_on=True,
        )
    )
    thread.start()

    deadline = time.time() + 5
    while not pid_file.is_file() and time.time() < deadline:
        time.sleep(0.02)
    assert pid_file.is_file()
    pid = int(pid_file.read_text(encoding="utf-8"))

    with pytest.raises(JobServiceError):
        service.start_job("B")

    service.cancel(job.id)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert errors
    assert subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True).returncode != 0
    assert service.store.load(job.id).status is Status.CANCELLED

    slow_overlay.clear()
    replacement = service.start_job("B")
    deadline = time.time() + 3
    while service.store.load(replacement.id).status is not Status.READY and time.time() < deadline:
        time.sleep(0.05)
    assert service.store.load(replacement.id).status is Status.READY


def test_overlay_completion_does_not_release_active_slot_while_base_renders_continue(tmp_path: Path) -> None:
    calls = Calls()
    release_remaining = threading.Event()
    results = [
        StorylineResult(0, "정면승부형", _doc("A")),
        StorylineResult(1, "반전형", _doc("B")),
        StorylineResult(2, "감정선형", _doc("C")),
    ]
    deps = _deps(tmp_path, calls, results)
    render_base = deps.render_base_and_assets

    def staged_render_base(video, segments, doc, style, out_dir, speed):
        if out_dir.parent.name != "s1":
            release_remaining.wait(3)
        return render_base(video, segments, doc, style, out_dir, speed)

    deps = JobServiceDeps(**{**deps.__dict__, "render_base_and_assets": staged_render_base})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_job("김현지대표인터뷰")

    deadline = time.time() + 3
    while time.time() < deadline:
        current = service.store.load(job.id)
        if current.storylines and current.storylines[0].status is Status.READY:
            break
        time.sleep(0.02)
    else:
        pytest.fail("first storyline did not become ready")

    service.select_variant(job.id, "s1", title_index=1, subtitles_on=False)

    with pytest.raises(JobServiceError, match="another job is already active"):
        service.start_job("replacement")

    service.cancel(job.id)
    release_remaining.set()
    deadline = time.time() + 3
    while service._active_job_id is not None and time.time() < deadline:
        time.sleep(0.02)
    assert service._active_job_id is None
    assert service.store.load(job.id).status is Status.CANCELLED


def _capture_exception(errors: list[BaseException], fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - test helper records thread failures
        errors.append(exc)
