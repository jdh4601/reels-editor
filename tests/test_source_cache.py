from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from reels_editor.source_cache import prepare_selected_source, selected_ranges
from reels_editor.timebase import US


def sample():
    segments = {"video_path": "/missing/source.mp4", "video_duration_us": 6 * US,
                "segments": [{"id": "a", "text": "First", "source_start_us": 800_000,
                              "source_end_us": 1_200_000},
                             {"id": "b", "text": "Last", "source_start_us": 4_500_000,
                              "source_end_us": 5_000_000}]}
    doc = {"cuts": [{"seg_ids": ["a", "b"]}]}
    return doc, segments


def test_ranges_merge_and_clamp_at_source_end():
    doc, segments = sample()
    assert selected_ranges(doc, segments) == [(550_000, 1_450_000), (4_250_000, 5_250_000)]
    segments["segments"][1].update(source_start_us=1_300_000, source_end_us=6 * US)
    assert selected_ranges(doc, segments) == [(550_000, 6 * US)]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="FFmpeg required")
def test_exact_sections_pack_remap_and_reuse_with_real_ffmpeg(tmp_path: Path):
    doc, segments = sample()
    downloads = []
    def downloader(url, directory, start, end, **kwargs):
        downloads.append((start, end))
        out = directory / "source.mp4"
        # Distinct color and tone prove each mapped cut uses its own source.
        color = "red" if start < US else "blue"
        frequency = 440 if start < US else 880
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                        f"color={color}:s=160x90:r=30", "-f", "lavfi", "-i",
                        f"sine=frequency={frequency}:sample_rate=48000", "-t", str((end-start)/US),
                        "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)], check=True)
        return out
    video, mapped = prepare_selected_source("https://youtu.be/abc123", segments, doc, tmp_path,
                                            cancelled=lambda: False, downloader=downloader)
    assert len(downloads) == 2
    assert 1.8 * US <= mapped["video_duration_us"] <= 2.1 * US
    assert mapped["segments"][0]["source_start_us"] == 250_000
    assert mapped["segments"][1]["source_start_us"] < 1.3 * US
    assert mapped["segments"][1]["original_source_start_us"] == 4_500_000
    assert segments["segments"][1]["source_start_us"] == 4_500_000
    for item, dominant in zip(mapped["segments"], (0, 2)):
        frame = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(item["source_start_us"]/US),
                                "-i", str(video), "-frames:v", "1", "-vf", "scale=1:1",
                                "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                               check=True, capture_output=True).stdout
        assert frame[dominant] > 200 and frame[1] < 50
    second, again = prepare_selected_source("https://youtube.com/watch?v=abc123", segments, doc, tmp_path,
                                            cancelled=lambda: False, downloader=downloader)
    assert second == video and again == mapped and len(downloads) == 2
    # Another reel selecting just one section also reuses its download.
    prepare_selected_source("https://youtu.be/abc123", segments, {"cuts": [{"seg_ids": ["b"]}]}, tmp_path,
                            cancelled=lambda: False, downloader=downloader)
    assert len(downloads) == 2
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-f", "null", "-"], check=True)


def test_cancelled_cache_wait_does_not_download(tmp_path: Path):
    doc, segments = sample()
    with pytest.raises(RuntimeError, match="취소"):
        prepare_selected_source("https://youtu.be/abc123", segments, doc, tmp_path,
                                cancelled=lambda: True)
