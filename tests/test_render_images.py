from pathlib import Path

from PIL import Image

from reels_editor import render
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_title_png_canvas_size_with_highlight(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png("빨리 실패하지 않으면 손해보는 이유", "손해보는 이유", style,
                                tmp_path / "title.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 122, 0, 255) in colors      # #FF7A00 오렌지 후킹 제목
    assert (255, 255, 255, 255) not in colors

    orange = img.getchannel("A").point(lambda _a: 0)
    pixels = list(img.get_flattened_data())
    orange.putdata([255 if pixel[:3] == (255, 122, 0) else 0 for pixel in pixels])
    orange_bbox = orange.getbbox()
    assert orange_bbox is not None
    title_bbox = img.getbbox()
    assert title_bbox is not None
    assert abs((title_bbox[1] + title_bbox[3]) / 2 - 446.5) <= 2


def test_watermark_png_in_bottom_bar(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_watermark_png(style, tmp_path / "wm.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    bbox = img.getbbox()
    assert bbox is not None
    assert abs((bbox[1] + bbox[3]) / 2 - 1460) <= 2
    assert img.getchannel("A").getextrema()[1] == 128


def test_subtitle_position_mid_canvas(tmp_path: Path) -> None:
    style = load_style(STYLE)
    (p,) = render.render_subtitle_pngs([[0.0, 2.0, "꿈이 있다면"]], [], style, tmp_path)
    img = Image.open(p).convert("RGBA")
    bbox = img.getbbox()
    assert bbox is not None
    _l, top, _r, bottom = bbox
    assert top >= style.top_bar
    assert bottom <= style.canvas[1] - style.bottom_bar
    assert abs((top + bottom) / 2 - 1160) <= 2
    assert img.getchannel("A").getextrema()[1] == 255


def test_subtitle_pngs_one_per_group(tmp_path: Path) -> None:
    style = load_style(STYLE)
    groups = [[0.0, 2.0, "일단 무조건 거부감을 가져요"], [2.0, 4.0, "보수적인 시장이고요"]]
    paths = render.render_subtitle_pngs(groups, ["거부감"], style, tmp_path)
    assert [p.name for p in paths] == ["s000.png", "s001.png"]
    img = Image.open(paths[0]).convert("RGBA")
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 59, 48, 255) in colors  # #FF3B30 레드 강조
