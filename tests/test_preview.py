"""프리뷰 합성: 캔버스 크기 / frame 없음 폴백 / 실제 렌더 코드 경로 재사용."""
import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from reels_editor.preview import compose_preview, extract_frame
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"

# style.py: canvas=(1080, 1920), top_bar=300, bottom_bar=380
# → video_area = (1080, 1240)
GREY_PLACEHOLDER = (60, 60, 60)

# 4분할 소스에 쓰는 사분면 색상. 서로 다른 색이라 오프셋이 틀린 크롭은
# 엉뚱한 사분면 색을 샘플링하게 되어 즉시 드러난다.
QUADRANT_COLORS = {
    "tl": (220, 40, 40),
    "tr": (40, 180, 220),
    "bl": (230, 200, 40),
    "br": (90, 200, 90),
}
# 사분면 경계선에서 충분히 떨어진 위치만 샘플링해 resize 보간(bicubic)이
# 만드는 경계 근처 blend 픽셀의 영향을 피한다.
CORNER_MARGIN = 100


@pytest.fixture
def style_preset():
    return load_style(STYLE)


def _video_area_crop(png: bytes, style_preset) -> Image.Image:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    vw, vh = style_preset.video_area()
    top = style_preset.top_bar
    return img.crop((0, top, vw, top + vh))


def _quadrant_frame(path: Path, sw: int, sh: int, mid_x: int, mid_y: int) -> None:
    """(0,0)-(mid_x,mid_y) 기준으로 4분할된 단색 사분면 이미지를 만든다."""
    img = Image.new("RGB", (sw, sh))
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, mid_x - 1, mid_y - 1), fill=QUADRANT_COLORS["tl"])
    draw.rectangle((mid_x, 0, sw - 1, mid_y - 1), fill=QUADRANT_COLORS["tr"])
    draw.rectangle((0, mid_y, mid_x - 1, sh - 1), fill=QUADRANT_COLORS["bl"])
    draw.rectangle((mid_x, mid_y, sw - 1, sh - 1), fill=QUADRANT_COLORS["br"])
    img.save(path)


def _aspect_fill(vw: int, vh: int, sw: int, sh: int) -> tuple[float, int, int]:
    """compose_preview의 aspect-fill 수식을 테스트 쪽에서 독립적으로 재계산한다:
    (vw/vh 중 더 큰 배율로 리사이즈) → (중앙 크롭 오프셋). 반환값: ratio, crop_x, crop_y.
    """
    ratio = max(vw / sw, vh / sh)
    resized_w, resized_h = round(sw * ratio), round(sh * ratio)
    crop_x, crop_y = (resized_w - vw) // 2, (resized_h - vh) // 2
    return ratio, crop_x, crop_y


def _expected_quadrant_color(ox: int, oy: int, ratio: float, crop_x: int, crop_y: int,
                             mid_x: int, mid_y: int) -> tuple[int, int, int]:
    """비디오 영역 내 출력 좌표(ox, oy)가 원본 소스의 어느 사분면에서 왔는지 역산한다."""
    sx, sy = (ox + crop_x) / ratio, (oy + crop_y) / ratio
    key = ("t" if sy < mid_y else "b") + ("l" if sx < mid_x else "r")
    return QUADRANT_COLORS[key]


def _assert_aspect_fill_center_crop(style_preset, tmp_path: Path, *, sw: int, sh: int,
                                    name: str) -> None:
    vw, vh = style_preset.video_area()
    mid_x, mid_y = sw // 2, sh // 2
    ratio, crop_x, crop_y = _aspect_fill(vw, vh, sw, sh)
    # 소스 크기가 목표 치수의 정배수면 ratio가 1.0이 되어 스케일 연산(round(x*ratio))이
    # 항등 함수가 돼버린다 — 실제로 스케일이 일어나는지 항상 확인한다.
    assert ratio != 1.0, "source size must not make ratio exactly 1.0"

    frame_path = tmp_path / f"{name}.png"
    _quadrant_frame(frame_path, sw, sh, mid_x, mid_y)

    png = compose_preview(frame_path, "", "", "", [], style_preset)
    img = Image.open(io.BytesIO(png)).convert("RGB")

    assert img.size == tuple(style_preset.canvas)
    assert Image.open(io.BytesIO(png)).format == "PNG"

    for ox, oy in (
        (CORNER_MARGIN, CORNER_MARGIN),
        (vw - CORNER_MARGIN, CORNER_MARGIN),
        (CORNER_MARGIN, vh - CORNER_MARGIN),
        (vw - CORNER_MARGIN, vh - CORNER_MARGIN),
    ):
        expected = _expected_quadrant_color(ox, oy, ratio, crop_x, crop_y, mid_x, mid_y)
        actual = img.getpixel((ox, style_preset.top_bar + oy))
        assert actual == expected, (
            f"({ox},{oy}) 기대 {expected}, 실제 {actual} "
            f"(ratio={ratio:.6f}, crop=({crop_x},{crop_y}))"
        )

    crop_colors = {c for _n, c in
                   _video_area_crop(png, style_preset).getcolors(maxcolors=1_000_000)}
    assert GREY_PLACEHOLDER not in crop_colors


def test_compose_preview_returns_canvas_png(style_preset) -> None:
    png = compose_preview(None, "타이틀 텍스트", "타이틀", "자막 샘플입니다",
                          ["샘플"], style_preset)
    img = Image.open(io.BytesIO(png))
    assert img.size == tuple(style_preset.canvas)
    assert img.format == "PNG"


def test_compose_preview_empty_texts_still_works(style_preset) -> None:
    png = compose_preview(None, "", "", "", [], style_preset)
    assert Image.open(io.BytesIO(png)).size == tuple(style_preset.canvas)


def test_compose_preview_wide_frame_center_crops_left_right(
        style_preset, tmp_path) -> None:
    """소스가 목표 비율보다 가로로 넓을 때: 세로 기준으로 스케일하고 좌우를 크롭한다.

    sw=1600, sh=1400은 vw(1080)/vh(1240)의 정배수가 아니므로 ratio가 1.0이 되지
    않는다 (실측 ratio ≈ 0.885714, 높이 기준). 4분면 소스로 크롭 오프셋이 어긋나면
    코너 샘플이 엉뚱한 색을 반환해 실패한다.
    """
    _assert_aspect_fill_center_crop(style_preset, tmp_path, sw=1600, sh=1400,
                                    name="wide_frame")


def test_compose_preview_tall_frame_center_crops_top_bottom(
        style_preset, tmp_path) -> None:
    """소스가 목표 비율보다 세로로 길 때: 가로 기준으로 스케일하고 상하를 크롭한다.

    sw=1400, sh=2000은 vw(1080)/vh(1240)의 정배수가 아니므로 ratio가 1.0이 되지
    않는다 (실측 ratio ≈ 0.771429, 너비 기준). 4분면 소스로 크롭 오프셋이 어긋나면
    코너 샘플이 엉뚱한 색을 반환해 실패한다.
    """
    _assert_aspect_fill_center_crop(style_preset, tmp_path, sw=1400, sh=2000,
                                    name="tall_frame")


def test_extract_frame_returns_none_for_invalid_input(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.mp4"
    out = tmp_path / "out.png"
    assert extract_frame(missing, 0.0, out) is None
