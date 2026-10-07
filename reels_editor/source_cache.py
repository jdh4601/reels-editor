"""Shared source cache and exact section preparation for transcript-first jobs."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

from reels_editor import edl, processes, youtube
from reels_editor.timebase import US


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


@contextmanager
def locked(path: Path, cancelled: Callable[[], bool]) -> Iterator[None]:
    """Serialize identical cache writes across tabs and local service processes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        while True:
            if cancelled():
                raise youtube.YouTubeSourceError("캐시 준비가 취소되었습니다.")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def selected_ranges(doc: dict, segments: dict) -> list[tuple[int, int]]:
    """Merge overlapping selected cuts; include 250ms handles for exact trimming."""
    windows = sorted((max(0, s["source_start_us"] - US // 4),
                      s["source_end_us"] + US // 4)
                     for s in edl.ordered_segments(doc, segments))
    duration = segments.get("video_duration_us")
    if duration:
        windows = [(start, min(end, duration)) for start, end in windows]
    merged: list[tuple[int, int]] = []
    for start, end in windows:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def download_section(url: str, output_dir: Path, start_us: int, end_us: int,
                     *, cancelled: Callable[[], bool]) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    def hook(_event: dict) -> None:
        if cancelled():
            raise youtube.YouTubeSourceError("구간 다운로드가 취소되었습니다.")
    options = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": youtube.DOWNLOAD_FORMAT, "merge_output_format": "mp4",
        "outtmpl": str(output_dir / "source.%(ext)s"),
        "download_ranges": lambda _info, _ydl: [{"start_time": start_us / US,
                                                  "end_time": end_us / US}],
        # Stream-copy can start at a preceding keyframe and shift subtitles.
        "force_keyframes_at_cuts": True,
        "external_downloader_args": {"ffmpeg_o": ["-c:v", "libx264", "-preset", "veryfast",
                                                   "-crf", "18", "-c:a", "aac"]},
        "progress_hooks": [hook], "socket_timeout": 20, "retries": 3, "overwrites": True,
    }
    with youtube._default_ydl_factory(options) as ydl:
        ydl.extract_info(youtube.validate_youtube_url(url), download=True)
    return youtube._find_downloaded_video(output_dir)


def _duration_us(path: Path) -> int:
    result = processes.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                            "-of", "default=nw=1:nk=1", str(path)],
                           check=True, capture_output=True, text=True)
    return round(float(result.stdout.strip()) * US)


def prepare_selected_source(url: str, segments: dict, doc: dict, cache_dir: Path,
                            *, cancelled: Callable[[], bool],
                            downloader: Callable[..., Path] = download_section) -> tuple[Path, dict]:
    """Pack only needed sections and map original subtitle IDs to local time."""
    ranges = selected_ranges(doc, segments)
    selected_ids = {sid for cut in doc["cuts"] for sid in cut["seg_ids"]}
    key = fingerprint({"version": 1, "ranges": ranges, "format": youtube.DOWNLOAD_FORMAT})
    bundle = cache_dir / "clips" / key
    with locked(bundle / ".lock", cancelled):
        manifest = bundle / "manifest.json"
        packed = bundle / "source.mp4"
        offsets = None
        if manifest.is_file() and packed.is_file() and packed.stat().st_size:
            try:
                offsets = json.loads(manifest.read_text())["offsets"]
            except (ValueError, KeyError):
                pass
        if offsets is None:
            parts: list[Path] = []
            offsets = []
            cursor = 0
            for start, end in ranges:
                section_dir = cache_dir / "sections" / fingerprint([start, end, youtube.DOWNLOAD_FORMAT])
                with locked(section_dir / ".lock", cancelled):
                    done = section_dir / "complete.json"
                    section = None
                    if done.is_file():
                        try:
                            section = youtube._find_downloaded_video(section_dir)
                            if not section.stat().st_size:
                                section = None
                        except youtube.YouTubeSourceError:
                            pass
                    if section is None:
                        section = downloader(url, section_dir, start, end, cancelled=cancelled)
                        duration = _duration_us(section)
                        if duration < end - start - US // 10:
                            raise youtube.YouTubeSourceError("다운로드한 구간이 요청한 컷보다 짧습니다.")
                        write_json(done, {"duration_us": duration})
                    duration = _duration_us(section)
                parts.append(section)
                offsets.append([start, end, cursor])
                cursor += duration
            if cancelled():
                raise youtube.YouTubeSourceError("구간 다운로드가 취소되었습니다.")
            # Paths are controlled hash directories; ffmpeg concat escaping still
            # matters when the user's home directory contains an apostrophe.
            listing = bundle / "concat.txt"
            listing.write_text("".join("file '" + str(p.resolve()).replace("'", "'\\''") + "'\n"
                                       for p in parts))
            temp = bundle / "packed.tmp.mp4"
            processes.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
                           "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(temp)],
                          check=True, capture_output=True)
            os.replace(temp, packed)
            write_json(manifest, {"offsets": offsets})
    mapped = dict(segments)
    mapped["video_path"] = str(packed)
    mapped["video_duration_us"] = _duration_us(packed)
    mapped["original_video_path"] = segments.get("video_path")
    mapped["segments"] = []
    for item in segments["segments"]:
        if item["id"] not in selected_ids:
            continue
        start, end, offset = next(window for window in offsets
                                  if window[0] <= item["source_start_us"]
                                  and item["source_end_us"] <= window[1])
        mapped["segments"].append({**item,
            "original_source_start_us": item["source_start_us"],
            "original_source_end_us": item["source_end_us"],
            "source_start_us": item["source_start_us"] - start + offset,
            "source_end_us": item["source_end_us"] - start + offset,
            "timeline_start_us": item["source_start_us"] - start + offset,
            "timeline_end_us": item["source_end_us"] - start + offset})
    return packed, mapped
