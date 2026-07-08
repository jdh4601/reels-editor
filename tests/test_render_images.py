from pathlib import Path

from PIL import Image

from reels_editor import render
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_title_png_canvas_size_with_highlight(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png("해양경찰이 선택한 스타트업", "해양경찰", style,
                                tmp_path / "title.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 122, 0, 255) in colors      # #FF7A00 오렌지 강조 존재
    assert (255, 255, 255, 255) in colors    # 흰 텍스트 존재


def test_watermark_png_in_bottom_bar(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_watermark_png(style, tmp_path / "wm.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    top = img.crop((0, 0, style.canvas[0], style.canvas[1] - style.bottom_bar))
    assert top.getbbox() is None  # 텍스트는 하단 바에만 존재


def test_subtitle_pngs_one_per_group(tmp_path: Path) -> None:
    style = load_style(STYLE)
    groups = [[0.0, 2.0, "일단 무조건 거부감을 가져요"], [2.0, 4.0, "보수적인 시장이고요"]]
    paths = render.render_subtitle_pngs(groups, ["거부감"], style, tmp_path)
    assert [p.name for p in paths] == ["s000.png", "s001.png"]
    img = Image.open(paths[0]).convert("RGBA")
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 59, 48, 255) in colors  # #FF3B30 레드 강조
