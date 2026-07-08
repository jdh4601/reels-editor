from pathlib import Path

from reels_editor import export


def test_srt_timestamp_format() -> None:
    assert export.srt_timestamp(0.0) == "00:00:00,000"
    assert export.srt_timestamp(1.466) == "00:00:01,466"
    assert export.srt_timestamp(3661.5) == "01:01:01,500"


def test_write_srt(tmp_path: Path) -> None:
    groups = [[0.0, 1.5, "결국은 제가"], [1.5, 3.0, "시장을 설득하는"]]
    p = export.write_srt(groups, tmp_path / "reel.srt")
    body = p.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\n결국은 제가" in body
    assert "2\n00:00:01,500 --> 00:00:03,000\n시장을 설득하는" in body


def test_write_outputs(tmp_path: Path, edl_doc: dict, segments: dict) -> None:
    export.write_outputs(tmp_path, edl_doc, segments)
    assert (tmp_path / "edl.json").is_file()
    assert (tmp_path / "segments.json").is_file()
