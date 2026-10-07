"""macOS Vision 기반 발화자 중심 세로 크롭 계획."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import statistics
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from reels_editor import processes
from reels_editor.timebase import US

# 와이드 2인 샷의 얼굴 폭은 화면의 0.045 수준까지 내려간다.
# 640px 샘플에서는 입술 영역이 10px에 그쳐 개폐 비율이 랜드마크 잡음에 지배된다.
SAMPLE_WIDTH = 1280
SAMPLE_QUALITY = 2
SAMPLES_PER_SECOND = 5.0
MIN_SAMPLES = 6
MAX_SAMPLES = 48
TRACKING_WINDOW_SECONDS = 2.0
TRACK_DISTANCE = 0.22
MIN_TWO_PERSON_FRAME_RATIO = 0.80
LEFT_ANCHOR_MAX_X = 1 / 3
RIGHT_ANCHOR_MIN_X = 2 / 3
TWO_PERSON_ZOOM = 1.3
ANALYSIS_CACHE_VERSION = 7


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


@dataclass(frozen=True)
class FocusSlice:
    segment_index: int
    start_s: float
    end_s: float
    point: FocusPoint


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


def build_tracking_windows(ordered: list[dict[str, Any]]) -> list[FocusWindow]:
    """긴 자막 구간 안에서도 화면 전환을 따라가도록 짧은 분석창으로 나눈다."""
    windows: list[FocusWindow] = []
    for segment_index, item in enumerate(ordered):
        start_s = float(item["source_start_us"]) / US
        end_s = float(item["source_end_us"]) / US
        cursor = start_s
        while cursor < end_s:
            window_end = min(end_s, cursor + TRACKING_WINDOW_SECONDS)
            windows.append(FocusWindow((segment_index,), cursor, window_end))
            cursor = window_end
    return windows


def sample_count_for(duration_s: float) -> int:
    """구간 길이에 비례해 입술 움직임을 잴 수 있는 표본 수를 정한다."""
    target = round(max(0.0, duration_s) * SAMPLES_PER_SECOND)
    return min(MAX_SAMPLES, max(MIN_SAMPLES, target))


def horizontal_anchor(x: float) -> float:
    """연속 좌표를 좌측 끝·중앙·우측 끝 중 하나로 고정한다."""
    if x <= LEFT_ANCHOR_MAX_X:
        return 0.0
    if x >= RIGHT_ANCHOR_MIN_X:
        return 1.0
    return 0.5


def content_relative_focus_x(
    point: FocusPoint,
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
) -> float:
    """중앙 고정은 보존하고, 투샷의 좌우 초점만 콘텐츠 좌표로 옮긴다."""
    if point.x == 0.5:
        return 0.5
    return horizontal_anchor(_content_relative_x(point.x, source_size, content_crop))


def choose_active_face(frames: list[list[FaceSignal]]) -> FocusPoint | None:
    """투샷일 때만 입술 움직임이 큰 인물 쪽으로 수평 초점을 옮긴다."""
    two_person_frames = sum(len(frame) >= 2 for frame in frames)
    required_two_person_frames = max(
        2,
        math.ceil(len(frames) * MIN_TWO_PERSON_FRAME_RATIO),
    )
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
        # 한 프레임의 입술 랜드마크 오검출이 점수를 지배하지 못하도록
        # 평균과 표준편차 대신 중앙값과 중앙값 절대편차로 발화량을 잰다.
        center = statistics.median(openness)
        motion = (
            statistics.median([abs(value - center) for value in openness])
            if len(openness) > 1 else 0.0
        )
        return center + motion * 1.5 + coverage * 0.08

    chosen = max(viable, key=score)
    chosen_signals = [signal for _index, signal in chosen]
    x = statistics.median(signal.x for signal in chosen_signals)
    # A missed second face must not hide the detected person at the edge.
    if two_person_frames < required_two_person_frames:
        if horizontal_anchor(x) != 0.5:
            return FocusPoint(x=horizontal_anchor(x))
        return FocusPoint()
    return FocusPoint(x=0.0 if x < 0.5 else 1.0, zoom=TWO_PERSON_ZOOM)


def frame_focus_points(frames: list[list[FaceSignal]], previous: FocusPoint = FocusPoint()) -> list[FocusPoint]:
    """React on the first two-shot frame, with lip-motion context and no empty-frame recentering."""
    points = []
    for index, faces in enumerate(frames):
        if len(faces) >= 2:
            context = [frame for frame in frames[max(0, index-3):index+4] if len(frame) >= 2]
            selected = choose_active_face(context) or previous
            # Restrict the selected anchor to faces visible in this frame.
            anchors = {0.0 if face.x < 0.5 else 1.0 for face in faces}
            # Keep the selected person throughout a wide shot; intermittent
            # mouth/second-face detection must not alternate the camera sides.
            anchor = previous.x if previous.x in anchors else (
                selected.x if selected.x in anchors else min(anchors, key=lambda x: abs(x-previous.x))
            )
            previous = FocusPoint(x=anchor, zoom=TWO_PERSON_ZOOM)
        elif faces:
            face = faces[0]
            anchor = horizontal_anchor(face.x)
            if anchor == 0.5 or face.width >= 0.12 or previous.x == 0.5:
                previous = FocusPoint(x=anchor)
            # One small edge face often means the other face in a wide shot was
            # missed. Keep the established side and zoom until a close-up.
        # No detection: hold the last camera position until a face is visible.
        points.append(previous)
    return points


def analyze_speaker_focus(
    video_path: Path,
    ordered: list[dict[str, Any]],
    cut_sizes: list[int],
    source_size: tuple[int, int],
    content_crop: tuple[int, int, int, int] | None,
    work_dir: Path,
) -> list[FocusSlice] | None:
    """Detect every decoded frame and coalesce equal crop positions before rendering."""
    _ = cut_sizes
    windows = build_tracking_windows(ordered)
    if not windows:
        return None
    focus_root = work_dir / "speaker-focus"
    focus_root.mkdir(parents=True, exist_ok=True)
    slices: list[FocusSlice] = []
    report: dict[str, Any] = {"windows": [], "error": None, "mode": "every-frame"}
    detected_faces = 0
    previous = FocusPoint()
    try:
        for window_index, window in enumerate(windows):
            cache_path = _window_cache_path(video_path, window, source_size, content_crop)
            cached = _read_cached_window(cache_path)
            cache_hit = cached is not None
            if cached is None:
                directory = focus_root / f"cut-{window_index:02d}"
                paths = _extract_sample_frames(video_path, window, directory)
                observations = [_detect_faces(path) for path in paths]
                timing_path = directory / "frame-times.json"
                if timing_path.is_file():
                    times = json.loads(timing_path.read_text())
                else:
                    times = [(window.end_s-window.start_s)*i/max(1, len(paths)) for i in range(len(paths))]
                cached = {"observations": [[asdict(face) for face in frame] for frame in observations],
                          "times": times, "detected_faces": sum(map(len, observations))}
                _write_cached_window(cache_path, cached)
            observations = [[FaceSignal(**face) for face in frame] for frame in cached["observations"]]
            # Use content-relative face positions before deciding left/right.
            observations = [[FaceSignal(x=_content_relative_x(face.x, source_size, content_crop),
                                         width=face.width, mouth_open=face.mouth_open,
                                         y=face.y, height=face.height) for face in frame] for frame in observations]
            points = frame_focus_points(observations, previous)
            if points:
                previous = points[-1]
            times = cached["times"]
            if not points:
                slices.append(FocusSlice(window.segment_indexes[0], window.start_s, window.end_s, previous))
            for index, point in enumerate(points):
                start = window.start_s if index == 0 else window.start_s + times[index]
                end = window.end_s if index+1 == len(points) else window.start_s + times[index+1]
                start, end = max(window.start_s, start), min(window.end_s, end)
                if end <= start:
                    continue
                segment_index = window.segment_indexes[0]
                if (slices and slices[-1].segment_index == segment_index
                    and abs(slices[-1].end_s-start) < 1e-6 and slices[-1].point == point):
                    last = slices.pop()
                    start = last.start_s
                slices.append(FocusSlice(segment_index, start, end, point))
            detected_faces += cached["detected_faces"]
            report["windows"].append({"index": window_index, "start_s": window.start_s,
                "end_s": window.end_s, "frame_count": len(points),
                "face_counts": list(map(len, observations)), "cache_hit": cache_hit})
    except (ImportError, OSError, RuntimeError, ValueError, TypeError) as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        _write_report(focus_root / "plan.json", report)
        return None
    report["slices"] = [asdict(item) for item in slices]
    _write_report(focus_root / "plan.json", report)
    return slices if detected_faces and any(item.point.x != 0.5 for item in slices) else None


def _extract_sample_frames(video_path: Path, window: FocusWindow, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("frame-*.jpg"):
        old.unlink()
    duration = window.end_s - window.start_s
    output_pattern = out_dir / "frame-%06d.jpg"
    result = processes.run(
        ["ffmpeg", "-y", "-loglevel", "info", "-ss", f"{window.start_s:.6f}",
         "-t", f"{duration:.6f}", "-i", str(video_path),
         "-vf", f"scale={SAMPLE_WIDTH}:-2,showinfo", "-fps_mode", "passthrough",
         "-q:v", str(SAMPLE_QUALITY), str(output_pattern)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"화자 분석 프레임 추출 실패: {result.stderr.strip()}")
    paths = sorted(out_dir.glob("frame-*.jpg"))
    times = [float(value) for value in re.findall(r"\bpts_time:([-+0-9.eE]+)", result.stderr)]
    if len(times) != len(paths):
        raise RuntimeError("화자 분석 프레임과 시간 정보가 일치하지 않습니다.")
    (out_dir / "frame-times.json").write_text(json.dumps(times))
    return paths


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
            "sample_quality": SAMPLE_QUALITY,
            "sample_range": [MIN_SAMPLES, MAX_SAMPLES, SAMPLES_PER_SECOND],
        },
        sort_keys=True,
    )
    key = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return video_path.parent / ".analysis-cache" / "speaker-focus" / f"{key}.json"


def _read_cached_window(path: Path) -> dict[str, Any] | None:
    """필수 항목을 모두 갖춘 캐시만 재사용한다. 이전 스키마는 폐기한다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("observations"), list) or not isinstance(data.get("times"), list):
        return None
    if len(data["observations"]) != len(data["times"]):
        return None
    if not isinstance(data.get("detected_faces"), int):
        return None
    return data


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


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
