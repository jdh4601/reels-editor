from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

from reels_editor.desktop.dialogs import FakeDialogProvider
from reels_editor.desktop.server import create_app
from reels_editor.jobs import Job, JobStore, Status, Storyline, Variant
from reels_editor.config import AppConfig, load_config


class FakeService:
    def __init__(self, store: JobStore, job: Job | None = None) -> None:
        self.store = store
        self.job = job
        self.youtube_start_args: dict | None = None
        self.generate_args: dict | None = None
        self.caption_args: dict | None = None
        self.selection_args: dict | None = None
        self.export_args: dict | None = None
        self.batch_export_args: dict | None = None
        self.clear_current_called = False
        self.title_args: dict | None = None
        self.config = AppConfig(provider="codex-cli")
        self.archive_override: list[Job] | None = None

    def snapshot(self, job_id: str | None = None) -> Job | None:
        return self.job

    def clear_current(self) -> None:
        self.clear_current_called = True
        self.job = None

    def start_youtube_job(
        self,
        youtube_url: str,
        *,
        content_types: list[str] | None = None,
        provider: str | None = None,
        episode_number: int = 1,
    ) -> Job:
        self.youtube_start_args = {
            "youtube_url": youtube_url,
            "content_types": content_types,
            "provider": provider,
            "episode_number": episode_number,
        }
        assert self.job is not None
        self.job.source_url = youtube_url
        self.job.episode_number = episode_number
        return self.job

    def archive_jobs(self) -> list[Job]:
        if self.archive_override is not None:
            return self.archive_override
        return [self.job] if self.job is not None else []

    def open_job(self, job_id: str) -> Job:
        assert self.job is not None and self.job.id == job_id
        return self.job

    def start_selected_generation(self, job_id: str, candidate_ids: list[str]) -> Job:
        self.generate_args = {"job_id": job_id, "candidate_ids": candidate_ids}
        assert self.job is not None
        return self.job

    def select_variant(self, job_id: str, storyline_id: str, **kwargs) -> Job:
        self.selection_args = {"job_id": job_id, "storyline_id": storyline_id, **kwargs}
        assert self.job is not None
        return self.job

    def retry_storyline(self, job_id: str, storyline_id: str) -> Job:
        assert self.job is not None
        return self.job

    def generate_instagram_caption(self, job_id: str, storyline_id: str) -> Job:
        self.caption_args = {"job_id": job_id, "storyline_id": storyline_id}
        assert self.job is not None
        story = next(item for item in self.job.storylines if item.id == storyline_id)
        story.instagram_caption = "Ep 1. 첫 고객을 만든 방법\n\n본문\n\n질문?\n\n다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀"
        return self.job

    def update_storyline_title(
        self,
        job_id: str,
        storyline_id: str,
        title: str | None = None,
        *,
        title_upper: str | None = None,
        title_lower: str | None = None,
    ) -> Job:
        self.title_args = {"job_id": job_id, "storyline_id": storyline_id, "title": title}
        if title_upper is not None or title_lower is not None:
            self.title_args.update({"title_upper": title_upper, "title_lower": title_lower})
        assert self.job is not None
        story = next(item for item in self.job.storylines if item.id == storyline_id)
        story.title = title or " ".join(part for part in (title_upper, title_lower) if part)
        story.title_upper = title_upper or ""
        story.title_lower = title_lower or story.title
        return self.job

    def suggested_export_filename(
        self,
        job_id: str,
        storyline_id: str | None = None,
    ) -> str:
        assert self.job is not None
        index = int(storyline_id.removeprefix("s")) if storyline_id else 1
        return f"{self.job.project_name or '릴스'} - {index}.mp4"

    def export_selected(
        self,
        job_id: str,
        destination: Path | None = None,
        *,
        storyline_id: str | None = None,
        subtitles_on: bool | None = None,
    ) -> Job:
        self.export_args = {"job_id": job_id, "storyline_id": storyline_id, "subtitles_on": subtitles_on}
        assert self.job is not None
        destination = destination or self.store.root.parent / "archive" / "reel.mp4"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"exported")
        self.job.export.output_path = str(destination)
        self.job.export.status = Status.READY
        return self.job

    def export_many(
        self,
        job_id: str,
        destination_dir: Path | None = None,
        *,
        storyline_ids: list[str],
        subtitles_on: bool | None = None,
    ) -> Job:
        destination_dir = destination_dir or self.store.root.parent / "archive"
        self.batch_export_args = {
            "job_id": job_id,
            "destination_dir": destination_dir,
            "storyline_ids": storyline_ids,
            "subtitles_on": subtitles_on,
        }
        assert self.job is not None
        destination_dir.mkdir(parents=True, exist_ok=True)
        self.job.export.output_path = str(destination_dir)
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


def test_snapshot_returns_no_reels_when_no_job(tmp_path: Path) -> None:
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=FakeService(JobStore(tmp_path / "jobs")),
        session_token="secret",
    )
    payload = TestClient(app).get("/api/snapshot?token=secret").json()

    assert payload["job_id"] == ""
    assert payload["storylines"] == []
    assert payload["n_storylines"] == 0
    assert payload["duration_s"] == 35
    assert payload["episode_number"] == 1
    assert payload["source_thumbnail_url"] is None


def test_clear_snapshot_releases_current_job_without_deleting_history(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(source_url="https://youtu.be/interview", project_name="인터뷰")
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).delete("/api/snapshot?token=secret")

    assert response.status_code == 200
    assert response.json()["source_url"] is None
    assert response.json()["project_name"] == "Reels Editor"
    assert service.clear_current_called is True
    assert store.load(job.id).source_url == "https://youtu.be/interview"


def test_create_job_requires_youtube_url(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        "/api/jobs?token=secret",
        json={},
    )

    assert response.status_code == 422
    assert service.youtube_start_args is None


def test_create_youtube_job_passes_url_and_selected_content_types_to_service(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        "/api/jobs?token=secret",
        json={
            "youtube_url": "https://youtu.be/abc123",
            "episode_number": 37,
            "content_types": ["strategy", "failure"],
            "provider": "codex-cli",
        },
    )

    assert response.status_code == 200
    assert response.json()["source_url"] == "https://youtu.be/abc123"
    assert service.youtube_start_args == {
        "youtube_url": "https://youtu.be/abc123",
        "content_types": ["strategy", "failure"],
        "provider": "codex-cli",
        "episode_number": 37,
    }


def test_create_job_rejects_empty_content_types(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        "/api/jobs?token=secret",
        json={"youtube_url": "https://youtu.be/abc123", "content_types": []},
    )

    assert response.status_code == 422
    assert service.youtube_start_args is None


@pytest.mark.parametrize(
    ("field", "value"),
    [("content_types", ["unsupported"]), ("provider", "unsupported")],
)
def test_create_job_rejects_invalid_generation_settings(tmp_path: Path, field: str, value: object) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        "/api/jobs?token=secret",
        json={"youtube_url": "https://youtu.be/abc123", field: value},
    )

    assert response.status_code == 422
    assert service.youtube_start_args is None


def test_generate_selected_candidates_passes_only_chosen_ids(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        f"/api/jobs/{job.id}/generate?token=secret",
        json={"candidate_ids": ["c2", "c7"]},
    )

    assert response.status_code == 200
    assert service.generate_args == {"job_id": job.id, "candidate_ids": ["c2", "c7"]}


def test_registered_artifact_range_and_snapshot_url_stays_tokenless(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_name="김현지대표인터뷰")
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
            title="A",
            active_variant_path=str(artifact_path),
            variants=[
                Variant(
                    id=artifact.id,
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


def test_archive_returns_completed_reel_identity_and_open_reuses_snapshot(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(
        project_name="창업가 인터뷰",
        source_url="https://youtu.be/archive123",
        episode_number=37,
    )
    artifact_path = store.job_dir(job.id) / "s1" / "ready.mp4"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"ready")
    artifact = store.register_artifact(job.id, artifact_path, kind="video/mp4")
    job = store.load(job.id)
    job.status = Status.READY
    job.storylines = [Storyline(
        id="s1",
        index=0,
        status=Status.READY,
        title="끝까지 버틴 이유",
        active_variant_path=str(artifact_path),
        archive_path=str(tmp_path / "Movies" / "Reels Editor" / "saved.mp4"),
        variants=[Variant(
            id=artifact.id,
            title_text="끝까지 버틴 이유",
            subtitles_enabled=True,
            status=Status.READY,
            path=str(artifact_path),
        )],
    )]
    job = store.save(job)
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )
    client = TestClient(app)

    archive = client.get("/api/archive?token=secret")
    opened = client.post(f"/api/jobs/{job.id}/open?token=secret")

    assert archive.status_code == 200
    item = archive.json()["items"][0]
    assert item["job_id"] == job.id
    assert item["storyline_id"] == "s1"
    assert item["episode_number"] == 37
    assert item["source_thumbnail_url"].endswith("/archive123/hqdefault.jpg")
    assert item["reel_title"] == "끝까지 버틴 이유"
    assert item["video_url"] == f"/media/{job.id}/{artifact.id}"
    assert opened.json()["job_id"] == job.id
    assert opened.json()["episode_number"] == 37


def test_archive_api_uses_existing_ready_variant_when_recorded_active_is_missing(
    tmp_path: Path,
) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job(project_name="창업가 인터뷰")
    good_path = store.job_dir(job.id) / "s1" / "ready.mp4"
    stale_path = good_path.with_name("missing.mp4")
    good_path.parent.mkdir(parents=True)
    good_path.write_bytes(b"ready")
    good_artifact = store.register_artifact(job.id, good_path, kind="video/mp4")
    stale_path.write_bytes(b"stale")
    stale_artifact = store.register_artifact(job.id, stale_path, kind="video/mp4")
    stale_path.unlink()
    job = store.load(job.id)
    job.status = Status.READY
    job.storylines = [Storyline(
        id="s1",
        index=0,
        status=Status.READY,
        title="삭제된 제목입니다",
        active_variant_path=str(stale_path),
        variants=[
            Variant(
                id=good_artifact.id,
                title_text="재생 가능한 제목",
                subtitles_enabled=True,
                status=Status.READY,
                path=str(good_path),
            ),
            Variant(
                id=stale_artifact.id,
                title_text="삭제된 제목입니다",
                subtitles_enabled=True,
                status=Status.READY,
                path=str(stale_path),
            ),
        ],
    )]
    job = store.save(job)
    service = FakeService(store, job)
    service.archive_override = [job]
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).get("/api/archive?token=secret")

    assert response.status_code == 200
    assert response.json()["items"][0]["video_url"] == (
        f"/media/{job.id}/{good_artifact.id}"
    )


def test_title_patch_passes_validated_payload_to_service(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    job.storylines = [Storyline(id="s1", index=0, status=Status.READY, title="이전 제목입니다")]
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).patch(
        f"/api/jobs/{job.id}/storylines/s1/title?token=secret",
        json={"title": "새로운 제목이다"},
    )

    assert response.status_code == 200
    assert service.title_args == {
        "job_id": job.id,
        "storyline_id": "s1",
        "title": "새로운 제목이다",
    }
    assert response.json()["storylines"][0]["title"] == "새로운 제목이다"


def test_title_patch_passes_explicit_white_and_orange_lines(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    job.storylines = [Storyline(id="s1", index=0, status=Status.READY, title="이전 제목입니다")]
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).patch(
        f"/api/jobs/{job.id}/storylines/s1/title?token=secret",
        json={"title_upper": "첫 번째 문구", "title_lower": "두 번째 문구"},
    )

    assert response.status_code == 200
    assert service.title_args == {
        "job_id": job.id,
        "storyline_id": "s1",
        "title": None,
        "title_upper": "첫 번째 문구",
        "title_lower": "두 번째 문구",
    }
    assert response.json()["storylines"][0]["title_upper"] == "첫 번째 문구"
    assert response.json()["storylines"][0]["title_lower"] == "두 번째 문구"


def test_selection_request_passes_selected_for_export(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).patch(
        f"/api/jobs/{job.id}/storylines/s2/selection?token=secret",
        json={"subtitles_on": False, "selected_for_export": True},
    )

    assert response.status_code == 200
    assert service.selection_args == {
        "job_id": job.id,
        "storyline_id": "s2",
        "subtitles_on": False,
        "selected_for_export": True,
    }


def test_caption_request_generates_and_returns_reel_caption(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    job.storylines = [Storyline(id="s1", index=0, status=Status.READY)]
    service = FakeService(store, job)
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        f"/api/jobs/{job.id}/storylines/s1/caption?token=secret",
    )

    assert response.status_code == 200
    assert service.caption_args == {"job_id": job.id, "storyline_id": "s1"}
    assert response.json()["storylines"][0]["instagram_caption"].startswith("Ep 1. ")


def test_export_request_passes_requested_subtitle_state(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    dialogs = FakeDialogProvider(save_file=str(tmp_path / "out.mp4"))
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        dialog_provider=dialogs,
        job_service=service,
        session_token="secret",
    )

    response = TestClient(app).post(
        f"/api/jobs/{job.id}/export?token=secret",
        json={"storyline_id": "s2", "subtitles_on": False},
    )

    assert response.status_code == 200
    assert service.export_args == {"job_id": job.id, "storyline_id": "s2", "subtitles_on": False}
    assert Path(service.job.export.output_path or "").name == "reel.mp4"
    assert dialogs.opened_directories == [tmp_path / "archive"]


def test_batch_export_request_passes_multiple_storylines_and_folder(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
    service = FakeService(store, job)
    dialogs = FakeDialogProvider(folder=str(tmp_path / "ignored-destination"))
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        dialog_provider=dialogs,
        job_service=service,
        session_token="secret",
    )

    storyline_ids = [f"s{index}" for index in range(1, 11)]
    response = TestClient(app).post(
        f"/api/jobs/{job.id}/export-batch?token=secret",
        json={"storyline_ids": storyline_ids, "subtitles_on": False},
    )

    assert response.status_code == 200
    assert service.batch_export_args == {
        "job_id": job.id,
        "destination_dir": tmp_path / "archive",
        "storyline_ids": storyline_ids,
        "subtitles_on": False,
    }
    assert dialogs.opened_directories == [tmp_path / "archive"]


def test_playback_speed_settings_persist_and_update_service(tmp_path: Path) -> None:
    service = FakeService(JobStore(tmp_path / "jobs"))
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=service,
        session_token="secret",
        config_path=tmp_path / "config.yaml",
    )
    client = TestClient(app)

    initial = client.get("/api/settings/playback-speed?token=secret")
    saved = client.put(
        "/api/settings/playback-speed?token=secret",
        json={"speed": 1.35},
    )

    assert initial.json() == {"speed": 1.2}
    assert saved.status_code == 200
    assert saved.json() == {"speed": 1.35}
    assert service.config.style["speed"] == 1.35
    assert load_config(tmp_path / "config.yaml").style["speed"] == 1.35


@pytest.mark.parametrize("speed", [0.95, 1.55])
def test_playback_speed_settings_reject_out_of_range(tmp_path: Path, speed: float) -> None:
    app = create_app(
        static_dir=_static(tmp_path),
        media_dir=tmp_path,
        job_service=FakeService(JobStore(tmp_path / "jobs")),
        session_token="secret",
        config_path=tmp_path / "config.yaml",
    )

    response = TestClient(app).put(
        "/api/settings/playback-speed?token=secret",
        json={"speed": speed},
    )

    assert response.status_code == 422


def test_events_websocket_requires_token_and_honors_after_seq(tmp_path: Path) -> None:
    store = JobStore(tmp_path / "jobs")
    job = store.create_job()
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
