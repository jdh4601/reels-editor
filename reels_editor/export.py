"""수정용 재료 산출: srt, 비트별 컷 클립, edl/segments 저장."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from reels_editor.capcut import US


def srt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(groups: list[list], path: Path) -> Path:
    blocks = [f"{i + 1}\n{srt_timestamp(a)} --> {srt_timestamp(b)}\n{t}\n"
              for i, (a, b, t) in enumerate(groups)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def cut_filter(segs: list[dict], speed: float) -> str:
    """컷의 세그먼트들을 개별 trim+배속 후 concat하는 filter_complex (비연속 안전)."""
    parts: list[str] = []
    for j, s in enumerate(segs):
        a = s["source_start_us"] / US
        b = s["source_end_us"] / US
        parts.append(f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed}[v{j}];")
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,atempo={speed}[a{j}];")
    concat = ("".join(f"[v{j}][a{j}]" for j in range(len(segs)))
              + f"concat=n={len(segs)}:v=1:a=1[v][a]")
    return "".join(parts) + concat


def export_cuts(video_path: Path, edl_doc: dict, segments: dict,
                out_dir: Path, speed: float) -> list[Path]:
    """비트별 클립(배속 적용) — CapCut에서 부분 교체용."""
    if not 0.5 <= speed <= 2.0:
        raise ValueError(f"speed {speed}는 ffmpeg atempo 지원 범위(0.5~2.0)를 벗어남")
    idx = {s["id"]: s for s in segments["segments"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, cut in enumerate(edl_doc["cuts"], start=1):
        segs = [idx[sid] for sid in cut["seg_ids"]]
        safe_beat = (cut.get("beat") or f"cut{i}").replace("/", "-")
        p = out_dir / f"{i:03d}-{safe_beat}.mp4"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
             "-filter_complex", cut_filter(segs, speed),
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "aac", str(p)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"컷 추출 실패 ({p.name}):\n{r.stderr}")
        paths.append(p)
    return paths


def write_outputs(work: Path, edl_doc: dict, segments: dict) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "edl.json").write_text(
        json.dumps(edl_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "segments.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
