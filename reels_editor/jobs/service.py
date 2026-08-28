from __future__ import annotations

import json
import hashlib
import os
import re
import shutil
import subprocess
import threading
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from reels_editor import candidate_analyzer, edl, export, instagram_caption, render, youtube
from reels_editor.config import AppConfig, merged_style
from reels_editor.llm import build_runner
from reels_editor.processes import ProcessRegistry, use_process_registry
from reels_editor.storyteller import (
    StorylineResult,
    generate_script,
    harmonize_speaker_metadata,
)
from reels_editor.style import StylePreset, load_style
from reels_editor.title_rules import (
    editor_title_lines,
    normalize_title,
    validate_editor_title_lines,
    validate_title,
)

from .models import ContentCandidate, ExportState, Job, Status, Storyline, Variant
from .store import JobStore

DEFAULT_STYLE = Path(__file__).parent.parent.parent / "styles" / "done.yaml"
MAX_DESKTOP_STORYLINES = 10
MAX_BASE_RENDERS = 2
DESKTOP_PROVIDERS = frozenset({"codex-cli", "claude-cli", "gemini-cli", "openai", "kimi"})
EXPORT_TITLE_MAX_BYTES = 220
DEFAULT_EPISODE_NUMBER = 1
_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_FILENAME_WHITESPACE = re.compile(r"\s+")


class JobServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobServiceDeps:
    analyze_candidates: Callable[..., list[ContentCandidate]] = candidate_analyzer.generate_candidates
    generate_selected_candidates: Callable[..., list[StorylineResult]] = candidate_analyzer.generate_selected_candidates
    generate_instagram_caption: Callable[..., str] = instagram_caption.generate_caption
    generate_script: Callable[..., dict[str, Any]] = generate_script
    build_runner: Callable[[AppConfig], Callable[[str], str]] = build_runner
    load_style: Callable[[Path], StylePreset] = load_style
    render_base_and_assets: Callable[..., render.RenderAssets] = render.render_base_and_assets
    render_overlay_variant: Callable[..., Path] = render.render_overlay_variant
    write_outputs: Callable[[Path, dict[str, Any], dict[str, Any]], None] = export.write_outputs
    write_srt: Callable[[list[list], Path], Path] = export.write_srt
    download_youtube_source: Callable[..., youtube.YouTubeSource] = youtube.download_youtube_source


class JobService:
    def __init__(
        self,
        *,
        store: JobStore | None = None,
        deps: JobServiceDeps | None = None,
        style_path: Path = DEFAULT_STYLE,
        config: AppConfig | None = None,
        archive_root: Path | None = None,
    ) -> None:
        self.store = store or JobStore()
        self.deps = deps or JobServiceDeps()
        self.style_path = style_path
        self.config = config or AppConfig(provider="codex-cli", n_storylines=3)
        self.archive_root = (
            archive_root.expanduser()
            if archive_root is not None
            else self._default_archive_root()
        )
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._active_job_id: str | None = None
        self._worker: threading.Thread | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._process_registries: dict[str, ProcessRegistry] = {}
        self._operation_counts: dict[str, int] = {}
        self._shutdown = threading.Event()
        self._archive_lock = threading.RLock()

    def _default_archive_root(self) -> Path:
        if self.store.root == JobStore.default_root():
            return Path.home() / "Movies" / "Reels Editor"
        return self.store.root.parent / "Reels Editor Archive"

    def start_youtube_job(
        self,
        youtube_url: str,
        *,
        content_types: list[str] | None = None,
        provider: str | None = None,
        episode_number: int = DEFAULT_EPISODE_NUMBER,
    ) -> Job:
        source_url = youtube.validate_youtube_url(youtube_url)
        selected_types = self._validated_content_types(content_types)
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._create_job(
                self._validated_provider(provider),
                source_url=source_url,
                content_types=selected_types,
                episode_number=episode_number,
            )
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
            self._worker = threading.Thread(
                target=self._run_job_guarded,
                args=(job.id,),
                daemon=True,
                name=f"reels-analyze-{job.id[:8]}",
            )
            self._worker.start()
            return job

    def run_youtube_job_sync(
        self,
        youtube_url: str,
        *,
        content_types: list[str] | None = None,
        provider: str | None = None,
        episode_number: int = DEFAULT_EPISODE_NUMBER,
    ) -> Job:
        source_url = youtube.validate_youtube_url(youtube_url)
        selected_types = self._validated_content_types(content_types)
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._create_job(
                self._validated_provider(provider),
                source_url=source_url,
                content_types=selected_types,
                episode_number=episode_number,
            )
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
        self._run_job_guarded(job.id)
        return self.store.load(job.id)

    def start_selected_generation(self, job_id: str, candidate_ids: list[str]) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._prepare_selected_generation(job_id, candidate_ids)
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
            self._worker = threading.Thread(
                target=self._run_generation_guarded,
                args=(job.id,),
                daemon=True,
                name=f"reels-generate-{job.id[:8]}",
            )
            self._worker.start()
            return job

    def generate_selected_sync(self, job_id: str, candidate_ids: list[str]) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._prepare_selected_generation(job_id, candidate_ids)
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
        self._run_generation_guarded(job.id)
        return self.store.load(job.id)

    def snapshot(self, job_id: str | None = None) -> Job | None:
        with self._lock:
            if job_id is not None:
                return self.store.load(job_id)
            if self._active_job_id is not None:
                return self.store.load(self._active_job_id)
            return self.store.current_job()

    def clear_current(self) -> None:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("cannot clear the project while a job is active")
            self.store.clear_current()
            self._condition.notify_all()

    def open_job(self, job_id: str) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("cannot open another project while a job is active")
            job = self.store.set_current(job_id)
            self._condition.notify_all()
            return job

    def archive_jobs(self) -> list[Job]:
        """Return historical jobs containing at least one playable completed reel.

        Existing ready jobs are migrated lazily into durable archive storage. A
        migration failure never removes the internal playable artifact.
        """
        archived: list[Job] = []
        for candidate in self.store.list_recent(limit=1000):
            playable_ids = [
                story.id
                for story in candidate.storylines
                if self._storyline_is_playable(story)
            ]
            if not playable_ids:
                continue
            for storyline_id in playable_ids:
                try:
                    self._ensure_playback_artifact(candidate.id, storyline_id)
                    self._ensure_durable_export(
                        candidate.id,
                        storyline_id,
                        completed_at_fallback=(
                            candidate.updated_at or candidate.created_at or None
                        ),
                    )
                except (OSError, ValueError, JobServiceError):
                    pass
            archived.append(self.store.load(candidate.id))
        return archived

    def wait_for_update(self, after_seq: int, timeout: float | None = None) -> Job | None:
        with self._condition:
            def newer() -> Job | None:
                job = self.snapshot()
                return job if job is not None and job.seq > after_seq else None

            current = newer()
            if current is not None:
                return current
            self._condition.wait_for(lambda: self._shutdown.is_set() or newer() is not None, timeout=timeout)
            return newer()

    def cancel(self, job_id: str | None = None) -> Job:
        with self._lock:
            job = self._require_job(job_id)
            self._cancel_for(job.id).set()
            registry = self._process_registries.get(job.id)
            if registry is not None:
                registry.terminate_all()
            job.status = Status.CANCELLED
            job.phase = "cancelled"
            job.message = "작업이 취소되었습니다."
            for storyline in job.storylines:
                if storyline.status in {Status.LOADING, Status.GENERATING, Status.RENDERING_BASE, Status.RENDERING_OVERLAY}:
                    storyline.status = Status.CANCELLED
                    storyline.error = storyline.error or "cancelled"
            saved = self._save(job)
            return saved

    def shutdown(self) -> None:
        self._shutdown.set()
        with self._lock:
            active = self._active_job_id
        if active is not None:
            try:
                self.cancel(active)
            except JobServiceError:
                pass
        else:
            for event in self._cancel_events.values():
                event.set()
            for registry in self._process_registries.values():
                registry.terminate_all()
        with self._condition:
            self._condition.notify_all()
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=2)

    def select_variant(
        self,
        job_id: str,
        storyline_id: str,
        *,
        subtitles_on: bool,
        selected_for_export: bool = False,
    ) -> Job:
        with self._lock:
            job = self.store.load(job_id)
            storyline = self._find_storyline(job, storyline_id)
            if storyline.status not in {Status.READY, Status.RENDERING_OVERLAY}:
                raise JobServiceError("storyline is not ready for subtitle selection")
            storyline.subtitles_on = subtitles_on
            storyline.render_request_id += 1
            request_id = storyline.render_request_id
            storyline.status = Status.RENDERING_OVERLAY
            storyline.progress = 0.94
            job.status = Status.RENDERING_OVERLAY
            job.phase = "overlay"
            job.message = "자막 오버레이를 반영하는 중입니다."
            self._save(job)

        with self._job_operation(job_id):
            self._render_selection(
                job_id,
                storyline_id,
                request_id,
                selected_for_export=selected_for_export,
            )
        return self.store.load(job_id)

    def select_for_export(self, job_id: str, storyline_id: str) -> Job:
        with self._lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            variant = self._active_variant(story)
            if variant.path is None or variant.status is not Status.READY:
                raise JobServiceError("storyline has no ready variant to select")
            return self._select_export_variant(job, story, variant)

    def retry_storyline(self, job_id: str, storyline_id: str) -> Job:
        with self._lock:
            job = self.store.load(job_id)
            storyline = self._find_storyline(job, storyline_id)
            if not storyline.edl_path:
                storyline.status = Status.GENERATING
                storyline.error = None
                storyline.progress = 0.05
                self._save(job)
                recover_generation = True
            else:
                recover_generation = False
                self._invalidate_storyline_variants(job, storyline)
                storyline.status = Status.RENDERING_BASE
                storyline.error = None
                storyline.progress = 0.2
                self._save(job)
        with self._job_operation(job_id):
            if recover_generation:
                self._recover_failed_generation(job_id, storyline_id)
            else:
                self._render_storyline_base(job_id, storyline_id)
        return self.store.load(job_id)

    def generate_instagram_caption(self, job_id: str, storyline_id: str) -> Job:
        with self._lock:
            job = self.store.load(job_id)
            storyline = self._find_storyline(job, storyline_id)
            if storyline.status is not Status.READY:
                raise JobServiceError("완성된 릴스만 Instagram 캡션을 만들 수 있습니다.")
            if not storyline.edl_path or not Path(storyline.edl_path).is_file():
                raise JobServiceError("릴스 대본 파일을 찾지 못했습니다.")
            segments_path = Path(storyline.edl_path).parent / "segments.json"
            if not segments_path.is_file():
                raise JobServiceError("릴스 원문 구간 파일을 찾지 못했습니다.")
            title = storyline.title or "창업가 인사이트"
            episode_number = job.episode_number
            candidate = self._candidate_for_storyline(job, storyline)
            provider = job.provider or self.config.provider
            cfg = AppConfig(
                provider=provider,
                model=job.model or "",
                base_url=self.config.base_url if provider == self.config.provider else "",
                n_storylines=job.n_storylines,
                style=dict(self.config.style),
            )
            edl_path = Path(storyline.edl_path)
            raw_dump = self.store.job_dir(job.id) / f"instagram_caption_raw_s{episode_number}.txt"

        doc = json.loads(edl_path.read_text(encoding="utf-8"))
        segments = json.loads(segments_path.read_text(encoding="utf-8"))
        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        runner = self.deps.build_runner(cfg)

        def managed_runner(prompt: str) -> str:
            with use_process_registry(registry):
                return runner(prompt)

        try:
            caption = self.deps.generate_instagram_caption(
                episode_number=episode_number,
                selected_title=title,
                candidate=candidate.to_dict() if candidate else None,
                doc=doc,
                segments=segments,
                runner=managed_runner,
                raw_dump=raw_dump,
            )
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            raise JobServiceError(str(exc)) from exc

        with self._lock:
            current = self.store.load(job_id)
            current_storyline = self._find_storyline(current, storyline_id)
            current_storyline.instagram_caption = caption
            return self._save(current)

    def update_storyline_title(
        self,
        job_id: str,
        storyline_id: str,
        title: str | None = None,
        *,
        title_upper: str | None = None,
        title_lower: str | None = None,
    ) -> Job:
        if title_upper is None and title_lower is None:
            normalized = validate_reel_title(title or "")
            normalized_upper, normalized_lower = editor_title_lines(normalized)
        else:
            try:
                normalized_upper, normalized_lower, normalized = validate_editor_title_lines(
                    title_upper or "",
                    title_lower or "",
                )
            except ValueError as exc:
                raise JobServiceError(str(exc)) from exc
        with self._lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            if not self._storyline_is_playable(story) or not story.assets_path:
                raise JobServiceError("완성된 릴스의 제목만 수정할 수 있습니다.")
            previous_title = story.title
            previous_title_upper = story.title_upper
            previous_title_lower = story.title_lower
            previous_caption = story.instagram_caption
            previous_story_status = story.status
            previous_story_progress = story.progress
            previous_job_status = job.status
            previous_job_phase = job.phase
            previous_job_progress = job.progress
            story.title = normalized
            story.title_upper = normalized_upper
            story.title_lower = normalized_lower
            story.instagram_caption = ""
            story.status = Status.RENDERING_OVERLAY
            story.progress = 0.94
            story.error = None
            story.render_request_id += 1
            request_id = story.render_request_id
            job.status = Status.RENDERING_OVERLAY
            job.phase = "overlay"
            job.message = "수정한 제목 오버레이를 반영하는 중입니다."
            self._save(job)

        try:
            with self._job_operation(job_id):
                current = self.store.load(job_id)
                story = self._find_storyline(current, storyline_id)
                style = self._style_for_episode(
                    merged_style(self.deps.load_style(self.style_path), self.config.style),
                    current.episode_number,
                )
                assets = render.RenderAssets.read_manifest(Path(story.assets_path or ""))
                doc = self._harmonized_storyline_doc(current, story)
                speaker_text = render.speaker_label(doc)
                key = render.variant_cache_key(
                    storyline_id=storyline_id,
                    title_text=normalized,
                    subtitles_enabled=story.subtitles_on,
                    style_hash_value=(
                        f"{render.style_hash(style)}-"
                        f"{_assets_fingerprint(Path(story.assets_path or ''), assets)}"
                    ),
                    speaker_text=speaker_text,
                    title_upper=normalized_upper,
                    title_lower=normalized_lower,
                )
                out = Path(story.assets_path or "").parent.parent / f"{key}.mp4"
                if not out.is_file():
                    render_tmp = out.with_name(
                        f".{out.stem}.{os.getpid()}.{threading.get_ident()}.part.mp4"
                    )
                    try:
                        self.deps.render_overlay_variant(
                            assets,
                            title_text=normalized,
                            keyword="",
                            style=style,
                            out_path=render_tmp,
                            subtitles_enabled=story.subtitles_on,
                            speaker_text=speaker_text,
                            title_upper=normalized_upper,
                            title_lower=normalized_lower,
                        )
                        if not render_tmp.is_file():
                            raise JobServiceError("overlay renderer produced no MP4")
                        os.replace(render_tmp, out)
                    finally:
                        if render_tmp.exists():
                            render_tmp.unlink()
                candidate = Variant(
                    id="",
                    title_text=normalized,
                    subtitles_enabled=story.subtitles_on,
                    subtitles_on=story.subtitles_on,
                    style_hash=render.style_hash(style),
                    status=Status.READY,
                    path=str(out),
                    title_upper=normalized_upper,
                    title_lower=normalized_lower,
                )
                with self._lock:
                    latest = self.store.load(job_id)
                    latest_story = self._find_storyline(latest, storyline_id)
                    if latest_story.render_request_id != request_id:
                        return latest
                    artifact_id = self._artifact_id_for_path(latest, out)
                    artifact = (
                        latest.artifacts[artifact_id]
                        if artifact_id
                        else self.store.register_artifact(job_id, out, kind="video/mp4")
                    )
                    candidate.id = artifact.id
                archive_path = self._durable_destination(current, story)
                archive_path = self._copy_export_variant(
                    job_id,
                    story,
                    candidate,
                    archive_path,
                )

                with self._lock:
                    latest = self.store.load(job_id)
                    latest_story = self._find_storyline(latest, storyline_id)
                    if latest_story.render_request_id != request_id:
                        return latest
                    latest_story.variants = [
                        item for item in latest_story.variants if item.path != str(out)
                    ]
                    latest_story.variants.append(candidate)
                    latest_story.active_variant_path = str(out)
                    latest_story.archive_path = str(archive_path)
                    latest_story.title = normalized
                    latest_story.title_upper = normalized_upper
                    latest_story.title_lower = normalized_lower
                    latest_story.instagram_caption = ""
                    latest_story.status = Status.READY
                    latest_story.progress = 1.0
                    latest_story.error = None
                    latest.status = (
                        previous_job_status
                        if previous_job_status is Status.FAILED
                        else Status.READY
                    )
                    latest.phase = (
                        previous_job_phase
                        if previous_job_status is Status.FAILED
                        else "ready"
                    )
                    latest.progress = (
                        previous_job_progress
                        if previous_job_status is Status.FAILED
                        else 1.0
                    )
                    latest.message = "수정한 제목이 영상에 반영되었습니다."
                    saved = self._save(latest)
                    if saved.selected_storyline_id == storyline_id:
                        saved_story = self._find_storyline(saved, storyline_id)
                        return self._select_export_variant(saved, saved_story, candidate)
                    return saved
        except Exception as exc:  # noqa: BLE001 - restore prior playable state atomically
            with self._lock:
                failed = self.store.load(job_id)
                failed_story = self._find_storyline(failed, storyline_id)
                failed_story.title = previous_title
                failed_story.title_upper = previous_title_upper
                failed_story.title_lower = previous_title_lower
                failed_story.instagram_caption = previous_caption
                failed_story.status = previous_story_status
                failed_story.progress = previous_story_progress
                failed_story.error = f"제목 수정에 실패했습니다. 다시 시도하세요: {exc}"
                failed.status = previous_job_status
                failed.phase = previous_job_phase
                failed.progress = previous_job_progress
                failed.message = "제목 수정에 실패했습니다. 이전 영상을 유지합니다."
                self._save(failed)
            raise JobServiceError(str(exc)) from exc

    def _recover_failed_generation(self, job_id: str, storyline_id: str) -> None:
        """저장된 마지막 LLM 응답을 새 파서로 복구해 실패한 후보만 렌더한다."""
        job = self.store.load(job_id)
        storyline = self._find_storyline(job, storyline_id)
        work = self.store.job_dir(job_id)
        raw_path = work / f"llm_raw_s{storyline.index + 1}.txt"
        segments_path = self._recovery_segments_path(job, work)
        if not raw_path.is_file() or not segments_path.is_file():
            raise JobServiceError(
                "실패한 AI 응답 또는 원본 자막을 찾지 못했습니다. 전체 작업을 다시 생성하세요."
            )
        segments = json.loads(segments_path.read_text(encoding="utf-8"))
        raw = raw_path.read_text(encoding="utf-8")
        style = self._style_for_episode(
            merged_style(self.deps.load_style(self.style_path), self.config.style),
            job.episode_number,
        )
        try:
            doc = self.deps.generate_script(
                segments,
                job.duration_s,
                runner=lambda _prompt: raw,
                raw_dump=raw_path,
                speed=style.speed,
            )
        except RuntimeError as exc:
            with self._lock:
                current = self.store.load(job_id)
                failed = self._find_storyline(current, storyline_id)
                failed.status = Status.FAILED
                failed.progress = 1.0
                failed.error = str(exc)
                self._save(current)
            raise JobServiceError(str(exc)) from exc

        with self._lock:
            current = self.store.load(job_id)
            recovered = self._find_storyline(current, storyline_id)
            if not recovered.title:
                recovered.title = _fallback_doc_title(doc)
            recovered.status = Status.RENDERING_BASE
            recovered.progress = 0.2
            recovered.error = None
            self._save(current)

        result = StorylineResult(
            storyline.index, storyline.angle_name, doc, title=storyline.title
        )
        self._render_storyline_from_result(
            job_id,
            result,
            segments,
            Path(segments["video_path"]),
            style,
            style.speed,
        )
        with self._lock:
            current = self.store.load(job_id)
            ready = sum(item.status is Status.READY for item in current.storylines)
            current.progress = 1.0
            if ready == current.n_storylines:
                current.status = Status.READY
                current.phase = "ready"
                current.error = None
                current.message = f"대표 영상 {ready}개가 준비되었습니다."
            else:
                current.status = Status.FAILED
                current.phase = "partial-failure"
                current.error = f"대표 영상 {ready}/{current.n_storylines}개만 준비되었습니다."
                current.message = current.error
            self._save(current)

    def export_selected(
        self,
        job_id: str,
        destination: Path | None = None,
        *,
        storyline_id: str | None = None,
        subtitles_on: bool | None = None,
    ) -> Job:
        initial = self.store.load(job_id)
        selected_storyline_id = storyline_id or initial.selected_storyline_id or initial.export.selected_storyline_id
        if not selected_storyline_id:
            raise JobServiceError("storyline_id is required")
        story_for_request = self._find_storyline(initial, selected_storyline_id)
        if subtitles_on is not None and story_for_request.subtitles_on != subtitles_on:
            self.select_variant(
                job_id,
                selected_storyline_id,
                subtitles_on=subtitles_on,
                selected_for_export=True,
            )
        with self._lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, selected_storyline_id)
            variant = self._active_variant(story)
            if variant.path is None or variant.status is not Status.READY:
                raise JobServiceError("selected variant is not ready")
            job = self.store.select_export(job.id, storyline_id=story.id, variant_id=variant.id)
            job.export.status = Status.EXPORTING
            job.phase = "export"
            job.message = "선택한 영상을 내보내는 중입니다."
            self._save(job)

        if destination is None:
            destination = self._durable_destination(job, story)
        try:
            destination = self._copy_export_variant(job_id, story, variant, destination)
        except Exception as exc:
            self._record_export_failure(job_id, exc)
            raise

        with self._lock:
            job = self.store.load(job_id)
            job.export.status = Status.READY
            job.export.output_path = str(destination)
            job.export.error = None
            job.phase = "ready"
            job.message = "내보내기가 완료되었습니다."
            if self._is_archive_path(destination):
                exported_story = self._find_storyline(job, selected_storyline_id)
                exported_story.archive_path = str(destination)
            return self._save(job)

    def suggested_export_filename(
        self,
        job_id: str,
        storyline_id: str | None = None,
    ) -> str:
        job = self.store.load(job_id)
        selected_storyline_id = (
            storyline_id
            or job.selected_storyline_id
            or job.export.selected_storyline_id
        )
        story = self._find_storyline(job, selected_storyline_id)
        return _export_filename(job, story)

    def export_many(
        self,
        job_id: str,
        destination_dir: Path | None = None,
        *,
        storyline_ids: list[str],
        subtitles_on: bool | None = None,
    ) -> Job:
        selected_ids = list(dict.fromkeys(storyline_ids))
        if not selected_ids:
            raise JobServiceError("at least one storyline_id is required")

        initial = self.store.load(job_id)
        for storyline_id in selected_ids:
            story = self._find_storyline(initial, storyline_id)
            if subtitles_on is not None and story.subtitles_on != subtitles_on:
                self.select_variant(
                    job_id,
                    storyline_id,
                    subtitles_on=subtitles_on,
                    selected_for_export=False,
                )

        with self._lock:
            job = self.store.load(job_id)
            exports: list[tuple[Storyline, Variant]] = []
            for storyline_id in selected_ids:
                story = self._find_storyline(job, storyline_id)
                variant = self._active_variant(story)
                if variant.path is None or variant.status is not Status.READY:
                    raise JobServiceError(f"selected variant is not ready: {storyline_id}")
                exports.append((story, variant))
            job.export.status = Status.EXPORTING
            job.phase = "export"
            job.message = f"선택한 영상 {len(exports)}개를 내보내는 중입니다."
            self._save(job)

        if destination_dir is None:
            destination_dir = self._durable_job_directory(job)
        destination_dir = destination_dir.expanduser()
        destination_dir.mkdir(parents=True, exist_ok=True)
        try:
            for story, variant in exports:
                destination = (
                    self._durable_destination(job, story, directory=destination_dir)
                    if self._is_archive_directory(destination_dir)
                    else destination_dir / _export_filename(job, story)
                )
                actual = self._copy_export_variant(job_id, story, variant, destination)
                with self._lock:
                    current = self.store.load(job_id)
                    current_story = self._find_storyline(current, story.id)
                    if self._is_archive_path(actual):
                        current_story.archive_path = str(actual)
                    self._save(current)
        except Exception as exc:
            self._record_export_failure(job_id, exc)
            raise

        with self._lock:
            job = self.store.load(job_id)
            job.export.status = Status.READY
            job.export.output_path = str(destination_dir)
            job.export.error = None
            job.phase = "ready"
            job.message = f"선택한 영상 {len(exports)}개 내보내기가 완료되었습니다."
            return self._save(job)

    def _copy_export_variant(
        self,
        job_id: str,
        story: Storyline,
        variant: Variant,
        destination: Path,
    ) -> Path:
        with self._archive_lock:
            if variant.path is None:
                raise JobServiceError("selected variant has no output path")
            destination = destination.expanduser()
            if self._is_archive_namespace_path(destination):
                self._assert_safe_archive_directory(destination.parent)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
            destination = self._collision_safe_destination(
                destination,
                job_id=job_id,
                storyline_id=story.id,
            )
            operation_id = f"{os.getpid()}.{threading.get_ident()}.{uuid.uuid4().hex}"
            tmp = destination.with_name(
                f".{destination.stem}.{operation_id}.part{destination.suffix}"
            )
            manifest = destination.with_suffix(destination.suffix + ".manifest.json")
            manifest_tmp = manifest.with_name(f".{manifest.name}.{operation_id}.part")
            destination_backup = destination.with_name(
                f".{destination.name}.{operation_id}.backup"
            )
            manifest_backup = manifest.with_name(
                f".{manifest.name}.{operation_id}.backup"
            )
            destination_existed = destination.is_file()
            manifest_existed = manifest.is_file()
            for output in (
                destination,
                manifest,
                tmp,
                manifest_tmp,
                destination_backup,
                manifest_backup,
            ):
                self._assert_safe_export_output(output)
            try:
                self._copy_file_exclusive(Path(variant.path), tmp)
                with manifest_tmp.open("x", encoding="utf-8") as file:
                    file.write(json.dumps(
                        {
                            "job_id": job_id,
                            "storyline_id": story.id,
                            "variant_id": variant.id,
                            "title": variant.title_text,
                            "subtitles_on": variant.subtitles_enabled,
                            "output_path": str(destination),
                        },
                        ensure_ascii=False,
                        indent=2,
                    ))
                if destination_existed:
                    self._backup_export_file(destination, destination_backup)
                if manifest_existed:
                    self._backup_export_file(manifest, manifest_backup)
                os.replace(tmp, destination)
                os.replace(manifest_tmp, manifest)
            except Exception:
                self._restore_export_file(
                    destination,
                    destination_backup,
                    existed=destination_existed,
                )
                self._restore_export_file(
                    manifest,
                    manifest_backup,
                    existed=manifest_existed,
                )
                raise
            finally:
                for temporary in (
                    tmp,
                    manifest_tmp,
                    destination_backup,
                    manifest_backup,
                ):
                    if temporary.exists() or temporary.is_symlink():
                        temporary.unlink()
            return destination

    @staticmethod
    def _copy_file_exclusive(source: Path, destination: Path) -> None:
        with source.open("rb") as source_file, destination.open("xb") as output_file:
            shutil.copyfileobj(source_file, output_file)
        shutil.copystat(source, destination, follow_symlinks=False)

    @staticmethod
    def _backup_export_file(source: Path, backup: Path) -> None:
        try:
            os.link(source, backup)
        except OSError:
            if backup.exists() or backup.is_symlink():
                raise
            JobService._copy_file_exclusive(source, backup)

    @staticmethod
    def _restore_export_file(destination: Path, backup: Path, *, existed: bool) -> None:
        if existed and backup.is_file():
            os.replace(backup, destination)
        elif not existed and destination.exists():
            destination.unlink()

    def _ensure_durable_export(
        self,
        job_id: str,
        storyline_id: str,
        *,
        completed_at_fallback: str | None = None,
    ) -> Path:
        with self._archive_lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            if not self._storyline_is_playable(story):
                raise JobServiceError("storyline has no playable completed variant")
            variant = self._active_variant(story)
            destination = self._durable_destination(job, story)
            actual = (
                destination
                if self._destination_is_current(destination, job_id, story, variant)
                else self._copy_export_variant(job_id, story, variant, destination)
            )
            with self._lock:
                current = self.store.load(job_id)
                current_story = self._find_storyline(current, storyline_id)
                changed = False
                if current_story.archive_path != str(actual):
                    current_story.archive_path = str(actual)
                    changed = True
                if not current_story.completed_at and completed_at_fallback:
                    current_story.completed_at = completed_at_fallback
                    changed = True
                if changed:
                    self._save(current)
            return actual

    def _ensure_playback_artifact(self, job_id: str, storyline_id: str) -> None:
        with self._lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            variant = self._active_variant(story)
            artifact_id = self._artifact_id_for_path(job, Path(variant.path or ""))
            if artifact_id is None:
                artifact = self.store.register_artifact(
                    job_id,
                    Path(variant.path or ""),
                    kind="video/mp4",
                )
                artifact_id = artifact.id
                current = self.store.load(job_id)
            else:
                current = job
            current_story = self._find_storyline(current, storyline_id)
            current_variant = next(
                (item for item in current_story.variants if item.path == variant.path),
                None,
            )
            changed = False
            if current_story.active_variant_path != variant.path:
                current_story.active_variant_path = variant.path
                current_story.title = variant.title_text
                current_story.title_upper = variant.title_upper
                current_story.title_lower = variant.title_lower
                current_story.subtitles_on = variant.subtitles_enabled
                changed = True
            if current_variant is not None:
                if current_variant.id != artifact_id:
                    current_variant.id = artifact_id
                    changed = True
            if changed:
                self._save(current)

    @staticmethod
    def _storyline_is_playable(story: Storyline) -> bool:
        if story.status is not Status.READY:
            return False
        try:
            JobService._active_variant(story)
        except JobServiceError:
            return False
        return True

    def _durable_job_directory(self, job: Job) -> Path:
        safe_title = _safe_filename_component(
            job.project_name or "YouTube 인터뷰",
            max_bytes=EXPORT_TITLE_MAX_BYTES,
        )
        base_name = f"Ep-{job.episode_number}_{safe_title}"
        with self._archive_lock:
            self.archive_root.mkdir(parents=True, exist_ok=True)
            for collision_index in range(1, 10_000):
                suffix = "" if collision_index == 1 else f" ({collision_index})"
                candidate = self.archive_root / f"{base_name}{suffix}"
                marker = candidate / ".reels-editor-job.json"
                if candidate.is_symlink():
                    raise JobServiceError("archive directory is a symlink")
                if candidate.exists():
                    self._assert_safe_archive_directory(candidate)
                    self._assert_safe_export_output(marker)
                    if self._directory_belongs_to_job(candidate, job.id):
                        return candidate
                    try:
                        is_empty = not any(candidate.iterdir())
                    except OSError:
                        is_empty = False
                    if not is_empty:
                        continue
                candidate.mkdir(parents=True, exist_ok=True)
                self._assert_safe_archive_directory(candidate)
                marker_tmp = candidate / (
                    f".{marker.name}.{os.getpid()}.{uuid.uuid4().hex}.part"
                )
                self._assert_safe_export_output(marker)
                self._assert_safe_export_output(marker_tmp)
                try:
                    with marker_tmp.open("x", encoding="utf-8") as file:
                        file.write(json.dumps({"job_id": job.id}, ensure_ascii=False))
                    os.replace(marker_tmp, marker)
                finally:
                    if marker_tmp.exists() or marker_tmp.is_symlink():
                        marker_tmp.unlink()
                return candidate
        raise JobServiceError("archive directory collision limit exceeded")

    @staticmethod
    def _directory_belongs_to_job(directory: Path, job_id: str) -> bool:
        marker = directory / ".reels-editor-job.json"
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("job_id") == job_id:
                return True
        except (OSError, json.JSONDecodeError):
            pass
        for manifest in directory.glob("*.mp4.manifest.json"):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict) and payload.get("job_id") == job_id:
                return True
        return False

    def _durable_destination(
        self,
        job: Job,
        story: Storyline,
        *,
        directory: Path | None = None,
    ) -> Path:
        if story.archive_path:
            previous = Path(story.archive_path).expanduser()
            if self._is_archive_path(previous):
                return previous
        target_dir = directory or self._durable_job_directory(job)
        return target_dir / _export_filename(job, story)

    def _collision_safe_destination(
        self,
        destination: Path,
        *,
        job_id: str,
        storyline_id: str,
    ) -> Path:
        self._assert_safe_export_output(destination)
        if not destination.exists() or self._destination_belongs_to_story(
            destination,
            job_id,
            storyline_id,
        ):
            return destination
        for collision_index in range(2, 10_000):
            candidate = destination.with_name(
                f"{destination.stem} ({collision_index}){destination.suffix}"
            )
            self._assert_safe_export_output(candidate)
            if not candidate.exists() or self._destination_belongs_to_story(
                candidate,
                job_id,
                storyline_id,
            ):
                return candidate
        raise JobServiceError("export filename collision limit exceeded")

    def _destination_belongs_to_story(
        self,
        destination: Path,
        job_id: str,
        storyline_id: str,
    ) -> bool:
        manifest = destination.with_suffix(destination.suffix + ".manifest.json")
        self._assert_safe_export_output(manifest)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("job_id") == job_id
            and payload.get("storyline_id") == storyline_id
        )

    def _destination_is_current(
        self,
        destination: Path,
        job_id: str,
        story: Storyline,
        variant: Variant,
    ) -> bool:
        self._assert_safe_export_output(destination)
        if not destination.is_file():
            return False
        manifest = destination.with_suffix(destination.suffix + ".manifest.json")
        self._assert_safe_export_output(manifest)
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("job_id") == job_id
            and payload.get("storyline_id") == story.id
            and payload.get("variant_id") == variant.id
            and payload.get("title") == variant.title_text
            and payload.get("subtitles_on") == variant.subtitles_enabled
        )

    def _is_archive_path(self, path: Path) -> bool:
        return self._is_relative_to(path.expanduser().resolve(), self.archive_root.resolve())

    def _is_archive_directory(self, path: Path) -> bool:
        return self._is_archive_path(path)

    def _is_archive_namespace_path(self, path: Path) -> bool:
        root = Path(os.path.abspath(self.archive_root.expanduser()))
        target = Path(os.path.abspath(path.expanduser()))
        return self._is_relative_to(target, root)

    def _assert_safe_archive_directory(self, directory: Path) -> None:
        if not self._is_archive_namespace_path(directory):
            raise JobServiceError("archive directory is outside archive root")
        if directory.is_symlink():
            raise JobServiceError("archive directory is a symlink")
        if not directory.is_dir():
            raise JobServiceError("archive directory is missing")
        if not self._is_archive_path(directory):
            raise JobServiceError("archive directory is outside archive root")

    def _assert_safe_export_output(self, path: Path) -> None:
        if path.is_symlink():
            raise JobServiceError("export destination is a symlink")
        if self._is_archive_namespace_path(path):
            self._assert_safe_archive_directory(path.parent)

    def _record_export_failure(self, job_id: str, exc: Exception) -> None:
        with self._lock:
            job = self.store.load(job_id)
            job.export.status = Status.FAILED
            job.export.error = str(exc)
            job.phase = "export-failed"
            job.message = "내보내기에 실패했습니다."
            self._save(job)

    def _validated_content_types(self, content_types: list[str] | None) -> list[str]:
        try:
            return candidate_analyzer.validate_content_types(
                content_types or list(candidate_analyzer.CONTENT_TYPES)
            )
        except ValueError as exc:
            raise JobServiceError(str(exc)) from exc

    def _validated_provider(self, provider: str | None) -> str:
        selected = self.config.provider if provider is None else provider
        if selected not in DESKTOP_PROVIDERS:
            raise JobServiceError(f"provider must be one of {sorted(DESKTOP_PROVIDERS)}")
        return selected

    @staticmethod
    def _validated_episode_number(episode_number: int) -> int:
        if isinstance(episode_number, bool) or episode_number < 1:
            raise JobServiceError("episode_number must be a positive integer")
        return episode_number

    def _create_job(
        self,
        provider: str,
        *,
        source_url: str,
        content_types: list[str],
        episode_number: int,
    ) -> Job:
        model = self.config.model if provider == self.config.provider else ""
        job = self.store.create_job(
            source_url=source_url,
            source_thumbnail_url=youtube.thumbnail_url_for_video(
                youtube.video_id_from_url(source_url)
            ),
            episode_number=self._validated_episode_number(episode_number),
            provider=provider,
            model=model,
            duration_s=candidate_analyzer.TARGET_DURATION_S,
            n_storylines=0,
            content_types=content_types,
        )
        job.status = Status.LOADING
        job.phase = "loading"
        job.progress = 0.02
        job.message = "YouTube 영상 정보를 확인하는 중입니다."
        job.work_dir = str(self.store.job_dir(job.id))
        return self._save(job)

    def _run_job_guarded(self, job_id: str) -> None:
        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        try:
            with use_process_registry(registry):
                self._analyze_job(job_id)
        except Exception as exc:  # noqa: BLE001 - boundary converts background failures to job state
            self._record_background_failure(job_id, exc)
        finally:
            with self._lock:
                self._release_job_operation_locked(job_id)

    def _run_generation_guarded(self, job_id: str) -> None:
        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        try:
            with use_process_registry(registry):
                self._generate_job(job_id)
        except Exception as exc:  # noqa: BLE001 - boundary converts background failures to job state
            self._record_background_failure(job_id, exc)
        finally:
            with self._lock:
                self._release_job_operation_locked(job_id)

    def _record_background_failure(self, job_id: str, exc: Exception) -> None:
        with self._lock:
            job = self.store.load(job_id)
            if not self._is_cancelled(job_id) and job.status is not Status.CANCELLED:
                job.status = Status.FAILED
                job.phase = "failed"
                job.error = str(exc)
                job.message = "작업이 실패했습니다."
                self._save(job)

    def _analyze_job(self, job_id: str) -> None:
        job = self.store.load(job_id)
        provider = job.provider or self.config.provider
        cfg = AppConfig(
            provider=provider,
            model=job.model or "",
            base_url=self.config.base_url if provider == self.config.provider else "",
            n_storylines=candidate_analyzer.CANDIDATE_COUNT,
            style=dict(self.config.style),
        )
        source = self._prepare_youtube_source(job_id, job)
        project_name = source.title
        segments = dict(source.segments)
        segments.setdefault("source_title", source.title)
        work = self.store.job_dir(job.id)

        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.project_name = project_name
            job.input_path = str(source.video_path)
            job.output_dir = str(work)
            job.status = Status.GENERATING
            job.phase = "analyzing"
            job.progress = 0.20
            job.message = f"{cfg.provider}로 서로 다른 콘텐츠 후보 10개를 분석하는 중입니다."
            self._save(job)
        self._raise_if_cancelled(job_id)

        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        runner = self.deps.build_runner(cfg)

        def managed_runner(prompt: str) -> str:
            with use_process_registry(registry):
                return runner(prompt)

        candidates = self.deps.analyze_candidates(
            segments,
            job.content_types,
            runner=managed_runner,
            raw_dump=work / "candidate_analysis_raw.txt",
        )
        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.candidates = candidates
            job.status = Status.AWAITING_SELECTION
            job.phase = "awaiting_selection"
            job.progress = 1.0
            job.error = None
            job.message = "분석이 끝났습니다. 만들 후보를 선택하세요."
            self._save(job)

    def _prepare_selected_generation(self, job_id: str, candidate_ids: list[str]) -> Job:
        job = self.store.load(job_id)
        if job.status is not Status.AWAITING_SELECTION:
            raise JobServiceError("콘텐츠 후보 분석이 완료된 작업만 생성할 수 있습니다.")
        unique_ids = list(dict.fromkeys(candidate_ids))
        if not unique_ids:
            raise JobServiceError("생성할 콘텐츠 후보를 하나 이상 선택하세요.")
        if len(unique_ids) > MAX_DESKTOP_STORYLINES:
            raise JobServiceError(f"후보는 최대 {MAX_DESKTOP_STORYLINES}개까지 선택할 수 있습니다.")
        available = {candidate.id for candidate in job.candidates}
        unknown = [candidate_id for candidate_id in unique_ids if candidate_id not in available]
        if unknown:
            raise JobServiceError("존재하지 않는 콘텐츠 후보: " + ", ".join(unknown))
        job.selected_candidate_ids = unique_ids
        job.n_storylines = len(unique_ids)
        job.storylines = []
        job.status = Status.GENERATING
        job.phase = "generating"
        job.progress = 0.20
        job.error = None
        job.message = f"선택한 후보 {len(unique_ids)}개의 릴스 대본을 만드는 중입니다."
        return self._save(job)

    def _generate_job(self, job_id: str) -> None:
        job = self.store.load(job_id)
        provider = job.provider or self.config.provider
        cfg = AppConfig(
            provider=provider,
            model=job.model or "",
            base_url=self.config.base_url if provider == self.config.provider else "",
            n_storylines=job.n_storylines,
            style=dict(self.config.style),
        )
        work = self.store.job_dir(job.id)
        if not job.input_path:
            raise JobServiceError("저장된 YouTube 영상 또는 자막을 찾지 못했습니다. 다시 분석하세요.")
        segment_candidates = [
            work / "source" / "segments.json",
            Path(job.input_path).parent / "segments.json",
        ]
        segments_path = next((path for path in segment_candidates if path.is_file()), segment_candidates[0])
        if not segments_path.is_file():
            raise JobServiceError("저장된 YouTube 영상 또는 자막을 찾지 못했습니다. 다시 분석하세요.")
        segments = json.loads(segments_path.read_text(encoding="utf-8"))
        segments.setdefault("source_title", job.project_name or "")
        video = Path(job.input_path)
        style = self._style_for_episode(
            merged_style(self.deps.load_style(self.style_path), cfg.style),
            job.episode_number,
        )
        speed = style.speed
        by_id = {candidate.id: candidate for candidate in job.candidates}
        selected_candidates = [by_id[candidate_id] for candidate_id in job.selected_candidate_ids]
        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        runner = self.deps.build_runner(cfg)

        def managed_runner(prompt: str) -> str:
            with use_process_registry(registry):
                return runner(prompt)

        results = self.deps.generate_selected_candidates(
            segments,
            selected_candidates,
            runner=managed_runner,
            raw_dump_dir=work,
            speed=speed,
        )
        # 의존성을 대체한 호출 경로까지 포함해 렌더 직전 한 번 더 정규화한다.
        # 함수는 멱등이므로 기본 candidate_analyzer 경로와 중복 호출해도 안전하다.
        harmonize_speaker_metadata(results)
        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.storylines = [self._storyline_from_result(result) for result in results]
            if all(result.doc is None for result in results):
                job.status = Status.FAILED
                job.phase = "failed"
                job.progress = 1.0
                job.error = "선택한 모든 후보의 대본 생성에 실패했습니다."
                job.message = job.error
                self._save(job)
                return
            job.status = Status.RENDERING_BASE
            job.phase = "rendering"
            job.progress = 0.28
            job.message = f"선택한 릴스 {job.n_storylines}개를 렌더링하는 중입니다."
            self._save(job)

        alive = [result for result in results if result.doc is not None]
        with ThreadPoolExecutor(max_workers=MAX_BASE_RENDERS) as executor:
            list(executor.map(
                lambda result: self._render_storyline_with_registry(
                    registry,
                    job_id,
                    result,
                    segments,
                    video,
                    style,
                    speed,
                ),
                alive,
            ))

        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            ready = [story for story in job.storylines if story.status is Status.READY]
            if not ready:
                job.status = Status.FAILED
                job.phase = "failed"
                job.error = "렌더링에 성공한 릴스가 없습니다."
                job.message = job.error
            else:
                first = ready[0]
                job.progress = 1.0
                job.selected_storyline_id = first.id
                first.variants[0].selected = True
                job.export = ExportState(status=Status.IDLE, selected_storyline_id=first.id, selected_variant_id=first.variants[0].id)
                if len(ready) == job.n_storylines:
                    job.status = Status.READY
                    job.phase = "ready"
                    job.error = None
                    job.message = f"선택한 릴스 {job.n_storylines}개가 준비되었습니다."
                else:
                    job.status = Status.FAILED
                    job.phase = "partial-failure"
                    job.error = f"선택한 릴스 {len(ready)}/{job.n_storylines}개만 준비되었습니다."
                    job.message = job.error
            self._save(job)

    def _prepare_youtube_source(self, job_id: str, job: Job) -> youtube.YouTubeSource:
        source_url = job.source_url
        if not source_url:
            raise JobServiceError("YouTube URL이 비어 있습니다.")
        cached = self._find_cached_youtube_source(job_id, source_url)
        if cached is not None:
            self._set_job_progress(
                job_id,
                phase="transcript",
                progress=0.17,
                message=(
                    "기존에 저장된 YouTube 영상과 원문 자막을 재사용합니다. "
                    f"다운로드를 건너뛰었습니다. · {cached.transcript_language} {cached.transcript_kind}"
                ),
            )
            self._save_youtube_transcript_metadata(job_id, cached)
            return cached
        self._set_job_progress(
            job_id,
            phase="downloading",
            progress=0.04,
            message="YouTube 영상을 이 Mac으로 다운로드하는 중입니다.",
        )
        last_reported = -1.0

        def on_download_progress(fraction: float) -> None:
            nonlocal last_reported
            if fraction < 1.0 and fraction - last_reported < 0.02:
                return
            last_reported = fraction
            self._set_job_progress(
                job_id,
                phase="downloading",
                progress=0.04 + 0.10 * fraction,
                message=f"YouTube 영상을 이 Mac으로 다운로드하는 중입니다. · {round(fraction * 100)}%",
            )

        source = self.deps.download_youtube_source(
            source_url,
            self.store.job_dir(job_id) / "source",
            progress_cb=on_download_progress,
            cancelled=lambda: self._is_cancelled(job_id),
        )
        self._raise_if_cancelled(job_id)
        self._set_job_progress(
            job_id,
            phase="transcript",
            progress=0.17,
            message=(
                f"YouTube 제공 자막을 클립용 타임코드로 변환했습니다. "
                f"· {source.transcript_language} {source.transcript_kind}"
            ),
        )
        self._save_youtube_transcript_metadata(job_id, source)
        return source

    def _find_cached_youtube_source(self, job_id: str, source_url: str) -> youtube.YouTubeSource | None:
        requested_video_id = youtube.video_id_from_url(source_url)
        for candidate in self.store.list_recent(limit=1000):
            if candidate.id == job_id or not candidate.source_url:
                continue
            candidate_video_id = youtube.video_id_from_url(candidate.source_url)
            same_source = (
                requested_video_id is not None
                and candidate_video_id == requested_video_id
            ) or candidate.source_url == source_url
            if not same_source:
                continue
            cached = youtube.load_cached_youtube_source(
                self.store.job_dir(candidate.id) / "source",
                source_url,
                expected_video_id=requested_video_id or candidate_video_id,
                fallback_title=candidate.project_name or "YouTube 인터뷰",
            )
            if cached is not None:
                return cached
        return None

    @staticmethod
    def _recovery_segments_path(job: Job, work: Path) -> Path:
        candidates = [work / "source" / "segments.json"]
        if job.input_path:
            candidates.append(Path(job.input_path).parent / "segments.json")
        candidates.extend(sorted(work.glob("s*/segments.json")))
        return next((path for path in candidates if path.is_file()), candidates[0])

    def _save_youtube_transcript_metadata(self, job_id: str, source: youtube.YouTubeSource) -> None:
        with self._lock:
            current = self.store.load(job_id)
            current.transcript_language = source.transcript_language
            current.transcript_kind = source.transcript_kind
            current.source_thumbnail_url = (
                source.thumbnail_url
                or current.source_thumbnail_url
                or youtube.thumbnail_url_for_video(source.video_id)
            )
            self._save(current)

    def _storyline_from_result(self, result: StorylineResult) -> Storyline:
        storyline = Storyline(
            id=f"s{result.index + 1}",
            index=result.index,
            angle_name=result.angle_name,
            status=Status.GENERATING if result.doc is not None else Status.FAILED,
            progress=0.0,
            error=result.error,
        )
        storyline.title = normalize_title(result.title or (
            _fallback_doc_title(result.doc) if result.doc is not None else ""
        ))
        return storyline

    def _render_storyline_with_registry(
        self,
        registry: ProcessRegistry,
        job_id: str,
        result: StorylineResult,
        segments: dict[str, Any],
        video: Path,
        style: StylePreset,
        speed: float,
    ) -> None:
        with use_process_registry(registry):
            self._render_storyline_from_result(job_id, result, segments, video, style, speed)

    def _render_storyline_from_result(
        self,
        job_id: str,
        result: StorylineResult,
        segments: dict[str, Any],
        video: Path,
        style: StylePreset,
        speed: float,
    ) -> None:
        if result.doc is None:
            return
        story_id = f"s{result.index + 1}"
        self._set_storyline_render_progress(
            job_id,
            story_id,
            progress=0.25,
            status=Status.RENDERING_BASE,
            detail="컷 순서와 자막 구간을 준비하는 중입니다.",
        )
        try:
            self._raise_if_cancelled(job_id)
            sdir = self.store.job_dir(job_id) / story_id
            self._write_storyline_outputs_once(sdir, result.doc, segments, speed)
            self._raise_if_cancelled(job_id)
            self._set_storyline_render_progress(
                job_id,
                story_id,
                progress=0.45,
                status=Status.RENDERING_BASE,
                detail="세로 영상용 화자 위치와 크롭·자막 에셋을 준비하는 중입니다.",
            )
            job = self.store.load(job_id)
            assets = self.deps.render_base_and_assets(
                video,
                segments,
                result.doc,
                style,
                sdir / ".render",
                speed,
                episode_number=job.episode_number,
            )
            self._raise_if_cancelled(job_id)
            self._set_storyline_render_progress(
                job_id,
                story_id,
                progress=0.78,
                status=Status.RENDERING_OVERLAY,
                detail="크롭·제목·자막·로고를 합쳐 최종 영상을 인코딩하는 중입니다.",
            )
            assets_path = assets.write_manifest(sdir / ".render" / "assets.json")
            title_text = normalize_title(result.title or _fallback_doc_title(result.doc))
            title_upper, title_lower = editor_title_lines(title_text)
            speaker_text = render.speaker_label(result.doc)
            key = render.variant_cache_key(
                storyline_id=story_id,
                title_text=title_text,
                subtitles_enabled=True,
                style_hash_value=f"{render.style_hash(style)}-{_assets_fingerprint(assets_path, assets)}",
                speaker_text=speaker_text,
                title_upper=title_upper,
                title_lower=title_lower,
            )
            out = sdir / f"{key}.mp4"
            self.deps.render_overlay_variant(
                assets,
                title_text=title_text,
                keyword="",
                style=style,
                out_path=out,
                subtitles_enabled=True,
                speaker_text=speaker_text,
                title_upper=title_upper,
                title_lower=title_lower,
            )
            with self._lock:
                job = self.store.load(job_id)
                if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                    return
                storyline = self._find_storyline(job, story_id)
                artifact_id = self._artifact_id_for_path(job, out)
                artifact = job.artifacts[artifact_id] if artifact_id else self.store.register_artifact(job_id, out, kind="video/mp4")
                job = self.store.load(job_id)
                storyline = self._find_storyline(job, story_id)
                storyline.status = Status.READY
                storyline.progress = 1.0
                storyline.base_path = str(assets.base)
                storyline.base_video_path = str(assets.base)
                storyline.assets_path = str(assets_path)
                storyline.edl_path = str(sdir / "edl.json")
                storyline.active_variant_path = str(out)
                storyline.title = title_text
                storyline.title_upper = title_upper
                storyline.title_lower = title_lower
                storyline.subtitles_on = True
                storyline.variants = [
                    Variant(
                        id=artifact.id,
                        title_text=title_text,
                        subtitles_enabled=True,
                        subtitles_on=True,
                        style_hash=render.style_hash(style),
                        status=Status.READY,
                        path=str(out),
                        title_upper=title_upper,
                        title_lower=title_lower,
                    )
                ]
                storyline.completed_at = (
                    storyline.completed_at or datetime.now(UTC).isoformat()
                )
                self._save(job)
            try:
                self._ensure_durable_export(job_id, story_id)
            except (OSError, JobServiceError) as exc:
                with self._lock:
                    archived = self.store.load(job_id)
                    archived_story = self._find_storyline(archived, story_id)
                    archived_story.error = f"보관용 MP4 저장에 실패했습니다: {exc}"
                    self._save(archived)
            self._set_storyline_render_progress(
                job_id,
                story_id,
                progress=1.0,
                status=Status.READY,
                detail="대표 영상 렌더링을 완료했습니다.",
            )
        except Exception as exc:  # noqa: BLE001 - per-storyline partial success boundary
            with self._lock:
                job = self.store.load(job_id)
                if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                    return
                storyline = self._find_storyline(job, story_id)
                if storyline.status is not Status.CANCELLED:
                    storyline.status = Status.FAILED
                    storyline.error = str(exc)
                    storyline.progress = 1.0
                    self._save(job)

    def _set_job_progress(self, job_id: str, *, phase: str, progress: float, message: str) -> None:
        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.phase = phase
            job.progress = progress
            job.message = message
            self._save(job)

    def _set_storyline_render_progress(
        self,
        job_id: str,
        storyline_id: str,
        *,
        progress: float,
        status: Status,
        detail: str,
    ) -> None:
        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            storyline = self._find_storyline(job, storyline_id)
            storyline.status = status
            storyline.progress = max(storyline.progress, progress)
            if job.status is Status.RENDERING_BASE:
                completed = sum(
                    story.status in {Status.READY, Status.FAILED, Status.CANCELLED}
                    for story in job.storylines
                )
                total = max(1, len(job.storylines))
                aggregate = sum(
                    1.0 if story.status in {Status.READY, Status.FAILED, Status.CANCELLED} else story.progress
                    for story in job.storylines
                ) / total
                job.phase = "rendering"
                job.progress = min(0.96, 0.28 + 0.68 * aggregate)
                job.message = (
                    f"릴스 {storyline.index + 1}: {detail} "
                    f"· 전체 {completed}/{job.n_storylines}개 완료"
                )
            self._save(job)

    def _render_storyline_base(self, job_id: str, storyline_id: str) -> None:
        job = self.store.load(job_id)
        story = self._find_storyline(job, storyline_id)
        if not story.edl_path:
            raise JobServiceError("storyline has no persisted EDL")
        segments = json.loads((Path(story.edl_path).parent / "segments.json").read_text(encoding="utf-8"))
        doc = self._harmonized_storyline_doc(job, story)
        style = self._style_for_episode(
            merged_style(self.deps.load_style(self.style_path), self.config.style),
            job.episode_number,
        )
        result = StorylineResult(story.index, story.angle_name, doc)
        self._render_storyline_from_result(job_id, result, segments, Path(segments["video_path"]), style, style.speed)

    def _render_selection(
        self,
        job_id: str,
        storyline_id: str,
        request_id: int,
        *,
        selected_for_export: bool = False,
    ) -> None:
        job = self.store.load(job_id)
        story = self._find_storyline(job, storyline_id)
        if story.render_request_id != request_id:
            return
        if not story.assets_path:
            raise JobServiceError("storyline has no render assets")
        style = self._style_for_episode(
            merged_style(self.deps.load_style(self.style_path), self.config.style),
            job.episode_number,
        )
        assets = render.RenderAssets.read_manifest(Path(story.assets_path))
        title_text = story.title
        title_upper, title_lower = (
            (story.title_upper, story.title_lower)
            if story.title_lower
            else editor_title_lines(title_text)
        )
        doc = self._harmonized_storyline_doc(job, story)
        speaker_text = render.speaker_label(doc)
        key = render.variant_cache_key(
            storyline_id=storyline_id,
            title_text=title_text,
            subtitles_enabled=story.subtitles_on,
            style_hash_value=f"{render.style_hash(style)}-{_assets_fingerprint(Path(story.assets_path), assets)}",
            speaker_text=speaker_text,
            title_upper=title_upper,
            title_lower=title_lower,
        )
        out = Path(story.assets_path).parent.parent / f"{key}.mp4"
        if not out.is_file():
            self.deps.render_overlay_variant(
                assets,
                title_text=title_text,
                keyword="",
                style=style,
                out_path=out,
                subtitles_enabled=story.subtitles_on,
                speaker_text=speaker_text,
                title_upper=title_upper,
                title_lower=title_lower,
            )
        with self._lock:
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED or story.render_request_id != request_id:
                return
            artifact_id = self._artifact_id_for_path(job, out)
            artifact = job.artifacts[artifact_id] if artifact_id else self.store.register_artifact(job_id, out, kind="video/mp4")
            job = self.store.load(job_id)
            story = self._find_storyline(job, storyline_id)
            variant = Variant(
                id=artifact.id,
                title_text=title_text,
                subtitles_enabled=story.subtitles_on,
                subtitles_on=story.subtitles_on,
                style_hash=render.style_hash(style),
                status=Status.READY,
                path=str(out),
                title_upper=title_upper,
                title_lower=title_lower,
            )
            story.variants = [item for item in story.variants if item.path != str(out)]
            story.variants.append(variant)
            story.active_variant_path = str(out)
            story.status = Status.READY
            story.progress = 1.0
            story.error = None
            job.status = Status.READY
            job.phase = "ready"
            job.progress = 1.0
            job.message = "선택한 자막 버전이 준비되었습니다."
            self._save(job)

            should_select_for_export = selected_for_export or job.selected_storyline_id == story.id
            if should_select_for_export:
                job = self.store.load(job_id)
                story = self._find_storyline(job, storyline_id)
                self._select_export_variant(job, story, variant)

        try:
            self._ensure_durable_export(job_id, storyline_id)
        except (OSError, JobServiceError) as exc:
            with self._lock:
                current = self.store.load(job_id)
                current_story = self._find_storyline(current, storyline_id)
                current_story.error = f"보관용 MP4 저장에 실패했습니다: {exc}"
                self._save(current)

    def _harmonized_storyline_doc(self, job: Job, story: Storyline) -> dict[str, Any]:
        """Load one persisted EDL with grounded speaker identity shared by sibling reels."""
        if not story.edl_path:
            return {}
        target_doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8"))
        target = StorylineResult(story.index, story.angle_name, target_doc)
        results = [target]
        for sibling in job.storylines:
            if sibling.id == story.id or not sibling.edl_path:
                continue
            sibling_path = Path(sibling.edl_path)
            if not sibling_path.is_file():
                continue
            try:
                sibling_doc = json.loads(sibling_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            results.append(StorylineResult(sibling.index, sibling.angle_name, sibling_doc))
        harmonize_speaker_metadata(results)
        return target.doc or target_doc

    def _write_storyline_outputs_once(
        self,
        sdir: Path,
        doc: dict[str, Any],
        segments: dict[str, Any],
        speed: float,
    ) -> None:
        if not (sdir / "edl.json").is_file():
            self.deps.write_outputs(sdir, doc, segments)
        if not (sdir / "reel.srt").is_file():
            ordered = edl.ordered_segments(doc, segments)
            groups = render.group_captions(
                [
                    [a, b, render.apply_text_fixes(text, render.DEFAULT_TEXT_FIXES)]
                    for a, b, text in render.timeline_items(ordered, speed)
                ]
            )
            self.deps.write_srt(groups, sdir / "reel.srt")
        # The desktop workflow renders straight from the source timeline. Encoding
        # every beat as a separate full-resolution MP4 only duplicates work; the
        # CLI keeps that optional editable-material export for users who need it.

    def _require_job(self, job_id: str | None) -> Job:
        target = job_id or self._active_job_id
        if target is None:
            raise JobServiceError("no active job")
        return self.store.load(target)

    def _find_storyline(self, job: Job, storyline_id: str | None) -> Storyline:
        if not storyline_id:
            raise JobServiceError("storyline_id is required")
        for storyline in job.storylines:
            if storyline.id == storyline_id:
                return storyline
        raise JobServiceError(f"storyline not found: {storyline_id}")

    @staticmethod
    def _candidate_for_storyline(job: Job, storyline: Storyline) -> ContentCandidate | None:
        if not 0 <= storyline.index < len(job.selected_candidate_ids):
            return None
        candidate_id = job.selected_candidate_ids[storyline.index]
        return next((item for item in job.candidates if item.id == candidate_id), None)

    @staticmethod
    def _active_variant(story: Storyline) -> Variant:
        active_path = story.active_variant_path
        for variant in story.variants:
            if variant.path == active_path and JobService._variant_is_playable(variant):
                return variant
        for variant in reversed(story.variants):
            if JobService._variant_is_playable(variant):
                return variant
        raise JobServiceError("storyline has no playable completed variant")

    @staticmethod
    def _variant_is_playable(variant: Variant) -> bool:
        return bool(
            variant.status is Status.READY
            and variant.path
            and Path(variant.path).is_file()
        )

    def _invalidate_storyline_variants(self, job: Job, storyline: Storyline) -> None:
        job_root = self.store.job_dir(job.id).resolve()
        stale_paths = {variant.path for variant in storyline.variants if variant.path}
        stale_paths.add(storyline.active_variant_path)
        for raw_path in stale_paths:
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            if self._is_relative_to(path, job_root) and path.is_file():
                path.unlink()
        stale_resolved = {
            str(Path(path).resolve())
            for path in stale_paths
            if path
        }
        job.artifacts = {
            artifact_id: artifact
            for artifact_id, artifact in job.artifacts.items()
            if str(Path(artifact.path).resolve()) not in stale_resolved
        }
        storyline.variants = []
        storyline.active_variant_path = None

    def _select_export_variant(self, job: Job, story: Storyline, variant: Variant) -> Job:
        for item in job.storylines:
            for candidate in item.variants:
                candidate.selected = item.id == story.id and candidate.id == variant.id
        job.selected_storyline_id = story.id
        job.export.selected_storyline_id = story.id
        job.export.selected_variant_id = variant.id
        job.export.status = Status.IDLE
        job.export.error = None
        return self._save(job)

    def _artifact_id_for_path(self, job: Job, path: Path) -> str | None:
        resolved = str(path.resolve())
        for artifact_id, artifact in job.artifacts.items():
            if str(Path(artifact.path).resolve()) == resolved:
                return artifact_id
        return None

    @staticmethod
    def _is_relative_to(path: Path, parent: Path) -> bool:
        try:
            path.relative_to(parent)
        except ValueError:
            return False
        return True

    @staticmethod
    def _style_for_episode(style: StylePreset, episode_number: int) -> StylePreset:
        return style.for_episode(episode_number)

    def _save(self, job: Job) -> Job:
        saved = self.store.save(job)
        self._condition.notify_all()
        return saved

    def _cancel_for(self, job_id: str) -> threading.Event:
        return self._cancel_events.setdefault(job_id, threading.Event())

    def _is_cancelled(self, job_id: str) -> bool:
        return self._cancel_events.get(job_id, threading.Event()).is_set()

    def _raise_if_cancelled(self, job_id: str) -> None:
        if self._is_cancelled(job_id):
            raise JobServiceError("cancelled")

    @contextmanager
    def _job_operation(self, job_id: str):
        with self._lock:
            active = self._active_job_id
            if active is not None and active != job_id:
                raise JobServiceError("another job is already active")
            self._active_job_id = job_id
            self._operation_counts[job_id] = self._operation_counts.get(job_id, 0) + 1
            registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        try:
            with use_process_registry(registry):
                yield
        finally:
            with self._lock:
                self._release_job_operation_locked(job_id)

    def _release_job_operation_locked(self, job_id: str) -> None:
        remaining = self._operation_counts.get(job_id, 0) - 1
        if remaining > 0:
            self._operation_counts[job_id] = remaining
            return
        self._operation_counts.pop(job_id, None)
        if self._active_job_id == job_id:
            self._active_job_id = None
        self._process_registries.pop(job_id, None)


def _fallback_doc_title(doc: dict[str, Any] | None) -> str:
    """후보 제목이 없는 저장본이나 복구 경로에서만 쓰는 대본 자체의 제목."""
    if not doc:
        return ""
    for item in doc.get("title_candidates", []):
        text = str(item.get("text", "")).strip() if isinstance(item, dict) else ""
        if text:
            return normalize_title(text)
    return ""


def _assets_fingerprint(manifest_path: Path, assets: render.RenderAssets) -> str:
    digest = hashlib.sha256()
    try:
        digest.update(manifest_path.read_bytes())
    except OSError:
        digest.update(str(manifest_path).encode("utf-8"))
    asset_paths = [assets.base, assets.wm_png, *assets.sub_pngs]
    if assets.source is not None and assets.source not in asset_paths:
        asset_paths.append(assets.source)
    if assets.base_filter is not None:
        asset_paths.append(assets.base_filter)
    for path in asset_paths:
        try:
            stat = path.stat()
        except OSError:
            digest.update(str(path).encode("utf-8"))
            continue
        digest.update(str(path).encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()[:12]


def _export_filename(job: Job, story: Storyline) -> str:
    founder_name = _story_speaker_name(story)
    if not founder_name:
        founder_name = job.project_name
    if not founder_name:
        founder_name = "인터뷰 화자"
    safe_name = _safe_filename_component(founder_name, max_bytes=EXPORT_TITLE_MAX_BYTES)
    return f"{safe_name} - {story.index + 1}.mp4"


def _story_speaker_name(story: Storyline) -> str:
    if not story.edl_path:
        return ""
    try:
        doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    speaker = doc.get("speaker")
    if not isinstance(speaker, dict):
        return ""
    return " ".join(str(speaker.get("name") or "").split())


def _safe_filename_component(value: str, *, max_bytes: int) -> str:
    cleaned = _INVALID_FILENAME_CHARS.sub(" ", value)
    cleaned = _FILENAME_WHITESPACE.sub(" ", cleaned).strip(" .")
    if not cleaned:
        cleaned = "릴스"

    encoded_size = 0
    truncated: list[str] = []
    for char in cleaned:
        char_size = len(char.encode("utf-8"))
        if encoded_size + char_size > max_bytes:
            break
        truncated.append(char)
        encoded_size += char_size
    return "".join(truncated).rstrip(" .") or "릴스"


def validate_reel_title(title: str) -> str:
    try:
        return validate_title(title)
    except ValueError as exc:
        raise JobServiceError(str(exc)) from exc
