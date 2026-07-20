from __future__ import annotations

import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import pytest

from reels_editor.jobs import JobService, JobServiceDeps, JobServiceError, JobStore, Status
from reels_editor import processes
from reels_editor.render import RenderAssets
from reels_editor.storyteller import StorylineResult
from reels_editor.style import StylePreset


@dataclass
class Calls:
    base: int = 0
    overlay: int = 0
    cuts: int = 0
    generate: int = 0
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

    def export_cuts(_video, _doc, _segments, out_dir: Path, _speed):
        calls.cuts += 1
        out_dir.mkdir(parents=True, exist_ok=True)
        cut = out_dir / "001-hook.mp4"
        cut.write_bytes(b"cut")
        return [cut]

    return JobServiceDeps(
        find_project=lambda name: tmp_path / name,
        load_project=lambda _path: {"draft": True},
        build_segments=lambda _draft: _segments(video),
        generate_many=lambda *_args, **_kwargs: _count_generate(calls, generated),
        build_runner=lambda _cfg: (lambda prompt: prompt),
        load_style=lambda _path: style,
        render_base_and_assets=render_base,
        render_overlay_variant=render_overlay,
        write_outputs=write_outputs,
        write_srt=lambda _groups, path: path.write_text("srt", encoding="utf-8") or path,
        export_cuts=export_cuts,
    )


def _count_generate(calls: Calls, results: list[StorylineResult]) -> list[StorylineResult]:
    calls.generate += 1
    return results


def test_job_service_keeps_partial_success_and_limits_base_parallelism(tmp_path: Path) -> None:
    calls = Calls()
    results = [
        StorylineResult(0, "정면승부형", _doc("A")),
        StorylineResult(1, "반전형", None, "LLM failed"),
        StorylineResult(2, "감정선형", _doc("C")),
    ]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = service.run_job_sync("김현지대표인터뷰")

    assert job.status is Status.READY
    assert [story.status for story in job.storylines] == [Status.READY, Status.FAILED, Status.READY]
    assert calls.generate == 1
    assert calls.base == 2
    assert calls.overlay == 2
    assert calls.cuts == 2
    assert calls.max_active_base <= 2
    assert job.selected_storyline_id == "s1"


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
    assert calls.cuts == 0


def test_selection_change_rerenders_overlay_only_and_exports_one_selected(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = service.run_job_sync("김현지대표인터뷰")
    before = (calls.generate, calls.base, calls.cuts, calls.overlay)

    selected_story_change = service.select_variant(job.id, "s1", title_index=1, subtitles_on=False)
    selected_story = next(item for item in selected_story_change.storylines if item.id == "s1")
    active_selected_variant = selected_story.variants[-1]

    assert selected_story_change.selected_storyline_id == "s1"
    assert selected_story_change.export.selected_variant_id == active_selected_variant.id
    assert active_selected_variant.selected is True
    assert (calls.generate, calls.base, calls.cuts) == before[:3]

    selected = service.select_variant(job.id, "s2", title_index=2, subtitles_on=False)

    assert (calls.generate, calls.base, calls.cuts) == before[:3]
    assert calls.overlay == before[3] + 2
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
    assert service.store.load(job_b.id).status is Status.READY
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


def _capture_exception(errors: list[BaseException], fn, *args, **kwargs) -> None:
    try:
        fn(*args, **kwargs)
    except BaseException as exc:  # noqa: BLE001 - test helper records thread failures
        errors.append(exc)
