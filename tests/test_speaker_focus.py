from __future__ import annotations

from pathlib import Path

from reels_editor import speaker_focus
from reels_editor.speaker_focus import (
    FaceSignal,
    build_focus_windows,
    choose_active_face,
)


def test_build_focus_windows_follows_edl_cut_sizes(segments: dict) -> None:
    ordered = [
        segments["segments"][1],
        segments["segments"][2],
        segments["segments"][0],
    ]

    windows = build_focus_windows(ordered, [2, 1])

    assert [window.segment_indexes for window in windows] == [(0, 1), (2,)]
    assert windows[0].start_s == 5.0
    assert windows[0].end_s == 23.0


def test_choose_active_face_prefers_speaking_face_and_zooms_wide_shot() -> None:
    frames = [
        [
            FaceSignal(0.14, 0.07, left, y=0.31),
            FaceSignal(0.88, 0.08, right, y=0.46),
        ]
        for left, right in [
            (0.45, 0.40),
            (0.88, 0.42),
            (0.52, 0.41),
            (0.91, 0.40),
            (0.60, 0.43),
        ]
    ]

    point = choose_active_face(frames)

    assert point is not None
    assert point.x == 0.14
    assert point.y == 0.31
    assert point.zoom == 1.4


def test_choose_active_face_keeps_close_single_speaker_at_normal_zoom() -> None:
    frames = [[FaceSignal(0.47, 0.25, openness)] for openness in (0.4, 0.8, 0.5)]

    point = choose_active_face(frames)

    assert point is not None
    assert point.x == 0.47
    assert point.zoom == 1.0


def test_analysis_cache_skips_reextracting_the_same_source_window(
        tmp_path: Path, segments: dict, monkeypatch) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source-video")
    ordered = [segments["segments"][0]]
    extraction_calls: list[Path] = []

    def fake_extract(_video: Path, _window, out_dir: Path) -> list[Path]:
        extraction_calls.append(out_dir)
        return [out_dir / f"frame-{index}.jpg" for index in range(3)]

    monkeypatch.setattr(speaker_focus, "_extract_sample_frames", fake_extract)
    monkeypatch.setattr(
        speaker_focus,
        "_detect_faces",
        lambda _path: [FaceSignal(0.3, 0.2, 0.7, y=0.4)],
    )

    first = speaker_focus.analyze_speaker_focus(
        video, ordered, [1], (1920, 1080), None, tmp_path / "render-1",
    )
    second = speaker_focus.analyze_speaker_focus(
        video, ordered, [1], (1920, 1080), None, tmp_path / "render-2",
    )

    assert first == second
    assert len(extraction_calls) == 1
    report = (tmp_path / "render-2" / "speaker-focus" / "plan.json").read_text(
        encoding="utf-8",
    )
    assert '"cache_hit": true' in report


# 실제 오선택 사례(job 9296937.../s4, cut-03)에서 640px 샘플로 측정한 값이다.
# 왼쪽 인물이 발화 중이고 오른쪽 인물은 노트를 보는 청자다.
LOW_RESOLUTION_REGRESSION = {
    "speaker_x": 0.205,
    "listener_x": 0.790,
    "speaker_openness": (0.548, 0.135, 0.949, 0.535, 0.771, 0.131, 0.985),
    "listener_openness": (0.275, 0.232, 1.331, 0.643, 0.600, 0.623, 0.572),
}


def test_choose_active_face_ignores_single_noisy_outlier_from_listener() -> None:
    """청자의 입 벌림 값 하나가 크게 튀어도 실제 발화자를 골라야 한다."""
    case = LOW_RESOLUTION_REGRESSION
    frames = [
        [
            FaceSignal(case["speaker_x"], 0.055, speaker, y=0.38),
            FaceSignal(case["listener_x"], 0.047, listener, y=0.36),
        ]
        for speaker, listener in zip(
            case["speaker_openness"], case["listener_openness"],
        )
    ]

    point = choose_active_face(frames)

    assert point is not None
    assert point.x == case["speaker_x"]


def test_sample_width_resolves_mouth_landmarks_on_wide_two_shot() -> None:
    """와이드 2인 샷의 얼굴 폭 0.045에서도 입술 영역이 충분히 커야 한다."""
    narrowest_face_ratio = 0.045
    face_pixels = speaker_focus.SAMPLE_WIDTH * narrowest_face_ratio

    assert face_pixels >= 50


def test_sample_plan_keeps_enough_frames_to_measure_lip_motion() -> None:
    """입술 움직임을 재려면 컷 길이와 무관하게 밀도가 유지되어야 한다."""
    assert speaker_focus.sample_count_for(3.1) >= 12
    assert speaker_focus.sample_count_for(6.3) >= 24
    assert speaker_focus.sample_count_for(18.4) >= 36
    assert speaker_focus.sample_count_for(600.0) <= speaker_focus.MAX_SAMPLES


def test_cached_window_from_an_older_schema_is_discarded(tmp_path: Path) -> None:
    """세로 위치가 없던 이전 스키마 캐시는 조용히 재사용하지 않는다."""
    stale = tmp_path / "stale.json"
    stale.write_text(
        '{"focus": {"x": 0.79, "zoom": 1.4}, "detected_faces": 14}',
        encoding="utf-8",
    )

    assert speaker_focus._read_cached_window(stale) is None


def test_cache_path_changes_when_the_analysis_version_changes(
        tmp_path: Path, monkeypatch) -> None:
    """알고리즘이 바뀌면 이전 캐시를 재사용하지 않도록 키가 달라져야 한다."""
    video = tmp_path / "source.mp4"
    video.write_bytes(b"source-video")
    window = speaker_focus.FocusWindow((0,), 0.0, 5.0)

    before = speaker_focus._window_cache_path(video, window, (1920, 1080), None)
    monkeypatch.setattr(speaker_focus, "ANALYSIS_CACHE_VERSION", 99)
    after = speaker_focus._window_cache_path(video, window, (1920, 1080), None)

    assert before != after


def test_sample_frames_are_extracted_with_low_compression_loss(
        tmp_path: Path, monkeypatch) -> None:
    """압축 아티팩트가 입술 랜드마크를 무너뜨리지 않도록 고품질로 추출한다."""
    commands: list[list[str]] = []

    class _Result:
        returncode = 0
        stderr = ""

    def fake_run(command: list[str], **_kwargs):
        commands.append(command)
        return _Result()

    monkeypatch.setattr(speaker_focus.processes, "run", fake_run)
    speaker_focus._extract_sample_frames(
        tmp_path / "source.mp4",
        speaker_focus.FocusWindow((0,), 0.0, 6.0),
        tmp_path / "frames",
    )

    assert commands
    command = commands[0]
    assert "-q:v" in command
    assert int(command[command.index("-q:v") + 1]) <= 2
