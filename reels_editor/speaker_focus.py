"""macOS Vision 기반 발화자 중심 세로 크롭 계획."""
from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reels_editor import processes
from reels_editor.timebase import US

SAMPLE_WIDTH = 640
MIN_SAMPLES = 3
MAX_SAMPLES = 7
TRACK_DISTANCE = 0.22
WIDE_SHOT_FACE_WIDTH = 0.14
WIDE_SHOT_ZOOM = 1.4
ANALYSIS_CACHE_VERSION = 1


@dataclass(frozen=True)
class FaceSignal:
    x: float
    width: float
    mouth_open: float
    # Vision은 좌하단 원점이지만 렌더 크롭은 좌상단 원점이다.
    # 탐지 시점에 좌상단 원점의 얼굴 중심으로 변환해 보관한다.
    y: float = 0.5
    height: float = 0.0


@dataclass(frozen=True)
class FocusPoint:
    x: float = 0.5
    y: float = 0.5
    zoom: float = 1.0


@dataclass(frozen=True)
class FocusWindow:
    segment_indexes: tuple[int, ...]
    start_s: float
    end_s: float


def vision_available() -> bool:
    """Return whether the local macOS Vision bridge can load face-landmark APIs."""
    try:
        from Foundation import NSURL  # noqa: F401
        from Vision import VNDetectFaceLandmarksRequest, VNImageRequestHandler  # noqa: F401
    except ImportError:
        return False
    return True


def build_focus_windows(ordered: list[dict[str, Any]], cut_sizes: list[int]) -> list[FocusWindow]:
    """EDL의 각 컷을 하나의 안정적인 카메라 이동 구간으로 만든다."""
    if not ordered or sum(cut_sizes) != len(ordered) or any(size < 1 for size in cut_sizes):
        return []
    windows: list[FocusWindow] = []
    cursor = 0
    for size in cut_sizes:
        indexes = tuple(range(cursor, cursor + size))
        items = [ordered[index] for index in indexes]
        windows.append(FocusWindow(
            segment_indexes=indexes,
            start_s=min(float(item["source_start_us"]) / US for item in items),
            end_s=max(float(item["source_end_us"]) / US for item in items),
        ))
        cursor += size
    return windows


def choose_active_face(frames: list[list[FaceSignal]]) -> FocusPoint | None:
    """프레임 사이 얼굴을 x좌표로 묶고 입 벌림·움직임이 큰 얼굴을 고른다."""
    tracks: list[list[tuple[int, FaceSignal]]] = []
    for frame_index, faces in enumerate(frames):
        used: set[int] = set()
        for face in sorted(faces, key=lambda item: item.x):
            candidates = [
                (abs(statistics.median(signal.x for _index, signal in track) - face.x), index)
                for index, track in enumerate(tracks)
                if index not in used
            ]
            distance, track_index = min(candidates, default=(math.inf, -1))
            if distance > TRACK_DISTANCE:
                tracks.append([(frame_index, face)])
                used.add(len(tracks) - 1)
            else:
                tracks[track_index].append((frame_index, face))
                used.add(track_index)

    if not tracks:
        return None
    minimum_observations = max(2, math.ceil(len(frames) * 0.4))
    viable = [track for track in tracks if len(track) >= minimum_observations]
    if not viable:
        viable = tracks

    def score(track: list[tuple[int, FaceSignal]]) -> float:
        openness = [signal.mouth_open for _index, signal in track]
        coverage = len({frame_index for frame_index, _signal in track}) / max(1, len(frames))
        motion = statistics.pstdev(openness) if len(openness) > 1 else 0.0
        return statistics.fmean(openness) + motion * 1.5 + coverage * 0.08

    chosen = max(viable, key=score)
    chosen_signals = [signal for _index, signal in chosen]
    x = statistics.median(signal.x for signal in chosen_signals)
    y = statistics.median(signal.y for signal in chosen_signals)
    mean_width = statistics.fmean(signal.width for signal in chosen_signals)
    max_faces = max((len(frame) for frame in frames), default=0)
    zoom = WIDE_SHOT_ZOOM if max_faces >= 2 or mean_width < WIDE_SHOT_FACE_WIDTH else 1.0
    return FocusPoint(
        x=max(0.0, min(1.0, x)),
        y=max(0.0, min(1.0, y)),
        zoom=zoom,
    )


def analyze_speaker_focus(
    video_path: Path,
    ordered: list[dict[str, Any]],
    cut_sizes: list[int],
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
    work_dir: Path,
) -> list[FocusPoint] | None:
    """각 EDL 컷의 발화자 위치를 계산한다. 실패하면 중앙 크롭으로 안전하게 폴백한다."""
    windows = build_focus_windows(ordered, cut_sizes)
    if not windows:
        return None
    focus_root = work_dir / "speaker-focus"
    focus_root.mkdir(parents=True, exist_ok=True)
    points = [FocusPoint() for _item in ordered]
    report: dict[str, Any] = {"windows": [], "error": None}
    detected_faces = 0
    try:
        for window_index, window in enumerate(windows):
            cache_path = _window_cache_path(
                video_path,
                window,
                source_size,
                content_crop,
            )
            cached = _read_cached_window(cache_path)
            if cached is None:
                frames = _extract_sample_frames(
                    video_path,
                    window,
                    focus_root / f"cut-{window_index:02d}",
                )
                observations = [_detect_faces(path) for path in frames]
                face_counts = [len(frame) for frame in observations]
                window_faces = sum(face_counts)
                point = choose_active_face(observations) or FocusPoint()
                point = FocusPoint(
                    x=_content_relative_x(point.x, source_size, content_crop),
                    y=_content_relative_y(point.y, source_size, content_crop),
                    zoom=point.zoom,
                )
                cached = {
                    "focus": asdict(point),
                    "detected_faces": window_faces,
                    "frame_count": len(frames),
                    "face_counts": face_counts,
                }
                _write_cached_window(cache_path, cached)
                cache_hit = False
            else:
                focus = cached["focus"]
                point = FocusPoint(
                    x=float(focus.get("x", 0.5)),
                    y=float(focus.get("y", 0.5)),
                    zoom=float(focus.get("zoom", 1.0)),
                )
                cache_hit = True
            detected_faces += int(cached.get("detected_faces", 0))
            for segment_index in window.segment_indexes:
                points[segment_index] = point
            report["windows"].append({
                "index": window_index,
                "start_s": window.start_s,
                "end_s": window.end_s,
                "frame_count": int(cached.get("frame_count", 0)),
                "face_counts": list(cached.get("face_counts", [])),
                "focus": asdict(point),
                "cache_hit": cache_hit,
            })
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        _write_report(focus_root / "plan.json", report)
        return None
    _write_report(focus_root / "plan.json", report)
    return points if detected_faces else None


def _extract_sample_frames(video_path: Path, window: FocusWindow, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.jpg"):
        old.unlink()
    duration = max(0.25, window.end_s - window.start_s)
    sample_count = min(MAX_SAMPLES, max(MIN_SAMPLES, round(duration * 1.5)))
    fps = sample_count / duration
    output_pattern = out_dir / "frame-%02d.jpg"
    result = processes.run(
        [
            "ffmpeg", "-y", "-loglevel", "error",
            "-ss", f"{window.start_s:.3f}", "-t", f"{duration:.3f}",
            "-i", str(video_path),
            "-vf", f"fps={fps:.6f},scale={SAMPLE_WIDTH}:-2",
            "-frames:v", str(sample_count),
            str(output_pattern),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"화자 분석 프레임 추출 실패: {result.stderr.strip()}")
    return sorted(out_dir.glob("frame-*.jpg"))


def _window_cache_path(
    video_path: Path,
    window: FocusWindow,
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
) -> Path:
    try:
        stat = video_path.stat()
        source_identity = [str(video_path.resolve()), stat.st_size, stat.st_mtime_ns]
    except OSError:
        source_identity = [str(video_path.resolve()), 0, 0]
    payload = json.dumps(
        {
            "version": ANALYSIS_CACHE_VERSION,
            "source": source_identity,
            "window": [round(window.start_s, 6), round(window.end_s, 6)],
            "source_size": source_size,
            "content_crop": content_crop,
            "sample_width": SAMPLE_WIDTH,
            "sample_range": [MIN_SAMPLES, MAX_SAMPLES],
        },
        sort_keys=True,
    )
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return video_path.parent / ".analysis-cache" / "speaker-focus" / f"{key}.json"


def _read_cached_window(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        focus = data.get("focus")
        if not isinstance(focus, dict):
            return None
        return data
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _write_cached_window(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.part"
    )
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _detect_faces(path: Path) -> list[FaceSignal]:
    from Foundation import NSURL
    from Vision import VNDetectFaceLandmarksRequest, VNImageRequestHandler

    request = VNDetectFaceLandmarksRequest.alloc().init()
    handler = VNImageRequestHandler.alloc().initWithURL_options_(
        NSURL.fileURLWithPath_(str(path)),
        {},
    )
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(f"Vision 얼굴 탐지 실패: {error}")
    faces: list[FaceSignal] = []
    for observation in request.results() or ():
        box = observation.boundingBox()
        if float(observation.confidence()) < 0.5 or box.size.width < 0.025:
            continue
        landmarks = observation.landmarks()
        region = landmarks.innerLips() if landmarks is not None else None
        if region is None and landmarks is not None:
            region = landmarks.outerLips()
        mouth_open = _mouth_openness(region)
        faces.append(FaceSignal(
            x=float(box.origin.x + box.size.width / 2),
            width=float(box.size.width),
            mouth_open=mouth_open,
            y=float(1.0 - (box.origin.y + box.size.height / 2)),
            height=float(box.size.height),
        ))
    return faces


def _mouth_openness(region: Any) -> float:
    if region is None or region.pointCount() < 2:
        return 0.0
    points = region.normalizedPoints()
    xy = [(float(points[index].x), float(points[index].y)) for index in range(region.pointCount())]
    width = max(x for x, _y in xy) - min(x for x, _y in xy)
    height = max(y for _x, y in xy) - min(y for _x, y in xy)
    return max(0.0, min(2.0, height / width if width > 0 else 0.0))


def _content_relative_x(
    x: float,
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
) -> float:
    if content_crop is None:
        return x
    source_w, _source_h = source_size
    crop_w, _crop_h, crop_x, _crop_y = content_crop
    if crop_w <= 0:
        return x
    return max(0.0, min(1.0, (x * source_w - crop_x) / crop_w))


def _content_relative_y(
    y: float,
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
) -> float:
    if content_crop is None:
        return y
    _source_w, source_h = source_size
    _crop_w, crop_h, _crop_x, crop_y = content_crop
    if crop_h <= 0:
        return y
    return max(0.0, min(1.0, (y * source_h - crop_y) / crop_h))


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
