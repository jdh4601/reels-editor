import pytest
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


def test_cut_filter_trims_each_segment_separately() -> None:
    # 비연속 세그먼트는 개별 trim + concat — 중간 구간(1s~5s)이 포함되면 안 된다
    segs = [
        {"source_start_us": 0, "source_end_us": 1_000_000},
        {"source_start_us": 5_000_000, "source_end_us": 6_000_000},
    ]
    f = export.cut_filter(segs, speed=1.2)
    assert "trim=0.0:1.0" in f
    assert "trim=5.0:6.0" in f
    assert "concat=n=2" in f


def test_export_cuts_rejects_unsupported_speed(segments: dict, edl_doc: dict,
                                               tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        export.export_cuts(Path("/tmp/x.mp4"), edl_doc, segments, tmp_path, speed=2.5)
