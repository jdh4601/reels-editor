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
    assert orange_bbox[0] >= 60
    assert orange_bbox[2] <= style.canvas[0] - 60
    assert abs((orange_bbox[1] + orange_bbox[3]) / 2 - 400) <= 2


def test_title_png_uses_one_safe_line_and_white_speaker_label(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png(
        "좋은 아이디어를 포기하는 창업가의 가장 어려운 결정",
        "가장 어려운 결정",
        style,
        tmp_path / "title-speaker.png",
        speaker_text="샘 알트만 (CEO of OpenAI)",
    )
    img = Image.open(p).convert("RGBA")
    orange = img.getchannel("A").point(lambda _a: 0)
    white = img.getchannel("A").point(lambda _a: 0)
    pixels = list(img.get_flattened_data())
    orange.putdata([255 if pixel[:3] == (255, 122, 0) else 0 for pixel in pixels])
    white.putdata([255 if pixel[:3] == (255, 255, 255) else 0 for pixel in pixels])
    orange_bbox = orange.getbbox()
    white_bbox = white.getbbox()

    assert orange_bbox is not None and white_bbox is not None
    assert orange_bbox[0] >= 60
    assert orange_bbox[2] <= style.canvas[0] - 60
    assert white_bbox[1] > orange_bbox[3]
    assert white_bbox[2] - white_bbox[0] < orange_bbox[2] - orange_bbox[0]


def test_watermark_png_in_bottom_bar(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_watermark_png(style, tmp_path / "wm.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    alpha = img.getchannel("A")
    logo_region_top = 1600
    episode_region_bottom = 1550
    logo_local_bbox = alpha.crop((0, logo_region_top, style.canvas[0], style.canvas[1])).getbbox()
    episode_bbox = alpha.crop((0, 1350, style.canvas[0], episode_region_bottom)).getbbox()
    logo_bbox = (
        None
        if logo_local_bbox is None
        else (
            logo_local_bbox[0],
            logo_region_top + logo_local_bbox[1],
            logo_local_bbox[2],
            logo_region_top + logo_local_bbox[3],
        )
    )
    if episode_bbox is not None:
        episode_bbox = (
            episode_bbox[0],
            1350 + episode_bbox[1],
            episode_bbox[2],
            1350 + episode_bbox[3],
        )
    assert logo_bbox is not None and episode_bbox is not None
    logo_center_y = (logo_bbox[1] + logo_bbox[3]) / 2
    episode_center_y = (episode_bbox[1] + episode_bbox[3]) / 2
    assert abs(logo_center_y - 1740) <= 2
    assert abs(episode_center_y - 1410) <= 2
    assert episode_bbox[1] > style.canvas[1] - style.bottom_bar
    assert episode_bbox[3] < logo_bbox[1]
    assert img.getchannel("A").getextrema()[1] == 255


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


def test_long_complete_subtitle_wraps_without_horizontal_clipping(tmp_path: Path) -> None:
    style = load_style(STYLE)
    text = "고객이 원하는 것을 모르고 제품부터 만들면 정말 오랜 시간 방향을 잃고 헤매게 됩니다"

    (path,) = render.render_subtitle_pngs([[0.0, 4.0, text]], [], style, tmp_path)

    bbox = Image.open(path).convert("RGBA").getbbox()
    assert bbox is not None
    assert bbox[0] >= 36
    assert bbox[2] <= style.canvas[0] - 36
