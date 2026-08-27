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

import reels_editor.jobs.service as job_service_module
from reels_editor.jobs import ContentCandidate, Job, JobService, JobServiceDeps, JobServiceError, JobStore, Status, Storyline, Variant
from reels_editor import processes
from reels_editor.render import RenderAssets
from reels_editor.storyteller import StorylineResult
from reels_editor.style import StylePreset
from reels_editor.config import AppConfig
from reels_editor.youtube import YouTubeSource

TEST_URL = "https://youtu.be/founder"


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
    caption_requests: list[dict[str, Any]] = field(default_factory=list)
    overlay_keywords: list[str] = field(default_factory=list)
    episode_texts: list[str] = field(default_factory=list)
    base_episode_numbers: list[int | None] = field(default_factory=list)
    overlay_title_lines: list[tuple[str, str]] = field(default_factory=list)
    speaker_texts: list[str] = field(default_factory=list)
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
        "speaker": {"name": "김현지", "role": "Founder"},
        "title_candidates": [
            {"text": f"{prefix} 제목 1", "keyword": "제목"},
            {"text": f"{prefix} 제목 2", "keyword": "제목"},
            {"text": f"{prefix} 제목 3", "keyword": "제목"},
        ],
        "subtitle_keywords": ["대표"],
        "cuts": [{"beat": "hook", "seg_ids": ["seg1"]}],
    }


def _candidates() -> list[ContentCandidate]:
    types = ["story", "strategy", "failure", "principle"]
    return [
        ContentCandidate(
            id=f"c{index + 1}",
            content_type=types[index % len(types)],
            title=f"서로 다른 후보 {index + 1}",
            summary=f"후보 {index + 1}의 구체적인 내용",
            takeaway=f"실행 교훈 {index + 1}",
            segment_ids=["seg1"],
        )
        for index in range(10)
    ]


def _deps(tmp_path: Path, calls: Calls, results: list[StorylineResult] | None = None) -> JobServiceDeps:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source")
    style = _style(tmp_path)
    generated = results or [
        StorylineResult(0, "정면승부형", _doc("https://youtu.be/A")),
        StorylineResult(1, "반전형", _doc("https://youtu.be/B")),
        StorylineResult(2, "감정선형", _doc("C")),
    ]

    def render_base(_video, _segments, _doc, _style, work_dir: Path, _speed, **_kwargs):
        calls.base_episode_numbers.append(_kwargs.get("episode_number"))
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
        calls.overlay_keywords.append(str(_kwargs.get("keyword", "")))
        calls.overlay_title_lines.append((
            str(_kwargs.get("title_upper", "")),
            str(_kwargs.get("title_lower", "")),
        ))
        calls.speaker_texts.append(str(_kwargs.get("speaker_text", "")))
        calls.episode_texts.append(str(_kwargs["style"].episode_text))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(f"{Path(_assets.base).read_text(encoding='utf-8')}:{title_text}:{subtitles_enabled}".encode())
        return out_path

    def write_outputs(work: Path, doc: dict[str, Any], segments: dict[str, Any]) -> None:
        work.mkdir(parents=True, exist_ok=True)
        (work / "edl.json").write_text(__import__("json").dumps(doc), encoding="utf-8")
        (work / "segments.json").write_text(__import__("json").dumps(segments), encoding="utf-8")

    def download(url: str, output_dir: Path, **_kwargs: Any) -> YouTubeSource:
        transcript = output_dir / "source.ko.json3"
        output_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text("{}", encoding="utf-8")
        segments = _segments(video)
        (output_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
        title = url.rstrip("/").rsplit("/", 1)[-1]
        return YouTubeSource(
            video_path=video,
            segments=segments,
            title=title,
            video_id=title,
            source_url=url,
            transcript_path=transcript,
            transcript_language="ko",
            transcript_kind="automatic",
        )

    def generate_caption(**kwargs: Any) -> str:
        calls.caption_requests.append(kwargs)
        return f"Ep {kwargs['episode_number']}. 첫 고객을 만든 방법\n\n맥락\n\n전략\n\n교훈\n\n여러분은 무엇을 먼저 검증하고 있나요?\n\n다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀"

    return JobServiceDeps(
        analyze_candidates=lambda _segments, _types, **_kwargs: _candidates(),
        generate_selected_candidates=lambda _segments, candidates, **_kwargs: _count_generate(
            calls,
            generated[:len(candidates)],
            35,
            len(candidates),
            _kwargs["speed"],
        ),
        generate_instagram_caption=generate_caption,
        build_runner=lambda cfg: _capture_provider(calls, cfg.provider),
        load_style=lambda _path: style,
        render_base_and_assets=render_base,
        render_overlay_variant=render_overlay,
        write_outputs=write_outputs,
        write_srt=lambda _groups, path: path.write_text("srt", encoding="utf-8") or path,
        download_youtube_source=download,
    )


def _run_ready(
    service: JobService,
    url: str = TEST_URL,
    *,
    candidate_count: int = 3,
    provider: str | None = None,
    content_types: list[str] | None = None,
    episode_number: int = 1,
):
    analyzed = service.run_youtube_job_sync(
        url,
        provider=provider,
        content_types=content_types,
        episode_number=episode_number,
    )
    return service.generate_selected_sync(
        analyzed.id,
        [candidate.id for candidate in analyzed.candidates[:candidate_count]],
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
        StorylineResult(0, "정면승부형", _doc("https://youtu.be/A")),
        StorylineResult(1, "반전형", None, "LLM failed"),
        StorylineResult(2, "감정선형", _doc("C")),
    ]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = _run_ready(service)

    assert job.status is Status.FAILED
    assert job.phase == "partial-failure"
    assert job.error == "선택한 릴스 2/3개만 준비되었습니다."
    assert [story.status for story in job.storylines] == [Status.READY, Status.FAILED, Status.READY]
    assert calls.generate == 1
    assert calls.base == 2
    assert calls.overlay == 2
    assert calls.max_active_base <= 2
    assert job.selected_storyline_id == "s1"
    assert not (Path(job.work_dir or "") / "s1" / "cuts").exists()


def test_job_service_harmonizes_grounded_speaker_role_before_render(tmp_path: Path) -> None:
    calls = Calls()
    grounded = _doc("A")
    grounded["speaker"] = {
        "name": "히텐 샤",
        "company": "Crazy Egg",
        "role": "창업자",
        "alternate_role": "",
        "evidence": "Hiten Shah is a founder. He started Crazy Egg.",
    }
    incomplete = _doc("B")
    incomplete["speaker"] = {
        "name": "히튼 샤",
        "company": "",
        "role": "",
        "alternate_role": "",
        "evidence": "Hiten Shah is a founder.",
    }
    results = [
        StorylineResult(0, "전략형", grounded),
        StorylineResult(1, "실패 분석형", incomplete),
    ]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    _run_ready(service, candidate_count=2)

    assert calls.speaker_texts == [
        "히텐 샤 (Crazy Egg 창업자)",
        "히텐 샤 (Crazy Egg 창업자)",
    ]


def test_job_service_analyzes_ten_candidates_then_generates_only_selected(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))

    analyzed = service.run_youtube_job_sync(
        TEST_URL,
        content_types=["strategy", "failure"],
    )

    assert analyzed.status is Status.AWAITING_SELECTION
    assert analyzed.content_types == ["strategy", "failure"]
    assert len(analyzed.candidates) == 10
    assert analyzed.storylines == []
    assert calls.generate == 0
    assert calls.base == 0

    generated = service.generate_selected_sync(analyzed.id, ["c2", "c7"])

    assert generated.status is Status.READY
    assert generated.selected_candidate_ids == ["c2", "c7"]
    assert generated.n_storylines == 2
    assert len(generated.storylines) == 2
    assert calls.generate == 1
    assert calls.base == 2


def test_job_service_uses_fixed_35_second_target(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))

    job = _run_ready(service)

    assert job.duration_s == 35
    assert calls.durations == [35]


def test_job_service_generates_and_persists_caption_for_selected_reel(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    ready = _run_ready(service, candidate_count=2, episode_number=37)

    updated = service.generate_instagram_caption(ready.id, "s2")

    caption = updated.storylines[1].instagram_caption
    assert caption.startswith("Ep 37. ")
    assert service.store.load(ready.id).storylines[1].instagram_caption == caption
    assert len(calls.caption_requests) == 1
    request = calls.caption_requests[0]
    assert request["episode_number"] == 37
    assert request["candidate"]["id"] == "c2"
    assert request["selected_title"].endswith("제목 1")


def test_episode_number_is_job_level_for_render_caption_and_archive(tmp_path: Path) -> None:
    calls = Calls()
    archive_root = tmp_path / "Movies" / "Reels Editor"
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        archive_root=archive_root,
    )

    ready = _run_ready(service, candidate_count=2, episode_number=37)
    captioned = service.generate_instagram_caption(ready.id, "s2")

    assert ready.episode_number == 37
    assert set(calls.base_episode_numbers) == {37}
    assert set(calls.episode_texts) == {"에피소드 37 / 1000"}
    assert captioned.storylines[1].instagram_caption.startswith("Ep 37. ")
    assert all(
        Path(story.archive_path or "").parent.name.startswith("Ep-37_")
        for story in ready.storylines
    )
    assert all(Path(story.archive_path or "").is_file() for story in ready.storylines)


def test_fixed_export_is_collision_safe_and_idempotent(tmp_path: Path) -> None:
    calls = Calls()
    archive_root = tmp_path / "Movies" / "Reels Editor"
    unrelated = archive_root / "Ep-9_founder"
    unrelated.mkdir(parents=True)
    (unrelated / "keep.txt").write_text("unrelated", encoding="utf-8")
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        archive_root=archive_root,
    )

    ready = _run_ready(service, candidate_count=1, episode_number=9)
    first_path = Path(ready.storylines[0].archive_path or "")
    exported = service.export_selected(ready.id, storyline_id="s1")
    second_path = Path(exported.export.output_path or "")

    assert first_path.parent.name == "Ep-9_founder (2)"
    assert first_path == second_path
    assert (unrelated / "keep.txt").read_text(encoding="utf-8") == "unrelated"
    assert len(list(first_path.parent.glob("*.mp4"))) == 1


def test_fixed_export_rejects_symlinked_archive_directory(tmp_path: Path) -> None:
    archive_root = tmp_path / "Movies" / "Reels Editor"
    outside = tmp_path / "outside"
    archive_root.mkdir(parents=True)
    outside.mkdir()
    (archive_root / "Ep-9_founder").symlink_to(outside, target_is_directory=True)
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=archive_root,
    )

    ready = _run_ready(service, candidate_count=1, episode_number=9)

    with pytest.raises(JobServiceError, match="symlink|outside archive root"):
        service.export_selected(ready.id, storyline_id="s1")
    assert list(outside.iterdir()) == []


def test_fixed_export_rejects_symlinked_archive_destination(tmp_path: Path) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    destination = Path(ready.storylines[0].archive_path or "")
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"unrelated")
    destination.unlink()
    destination.symlink_to(outside)

    with pytest.raises(JobServiceError, match="symlink"):
        service.export_selected(ready.id, storyline_id="s1")
    assert outside.read_bytes() == b"unrelated"


def test_fixed_export_rejects_symlinked_archive_manifest(tmp_path: Path) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    destination = Path(ready.storylines[0].archive_path or "")
    manifest = destination.with_suffix(destination.suffix + ".manifest.json")
    outside = tmp_path / "outside-manifest.json"
    outside.write_text('{"owner": "unrelated"}', encoding="utf-8")
    manifest.unlink()
    manifest.symlink_to(outside)

    with pytest.raises(JobServiceError, match="symlink"):
        service.export_selected(ready.id, storyline_id="s1")
    assert outside.read_text(encoding="utf-8") == '{"owner": "unrelated"}'


def test_archive_jobs_filters_non_playable_history(tmp_path: Path) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    failed = service.store.create_job(source_url="https://youtu.be/failed")
    failed.status = Status.FAILED
    service.store.save(failed)
    service.store.create_job(source_url="https://youtu.be/analysis-only")

    archived = service.archive_jobs()

    assert [job.id for job in archived] == [ready.id]


def test_archive_promotes_existing_ready_variant_instead_of_listing_deleted_active(
    tmp_path: Path,
) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    good_path = Path(ready.storylines[0].active_variant_path or "")
    stale_path = good_path.with_name("deleted-active.mp4")
    stale_path.write_bytes(b"stale")
    stale_artifact = service.store.register_artifact(ready.id, stale_path, kind="video/mp4")
    stale_path.unlink()
    job = service.store.load(ready.id)
    story = job.storylines[0]
    story.variants.append(
        Variant(
            id=stale_artifact.id,
            title_text="삭제된 제목입니다",
            subtitles_enabled=True,
            status=Status.READY,
            path=str(stale_path),
        )
    )
    story.active_variant_path = str(stale_path)
    service.store.save(job)

    archived = service.archive_jobs()

    assert len(archived) == 1
    promoted = archived[0].storylines[0]
    assert promoted.active_variant_path == str(good_path)
    assert promoted.title == promoted.variants[0].title_text
    assert Path(promoted.active_variant_path).is_file()


def test_archive_reads_are_idempotent_once_artifacts_are_current(tmp_path: Path) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    snapshot_path = service.store.job_dir(ready.id) / "job.json"
    before = service.store.load(ready.id)
    before_bytes = snapshot_path.read_bytes()

    service.archive_jobs()
    service.archive_jobs()

    after = service.store.load(ready.id)
    assert snapshot_path.read_bytes() == before_bytes
    assert after.revision == before.revision
    assert after.updated_at == before.updated_at
    assert after.storylines[0].completed_at == before.storylines[0].completed_at


def test_first_legacy_archive_migration_persists_stable_completion_date(
    tmp_path: Path,
) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    legacy = service.store.load(ready.id)
    legacy.storylines[0].completed_at = None
    legacy.storylines[0].archive_path = None
    service.store.save(legacy)
    before_migration = service.store.load(ready.id)

    service.archive_jobs()

    migrated = service.store.load(ready.id)
    expected_completed_at = before_migration.updated_at
    migrated_bytes = (service.store.job_dir(ready.id) / "job.json").read_bytes()
    service.archive_jobs()

    assert migrated.storylines[0].completed_at == expected_completed_at
    assert service.store.load(ready.id).storylines[0].completed_at == expected_completed_at
    assert (service.store.job_dir(ready.id) / "job.json").read_bytes() == migrated_bytes


def test_title_edit_rerenders_overlay_only_and_invalidates_caption(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1, episode_number=12)
    captioned = service.generate_instagram_caption(ready.id, "s1")
    before = (calls.generate, calls.base, calls.overlay)
    old_path = captioned.storylines[0].active_variant_path

    updated = service.update_storyline_title(ready.id, "s1", " 새로운 제목이다 ")
    story = updated.storylines[0]

    assert story.title == "새로운 제목이다"
    assert story.instagram_caption == ""
    assert story.active_variant_path != old_path
    assert (calls.generate, calls.base) == before[:2]
    assert calls.overlay == before[2] + 1
    assert "새로운 제목이다" in Path(story.active_variant_path or "").read_text(encoding="utf-8")
    assert Path(story.archive_path or "").read_bytes() == Path(story.active_variant_path or "").read_bytes()


def test_title_edit_preserves_explicit_white_and_orange_lines(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)

    updated = service.update_storyline_title(
        ready.id,
        "s1",
        title_upper="고객이 떠난 진짜 이유",
        title_lower="기능보다 복잡한 첫 화면",
    )

    story = updated.storylines[0]
    assert story.title_upper == "고객이 떠난 진짜 이유"
    assert story.title_lower == "기능보다 복잡한 첫 화면"
    assert story.title == "고객이 떠난 진짜 이유 기능보다 복잡한 첫 화면"
    assert calls.overlay_title_lines[-1] == (
        "고객이 떠난 진짜 이유",
        "기능보다 복잡한 첫 화면",
    )
    assert story.variants[-1].title_upper == story.title_upper
    assert story.variants[-1].title_lower == story.title_lower


@pytest.mark.parametrize(
    ("title", "expected_limit"),
    [("다섯글자", "6"), ("가" * 25, "24")],
)
def test_title_edit_rejects_titles_outside_display_bounds(
    tmp_path: Path,
    title: str,
    expected_limit: str,
) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)

    with pytest.raises(JobServiceError, match=expected_limit):
        service.update_storyline_title(ready.id, "s1", title)


def test_failed_title_render_preserves_previous_playable_and_archive_mp4(tmp_path: Path) -> None:
    calls = Calls()
    deps = _deps(tmp_path, calls)
    original_overlay = deps.render_overlay_variant

    def fail_title(assets, *, title_text: str, **kwargs):
        if title_text == "실패하는 제목입니다":
            raise RuntimeError("overlay exploded")
        return original_overlay(assets, title_text=title_text, **kwargs)

    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=replace(deps, render_overlay_variant=fail_title),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    before_story = ready.storylines[0]
    active_path = Path(before_story.active_variant_path or "")
    archive_path = Path(before_story.archive_path or "")
    active_bytes = active_path.read_bytes()
    archive_bytes = archive_path.read_bytes()

    with pytest.raises(JobServiceError, match="overlay exploded"):
        service.update_storyline_title(ready.id, "s1", "실패하는 제목입니다")

    failed = service.store.load(ready.id).storylines[0]
    assert failed.title == before_story.title
    assert failed.active_variant_path == str(active_path)
    assert failed.status is Status.READY
    assert "다시 시도" in (failed.error or "")
    assert active_path.read_bytes() == active_bytes
    assert archive_path.read_bytes() == archive_bytes


def test_failed_title_archive_install_restores_previous_mp4_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, Calls()),
        archive_root=tmp_path / "archive",
    )
    ready = _run_ready(service, candidate_count=1)
    before_story = ready.storylines[0]
    archive_path = Path(before_story.archive_path or "")
    manifest_path = archive_path.with_suffix(archive_path.suffix + ".manifest.json")
    archive_bytes = archive_path.read_bytes()
    manifest_bytes = manifest_path.read_bytes()
    original_replace = job_service_module.os.replace

    def fail_manifest_install(source: Path | str, destination: Path | str) -> None:
        source_path = Path(source)
        destination_path = Path(destination)
        if destination_path == manifest_path and source_path.name.endswith(".part"):
            raise OSError("manifest install exploded")
        original_replace(source, destination)

    monkeypatch.setattr(job_service_module.os, "replace", fail_manifest_install)

    with pytest.raises(JobServiceError, match="manifest install exploded"):
        service.update_storyline_title(ready.id, "s1", "새로운 제목이다")

    failed = service.store.load(ready.id).storylines[0]
    assert failed.title == before_story.title
    assert failed.active_variant_path == before_story.active_variant_path
    assert archive_path.read_bytes() == archive_bytes
    assert manifest_path.read_bytes() == manifest_bytes


def test_job_service_validates_storyline_length_with_configured_playback_speed(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(
        store=JobStore(tmp_path / "jobs"),
        deps=_deps(tmp_path, calls),
        config=AppConfig(provider="codex-cli", style={"speed": 1.45}),
    )

    _run_ready(service)

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
        output_dir.mkdir(parents=True, exist_ok=True)
        segments = _segments(video)
        (output_dir / "segments.json").write_text(json.dumps(segments), encoding="utf-8")
        return YouTubeSource(
            video_path=video,
            segments=segments,
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

    job = _run_ready(service, "https://www.youtube.com/watch?v=abc123")

    assert job.status is Status.READY
    assert job.source_url == "https://www.youtube.com/watch?v=abc123"
    assert job.project_name == "1시간 창업가 인터뷰"
    assert job.input_path == str(video)
    assert job.transcript_language == "ko"
    assert job.transcript_kind == "automatic"
    assert download_args["output_dir"] == tmp_path / "jobs" / job.id / "source"
    assert calls.durations == [35]
    assert calls.base == 3


def test_youtube_job_reuses_complete_prior_download_for_same_video_id(tmp_path: Path) -> None:
    calls = Calls()
    deps = _deps(tmp_path, calls)
    store = JobStore(tmp_path / "jobs")
    prior = store.create_job(
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

    job = _run_ready(service, "https://youtu.be/abc123?si=new")

    assert job.status is Status.READY
    assert job.project_name == "캐시된 창업가 인터뷰"
    assert job.input_path == str(video)
    assert job.transcript_language == "en-orig"
    assert job.transcript_kind == "automatic"
    assert calls.generate == 1
    assert calls.base == 3


def test_job_service_uses_selected_candidate_count_and_provider(tmp_path: Path) -> None:
    calls = Calls()
    results = [StorylineResult(index, f"관점 {index + 1}", _doc(str(index + 1))) for index in range(10)]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = _run_ready(service, candidate_count=10, provider="claude-cli")

    assert job.n_storylines == 10
    assert job.provider == "claude-cli"
    assert len(job.storylines) == 10
    assert calls.storyline_counts == [10]
    assert calls.providers == ["claude-cli", "claude-cli"]


def test_job_service_reports_detailed_progress_during_rendering(tmp_path: Path) -> None:
    calls = Calls()
    entered_render = threading.Event()
    release_render = threading.Event()
    deps = _deps(tmp_path, calls, [StorylineResult(0, "정면승부형", _doc("https://youtu.be/A"))])
    render_base = deps.render_base_and_assets

    def blocking_render_base(*args, **kwargs):
        entered_render.set()
        release_render.wait(3)
        return render_base(*args, **kwargs)

    deps = JobServiceDeps(**{**deps.__dict__, "render_base_and_assets": blocking_render_base})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    analyzed = service.run_youtube_job_sync(TEST_URL)
    job = service.start_selected_generation(analyzed.id, ["c1"])

    try:
        assert entered_render.wait(2)
        current = service.store.load(job.id)
        assert current.phase == "rendering"
        assert current.progress > 0.28
        assert "릴스 1" in (current.message or "")
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

    job = _run_ready(service)

    assert job.status is Status.FAILED
    assert calls.base == 0
    assert calls.overlay == 0


def test_selection_change_rerenders_overlay_only_and_exports_one_selected(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)
    before = (calls.generate, calls.base, calls.overlay)

    selected_story_change = service.select_variant(job.id, "s1", subtitles_on=False)
    selected_story = next(item for item in selected_story_change.storylines if item.id == "s1")
    active_selected_variant = selected_story.variants[-1]

    assert selected_story_change.selected_storyline_id == "s1"
    assert selected_story_change.export.selected_variant_id == active_selected_variant.id
    assert active_selected_variant.selected is True
    assert (calls.generate, calls.base) == before[:2]

    selected = service.select_variant(job.id, "s2", subtitles_on=False)

    assert (calls.generate, calls.base) == before[:2]
    assert calls.overlay == before[2] + 2
    story = next(item for item in selected.storylines if item.id == "s2")
    assert story.subtitles_on is False
    assert selected.selected_storyline_id == "s1"
    assert sum(variant.selected for item in selected.storylines for variant in item.variants) == 1

    selected = service.select_variant(
        job.id,
        "s2",
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
    job = _run_ready(service)
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
    job = _run_ready(service)
    destination = tmp_path / "exports"

    exported = service.export_many(
        job.id,
        destination,
        storyline_ids=["s1", "s3"],
        subtitles_on=False,
    )

    assert sorted(path.name for path in destination.glob("*.mp4")) == [
        "김현지 - 1.mp4",
        "김현지 - 3.mp4",
    ]
    assert sorted(path.name for path in destination.glob("*.manifest.json")) == [
        "김현지 - 1.mp4.manifest.json",
        "김현지 - 3.mp4.manifest.json",
    ]
    assert all(b":False" in path.read_bytes() for path in destination.glob("*.mp4"))
    assert exported.export.output_path == str(destination)


def test_export_filename_uses_sanitized_founder_name_and_storyline_number(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)
    story = next(story for story in job.storylines if story.id == "s3")
    assert story.edl_path is not None
    doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8"))
    doc["speaker"] = {"name": 'Founder: "Build/Ship?" | Interview', "role": "CEO"}
    Path(story.edl_path).write_text(json.dumps(doc), encoding="utf-8")

    assert service.suggested_export_filename(job.id, "s3") == (
        "Founder Build Ship Interview - 3.mp4"
    )


def test_export_filename_stays_within_filesystem_component_limit(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)
    story = next(story for story in job.storylines if story.id == "s1")
    assert story.edl_path is not None
    doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8"))
    doc["speaker"] = {"name": "매우 긴 창업가 이름" * 100, "role": "CEO"}
    Path(story.edl_path).write_text(json.dumps(doc), encoding="utf-8")

    filename = service.suggested_export_filename(job.id, "s1")

    assert filename.endswith(" - 1.mp4")
    assert len(filename.encode("utf-8")) <= 255


def test_batch_export_rejects_empty_selection(tmp_path: Path) -> None:
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, Calls()))
    job = _run_ready(service)

    with pytest.raises(JobServiceError, match="at least one"):
        service.export_many(job.id, tmp_path / "exports", storyline_ids=[])


def test_export_accepts_explicit_completed_storyline_for_archive_reexport(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)

    exported = service.export_selected(job.id, tmp_path / "second.mp4", storyline_id="s2")

    assert exported.export.selected_storyline_id == "s2"
    assert (tmp_path / "second.mp4").is_file()


def test_stale_overlay_request_is_suppressed(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)
    story = next(item for item in job.storylines if item.id == "s1")
    story.render_request_id = 9
    job = service.store.save(job)

    service._render_selection(job.id, "s1", request_id=8)

    after = service.store.load(job.id)
    story_after = next(item for item in after.storylines if item.id == "s1")
    assert story_after.render_request_id == 9
    assert len(story_after.variants) == len(story.variants)


def test_retry_invalidates_old_overlay_cache_for_same_title_choice(tmp_path: Path) -> None:
    calls = Calls()
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls))
    job = _run_ready(service)
    alternate = service.select_variant(job.id, "s1", subtitles_on=False)
    story = next(item for item in alternate.storylines if item.id == "s1")
    old_variant_path = Path(story.active_variant_path or "")
    old_payload = old_variant_path.read_text(encoding="utf-8")

    assert old_payload.startswith("base-v")

    retried = service.retry_storyline(job.id, "s1")
    retry_story = next(item for item in retried.storylines if item.id == "s1")
    retry_overlay_count = calls.overlay
    retry_base_count = calls.base

    rerendered = service.select_variant(retried.id, "s1", subtitles_on=False)
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
    malformed = json.dumps(_doc("복구 성공"), ensure_ascii=False).replace(
        '"복구 성공 제목 1"', '“복구 성공 제목 1"', 1
    )
    (store.job_dir(job.id) / "llm_raw_s1.txt").write_text(malformed, encoding="utf-8")

    recovered = service.retry_storyline(job.id, "s1")
    story = recovered.storylines[0]

    assert recovered.status is Status.READY
    assert story.status is Status.READY
    assert story.title == "복구 성공 제목 1"
    assert story.edl_path is not None


def test_cancel_marks_active_job_and_blocks_second_active_job(tmp_path: Path) -> None:
    calls = Calls()

    def slow_analyze(*_args, **_kwargs):
        time.sleep(0.2)
        return _candidates()

    deps = _deps(tmp_path, calls)
    deps = JobServiceDeps(**{**deps.__dict__, "analyze_candidates": slow_analyze})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_youtube_job(TEST_URL)

    with pytest.raises(JobServiceError):
        service.start_youtube_job("https://youtu.be/other")

    cancelled = service.cancel(job.id)
    time.sleep(0.25)

    assert cancelled.status is Status.CANCELLED
    assert service.store.load(job.id).status is Status.CANCELLED


def test_cancelled_job_cannot_resume_after_new_job_replaces_active_slot(tmp_path: Path) -> None:
    calls = Calls()
    release_generate = threading.Event()
    entered_generate = threading.Event()

    def slow_analyze(*_args, **_kwargs):
        entered_generate.set()
        release_generate.wait(2)
        return _candidates()

    deps = _deps(tmp_path, calls)
    deps = JobServiceDeps(**{**deps.__dict__, "analyze_candidates": slow_analyze})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job_a = service.start_youtube_job("https://youtu.be/A")
    assert entered_generate.wait(2)
    cancelled_a = service.cancel(job_a.id)

    with pytest.raises(JobServiceError):
        service.start_youtube_job("https://youtu.be/B")

    release_generate.set()
    time.sleep(0.25)

    job_b = service.start_youtube_job("https://youtu.be/B")
    time.sleep(0.25)

    assert cancelled_a.status is Status.CANCELLED
    assert service.store.load(job_a.id).status is Status.CANCELLED
    assert service.store.load(job_b.id).status is Status.AWAITING_SELECTION
    assert service.store.load(job_b.id).phase == "awaiting_selection"
    assert service.store.load(job_b.id).project_name == "B"


def test_cancel_terminates_runner_process_spawned_inside_generation_thread(tmp_path: Path) -> None:
    calls = Calls()
    pid_file = tmp_path / "runner.pid"

    def threaded_analyze(*_args, runner, **_kwargs):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(runner, "prompt")
            try:
                future.result()
            except RuntimeError:
                return _candidates()
        return _candidates()

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
    deps = JobServiceDeps(**{**deps.__dict__, "analyze_candidates": threaded_analyze, "build_runner": build_runner})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    job = service.start_youtube_job(TEST_URL)

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
    job = _run_ready(service)
    slow_overlay.set()
    errors: list[BaseException] = []
    thread = threading.Thread(
        target=lambda: _capture_exception(
            errors,
            service.select_variant,
            job.id,
            "s1",
            subtitles_on=False,
        )
    )
    thread.start()

    deadline = time.time() + 5
    while not pid_file.is_file() and time.time() < deadline:
        time.sleep(0.02)
    assert pid_file.is_file()
    pid = int(pid_file.read_text(encoding="utf-8"))

    with pytest.raises(JobServiceError):
        service.start_youtube_job("https://youtu.be/B")

    service.cancel(job.id)
    thread.join(timeout=3)

    assert not thread.is_alive()
    assert errors
    assert subprocess.run(["ps", "-p", str(pid)], capture_output=True, text=True).returncode != 0
    assert service.store.load(job.id).status is Status.CANCELLED

    slow_overlay.clear()
    replacement = service.start_youtube_job("https://youtu.be/B")
    deadline = time.time() + 3
    while service.store.load(replacement.id).status is not Status.AWAITING_SELECTION and time.time() < deadline:
        time.sleep(0.05)
    assert service.store.load(replacement.id).status is Status.AWAITING_SELECTION


def test_overlay_completion_does_not_release_active_slot_while_base_renders_continue(tmp_path: Path) -> None:
    calls = Calls()
    release_remaining = threading.Event()
    results = [
        StorylineResult(0, "정면승부형", _doc("https://youtu.be/A")),
        StorylineResult(1, "반전형", _doc("https://youtu.be/B")),
        StorylineResult(2, "감정선형", _doc("C")),
    ]
    deps = _deps(tmp_path, calls, results)
    render_base = deps.render_base_and_assets

    def staged_render_base(video, segments, doc, style, out_dir, speed, **kwargs):
        if out_dir.parent.name != "s1":
            release_remaining.wait(3)
        return render_base(video, segments, doc, style, out_dir, speed, **kwargs)

    deps = JobServiceDeps(**{**deps.__dict__, "render_base_and_assets": staged_render_base})
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=deps)
    analyzed = service.run_youtube_job_sync(TEST_URL)
    job = service.start_selected_generation(analyzed.id, ["c1", "c2", "c3"])

    deadline = time.time() + 3
    while time.time() < deadline:
        current = service.store.load(job.id)
        if current.storylines and current.storylines[0].status is Status.READY:
            break
        time.sleep(0.02)
    else:
        pytest.fail("first storyline did not become ready")

    service.select_variant(job.id, "s1", subtitles_on=False)

    with pytest.raises(JobServiceError, match="another job is already active"):
        service.start_youtube_job("https://youtu.be/replacement")

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


def test_candidate_title_becomes_the_rendered_reel_title(tmp_path: Path) -> None:
    calls = Calls()
    results = [StorylineResult(0, "전략형", _doc("https://youtu.be/A"), title="광고비 0원, 첫 고객")]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    job = _run_ready(service, candidate_count=1)

    story = job.storylines[0]
    assert story.title == "광고비 0원, 첫 고객"
    assert story.variants[0].title_text == "광고비 0원, 첫 고객"
    assert "광고비 0원, 첫 고객" in Path(story.active_variant_path).read_text(encoding="utf-8")


def test_rendered_title_has_no_highlight_keyword(tmp_path: Path) -> None:
    calls = Calls()
    results = [StorylineResult(0, "전략형", _doc("https://youtu.be/A"), title="직원 셋, 같은 날 퇴사")]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))

    _run_ready(service, candidate_count=1)

    assert calls.overlay_keywords == [""]


def test_subtitle_toggle_keeps_the_candidate_title(tmp_path: Path) -> None:
    calls = Calls()
    results = [StorylineResult(0, "전략형", _doc("https://youtu.be/A"), title="매출보다 먼저 무너진 것")]
    service = JobService(store=JobStore(tmp_path / "jobs"), deps=_deps(tmp_path, calls, results))
    job = _run_ready(service, candidate_count=1)

    toggled = service.select_variant(job.id, "s1", subtitles_on=False)

    story = next(item for item in toggled.storylines if item.id == "s1")
    assert story.title == "매출보다 먼저 무너진 것"
    assert story.subtitles_on is False
    assert story.variants[-1].title_text == "매출보다 먼저 무너진 것"
    assert set(calls.overlay_keywords) == {""}
