"""CapCut draft_info.json 파싱 → segments.json 구조 (자막을 소스 좌표로 매핑)."""
from __future__ import annotations

import json
import os
from pathlib import Path

US = 1_000_000  # 마이크로초 per 초
DEFAULT_CAPCUT_ROOT = Path.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"


def capcut_root() -> Path:
    return Path(os.environ.get("CAPCUT_ROOT", DEFAULT_CAPCUT_ROOT))


def find_project(name_or_path: str) -> Path:
    """이름이면 CapCut 루트에서, 경로면 그대로. draft_info.json 존재를 확인한다."""
    candidates = [Path(name_or_path).expanduser(), capcut_root() / name_or_path]
    for p in candidates:
        if (p / "draft_info.json").is_file():
            return p
    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"CapCut 프로젝트를 찾을 수 없습니다: {name_or_path!r}\n"
        f"찾아본 위치:\n  {searched}\n"
        f"CapCut에서 프로젝트를 열고 Text → 자동자막을 먼저 생성했는지 확인하세요.")


def load_project(project_dir: Path) -> dict:
    with open(project_dir / "draft_info.json", encoding="utf-8") as f:
        return json.load(f)


def caption_text(text_material: dict) -> str | None:
    """자막 머티리얼의 표시 텍스트. recognize_text 우선, content.text 폴백."""
    rt = text_material.get("recognize_text")
    if rt:
        return rt
    raw = text_material.get("content")
    if not raw:
        return None
    try:
        return json.loads(raw).get("text")
    except (ValueError, TypeError):
        return None


def map_timeline_to_source(video_segments: list[dict], t_us: int) -> tuple[int, float]:
    """타임라인 위치(us) → (원본 소스 위치 us, speed)."""
    for seg in video_segments:
        tr = seg["target_timerange"]
        start, dur = tr["start"], tr["duration"]
        if start <= t_us < start + dur:
            speed = float(seg.get("speed", 1.0))
            src = seg["source_timerange"]["start"] + int((t_us - start) * speed)
            return src, speed
    raise ValueError(f"타임라인 {t_us}us를 커버하는 비디오 세그먼트가 없음")


def _track(draft: dict, kind: str) -> dict:
    for tr in draft["tracks"]:
        if tr["type"] == kind:
            return tr
    if kind == "video":
        raise ValueError("비디오 트랙 없음")
    return {"segments": []}


def build_segments(draft: dict) -> dict:
    vsegs = _track(draft, "video")["segments"]
    text_mats = {m["id"]: m for m in draft["materials"]["texts"]}
    video_mat = draft["materials"]["videos"][0]

    segments: list[dict] = []
    for ts in sorted(_track(draft, "text")["segments"],
                     key=lambda s: s["target_timerange"]["start"]):
        text = caption_text(text_mats.get(ts["material_id"], {}))
        if not text:  # 자동자막 아닌 오버레이 등은 스킵
            continue
        tl = ts["target_timerange"]
        tl_start, tl_end = tl["start"], tl["start"] + tl["duration"]
        try:
            src_start, speed = map_timeline_to_source(vsegs, tl_start)
            src_end, _ = map_timeline_to_source(vsegs, tl_end - 1)
        except ValueError:
            continue
        segments.append({
            "id": ts["id"], "text": text,
            "timeline_start_us": tl_start, "timeline_end_us": tl_end,
            "source_start_us": src_start, "source_end_us": src_end + 1,
            "speed": speed,
        })
    return {
        "video_material_id": video_mat["id"],
        "video_path": video_mat.get("path"),
        "video_duration_us": video_mat.get("duration"),
        "fps": draft.get("fps"),
        "segments": segments,
    }
