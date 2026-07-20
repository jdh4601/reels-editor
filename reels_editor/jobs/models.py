from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = 1


class Status(StrEnum):
    IDLE = "idle"
    LOADING = "loading"
    GENERATING = "generating"
    RENDERING_BASE = "rendering_base"
    RENDERING_OVERLAY = "rendering_overlay"
    READY = "ready"
    EXPORTING = "exporting"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_STATUSES = {
    Status.LOADING,
    Status.GENERATING,
    Status.RENDERING_BASE,
    Status.RENDERING_OVERLAY,
    Status.EXPORTING,
}


def _status(value: Any, default: Status = Status.IDLE) -> Status:
    try:
        return Status(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Variant:
    id: str
    title_index: int
    title_text: str
    subtitles_enabled: bool
    subtitles_on: bool | None = None
    style_hash: str | None = None
    status: Status = Status.IDLE
    path: str | None = None
    selected: bool = False
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        subtitles_on = (
            self.subtitles_enabled
            if self.subtitles_on is None
            else self.subtitles_on
        )
        return {
            "id": self.id,
            "title_index": self.title_index,
            "title_text": self.title_text,
            "subtitles_enabled": self.subtitles_enabled,
            "subtitles_on": subtitles_on,
            "style_hash": self.style_hash,
            "status": self.status.value,
            "path": self.path,
            "selected": self.selected,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Variant:
        return cls(
            id=str(data.get("id", "")),
            title_index=int(data.get("title_index", 0)),
            title_text=str(data.get("title_text", "")),
            subtitles_enabled=bool(
                data.get("subtitles_enabled", data.get("subtitles_on", True))
            ),
            subtitles_on=bool(data["subtitles_on"]) if "subtitles_on" in data else None,
            style_hash=data.get("style_hash"),
            status=_status(data.get("status")),
            path=data.get("path"),
            selected=bool(data.get("selected", False)),
            error=data.get("error"),
        )


@dataclass
class Storyline:
    id: str
    index: int
    angle_name: str = ""
    status: Status = Status.IDLE
    progress: float = 0.0
    title_candidates: list[str] = field(default_factory=list)
    selected_title_index: int = 0
    subtitles_on: bool = True
    variants: list[Variant] = field(default_factory=list)
    base_video_path: str | None = None
    base_path: str | None = None
    assets_path: str | None = None
    active_variant_path: str | None = None
    render_request_id: int = 0
    edl_path: str | None = None
    doc_path: str | None = None
    segments_path: str | None = None
    revision: int = 0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        base_path = self.base_video_path or self.base_path
        return {
            "id": self.id,
            "index": self.index,
            "angle_name": self.angle_name,
            "status": self.status.value,
            "progress": self.progress,
            "title_candidates": self.title_candidates,
            "selected_title_index": self.selected_title_index,
            "subtitles_on": self.subtitles_on,
            "variants": [variant.to_dict() for variant in self.variants],
            "base_video_path": self.base_video_path,
            "base_path": base_path,
            "assets_path": self.assets_path,
            "active_variant_path": self.active_variant_path,
            "render_request_id": self.render_request_id,
            "edl_path": self.edl_path,
            "doc_path": self.doc_path,
            "segments_path": self.segments_path,
            "revision": self.revision,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Storyline:
        return cls(
            id=str(data.get("id", "")),
            index=int(data.get("index", 0)),
            angle_name=str(data.get("angle_name", "")),
            status=_status(data.get("status")),
            progress=float(data.get("progress", 0.0)),
            title_candidates=[str(item) for item in data.get("title_candidates", [])],
            selected_title_index=int(data.get("selected_title_index", 0)),
            subtitles_on=bool(data.get("subtitles_on", True)),
            variants=[
                Variant.from_dict(item)
                for item in data.get("variants", [])
                if isinstance(item, dict)
            ],
            base_video_path=data.get("base_video_path") or data.get("base_path"),
            base_path=data.get("base_path"),
            assets_path=data.get("assets_path"),
            active_variant_path=data.get("active_variant_path"),
            render_request_id=int(data.get("render_request_id", 0)),
            edl_path=data.get("edl_path"),
            doc_path=data.get("doc_path"),
            segments_path=data.get("segments_path"),
            revision=int(data.get("revision", 0)),
            error=data.get("error"),
        )


@dataclass
class ExportState:
    status: Status = Status.IDLE
    selected_storyline_id: str | None = None
    selected_variant_id: str | None = None
    output_path: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "selected_storyline_id": self.selected_storyline_id,
            "selected_variant_id": self.selected_variant_id,
            "output_path": self.output_path,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ExportState:
        if not isinstance(data, dict):
            return cls()
        return cls(
            status=_status(data.get("status")),
            selected_storyline_id=data.get("selected_storyline_id"),
            selected_variant_id=data.get("selected_variant_id"),
            output_path=data.get("output_path"),
            error=data.get("error"),
        )


@dataclass
class Artifact:
    id: str
    kind: str
    path: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "path": self.path}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Artifact:
        return cls(
            id=str(data.get("id", "")),
            kind=str(data.get("kind", "")),
            path=str(data.get("path", "")),
        )


@dataclass
class Job:
    id: str
    status: Status = Status.IDLE
    created_at: str = ""
    updated_at: str = ""
    input_path: str | None = None
    output_dir: str | None = None
    project_path: str | None = None
    project_name: str | None = None
    work_dir: str | None = None
    provider: str | None = None
    model: str | None = None
    phase: str | None = None
    progress: float = 0.0
    message: str | None = None
    revision: int = 0
    request_id: int = 0
    seq: int = 0
    selected_storyline_id: str | None = None
    storylines: list[Storyline] = field(default_factory=list)
    export: ExportState = field(default_factory=ExportState)
    artifacts: dict[str, Artifact] = field(default_factory=dict)
    error: str | None = None
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "id": self.id,
            "status": self.status.value,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "input_path": self.input_path,
            "output_dir": self.output_dir,
            "project_path": self.project_path,
            "project_name": self.project_name,
            "work_dir": self.work_dir,
            "provider": self.provider,
            "model": self.model,
            "phase": self.phase,
            "progress": self.progress,
            "message": self.message,
            "revision": self.revision,
            "request_id": self.request_id,
            "seq": self.seq,
            "selected_storyline_id": self.selected_storyline_id,
            "storylines": [storyline.to_dict() for storyline in self.storylines],
            "export": self.export.to_dict(),
            "artifacts": {
                artifact_id: artifact.to_dict()
                for artifact_id, artifact in self.artifacts.items()
            },
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        artifacts_data = data.get("artifacts", {})
        artifacts = {
            str(key): Artifact.from_dict(value)
            for key, value in artifacts_data.items()
            if isinstance(value, dict)
        } if isinstance(artifacts_data, dict) else {}
        return cls(
            id=str(data.get("id", "")),
            status=_status(data.get("status")),
            created_at=str(data.get("created_at", "")),
            updated_at=str(data.get("updated_at", "")),
            input_path=data.get("input_path"),
            output_dir=data.get("output_dir"),
            project_path=data.get("project_path"),
            project_name=data.get("project_name"),
            work_dir=data.get("work_dir"),
            provider=data.get("provider"),
            model=data.get("model"),
            phase=data.get("phase"),
            progress=float(data.get("progress", 0.0)),
            message=data.get("message"),
            revision=int(data.get("revision", 0)),
            request_id=int(data.get("request_id", 0)),
            seq=int(data.get("seq", data.get("request_id", 0))),
            selected_storyline_id=data.get("selected_storyline_id"),
            storylines=[
                Storyline.from_dict(item)
                for item in data.get("storylines", [])
                if isinstance(item, dict)
            ],
            export=ExportState.from_dict(data.get("export")),
            artifacts=artifacts,
            error=data.get("error"),
            schema_version=int(data.get("schema_version", SCHEMA_VERSION)),
        )
