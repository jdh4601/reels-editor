"""프리뷰 합성: 캔버스 크기 / frame 없음 폴백 / 실제 렌더 코드 경로 재사용."""
import io
from pathlib import Path

import pytest
from PIL import Image

from reels_editor.preview import compose_preview, extract_frame
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"

# style.py: canvas=(1080, 1920), top_bar=300, bottom_bar=380
# → video_area = (1080, 1240)
GREY_PLACEHOLDER = (60, 60, 60)
FRAME_COLOR = (10, 200, 30)


@pytest.fixture
def style_preset():
    return load_style(STYLE)


def _video_area_center_pixel(png: bytes, style_preset) -> tuple[int, int, int]:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    vw, vh = style_preset.video_area()
    x = vw // 2
    y = style_preset.top_bar + vh // 2
    return img.getpixel((x, y))


def _video_area_crop(png: bytes, style_preset) -> Image.Image:
    img = Image.open(io.BytesIO(png)).convert("RGB")
    vw, vh = style_preset.video_area()
    top = style_preset.top_bar
    return img.crop((0, top, vw, top + vh))


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
    """소스가 영상 영역보다 가로로 넓을 때: 세로 기준으로 맞추고 좌우를 크롭한다."""
    vw, vh = style_preset.video_area()
    # 목표 비율(vw/vh)보다 훨씬 넓은 소스 → 높이 기준 스케일, 좌우 크롭 발생
    frame_path = tmp_path / "wide_frame.png"
    Image.new("RGB", (vw * 3, vh), FRAME_COLOR).save(frame_path)

    png = compose_preview(frame_path, "", "", "", [], style_preset)
    img = Image.open(io.BytesIO(png))

    assert img.size == tuple(style_preset.canvas)
    assert img.format == "PNG"
    assert _video_area_center_pixel(png, style_preset) == FRAME_COLOR
    assert GREY_PLACEHOLDER not in _video_area_crop(png, style_preset).getdata()


def test_compose_preview_tall_frame_center_crops_top_bottom(
        style_preset, tmp_path) -> None:
    """소스가 영상 영역보다 세로로 길 때: 가로 기준으로 맞추고 상하를 크롭한다."""
    vw, vh = style_preset.video_area()
    # 목표 비율(vw/vh)보다 훨씬 좁고 긴 소스 → 너비 기준 스케일, 상하 크롭 발생
    frame_path = tmp_path / "tall_frame.png"
    Image.new("RGB", (vw, vh * 3), FRAME_COLOR).save(frame_path)

    png = compose_preview(frame_path, "", "", "", [], style_preset)
    img = Image.open(io.BytesIO(png))

    assert img.size == tuple(style_preset.canvas)
    assert img.format == "PNG"
    assert _video_area_center_pixel(png, style_preset) == FRAME_COLOR
    assert GREY_PLACEHOLDER not in _video_area_crop(png, style_preset).getdata()


def test_extract_frame_returns_none_for_invalid_input(tmp_path) -> None:
    missing = tmp_path / "does_not_exist.mp4"
    out = tmp_path / "out.png"
    assert extract_frame(missing, 0.0, out) is None
