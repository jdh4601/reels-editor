from pathlib import Path

import pytest

from reels_editor import capcut


def test_build_segments_maps_text_to_source_coords(raw_draft: dict) -> None:
    out = capcut.build_segments(raw_draft)
    assert out["video_path"] == "/tmp/footage.mp4"
    segs = out["segments"]
    assert [s["id"] for s in segs] == ["t0", "t1", "t2"]
    assert segs[1]["text"] == "그런데 도저히 꿈을 포기 못 하겠더라고요"
    assert segs[1]["source_start_us"] == 5_000_000
    assert segs[1]["speed"] == 1.0


def test_build_segments_applies_speed(raw_draft: dict) -> None:
    raw_draft["tracks"][0]["segments"][0]["speed"] = 1.2
    raw_draft["tracks"][0]["segments"][0]["source_timerange"]["duration"] = 36_000_000
    out = capcut.build_segments(raw_draft)
    assert out["segments"][0]["speed"] == 1.2
    assert out["segments"][0]["source_end_us"] == pytest.approx(6_000_000, abs=2)


def test_find_project_accepts_direct_path(tmp_path: Path) -> None:
    (tmp_path / "draft_info.json").write_text("{}")
    assert capcut.find_project(str(tmp_path)) == tmp_path


def test_find_project_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        capcut.find_project("존재하지않는프로젝트이름")
