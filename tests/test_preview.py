"""프리뷰 합성: 캔버스 크기 / frame 없음 폴백 / 실제 렌더 코드 경로 재사용."""
import io
from pathlib import Path

import pytest
from PIL import Image

from reels_editor.preview import compose_preview
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


@pytest.fixture
def style_preset():
    return load_style(STYLE)


def test_compose_preview_returns_canvas_png(style_preset) -> None:
    png = compose_preview(None, "타이틀 텍스트", "타이틀", "자막 샘플입니다",
                          ["샘플"], style_preset)
    img = Image.open(io.BytesIO(png))
    assert img.size == tuple(style_preset.canvas)
    assert img.format == "PNG"


def test_compose_preview_empty_texts_still_works(style_preset) -> None:
    png = compose_preview(None, "", "", "", [], style_preset)
    assert Image.open(io.BytesIO(png)).size == tuple(style_preset.canvas)
