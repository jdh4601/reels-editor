from pathlib import Path

from PIL import Image, ImageChops

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
    assert (255, 255, 255, 255) in colors    # 2줄 제목의 작은 흰색 첫 줄

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
    assert white_bbox[3] < orange_bbox[1]
    assert white_bbox[3] - white_bbox[1] < orange_bbox[3] - orange_bbox[1]


def test_two_line_title_keeps_large_orange_second_line_anchored(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png(
        "남의 성격 따라 하다 낭비한 창업의 몇 년",
        "",
        style,
        tmp_path / "two-line-speaker.png",
        speaker_text="데이비드 센라",
    )
    img = Image.open(p).convert("RGBA")
    pixels = list(img.get_flattened_data())
    orange = img.getchannel("A").point(lambda _a: 0)
    white = img.getchannel("A").point(lambda _a: 0)
    orange.putdata([255 if pixel[:3] == (255, 122, 0) else 0 for pixel in pixels])
    white.putdata([255 if pixel[:3] == (255, 255, 255) else 0 for pixel in pixels])
    orange_bbox = orange.getbbox()
    upper_white_bbox = white.crop((0, 0, style.canvas[0], 368)).getbbox()
    speaker_white_bbox = white.crop((0, 368, style.canvas[0], style.canvas[1])).getbbox()

    assert orange_bbox is not None and upper_white_bbox is not None and speaker_white_bbox is not None
    assert abs((orange_bbox[1] + orange_bbox[3]) / 2 - 368) <= 2
    assert upper_white_bbox[3] < orange_bbox[1]
    assert orange_bbox[1] - upper_white_bbox[3] >= 20
    assert upper_white_bbox[3] - upper_white_bbox[1] < orange_bbox[3] - orange_bbox[1]


def test_title_png_uses_explicit_editor_line_boundary(tmp_path: Path) -> None:
    style = load_style(STYLE)
    automatic = render.render_title_png(
        "고객이 떠난 진짜 이유 기능보다 복잡한 첫 화면",
        "",
        style,
        tmp_path / "automatic.png",
    )
    explicit = render.render_title_png(
        "고객이 떠난 진짜 이유 기능보다 복잡한 첫 화면",
        "",
        style,
        tmp_path / "explicit.png",
        title_upper="고객이 떠난 진짜",
        title_lower="이유 기능보다 복잡한 첫 화면",
    )

    difference = ImageChops.difference(
        Image.open(automatic).convert("RGBA"),
        Image.open(explicit).convert("RGBA"),
    )
    assert difference.getbbox() is not None


def test_title_png_uses_one_safe_line_and_white_speaker_label(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png(
        "좋은 아이디어의 함정",
        "아이디어",
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
    assert abs((orange_bbox[1] + orange_bbox[3]) / 2 - 368) <= 2
    assert white_bbox[1] > orange_bbox[3]
    assert white_bbox[1] - orange_bbox[3] >= 38
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
    assert abs(logo_center_y - 1685) <= 2
    assert abs(episode_center_y - 1460) <= 2
    assert episode_bbox[1] > style.canvas[1] - style.bottom_bar
    assert episode_bbox[3] < logo_bbox[1]
    assert img.getchannel("A").getextrema()[1] == 255


def test_watermark_accepts_job_episode_number(tmp_path: Path) -> None:
    style = load_style(STYLE)
    default = Image.open(
        render.render_watermark_png(style, tmp_path / "episode-1.png")
    ).convert("RGBA")
    episode_37 = Image.open(
        render.render_watermark_png(
            style,
            tmp_path / "episode-37.png",
            episode_number=37,
        )
    ).convert("RGBA")

    assert ImageChops.difference(default, episode_37).getbbox() is not None


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


def test_subtitle_pngs_one_per_group_without_red_highlight(tmp_path: Path) -> None:
    style = load_style(STYLE)
    groups = [[0.0, 2.0, "일단 무조건 거부감을 가져요"], [2.0, 4.0, "보수적인 시장이고요"]]
    paths = render.render_subtitle_pngs(groups, ["거부감"], style, tmp_path)
    assert [p.name for p in paths] == ["s000.png", "s001.png"]
    img = Image.open(paths[0]).convert("RGBA")
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 59, 48, 255) not in colors
    assert (255, 255, 255, 255) in colors


def test_long_subtitle_is_forced_to_one_safe_line(tmp_path: Path) -> None:
    style = load_style(STYLE)
    text = "고객이 원하는 것을 모르고 제품부터 만들면 정말 오랜 시간 방향을 잃고 헤매게 됩니다"
    groups = render.group_captions([[0.0, 4.0, text]])

    paths = render.render_subtitle_pngs(groups, [], style, tmp_path)

    for path in paths:
        bbox = Image.open(path).convert("RGBA").getbbox()
        assert bbox is not None
        assert bbox[0] >= 36
        assert bbox[2] <= style.canvas[0] - 36
        assert bbox[3] - bbox[1] < 80


def test_subtitle_font_size_never_shrinks_for_longer_group(tmp_path: Path) -> None:
    style = load_style(STYLE)
    paths = render.render_subtitle_pngs([
        [0.0, 1.0, "같은높이"],
        [1.0, 2.0, "같은높이 같은높이 같은높이 같은높이"],
    ], [], style, tmp_path)

    heights = []
    for path in paths:
        bbox = Image.open(path).convert("RGBA").getbbox()
        assert bbox is not None
        heights.append(bbox[3] - bbox[1])
    assert heights[0] == heights[1]


def test_many_keywords_never_render_red_with_default_style(tmp_path: Path) -> None:
    style = load_style(STYLE)
    groups = [[float(i), float(i + 1), f"핵심 고객 문제 {i}"] for i in range(12)]

    paths = render.render_subtitle_pngs(groups, ["핵심", "고객", "문제"], style, tmp_path)

    red = (255, 59, 48, 255)
    for path in paths:
        colors = {color for _count, color in Image.open(path).convert("RGBA").getcolors(maxcolors=1_000_000)}
        assert red not in colors
