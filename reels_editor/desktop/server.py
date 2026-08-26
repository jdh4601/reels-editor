from __future__ import annotations

import asyncio
import json
import secrets
import socket
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen

import uvicorn
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from reels_editor import candidate_analyzer
from reels_editor.config import (
    AppConfig,
    DEFAULT_PLAYBACK_SPEED,
    load_config,
    save_config,
)
from reels_editor.jobs import ContentCandidate, Job, JobService, JobServiceError, JobStore, Status, Storyline, Variant
from reels_editor.youtube import YouTubeSourceError, thumbnail_url_for_video, video_id_from_url

from .dialogs import DialogProvider, FakeDialogProvider
from .tools import probe_required_tools


class SaveDialogRequest(BaseModel):
    suggested_name: str = "reel.mp4"


class CreateJobRequest(BaseModel):
    youtube_url: str | None = Field(default=None, max_length=2048)
    episode_number: int = Field(default=1, ge=1)
    content_types: list[Literal["story", "strategy", "failure", "principle"]] = Field(
        default_factory=lambda: ["story", "strategy", "failure", "principle"],
        min_length=1,
        max_length=4,
    )
    provider: Literal["codex-cli", "claude-cli", "openai", "kimi"] = "codex-cli"


class SelectionRequest(BaseModel):
    subtitles_on: bool = True
    selected_for_export: bool = False


class ExportRequest(BaseModel):
    storyline_id: str | None = None
    subtitles_on: bool | None = None
    suggested_name: str = "reel.mp4"


class BatchExportRequest(BaseModel):
    storyline_ids: list[str] = Field(min_length=1, max_length=10)
    subtitles_on: bool | None = None


class GenerateCandidatesRequest(BaseModel):
    candidate_ids: list[str] = Field(min_length=1, max_length=10)


class StorylineTitleRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class PlaybackSpeedSettingsRequest(BaseModel):
    speed: float = Field(ge=1.0, le=1.5)


def create_app(
    *,
    static_dir: Path,
    media_dir: Path,
    dialog_provider: DialogProvider | None = None,
    job_service: JobService | None = None,
    session_token: str | None = None,
    config_path: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="Reels Editor Desktop")
    dialogs = dialog_provider or FakeDialogProvider()
    service = job_service or JobService(store=JobStore())
    token = session_token or secrets.token_urlsafe(24)
    app.state.session_token = token

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "static_dir": str(static_dir), "media_dir": str(media_dir), "token_required": True}

    def require_token(
        request: Request,
        authorization: str | None = Header(default=None),
        query_token: str | None = Query(default=None, alias="token"),
    ) -> None:
        supplied = query_token
        if authorization and authorization.lower().startswith("bearer "):
            supplied = authorization.split(" ", 1)[1].strip()
        if supplied != token:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session token")

    @app.get("/api/tools")
    def tools(_auth: None = Depends(require_token)) -> dict[str, Any]:
        return probe_required_tools()

    def playback_speed_settings() -> dict[str, float]:
        config = getattr(service, "config", AppConfig(provider="codex-cli"))
        speed = float(config.style.get("speed", DEFAULT_PLAYBACK_SPEED))
        return {"speed": round(speed, 2)}

    @app.get("/api/settings/playback-speed")
    def get_playback_speed_settings(_auth: None = Depends(require_token)) -> dict[str, float]:
        return playback_speed_settings()

    @app.put("/api/settings/playback-speed")
    def put_playback_speed_settings(
        request: PlaybackSpeedSettingsRequest,
        _auth: None = Depends(require_token),
    ) -> dict[str, float]:
        # UI 눈금과 동일하게 0.05배 단위로 정규화해 직접 API 호출도 일관되게 처리한다.
        speed = round(request.speed * 20) / 20
        persisted = load_config(config_path)
        save_config(replace(persisted, style={**persisted.style, "speed": speed}), config_path)
        current = getattr(service, "config", AppConfig(provider="codex-cli"))
        service.config = replace(current, style={**current.style, "speed": speed})
        return playback_speed_settings()

    @app.post("/api/dialogs/save-file")
    def save_file(request: SaveDialogRequest, _auth: None = Depends(require_token)) -> dict[str, str | None]:
        return {"path": dialogs.choose_save_file(request.suggested_name)}

    @app.get("/api/snapshot")
    def snapshot(_auth: None = Depends(require_token)) -> dict[str, Any]:
        return _snapshot_from_job(service.snapshot())

    @app.delete("/api/snapshot")
    def clear_snapshot(_auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            service.clear_current()
        except JobServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _snapshot_from_job(None)

    @app.post("/api/jobs")
    def create_job(request: CreateJobRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            if request.youtube_url and request.youtube_url.strip():
                job = service.start_youtube_job(
                    request.youtube_url,
                    content_types=request.content_types,
                    provider=request.provider,
                    episode_number=request.episode_number,
                )
            else:
                raise HTTPException(status_code=422, detail="YouTube URL이 필요합니다.")
        except YouTubeSourceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except JobServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.get("/api/archive")
    def archive(_auth: None = Depends(require_token)) -> dict[str, Any]:
        return {"items": _archive_items(service.archive_jobs())}

    @app.post("/api/jobs/{job_id}/open")
    def open_job(job_id: str, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = service.open_job(job_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc
        except JobServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/generate")
    def generate_candidates(
        job_id: str,
        request: GenerateCandidatesRequest,
        _auth: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            job = service.start_selected_generation(job_id, request.candidate_ids)
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.patch("/api/jobs/{job_id}/storylines/{storyline_id}/selection")
    def select_variant(
        job_id: str,
        storyline_id: str,
        request: SelectionRequest,
        _auth: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            job = service.select_variant(
                job_id,
                storyline_id,
                subtitles_on=request.subtitles_on,
                selected_for_export=request.selected_for_export,
            )
        except (JobServiceError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/storylines/{storyline_id}/retry")
    def retry_storyline(job_id: str, storyline_id: str, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            return _snapshot_from_job(service.retry_storyline(job_id, storyline_id))
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/storylines/{storyline_id}/caption")
    def generate_instagram_caption(
        job_id: str,
        storyline_id: str,
        _auth: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            job = service.generate_instagram_caption(job_id, storyline_id)
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.patch("/api/jobs/{job_id}/storylines/{storyline_id}/title")
    def update_storyline_title(
        job_id: str,
        storyline_id: str,
        request: StorylineTitleRequest,
        _auth: None = Depends(require_token),
    ) -> dict[str, Any]:
        try:
            job = service.update_storyline_title(job_id, storyline_id, request.title)
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/export")
    def export_job(job_id: str, request: ExportRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = service.export_selected(
                job_id,
                storyline_id=request.storyline_id,
                subtitles_on=request.subtitles_on,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if job.export.output_path:
            dialogs.show_in_file_manager(Path(job.export.output_path).expanduser().parent)
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/export-batch")
    def export_batch(job_id: str, request: BatchExportRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = service.export_many(
                job_id,
                storyline_ids=request.storyline_ids,
                subtitles_on=request.subtitles_on,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if job.export.output_path:
            dialogs.show_in_file_manager(Path(job.export.output_path).expanduser())
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            return _snapshot_from_job(service.cancel(job_id))
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.websocket("/api/events")
    async def events(websocket: WebSocket, after: int = 0, token: str | None = None) -> None:
        if token != app.state.session_token:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await websocket.accept()
        cursor = after
        try:
            first = service.snapshot()
            if first and first.seq > cursor:
                await websocket.send_json(_snapshot_from_job(first))
                cursor = first.seq
            while True:
                job = await asyncio.to_thread(service.wait_for_update, cursor, 25)
                if job is None:
                    await websocket.send_json({"event": "heartbeat", "seq": cursor})
                    continue
                payload = _snapshot_from_job(job)
                cursor = int(payload.get("seq", cursor))
                await websocket.send_json(payload)
        except WebSocketDisconnect:
            return

    @app.get("/api/media")
    def media(_auth: None = Depends(require_token)) -> dict[str, Any]:
        files = sorted(media_dir.glob("*.mp4"))
        return {
            "items": [
                {"name": path.name, "url": f"/media/{path.name}", "size": path.stat().st_size}
                for path in files
            ]
        }

    @app.get("/media/{filename}")
    def media_file(filename: str, _auth: None = Depends(require_token)) -> FileResponse:
        path = (media_dir / filename).resolve()
        if media_dir.resolve() not in path.parents or not path.is_file():
            raise HTTPException(status_code=404, detail="media not found")
        return FileResponse(path, media_type="video/mp4")

    @app.get("/media/{job_id}/{artifact_id}")
    def artifact_file(
        job_id: str,
        artifact_id: str,
        request: Request,
        _auth: None = Depends(require_token),
    ) -> Response:
        try:
            path = service.store.resolve_artifact(job_id, artifact_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="artifact not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail="artifact unavailable") from exc
        return _range_response(path, request.headers.get("range"))

    assets_dir = static_dir / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str) -> FileResponse:
        requested = (static_dir / path).resolve()
        if static_dir.resolve() in requested.parents and requested.is_file():
            return FileResponse(requested)
        return FileResponse(static_dir / "index.html")

    return app


def _snapshot_from_job(job: Job | None) -> dict[str, Any]:
    if job is None:
        return {
            "job_id": "",
            "project_name": "Reels Editor",
            "source_url": None,
            "source_thumbnail_url": None,
            "thumbnail_url": None,
            "episode_number": 1,
            "source_label": "YouTube 링크 없음",
            "connection": "connected",
            "generated_at": "",
            "storylines": [],
            "selected_storyline_id": None,
            "subtitles_on": True,
            "duration_s": candidate_analyzer.TARGET_DURATION_S,
            "n_storylines": 0,
            "content_types": list(candidate_analyzer.CONTENT_TYPES),
            "candidates": [],
            "selected_candidate_ids": [],
            "provider": "codex-cli",
            "seq": 0,
            "event_seq": 0,
        }
    return {
        "job_id": job.id,
        "project_name": job.project_name or "Reels Editor",
        "source_url": job.source_url,
        "source_thumbnail_url": _source_thumbnail_url(job),
        "thumbnail_url": _source_thumbnail_url(job),
        "episode_number": job.episode_number,
        "transcript_language": job.transcript_language,
        "transcript_kind": job.transcript_kind,
        "source_label": _source_label(job),
        "connection": "connected",
        "generated_at": job.updated_at,
        "status": job.status.value,
        "phase": job.phase,
        "progress": job.progress,
        "message": job.message,
        "error": job.error,
        "selected_storyline_id": job.selected_storyline_id or job.export.selected_storyline_id,
        "subtitles_on": _selected_subtitles(job),
        "duration_s": job.duration_s,
        "n_storylines": job.n_storylines,
        "content_types": job.content_types,
        "candidates": [_candidate_snapshot(candidate) for candidate in job.candidates],
        "selected_candidate_ids": job.selected_candidate_ids,
        "provider": job.provider or "codex-cli",
        "storylines": [_storyline_snapshot(job, storyline) for storyline in job.storylines],
        "export": job.export.to_dict(),
        "seq": job.seq,
        "event_seq": job.seq,
    }


def _candidate_snapshot(candidate: ContentCandidate) -> dict[str, Any]:
    definition = candidate_analyzer.CONTENT_TYPES.get(candidate.content_type, {})
    return {
        **candidate.to_dict(),
        "type_label": definition.get("label", candidate.content_type),
    }


def _storyline_snapshot(job: Job, storyline: Storyline) -> dict[str, Any]:
    variant = _active_variant(storyline)
    artifact_id = _artifact_for_variant(job, variant)
    content = _story_content_for_storyline(storyline)
    return {
        "id": storyline.id,
        "storyline_id": storyline.id,
        "index": storyline.index + 1,
        "label": f"릴스 {storyline.index + 1}",
        "hook": storyline.angle_name or storyline.title or "대표 영상",
        "summary": content["summary"],
        "sections": content["sections"],
        "status": _ui_status(storyline.status),
        "progress": int(round(storyline.progress * 100)) if storyline.progress <= 1 else int(storyline.progress),
        "video_url": _media_url(job.id, artifact_id) if artifact_id else None,
        "title": storyline.title,
        "instagram_caption": storyline.instagram_caption,
        "archive_path": storyline.archive_path,
        "completed_at": storyline.completed_at,
        "error": _storyline_error_message(storyline.error),
        "revision": storyline.revision,
    }


def _source_label(job: Job) -> str:
    if job.transcript_language:
        kind = "수동" if job.transcript_kind == "manual" else "자동"
        return f"YouTube · {job.transcript_language} {kind} 자막"
    return job.source_url or "YouTube 인터뷰"


def _source_thumbnail_url(job: Job) -> str | None:
    return job.source_thumbnail_url or thumbnail_url_for_video(
        video_id_from_url(job.source_url or "")
    )


def _archive_items(jobs: list[Job]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for job in jobs:
        for storyline in job.storylines:
            snapshot = _storyline_snapshot(job, storyline)
            if snapshot["status"] != "ready" or not snapshot["video_url"]:
                continue
            items.append(
                {
                    "job_id": job.id,
                    "storyline_id": storyline.id,
                    "episode_number": job.episode_number,
                    "project_name": job.project_name or "YouTube 인터뷰",
                    "source_title": job.project_name or "YouTube 인터뷰",
                    "source_url": job.source_url,
                    "source_thumbnail_url": _source_thumbnail_url(job),
                    "thumbnail_url": _source_thumbnail_url(job),
                    "reel_title": storyline.title or storyline.angle_name or "대표 영상",
                    "title": storyline.title or storyline.angle_name or "대표 영상",
                    "completed_at": storyline.completed_at or job.updated_at,
                    "generated_at": job.updated_at,
                    "video_url": snapshot["video_url"],
                    "instagram_caption": storyline.instagram_caption,
                    "archive_path": storyline.archive_path,
                    "export_path": storyline.archive_path,
                    "status": "ready",
                }
            )
    return items


def _active_variant(storyline: Storyline) -> Variant | None:
    if storyline.active_variant_path:
        for variant in storyline.variants:
            if (
                variant.path == storyline.active_variant_path
                and _variant_is_playable(variant)
            ):
                return variant
    return next(
        (variant for variant in reversed(storyline.variants) if _variant_is_playable(variant)),
        None,
    )


def _variant_is_playable(variant: Variant) -> bool:
    return bool(
        variant.status is Status.READY
        and variant.path
        and Path(variant.path).is_file()
    )


def _artifact_for_variant(job: Job, variant: Variant | None) -> str | None:
    if variant is None or not _variant_is_playable(variant):
        return None
    target = Path(variant.path).resolve()
    for artifact in job.artifacts.values():
        artifact_path = Path(artifact.path).resolve()
        if artifact_path == target and artifact_path.is_file():
            return artifact.id
    return None


def _placeholder_storyline(index: int) -> dict[str, Any]:
    display = index + 1
    return {
        "id": f"placeholder-{display}",
        "storyline_id": f"placeholder-{display}",
        "index": display,
        "label": f"릴스 {display}",
        "hook": "대기 중",
        "summary": "YouTube 인터뷰 링크를 넣으면 클립 후보와 후킹 제목이 여기에 표시됩니다.",
        "sections": [],
        "status": "queued",
        "progress": 0,
        "video_url": None,
        "title": "제목 준비 중",
        "error": None,
        "revision": 0,
    }


def _media_url(job_id: str, artifact_id: str | None) -> str | None:
    if artifact_id is None:
        return None
    return f"/media/{job_id}/{artifact_id}"


def _selected_subtitles(job: Job) -> bool:
    selected = job.selected_storyline_id or job.export.selected_storyline_id
    for storyline in job.storylines:
        if storyline.id == selected:
            return storyline.subtitles_on
    return True


_BEAT_ROLES = {
    "훅": "첫 3초에 시선을 붙잡는 문장",
    "맥락": "이야기를 이해시키는 배경",
    "갈등": "문제와 긴장을 선명하게 만드는 구간",
    "전환": "생각이나 행동이 바뀌는 순간",
    "핵심 장면": "변화를 증명하는 구체적인 장면",
    "라스트 답": "영상이 남기는 결론과 메시지",
}

_FIVE_LINE_BEATS = {
    "situation": ("훅 · 상황", "첫 장면에서 맥락과 궁금증을 만드는 문장"),
    "desire": ("목표", "주인공이 원하는 것을 보여주는 문장"),
    "conflict": ("갈등", _BEAT_ROLES["갈등"]),
    "change": ("전환", _BEAT_ROLES["전환"]),
    "result": ("결론", _BEAT_ROLES["라스트 답"]),
}


def _story_content_for_storyline(storyline: Storyline) -> dict[str, Any]:
    if not storyline.edl_path:
        error = _storyline_error_message(storyline.error)
        return {
            "summary": error or "릴스 생성 대기 중입니다.",
            "sections": [],
        }
    try:
        doc = json.loads(Path(storyline.edl_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"summary": _storyline_error_message(storyline.error) or "", "sections": []}

    segments_path = (
        Path(storyline.segments_path)
        if storyline.segments_path
        else Path(storyline.edl_path).with_name("segments.json")
    )
    try:
        segments_doc = json.loads(segments_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        segments_doc = {}
    segment_text = {
        str(item.get("id", "")): str(item.get("text", "")).strip()
        for item in segments_doc.get("segments", [])
        if isinstance(item, dict) and item.get("id") and item.get("text")
    }
    subtitle_translations = doc.get("subtitle_translations", {})
    if not isinstance(subtitle_translations, dict):
        subtitle_translations = {}

    sections: list[dict[str, str]] = []
    for cut in doc.get("cuts", []):
        if not isinstance(cut, dict):
            continue
        beat = str(cut.get("beat", "구간")).strip() or "구간"
        text = " ".join(
            str(subtitle_translations.get(str(segment_id)) or segment_text.get(str(segment_id), ""))
            for segment_id in cut.get("seg_ids", [])
        ).strip()
        if text:
            sections.append({
                "beat": beat,
                "role": _BEAT_ROLES.get(beat, "이야기의 흐름을 이어가는 구간"),
                "text": text,
            })

    if sections:
        return {
            "summary": " ".join(section["text"] for section in sections),
            "sections": sections,
        }

    five = doc.get("story", {}).get("five_lines", {})
    if isinstance(five, dict):
        for key, (beat, role) in _FIVE_LINE_BEATS.items():
            text = str(five.get(key, "")).strip()
            if text:
                sections.append({"beat": beat, "role": role, "text": text})
    summary = " ".join(section["text"] for section in sections)
    if not summary:
        summary = str(doc.get("story", {}).get("lens", ""))
    return {"summary": summary, "sections": sections}


def _storyline_error_message(error: str | None) -> str | None:
    if not error:
        return None
    if "대본 생성 3회 실패" in error and ("마지막 응답" in error or "JSON 파싱" in error):
        return (
            "AI 응답의 JSON 따옴표 형식이 올바르지 않아 대본을 읽지 못했습니다. "
            "작업이 끝난 뒤 다시 시도를 누르면 저장된 응답을 복구합니다."
        )
    return error if len(error) <= 600 else error[:597] + "..."


def _summary_for_storyline(storyline: Storyline) -> str:
    return str(_story_content_for_storyline(storyline)["summary"])


def _ui_status(value: Status) -> str:
    if value is Status.READY:
        return "ready"
    if value in {Status.FAILED, Status.CANCELLED}:
        return "failed"
    if value is Status.RENDERING_OVERLAY:
        return "overlaying"
    return "rendering" if value is not Status.IDLE else "queued"


def _range_response(path: Path, range_header: str | None) -> Response:
    size = path.stat().st_size
    headers = {"Accept-Ranges": "bytes"}
    if not range_header:
        return FileResponse(path, media_type="video/mp4", headers=headers)
    try:
        unit, raw_range = range_header.split("=", 1)
        if unit.strip().lower() != "bytes":
            raise ValueError
        start_raw, end_raw = raw_range.split("-", 1)
        if start_raw == "":
            suffix = int(end_raw)
            if suffix <= 0:
                raise ValueError
            start = max(0, size - suffix)
            end = size - 1
        else:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
        if start < 0 or end < start or start >= size:
            raise ValueError
        end = min(end, size - 1)
    except ValueError:
        return Response(status_code=416, headers={**headers, "Content-Range": f"bytes */{size}"})
    with path.open("rb") as file:
        file.seek(start)
        body = file.read(end - start + 1)
    return Response(
        body,
        status_code=206,
        media_type="video/mp4",
        headers={
            **headers,
            "Content-Range": f"bytes {start}-{end}/{size}",
            "Content-Length": str(len(body)),
        },
    )


class UvicornThread:
    def __init__(self, app: FastAPI):
        self.app = app
        self.host = "127.0.0.1"
        self.port: int | None = None
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if self.port is None:
            raise RuntimeError("server has not been started")
        return f"http://{self.host}:{self.port}"

    def start(self) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind((self.host, 0))
        sock.listen(2048)
        self.port = sock.getsockname()[1]
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="warning")
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(
            target=self.server.run,
            kwargs={"sockets": [sock]},
            daemon=True,
            name="reels-editor-uvicorn",
        )
        self.thread.start()
        self.wait_ready()
        return self.url

    def wait_ready(self, timeout: float = 10) -> None:
        deadline = time.monotonic() + timeout
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                with urlopen(f"{self.url}/api/health", timeout=0.5) as response:
                    if response.status == 200:
                        return
            except Exception as exc:  # pragma: no cover - timing dependent
                last_error = exc
                time.sleep(0.05)
        raise RuntimeError(f"server did not become ready: {last_error}")

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
