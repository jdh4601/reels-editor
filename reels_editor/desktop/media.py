from __future__ import annotations

import subprocess
from pathlib import Path


SAMPLE_COUNT = 3


def ensure_sample_media(media_dir: Path) -> None:
    media_dir.mkdir(parents=True, exist_ok=True)
    for index in range(1, SAMPLE_COUNT + 1):
        path = media_dir / f"sample-{index}.mp4"
        if path.is_file():
            continue
        _write_sample_video(path, index)


def _write_sample_video(path: Path, index: int) -> None:
    colors = ["#335c67", "#9e2a2b", "#2f6f4e"]
    color = colors[(index - 1) % len(colors)]
    command = [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=720x1280:d=2:r=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={360 + index * 80}:duration=2",
        "-shortest",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)
