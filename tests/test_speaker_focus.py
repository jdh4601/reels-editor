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
