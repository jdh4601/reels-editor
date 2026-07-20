from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from reels_editor.desktop.dialogs import FakeDialogProvider
from reels_editor.desktop.server import create_app
from reels_editor.jobs import Artifact, Job, JobStore, Status, Storyline, Variant


class FakeService:
    def __init__(self, store: JobStore, job: Job | None = None) -> None:
        self.store = store
        self.job = job
        self.selection_args: dict | None = None
        self.export_args: dict | None = None

    def snapshot(self, job_id: str | None = None) -> Job | None:
        return self.job

    def start_job(self, project_path: str) -> Job:
        assert self.job is not None
        return self.job

    def select_variant(self, job_id: str, storyline_id: str, **kwargs) -> Job:
        self.selection_args = {"job_id": job_id, "storyline_id": storyline_id, **kwargs}
        assert self.job is not None
        return self.job

    def retry_storyline(self, job_id: str, storyline_id: str) -> Job:
        assert self.job is not None
        return self.job

    def export_selected(
        self,
        job_id: str,
        destination: Path,
        *,
        storyline_id: str | None = None,
        subtitles_on: bool | None = None,
    ) -> Job:
        self.export_args = {"job_id": job_id, "storyline_id": storyline_id, "subtitles_on": subtitles_on}
        assert self.job is not None
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"exported")
        self.job.export.output_path = str(destination)
        self.job.export.status = Status.READY
        return self.job

    def cancel(self, job_id: str) -> Job:
        assert self.job is not None
        self.job.status = Status.CANCELLED
        return self.job

    def wait_for_update(self, after_seq: int, timeout: float | None = None) -> Job | None:
        return None


def test_api_requires_token_for_tools_snapshot_and_media(tmp_path: Path) -> None:
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    (media_dir / "sample.mp4").write_bytes(b"sample")
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=media_dir,
        dialog_provider=None,
        job_service=FakeService(JobStore(tmp_path / "jobs")),
        session_token="secret",
    )
    client = TestClient(app)

    assert client.get("/api/health").status_code == 200
    assert client.get("/api/tools").status_code == 401
    assert client.get("/api/snapshot").status_code == 401
    assert client.get("/api/media").status_code == 401
    assert client.get("/media/sample.mp4").status_code == 401

    assert client.get("/api/snapshot?token=secret").status_code == 200
    media = client.get("/api/media?token=secret").json()
    assert media["items"][0]["url"] == "/media/sample.mp4"


def test_snapshot_returns_placeholders_when_no_job(tmp_path: Path) -> None:
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=FakeService(JobStore(tmp_path / "jobs")),
        session_token="secret",
    )
    payload = TestClient(app).get("/api/snapshot?token=secret").json()

    assert payload["job_id"] == ""
    assert len(payload["storylines"]) == 3
    assert [item["status"] for item in payload["storylines"]] == ["queued", "queued", "queued"]


def test_registered_artifact_range_and_snapshot_url_stays_tokenless(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_path="/capcut/김현지대표인터뷰", project_name="김현지대표인터뷰")
    artifact_path = store.job_dir(job.id) / "s1" / "clip.mp4"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"0123456789")
    artifact = store.register_artifact(job.id, artifact_path, kind="video/mp4")
    job = store.load(job.id)
    job.status = Status.READY
    job.project_name = "김현지대표인터뷰"
    job.storylines = [
        Storyline(
            id="s1",
            index=0,
            angle_name="정면승부형",
            status=Status.READY,
            progress=1.0,
            title_candidates=["A", "B", "C"],
            active_variant_path=str(artifact_path),
            variants=[
                Variant(
                    id=artifact.id,
                    title_index=0,
                    title_text="A",
                    subtitles_enabled=True,
                    status=Status.READY,
                    path=str(artifact_path),
                )
            ],
        )
    ]
    job.selected_storyline_id = "s1"
    job = store.save(job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=FakeService(store, job),
        session_token="secret",
    )
    client = TestClient(app)

    snapshot = client.get("/api/snapshot?token=secret").json()
    video_url = snapshot["storylines"][0]["video_url"]
    assert video_url == f"/media/{job.id}/{artifact.id}"
    assert str(artifact_path) not in video_url

    response = client.get(f"{video_url}?token=secret", headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.content == b"2345"

    invalid = client.get(f"{video_url}?token=secret", headers={"Range": "bytes=20-30"})
    assert invalid.status_code == 416


def test_selection_request_passes_selected_for_export(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_path="/project")
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).patch(
        f"/api/jobs/{job.id}/storylines/s2/selection?token=secret",
        json={"title_index": 2, "subtitles_on": False, "selected_for_export": True},
    )

    assert response.status_code == 200
    assert service.selection_args == {
        "job_id": job.id,
        "storyline_id": "s2",
        "title_index": 2,
        "subtitles_on": False,
        "selected_for_export": True,
    }


def test_export_request_passes_requested_subtitle_state(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_path="/project")
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        dialog_provider=FakeDialogProvider(save_file=str(tmp_path / "out.mp4")),
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        f"/api/jobs/{job.id}/export?token=secret",
        json={"storyline_id": "s2", "subtitles_on": False},
    )

    assert response.status_code == 200
    assert service.export_args == {"job_id": job.id, "storyline_id": "s2", "subtitles_on": False}


def test_events_websocket_requires_token_and_honors_after_seq(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_path="/project")
    job.seq = 7
    job = store.save(job, bump_revision=False)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=FakeService(store, job),
        session_token="secret",
    )
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/events?after=6"):
            pass

    with client.websocket_connect("/api/events?after=6&token=secret") as websocket:
        payload = websocket.receive_json()

    assert payload["job_id"] == job.id
    assert payload["seq"] == 7


def _static(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir(exist_ok=True)
    (static / "index.html").write_text("<div id='root'></div>", encoding="utf-8")
    return static
