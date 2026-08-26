from pathlib import Path

import pytest

from reels_editor.style import episode_label, load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_load_done_preset() -> None:
    s = load_style(STYLE)
    assert s.canvas == (1080, 1920)
    assert s.title_highlight == "#FF7A00"
    assert s.title_color == "#FF7A00"
    assert s.sub_highlight == "#FFFFFF"
    assert s.watermark_text == ""
    assert s.title_font.name == "Pretendard-Bold.otf"
    assert s.sub_font.name == "Pretendard-Bold.otf"
    assert s.watermark_font.name == "Pretendard-Bold.otf"
    assert s.title_size == 105
    assert s.title_emphasis_size is None
    assert s.title_line_gap == 12
    assert s.title_max_lines == 2
    assert s.title_speaker_size == 46
    assert s.title_speaker_color == "#FFFFFF"
    assert s.title_speaker_gap == 40
    assert s.title_anchor_y == 1185
    assert s.sub_size == 40
    assert s.sub_opacity == 255
    assert s.sub_y == -400
    assert s.watermark_size == 75
    assert s.watermark_opacity == 255
    assert s.watermark_y == -1450
    assert s.watermark_image == (STYLE.parent / "assets" / "D.one.png").resolve()
    assert s.watermark_width == 212
    assert s.episode_text == "에피소드 1"
    assert s.episode_size == 48
    assert s.episode_color == "#FFFFFF"
    assert s.episode_opacity == 255
    assert s.episode_gap == 18
    assert s.episode_y == -1000
    assert s.title_y == 1120
    assert s.video_aspect == (9, 16)
    assert s.video_zoom == 1.0
    assert s.speed == 1.2
    assert s.title_font.is_file()  # Pretendard 실제 설치 확인


def test_video_area_excludes_bars() -> None:
    s = load_style(STYLE)
    assert s.video_area() == (1080, 1920 - s.top_bar - s.bottom_bar)


def test_video_area_matches_reference_window() -> None:
    s = load_style(STYLE)
    assert s.video_area() == (1080, 790)


def test_missing_font_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(STYLE.read_text().replace("Pretendard-Bold", "없는폰트"),
                   encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_style(bad)


def test_job_episode_creates_render_style_without_fixed_total() -> None:
    style = load_style(STYLE)

    episode_style = style.for_episode(37)

    assert episode_label(37) == "에피소드 37"
    assert episode_style.episode_text == "에피소드 37"
    assert "/ 1000" not in episode_style.episode_text
    assert style.episode_text == "에피소드 1"
    with pytest.raises(ValueError):
        style.for_episode(0)
