from pathlib import Path

import pytest

from reels_editor.style import StylePreset, load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_load_done_preset() -> None:
    s = load_style(STYLE)
    assert s.canvas == (1080, 1920)
    assert s.title_highlight == "#FF7A00"
    assert s.sub_highlight == "#FF3B30"
    assert s.watermark_text == "D.one"
    assert s.speed == 1.2
    assert s.title_font.is_file()  # Pretendard 실제 설치 확인


def test_video_area_excludes_bars() -> None:
    s = load_style(STYLE)
    assert s.video_area() == (1080, 1920 - s.top_bar - s.bottom_bar)


def test_missing_font_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(STYLE.read_text().replace("Pretendard-ExtraBold", "없는폰트"),
                   encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_style(bad)
