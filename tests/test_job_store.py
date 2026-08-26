from __future__ import annotations

import json
from pathlib import Path

import pytest

from reels_editor.jobs import (
    JobStore,
    Status,
    Storyline,
    Variant,
)


def test_job_store_persists_and_lists_recent_jobs(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job(
        input_path="/clips/interview.mp4",
        source_url="https://youtu.be/abc123",
        source_thumbnail_url="https://i.ytimg.com/vi/abc123/hqdefault.jpg",
        episode_number=37,
    )
    job.status = Status.GENERATING
    job.storylines.append(
        Storyline(
            id="s1",
            index=0,
            angle_name="정면승부형",
            status=Status.READY,
            title="첫 번째 제목",
            instagram_caption="Ep 1. 첫 번째 캡션",
            variants=[
                Variant(
                    id="s1-t1-on",
                    title_text="첫 번째 제목",
                    subtitles_enabled=True,
                )
            ],
        )
    )

    first_revision = job.revision
    saved = store.save(job)
    loaded = store.load(job.id)

    assert saved.revision > first_revision
    assert saved.request_id > 0
    assert loaded.id == job.id
    assert loaded.storylines[0].title == "첫 번째 제목"
    assert loaded.storylines[0].variants[0].subtitles_enabled is True
    assert loaded.storylines[0].instagram_caption == "Ep 1. 첫 번째 캡션"
    assert loaded.source_url == "https://youtu.be/abc123"
    assert loaded.source_thumbnail_url.endswith("/abc123/hqdefault.jpg")
    assert loaded.episode_number == 37
    assert [item.id for item in store.list_recent(limit=5)] == [job.id]


def test_current_job_can_be_cleared_without_deleting_history(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    first = store.create_job(source_url="https://youtu.be/first")

    assert store.current_job().id == first.id

    store.clear_current()

    assert store.current_job() is None
    assert store.load(first.id).source_url == "https://youtu.be/first"
    assert JobStore(root=tmp_path).current_job() is None

    second = store.create_job(source_url="https://youtu.be/second")
    assert store.current_job().id == second.id


def test_current_job_falls_back_to_recent_for_legacy_store(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job(source_url="https://youtu.be/legacy")
    store.current_path.unlink()

    assert JobStore(root=tmp_path).current_job().id == job.id


def test_job_decode_is_backward_tolerant(tmp_path: Path) -> None:
    job_dir = tmp_path / "legacy"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "id": "legacy",
                "status": "ready",
                "created_at": "2026-07-20T01:00:00+00:00",
                "unknown_top_level": "ignored",
                "storylines": [{"id": "s1", "index": 0, "extra": "ignored"}],
            }
        ),
        encoding="utf-8",
    )

    loaded = JobStore(root=tmp_path).load("legacy")

    assert loaded.id == "legacy"
    assert loaded.status is Status.READY
    assert loaded.storylines[0].status is Status.IDLE
    assert loaded.export.selected_variant_id is None
    assert loaded.episode_number == 1
    assert loaded.source_thumbnail_url is None


def test_set_current_reopens_a_saved_job(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    first = store.create_job(source_url="https://youtu.be/first")
    store.create_job(source_url="https://youtu.be/second")

    reopened = store.set_current(first.id)

    assert reopened.id == first.id
    assert JobStore(root=tmp_path).current_job().id == first.id


def test_job_snapshot_keeps_dashboard_snake_case_fields(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job(
        project_name="김현지대표인터뷰",
        work_dir="/work/job",
        provider="codex",
        model="gpt-5.5",
    )
    job.phase = "rendering"
    job.progress = 0.5
    job.message = "대표 영상 렌더링 중"
    job.storylines.append(
        Storyline(
            id="s1",
            index=0,
            angle_name="반전형",
            status=Status.RENDERING_OVERLAY,
            progress=0.8,
            title="B",
            subtitles_on=False,
            base_path="/work/job/s1/base.mp4",
            assets_path="/work/job/s1/assets.json",
            active_variant_path="/work/job/s1/t2-off.mp4",
            render_request_id=7,
            variants=[
                Variant(
                    id="v1",
                    title_text="B",
                    subtitles_enabled=False,
                    subtitles_on=False,
                    style_hash="style",
                    path="/work/job/s1/t2-off.mp4",
                )
            ],
        )
    )

    data = store.save(job).to_dict()

    assert data["project_name"] == "김현지대표인터뷰"
    assert data["provider"] == "codex"
    assert data["seq"] == 2
    assert data["storylines"][0]["title"] == "B"
    assert data["storylines"][0]["subtitles_on"] is False
    assert data["storylines"][0]["base_path"] == "/work/job/s1/base.mp4"
    assert data["storylines"][0]["variants"][0]["subtitles_on"] is False
    assert data["storylines"][0]["variants"][0]["style_hash"] == "style"


def test_recover_interrupted_jobs_marks_active_work_failed(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job()
    job.status = Status.RENDERING_BASE
    job.storylines.append(Storyline(id="s1", index=0, status=Status.RENDERING_OVERLAY))
    done = store.create_job()
    done.status = Status.READY
    store.save(job)
    store.save(done)

    recovered = store.recover_interrupted()

    assert recovered == [job.id]
    assert store.load(job.id).status is Status.FAILED
    assert store.load(job.id).storylines[0].status is Status.FAILED
    assert store.load(done.id).status is Status.READY


def test_select_export_enforces_exactly_one_variant(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job()
    job.storylines.append(
        Storyline(
            id="s1",
            index=0,
            variants=[
                Variant(id="v1", title_text="A", subtitles_enabled=True),
                Variant(id="v2", title_text="B", subtitles_enabled=False),
            ],
        )
    )
    store.save(job)

    selected = store.select_export(job.id, storyline_id="s1", variant_id="v2")

    assert selected.export.selected_storyline_id == "s1"
    assert selected.export.selected_variant_id == "v2"
    assert [variant.selected for variant in selected.storylines[0].variants] == [False, True]

    with pytest.raises(ValueError, match="variant"):
        store.select_export(job.id, storyline_id="s1", variant_id="missing")


def test_registered_artifacts_cannot_escape_job_directory(tmp_path: Path) -> None:
    store = JobStore(root=tmp_path)
    job = store.create_job()
    inside = store.job_dir(job.id) / "artifacts" / "v1.mp4"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"mp4")

    artifact = store.register_artifact(job.id, inside, kind="video/mp4")

    assert artifact.path == str(inside.resolve())
    assert store.resolve_artifact(job.id, artifact.id) == inside.resolve()

    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    with pytest.raises(ValueError, match="outside"):
        store.register_artifact(job.id, outside, kind="video/mp4")

    link = store.job_dir(job.id) / "artifacts" / "linked.mp4"
    link.symlink_to(outside)
    with pytest.raises(ValueError, match="outside"):
        store.register_artifact(job.id, link, kind="video/mp4")


def test_default_root_uses_macos_application_support(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert JobStore.default_root() == tmp_path / "Library" / "Application Support" / "reels-editor" / "jobs"
