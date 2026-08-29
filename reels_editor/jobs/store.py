from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import ACTIVE_STATUSES, Artifact, Job, Status


class JobStore:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or self.default_root()).expanduser()
        self.current_path = self.root / "current.json"

    @staticmethod
    def default_root() -> Path:
        return Path.home() / "Library" / "Application Support" / "reels-editor" / "jobs"

    def job_dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create_job(
        self,
        *,
        input_path: str | None = None,
        output_dir: str | None = None,
        project_name: str | None = None,
        source_url: str | None = None,
        source_thumbnail_url: str | None = None,
        episode_number: int = 1,
        work_dir: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        duration_s: int = 30,
        n_storylines: int = 3,
        content_types: list[str] | None = None,
        job_id: str | None = None,
    ) -> Job:
        now = _now()
        job = Job(
            id=job_id or uuid.uuid4().hex,
            created_at=now,
            updated_at=now,
            input_path=input_path,
            output_dir=output_dir,
            project_name=project_name,
            source_url=source_url,
            source_thumbnail_url=source_thumbnail_url,
            episode_number=episode_number if episode_number > 0 else 1,
            work_dir=work_dir,
            provider=provider,
            model=model,
            duration_s=duration_s,
            n_storylines=n_storylines,
            content_types=list(content_types or []),
        )
        saved = self.save(job)
        self._write_current(saved.id)
        return saved

    def current_job(self) -> Job | None:
        if not self.current_path.is_file():
            recent = self.list_recent(limit=1)
            return recent[0] if recent else None
        try:
            payload = json.loads(self.current_path.read_text(encoding="utf-8"))
            job_id = payload.get("job_id") if isinstance(payload, dict) else None
        except (OSError, json.JSONDecodeError):
            recent = self.list_recent(limit=1)
            return recent[0] if recent else None
        if not job_id:
            return None
        try:
            return self.load(str(job_id))
        except FileNotFoundError:
            return None

    def clear_current(self) -> None:
        self._write_current(None)

    def delete_job(self, job_id: str) -> None:
        """Delete one job directory without following paths outside the store."""
        target = Path(os.path.abspath(self.job_dir(job_id)))
        root = Path(os.path.abspath(self.root))
        if target.parent != root or target.name != job_id:
            raise ValueError("job directory must be a direct child of the store")
        if target.is_symlink():
            raise ValueError("job directory is a symlink")
        if not target.is_dir():
            raise FileNotFoundError(f"job not found: {job_id}")

        shutil.rmtree(target)
        try:
            payload = json.loads(self.current_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict) and payload.get("job_id") == job_id:
            self._write_current(None)

    def set_current(self, job_id: str) -> Job:
        job = self.load(job_id)
        self._write_current(job.id)
        return job

    def save(self, job: Job, *, bump_revision: bool = True) -> Job:
        if bump_revision:
            job.revision += 1
            job.request_id += 1
            job.seq += 1
            job.updated_at = _now()
        if not job.created_at:
            job.created_at = job.updated_at or _now()
        self._write_job(job)
        return job

    def load(self, job_id: str) -> Job:
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise FileNotFoundError(f"job not found: {job_id}")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"job data must be an object: {path}")
        return Job.from_dict(data)

    def list_recent(self, *, limit: int = 20) -> list[Job]:
        if not self.root.exists():
            return []
        jobs: list[Job] = []
        for path in self.root.glob("*/job.json"):
            try:
                jobs.append(Job.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return sorted(jobs, key=lambda job: job.updated_at, reverse=True)[:limit]

    def recover_interrupted(self) -> list[str]:
        recovered: list[str] = []
        for job in self.list_recent(limit=1000):
            if job.status not in ACTIVE_STATUSES:
                continue
            job.status = Status.FAILED
            job.error = job.error or "Recovered after interrupted desktop session."
            for storyline in job.storylines:
                if storyline.status in ACTIVE_STATUSES:
                    storyline.status = Status.FAILED
                    storyline.error = storyline.error or job.error
                for variant in storyline.variants:
                    if variant.status in ACTIVE_STATUSES:
                        variant.status = Status.FAILED
                        variant.error = variant.error or job.error
            if job.export.status in ACTIVE_STATUSES:
                job.export.status = Status.FAILED
                job.export.error = job.export.error or job.error
            self.save(job)
            recovered.append(job.id)
        return recovered

    def select_export(self, job_id: str, *, storyline_id: str, variant_id: str) -> Job:
        job = self.load(job_id)
        found = None
        for storyline in job.storylines:
            for variant in storyline.variants:
                selected = storyline.id == storyline_id and variant.id == variant_id
                variant.selected = selected
                if selected:
                    found = variant
        if found is None:
            raise ValueError(f"variant not found for export: {storyline_id}/{variant_id}")
        job.export.selected_storyline_id = storyline_id
        job.export.selected_variant_id = variant_id
        job.selected_storyline_id = storyline_id
        job.export.status = Status.IDLE
        job.export.error = None
        return self.save(job)

    def register_artifact(self, job_id: str, path: Path, *, kind: str) -> Artifact:
        job = self.load(job_id)
        resolved = path.resolve()
        job_root = self.job_dir(job_id).resolve()
        if not _is_relative_to(resolved, job_root) or not resolved.is_file():
            raise ValueError(
                f"artifact path is outside job directory or missing: {resolved}"
            )
        artifact = Artifact(id=uuid.uuid4().hex, kind=kind, path=str(resolved))
        job.artifacts[artifact.id] = artifact
        self.save(job)
        return artifact

    def resolve_artifact(self, job_id: str, artifact_id: str) -> Path:
        job = self.load(job_id)
        try:
            artifact = job.artifacts[artifact_id]
        except KeyError as exc:
            raise FileNotFoundError(f"artifact not found: {artifact_id}") from exc
        resolved = Path(artifact.path).resolve()
        job_root = self.job_dir(job_id).resolve()
        if not _is_relative_to(resolved, job_root) or not resolved.is_file():
            raise ValueError(
                f"artifact path is outside job directory or missing: {resolved}"
            )
        return resolved

    def _write_job(self, job: Job) -> None:
        job_dir = self.job_dir(job.id)
        job_dir.mkdir(parents=True, exist_ok=True)
        final = job_dir / "job.json"
        tmp = job_dir / f".job.{uuid.uuid4().hex}.tmp"
        payload = json.dumps(job.to_dict(), ensure_ascii=False, indent=2, sort_keys=True)
        with tmp.open("w", encoding="utf-8") as file:
            file.write(payload)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp, final)
        _fsync_dir(job_dir)

    def _write_current(self, job_id: str | None) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f".current.{uuid.uuid4().hex}.tmp"
        tmp.write_text(json.dumps({"job_id": job_id}) + "\n", encoding="utf-8")
        os.replace(tmp, self.current_path)
        _fsync_dir(self.root)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
