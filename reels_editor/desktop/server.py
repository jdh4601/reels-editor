from __future__ import annotations

import asyncio
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

from reels_editor.config import (
    AppConfig,
    load_config,
    mask_key,
    resolve_api_key,
    save_config,
    save_credential,
)
from reels_editor.jobs import Job, JobService, JobServiceError, JobStore, Status, Storyline, Variant

from .dialogs import DialogProvider, FakeDialogProvider
from .tools import probe_required_tools


class SaveDialogRequest(BaseModel):
    suggested_name: str = "reel.mp4"


class CreateJobRequest(BaseModel):
    project_path: str
    duration_s: Literal[15, 30, 60] = 30
    n_storylines: int = Field(default=3, ge=1, le=10)
    provider: Literal["codex-cli", "claude-cli", "openai", "kimi"] = "codex-cli"


class SelectionRequest(BaseModel):
    title_index: int
    subtitles_on: bool = True
    selected_for_export: bool = False


class ExportRequest(BaseModel):
    storyline_id: str | None = None
    subtitles_on: bool | None = None
    suggested_name: str = "reel.mp4"


class BatchExportRequest(BaseModel):
    storyline_ids: list[str] = Field(min_length=1, max_length=10)
    subtitles_on: bool | None = None


class VoiceIsolationSettingsRequest(BaseModel):
    enabled: bool
    api_key: str | None = Field(default=None, max_length=512)


def create_app(
    *,
    static_dir: Path,
    media_dir: Path,
    dialog_provider: DialogProvider | None = None,
    job_service: JobService | None = None,
    session_token: str | None = None,
    config_path: Path | None = None,
    credentials_path: Path | None = None,
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

    def voice_isolation_settings() -> dict[str, Any]:
        key = resolve_api_key("elevenlabs", credentials_path)
        config = getattr(service, "config", AppConfig(provider="codex-cli"))
        return {
            "enabled": bool(config.voice_isolation),
            "configured": bool(key),
            "masked_key": mask_key(key) if key else None,
        }

    @app.get("/api/settings/voice-isolation")
    def get_voice_isolation_settings(_auth: None = Depends(require_token)) -> dict[str, Any]:
        return voice_isolation_settings()

    @app.put("/api/settings/voice-isolation")
    def put_voice_isolation_settings(
        request: VoiceIsolationSettingsRequest,
        _auth: None = Depends(require_token),
    ) -> dict[str, Any]:
        api_key = (request.api_key or "").strip()
        if api_key:
            save_credential("elevenlabs", api_key, credentials_path)
        if request.enabled and not resolve_api_key("elevenlabs", credentials_path):
            raise HTTPException(status_code=400, detail="ElevenLabs API key가 필요합니다.")
        persisted = replace(load_config(config_path), voice_isolation=request.enabled)
        save_config(persisted, config_path)
        current = getattr(service, "config", AppConfig(provider="codex-cli"))
        service.config = replace(current, voice_isolation=request.enabled)
        return voice_isolation_settings()

    @app.post("/api/dialogs/open-folder")
    def open_folder(_auth: None = Depends(require_token)) -> dict[str, str | None]:
        return {"path": dialogs.choose_folder()}

    @app.post("/api/dialogs/save-file")
    def save_file(request: SaveDialogRequest, _auth: None = Depends(require_token)) -> dict[str, str | None]:
        return {"path": dialogs.choose_save_file(request.suggested_name)}

    @app.get("/api/snapshot")
    def snapshot(_auth: None = Depends(require_token)) -> dict[str, Any]:
        return _snapshot_from_job(service.snapshot())

    @app.post("/api/jobs")
    def create_job(request: CreateJobRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        try:
            job = service.start_job(
                request.project_path,
                duration_s=request.duration_s,
                n_storylines=request.n_storylines,
                provider=request.provider,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
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
                title_index=request.title_index,
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

    @app.post("/api/jobs/{job_id}/export")
    def export_job(job_id: str, request: ExportRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        destination = dialogs.choose_save_file(request.suggested_name)
        if not destination:
            raise HTTPException(status_code=400, detail="export cancelled")
        try:
            job = service.export_selected(
                job_id,
                Path(destination),
                storyline_id=request.storyline_id,
                subtitles_on=request.subtitles_on,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dialogs.show_in_file_manager(Path(destination).expanduser().parent)
        return _snapshot_from_job(job)

    @app.post("/api/jobs/{job_id}/export-batch")
    def export_batch(job_id: str, request: BatchExportRequest, _auth: None = Depends(require_token)) -> dict[str, Any]:
        destination = dialogs.choose_folder()
        if not destination:
            raise HTTPException(status_code=400, detail="export cancelled")
        try:
            job = service.export_many(
                job_id,
                Path(destination),
                storyline_ids=request.storyline_ids,
                subtitles_on=request.subtitles_on,
            )
        except JobServiceError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        dialogs.show_in_file_manager(Path(destination).expanduser())
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
            "project_path": None,
            "source_label": "프로젝트 없음",
            "connection": "connected",
            "generated_at": "",
            "storylines": [_placeholder_storyline(index) for index in range(3)],
            "selected_storyline_id": None,
            "subtitles_on": True,
            "duration_s": 30,
            "n_storylines": 3,
            "provider": "codex-cli",
            "seq": 0,
            "event_seq": 0,
        }
    return {
        "job_id": job.id,
        "project_name": job.project_name or "Reels Editor",
        "project_path": job.project_path,
        "source_label": job.project_path or job.input_path or "선택된 프로젝트",
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
        "provider": job.provider or "codex-cli",
        "storylines": [_storyline_snapshot(job, storyline) for storyline in job.storylines],
        "export": job.export.to_dict(),
        "seq": job.seq,
        "event_seq": job.seq,
    }


def _storyline_snapshot(job: Job, storyline: Storyline) -> dict[str, Any]:
    variant = _active_variant(storyline)
    artifact_id = _artifact_for_variant(job, variant)
    return {
        "id": storyline.id,
        "storyline_id": storyline.id,
        "index": storyline.index + 1,
        "label": f"스토리라인 {storyline.index + 1}",
        "hook": storyline.angle_name or (storyline.title_candidates[0] if storyline.title_candidates else "대표 영상"),
        "summary": _summary_for_storyline(storyline),
        "status": _ui_status(storyline.status),
        "progress": int(round(storyline.progress * 100)) if storyline.progress <= 1 else int(storyline.progress),
        "video_url": _media_url(job.id, artifact_id) if artifact_id else None,
        "title_options": storyline.title_candidates[:3],
        "selected_title_index": storyline.selected_title_index,
        "selected_title": (
            storyline.title_candidates[storyline.selected_title_index]
            if 0 <= storyline.selected_title_index < len(storyline.title_candidates)
            else ""
        ),
        "error": storyline.error,
        "revision": storyline.revision,
    }


def _active_variant(storyline: Storyline) -> Variant | None:
    if storyline.active_variant_path:
        for variant in storyline.variants:
            if variant.path == storyline.active_variant_path:
                return variant
    return storyline.variants[-1] if storyline.variants else None


def _artifact_for_variant(job: Job, variant: Variant | None) -> str | None:
    if variant is None or not variant.path:
        return None
    target = Path(variant.path).resolve()
    for artifact in job.artifacts.values():
        if Path(artifact.path).resolve() == target:
            return artifact.id
    if variant.id in job.artifacts:
        return variant.id
    return None


def _placeholder_storyline(index: int) -> dict[str, Any]:
    display = index + 1
    return {
        "id": f"placeholder-{display}",
        "storyline_id": f"placeholder-{display}",
        "index": display,
        "label": f"스토리라인 {display}",
        "hook": "대기 중",
        "summary": "프로젝트를 선택하면 대표 영상과 추천 제목이 여기에 표시됩니다.",
        "status": "queued",
        "progress": 0,
        "video_url": None,
        "title_options": ["제목 생성 대기", "추천 제목 준비 중", "렌더 후 선택 가능"],
        "selected_title_index": 0,
        "selected_title": "제목 생성 대기",
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


def _summary_for_storyline(storyline: Storyline) -> str:
    if not storyline.edl_path:
        return storyline.error or "스토리라인 생성 대기 중입니다."
    try:
        import json

        doc = json.loads(Path(storyline.edl_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return storyline.error or ""
    five = doc.get("story", {}).get("five_lines", {})
    if isinstance(five, dict):
        return " ".join(str(value) for value in five.values() if value)[:140]
    return str(doc.get("story", {}).get("lens", ""))[:140]


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
