from pathlib import Path

import pytest

from reels_editor.style import StylePreset, load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_load_done_preset() -> None:
    s = load_style(STYLE)
    assert s.canvas == (1080, 1920)
    assert s.title_highlight == "#FF7A00"
    assert s.title_color == "#FF7A00"
    assert s.sub_highlight == "#FF3B30"
    assert s.watermark_text == "D.one"
    assert s.title_font.name == "Pretendard-Bold.otf"
    assert s.sub_font.name == "Pretendard-Bold.otf"
    assert s.watermark_font.name == "Pretendard-Bold.otf"
    assert s.title_size == 65
    assert s.title_emphasis_size == 85
    assert s.title_line_gap == 18
    assert s.sub_size == 40
    assert s.sub_opacity == 255
    assert s.sub_y == -400
    assert s.watermark_size == 75
    assert s.watermark_opacity == 128
    assert s.watermark_y == -1000
    assert s.title_y == 1027
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
