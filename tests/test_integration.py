"""합성 영상으로 전체 렌더 검증. ffmpeg 필요 — LLM/CapCut은 fixture로 대체."""
import json
import subprocess
from pathlib import Path

import pytest

from reels_editor import edl, export, render
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


@pytest.fixture(scope="module")
def synth_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30초 640x480 테스트 영상(영상+사인파 오디오)."""
    p = tmp_path_factory.mktemp("video") / "synth.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=30:size=640x480:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p)],
        check=True)
    return p


def _probe(path: Path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries,
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()


def test_render_reel_full(synth_video: Path, segments: dict, edl_doc: dict,
                          tmp_path: Path) -> None:
    style = load_style(STYLE)
    out = render.render_reel(synth_video, segments, edl_doc, style,
                             tmp_path / "reel.mp4", work_dir=tmp_path / "work")
    assert out.is_file()
    w, h = _probe(out, "stream=width,height").splitlines()[0].split(",")
    assert (int(w), int(h)) == style.canvas
    # 소스 18초(t1 10s + t2 8s) / 1.2배속 = 15초
    dur = float(_probe(out, "format=duration"))
    assert dur == pytest.approx(15.0, abs=1.0)
    # 오디오 트랙 존재
    assert "aac" in _probe(out, "stream=codec_name")


def test_export_cuts_per_beat(synth_video: Path, segments: dict, edl_doc: dict,
                              tmp_path: Path) -> None:
    paths = export.export_cuts(synth_video, edl_doc, segments,
                               tmp_path / "cuts", speed=1.2)
    assert [p.name for p in paths] == ["001-훅.mp4", "002-라스트 답.mp4"]
    assert all(p.stat().st_size > 0 for p in paths)


def test_srt_matches_render_groups(segments: dict, edl_doc: dict,
                                   tmp_path: Path) -> None:
    ordered = edl.ordered_segments(edl_doc, segments)
    groups = render.group_captions(render.timeline_items(ordered, 1.2))
    p = export.write_srt(groups, tmp_path / "reel.srt")
    assert "-->" in p.read_text(encoding="utf-8")
