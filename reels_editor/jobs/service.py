from __future__ import annotations

import json
import os
import shutil
import threading
import hashlib
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from reels_editor import capcut, edl, export, render, voice_isolation
from reels_editor.config import AppConfig, merged_style, resolve_api_key
from reels_editor.llm import build_runner
from reels_editor.processes import ProcessRegistry, use_process_registry
from reels_editor.storyteller import StorylineResult, generate_many
from reels_editor.style import StylePreset, load_style

from .models import ExportState, Job, Status, Storyline, Variant
from .store import JobStore

DEFAULT_STYLE = Path(__file__).parent.parent.parent / "styles" / "done.yaml"
MAX_DESKTOP_STORYLINES = 10
MAX_BASE_RENDERS = 2
ALLOWED_DURATIONS = frozenset({15, 30, 60})
DESKTOP_PROVIDERS = frozenset({"codex-cli", "claude-cli", "openai", "kimi"})


class JobServiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobServiceDeps:
    find_project: Callable[[str], Path] = capcut.find_project
    load_project: Callable[[Path], dict[str, Any]] = capcut.load_project
    build_segments: Callable[[dict[str, Any]], dict[str, Any]] = capcut.build_segments
    generate_many: Callable[..., list[StorylineResult]] = generate_many
    build_runner: Callable[[AppConfig], Callable[[str], str]] = build_runner
    load_style: Callable[[Path], StylePreset] = load_style
    render_base_and_assets: Callable[..., render.RenderAssets] = render.render_base_and_assets
    render_overlay_variant: Callable[..., Path] = render.render_overlay_variant
    write_outputs: Callable[[Path, dict[str, Any], dict[str, Any]], None] = export.write_outputs
    write_srt: Callable[[list[list], Path], Path] = export.write_srt
    export_cuts: Callable[[Path, dict[str, Any], dict[str, Any], Path, float], list[Path]] = export.export_cuts
    enhance_export_video: Callable[..., voice_isolation.IsolationResult] = voice_isolation.enhance_video
    resolve_voice_isolation_key: Callable[[], str | None] = lambda: resolve_api_key("elevenlabs")


class JobService:
    def __init__(
        self,
        *,
        store: JobStore | None = None,
        deps: JobServiceDeps | None = None,
        style_path: Path = DEFAULT_STYLE,
        config: AppConfig | None = None,
        duration_s: int = 30,
    ) -> None:
        self.store = store or JobStore()
        self.deps = deps or JobServiceDeps()
        self.style_path = style_path
        self.config = config or AppConfig(provider="codex-cli", n_storylines=3)
        self.duration_s = duration_s
        self._lock = threading.RLock()
        self._condition = threading.Condition(self._lock)
        self._active_job_id: str | None = None
        self._worker: threading.Thread | None = None
        self._cancel_events: dict[str, threading.Event] = {}
        self._process_registries: dict[str, ProcessRegistry] = {}
        self._operation_counts: dict[str, int] = {}
        self._shutdown = threading.Event()

    def start_job(
        self,
        project_path: str,
        *,
        duration_s: int | None = None,
        n_storylines: int | None = None,
        provider: str | None = None,
    ) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._create_job(
                project_path,
                self._validated_duration(duration_s),
                self._validated_storyline_count(n_storylines),
                self._validated_provider(provider),
            )
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
            self._worker = threading.Thread(
                target=self._run_job_guarded,
                args=(job.id,),
                daemon=True,
                name=f"reels-job-{job.id[:8]}",
            )
            self._worker.start()
            return job

    def run_job_sync(
        self,
        project_path: str,
        *,
        duration_s: int | None = None,
        n_storylines: int | None = None,
        provider: str | None = None,
    ) -> Job:
        with self._lock:
            if self._active_job_id is not None:
                raise JobServiceError("another job is already active")
            job = self._create_job(
                project_path,
                self._validated_duration(duration_s),
                self._validated_storyline_count(n_storylines),
                self._validated_provider(provider),
            )
            self._cancel_events[job.id] = threading.Event()
            self._process_registries[job.id] = ProcessRegistry()
            self._operation_counts[job.id] = 1
            self._active_job_id = job.id
        self._run_job_guarded(job.id)
        return self.store.load(job.id)

    def snapshot(self, job_id: str | None = None) -> Job | None:
        with self._lock:
            target = job_id or self._active_job_id
            if target is None:
                recent = self.store.list_recent(limit=1)
                return recent[0] if recent else None
            return self.store.load(target)

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
        title_index: int,
        subtitles_on: bool,
        selected_for_export: bool = False,
    ) -> Job:
        with self._lock:
            job = self.store.load(job_id)
            storyline = self._find_storyline(job, storyline_id)
            if storyline.status not in {Status.READY, Status.RENDERING_OVERLAY}:
                raise JobServiceError("storyline is not ready for title selection")
            if not 0 <= title_index < len(storyline.title_candidates):
                raise JobServiceError("title_index is out of range")
            storyline.selected_title_index = title_index
            storyline.subtitles_on = subtitles_on
            storyline.render_request_id += 1
            request_id = storyline.render_request_id
            storyline.status = Status.RENDERING_OVERLAY
            storyline.progress = 0.94
            job.status = Status.RENDERING_OVERLAY
            job.phase = "overlay"
            job.message = "제목/자막 오버레이를 반영하는 중입니다."
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
                raise JobServiceError("retry requires a generated EDL")
            self._invalidate_storyline_variants(job, storyline)
            storyline.status = Status.RENDERING_BASE
            storyline.error = None
            storyline.progress = 0.2
            self._save(job)
        with self._job_operation(job_id):
            self._render_storyline_base(job_id, storyline_id)
        return self.store.load(job_id)

    def export_selected(
        self,
        job_id: str,
        destination: Path,
        *,
        storyline_id: str | None = None,
        subtitles_on: bool | None = None,
    ) -> Job:
        initial = self.store.load(job_id)
        selected_storyline_id = storyline_id or initial.selected_storyline_id or initial.export.selected_storyline_id
        if not selected_storyline_id:
            raise JobServiceError("storyline_id is required")
        current_selected_id = initial.selected_storyline_id or initial.export.selected_storyline_id
        if storyline_id is not None and current_selected_id is not None and storyline_id != current_selected_id:
            raise JobServiceError("requested storyline is not selected for export")
        story_for_request = self._find_storyline(initial, selected_storyline_id)
        if subtitles_on is not None and story_for_request.subtitles_on != subtitles_on:
            self.select_variant(
                job_id,
                selected_storyline_id,
                title_index=story_for_request.selected_title_index,
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

        try:
            self._copy_export_variant(job_id, story, variant, destination)
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
            return self._save(job)

    def export_many(
        self,
        job_id: str,
        destination_dir: Path,
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
                    title_index=story.selected_title_index,
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

        destination_dir = destination_dir.expanduser()
        destination_dir.mkdir(parents=True, exist_ok=True)
        try:
            for story, variant in exports:
                destination = destination_dir / f"storyline-{story.index + 1}.mp4"
                self._copy_export_variant(job_id, story, variant, destination)
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
    ) -> None:
        if variant.path is None:
            raise JobServiceError("selected variant has no output path")
        destination = destination.expanduser()
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_name(f".{destination.stem}.part{destination.suffix}")
        isolation_meta: dict[str, Any] = {
            "voice_isolation": False,
            "voice_isolation_cache_hit": None,
            "voice_isolation_audio_hash": None,
        }
        try:
            if self.config.voice_isolation:
                api_key = self.deps.resolve_voice_isolation_key()
                if not api_key:
                    raise JobServiceError(
                        "ElevenLabs API key가 없습니다. 설정에서 API 키를 저장하세요."
                    )
                try:
                    result = self.deps.enhance_export_video(
                        Path(variant.path),
                        tmp,
                        cache_dir=self.store.job_dir(job_id) / ".voice-isolation",
                        api_key=api_key,
                    )
                except voice_isolation.VoiceIsolationError as exc:
                    raise JobServiceError(str(exc)) from exc
                isolation_meta = {
                    "voice_isolation": True,
                    "voice_isolation_cache_hit": result.cache_hit,
                    "voice_isolation_audio_hash": result.audio_hash,
                }
            else:
                shutil.copy2(variant.path, tmp)
            os.replace(tmp, destination)
        finally:
            if tmp.exists():
                tmp.unlink()
        manifest = destination.with_suffix(destination.suffix + ".manifest.json")
        manifest.write_text(
            json.dumps(
                {
                    "job_id": job_id,
                    "storyline_id": story.id,
                    "variant_id": variant.id,
                    "title": variant.title_text,
                    "subtitles_on": variant.subtitles_enabled,
                    "output_path": str(destination),
                    **isolation_meta,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _record_export_failure(self, job_id: str, exc: Exception) -> None:
        with self._lock:
            job = self.store.load(job_id)
            job.export.status = Status.FAILED
            job.export.error = str(exc)
            job.phase = "export-failed"
            job.message = "내보내기에 실패했습니다."
            self._save(job)

    def _validated_duration(self, duration_s: int | None) -> int:
        selected = self.duration_s if duration_s is None else duration_s
        if selected not in ALLOWED_DURATIONS:
            raise JobServiceError(f"duration_s must be one of {sorted(ALLOWED_DURATIONS)}")
        return selected

    def _validated_storyline_count(self, n_storylines: int | None) -> int:
        selected = self.config.n_storylines if n_storylines is None else n_storylines
        if not 1 <= selected <= MAX_DESKTOP_STORYLINES:
            raise JobServiceError(f"n_storylines must be between 1 and {MAX_DESKTOP_STORYLINES}")
        return selected

    def _validated_provider(self, provider: str | None) -> str:
        selected = self.config.provider if provider is None else provider
        if selected not in DESKTOP_PROVIDERS:
            raise JobServiceError(f"provider must be one of {sorted(DESKTOP_PROVIDERS)}")
        return selected

    def _create_job(
        self,
        project_path: str,
        duration_s: int,
        n_storylines: int,
        provider: str,
    ) -> Job:
        model = self.config.model if provider == self.config.provider else ""
        job = self.store.create_job(
            project_path=project_path,
            provider=provider,
            model=model,
            duration_s=duration_s,
            n_storylines=n_storylines,
        )
        job.status = Status.LOADING
        job.phase = "loading"
        job.progress = 0.02
        job.message = "CapCut 프로젝트를 불러오는 중입니다."
        job.work_dir = str(self.store.job_dir(job.id))
        return self._save(job)

    def _run_job_guarded(self, job_id: str) -> None:
        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        try:
            with use_process_registry(registry):
                self._run_job(job_id)
        except Exception as exc:  # noqa: BLE001 - boundary converts background failures to job state
            with self._lock:
                job = self.store.load(job_id)
                if not self._is_cancelled(job_id) and job.status is not Status.CANCELLED:
                    job.status = Status.FAILED
                    job.phase = "failed"
                    job.error = str(exc)
                    job.message = "작업이 실패했습니다."
                    self._save(job)
        finally:
            with self._lock:
                self._release_job_operation_locked(job_id)

    def _run_job(self, job_id: str) -> None:
        job = self.store.load(job_id)
        provider = job.provider or self.config.provider
        cfg = AppConfig(
            provider=provider,
            model=job.model or "",
            base_url=self.config.base_url if provider == self.config.provider else "",
            n_storylines=job.n_storylines,
            style=dict(self.config.style),
        )
        project_dir = self.deps.find_project(str(job.project_path))
        self._set_job_progress(
            job_id,
            phase="loading",
            progress=0.05,
            message="CapCut 프로젝트 폴더와 초안 파일을 확인하는 중입니다.",
        )
        draft = self.deps.load_project(project_dir)
        self._set_job_progress(
            job_id,
            phase="loading",
            progress=0.08,
            message="타임라인의 영상·오디오·자막 구간을 분석하는 중입니다.",
        )
        segments = self.deps.build_segments(draft)
        video = Path(segments["video_path"])
        style = merged_style(self.deps.load_style(self.style_path), cfg.style)
        speed = style.speed
        work = self.store.job_dir(job.id)

        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.project_name = project_dir.name
            job.input_path = str(video)
            job.output_dir = str(work)
            job.status = Status.GENERATING
            job.phase = "generating"
            job.progress = 0.12
            job.message = f"{cfg.provider}로 스토리라인 {job.n_storylines}개를 생성하는 중입니다."
            self._save(job)
        self._raise_if_cancelled(job_id)

        registry = self._process_registries.setdefault(job_id, ProcessRegistry())
        runner = self.deps.build_runner(cfg)

        def managed_runner(prompt: str) -> str:
            with use_process_registry(registry):
                return runner(prompt)

        results = self.deps.generate_many(
            segments,
            job.n_storylines,
            job.duration_s,
            runner=managed_runner,
            raw_dump_dir=work,
        )
        with self._lock:
            job = self.store.load(job_id)
            if self._is_cancelled(job_id) or job.status is Status.CANCELLED:
                return
            job.storylines = [self._storyline_from_result(result) for result in results]
            if all(story.doc is None for story in results):
                job.status = Status.FAILED
                job.phase = "failed"
                job.progress = 1.0
                job.error = "모든 스토리라인 생성에 실패했습니다."
                job.message = job.error
                self._save(job)
                return
            job.status = Status.RENDERING_BASE
            job.phase = "rendering"
            job.progress = 0.28
            job.message = f"대표 영상 {job.n_storylines}개를 렌더링하는 중입니다."
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
                job.error = "렌더링에 성공한 스토리라인이 없습니다."
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
                    job.message = f"대표 영상 {job.n_storylines}개가 준비되었습니다."
                else:
                    job.status = Status.FAILED
                    job.phase = "partial-failure"
                    job.error = f"대표 영상 {len(ready)}/{job.n_storylines}개만 준비되었습니다."
                    job.message = job.error
            self._save(job)

    def _storyline_from_result(self, result: StorylineResult) -> Storyline:
        storyline = Storyline(
            id=f"s{result.index + 1}",
            index=result.index,
            angle_name=result.angle_name,
            status=Status.GENERATING if result.doc is not None else Status.FAILED,
            progress=0.0,
            error=result.error,
        )
        if result.doc is not None:
            storyline.title_candidates = [
                str(item.get("text", "")).strip()
                for item in result.doc.get("title_candidates", [])
            ][:3]
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
            self._write_storyline_outputs_once(sdir, result.doc, segments, video, style, speed)
            self._raise_if_cancelled(job_id)
            self._set_storyline_render_progress(
                job_id,
                story_id,
                progress=0.45,
                status=Status.RENDERING_BASE,
                detail="선택한 구간을 세로 영상으로 렌더링하는 중입니다.",
            )
            assets = self.deps.render_base_and_assets(video, segments, result.doc, style, sdir / ".render", speed)
            self._raise_if_cancelled(job_id)
            self._set_storyline_render_progress(
                job_id,
                story_id,
                progress=0.78,
                status=Status.RENDERING_OVERLAY,
                detail="제목·자막 오버레이와 오디오를 합성하는 중입니다.",
            )
            assets_path = assets.write_manifest(sdir / ".render" / "assets.json")
            title = result.doc["title_candidates"][0]
            key = render.variant_cache_key(
                storyline_id=story_id,
                title_text=title["text"],
                subtitles_enabled=True,
                style_hash_value=f"{render.style_hash(style)}-{_assets_fingerprint(assets_path, assets)}",
            )
            out = sdir / f"{key}.mp4"
            self.deps.render_overlay_variant(
                assets,
                title_text=title["text"],
                keyword=title.get("keyword", ""),
                style=style,
                out_path=out,
                subtitles_enabled=True,
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
                storyline.selected_title_index = 0
                storyline.subtitles_on = True
                storyline.variants = [
                    Variant(
                        id=artifact.id,
                        title_index=0,
                        title_text=title["text"],
                        subtitles_enabled=True,
                        subtitles_on=True,
                        style_hash=render.style_hash(style),
                        status=Status.READY,
                        path=str(out),
                    )
                ]
                self._save(job)
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
                    f"스토리라인 {storyline.index + 1}: {detail} "
                    f"· 전체 {completed}/{job.n_storylines}개 완료"
                )
            self._save(job)

    def _render_storyline_base(self, job_id: str, storyline_id: str) -> None:
        job = self.store.load(job_id)
        story = self._find_storyline(job, storyline_id)
        if not story.edl_path:
            raise JobServiceError("storyline has no persisted EDL")
        segments = json.loads((Path(story.edl_path).parent / "segments.json").read_text(encoding="utf-8"))
        doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8"))
        style = merged_style(self.deps.load_style(self.style_path), self.config.style)
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
        style = merged_style(self.deps.load_style(self.style_path), self.config.style)
        assets = render.RenderAssets.read_manifest(Path(story.assets_path))
        title_index = story.selected_title_index
        title_text = story.title_candidates[title_index]
        doc = json.loads(Path(story.edl_path).read_text(encoding="utf-8")) if story.edl_path else {"title_candidates": []}
        title_doc = doc.get("title_candidates", [{}])[title_index] if title_index < len(doc.get("title_candidates", [])) else {}
        key = render.variant_cache_key(
            storyline_id=storyline_id,
            title_text=title_text,
            subtitles_enabled=story.subtitles_on,
            style_hash_value=f"{render.style_hash(style)}-{_assets_fingerprint(Path(story.assets_path), assets)}",
        )
        out = Path(story.assets_path).parent.parent / f"{key}.mp4"
        if not out.is_file():
            self.deps.render_overlay_variant(
                assets,
                title_text=title_text,
                keyword=str(title_doc.get("keyword", "")),
                style=style,
                out_path=out,
                subtitles_enabled=story.subtitles_on,
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
                title_index=title_index,
                title_text=title_text,
                subtitles_enabled=story.subtitles_on,
                subtitles_on=story.subtitles_on,
                style_hash=render.style_hash(style),
                status=Status.READY,
                path=str(out),
            )
            story.variants = [item for item in story.variants if item.path != str(out)]
            story.variants.append(variant)
            story.active_variant_path = str(out)
            story.status = Status.READY
            story.progress = 1.0
            job.status = Status.READY
            job.phase = "ready"
            job.progress = 1.0
            job.message = "선택한 제목/자막 버전이 준비되었습니다."
            self._save(job)
            should_select_for_export = selected_for_export or job.selected_storyline_id == story.id
            if should_select_for_export:
                job = self.store.load(job_id)
                story = self._find_storyline(job, storyline_id)
                self._select_export_variant(job, story, variant)

    def _write_storyline_outputs_once(
        self,
        sdir: Path,
        doc: dict[str, Any],
        segments: dict[str, Any],
        video: Path,
        style: StylePreset,
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
        cuts_dir = sdir / "cuts"
        if not cuts_dir.is_dir() or not any(cuts_dir.glob("*.mp4")):
            self.deps.export_cuts(video, doc, segments, cuts_dir, speed)

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

    def _active_variant(self, story: Storyline) -> Variant:
        active_path = story.active_variant_path
        for variant in story.variants:
            if variant.path == active_path:
                return variant
        if story.variants:
            return story.variants[-1]
        raise JobServiceError("storyline has no variants")

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


def _assets_fingerprint(manifest_path: Path, assets: render.RenderAssets) -> str:
    digest = hashlib.sha256()
    try:
        digest.update(manifest_path.read_bytes())
    except OSError:
        digest.update(str(manifest_path).encode("utf-8"))
    for path in [assets.base, assets.wm_png, *assets.sub_pngs]:
        try:
            stat = path.stat()
        except OSError:
            digest.update(str(path).encode("utf-8"))
            continue
        digest.update(str(path).encode("utf-8"))
        digest.update(str(stat.st_size).encode("ascii"))
        digest.update(str(stat.st_mtime_ns).encode("ascii"))
    return digest.hexdigest()[:12]
