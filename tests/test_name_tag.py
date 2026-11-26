import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from reels_editor import name_tag
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "reels_editor" / "resources" / "styles" / "default.yaml"
GROUNDED = {
    "name": "Eric Migicovsky",
    "name_ko": "에릭 미기코브스키",
    "company": "Pebble",
    "role": "창업자",
    "evidence": "Eric Migicovsky, founder of Pebble",
}


def _white_box(path: Path) -> tuple[int, int, int, int]:
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    assert bbox is not None
    return bbox


def _has_black_text(path: Path) -> bool:
    img = Image.open(path).convert("RGBA")
    return any(a == 255 and r < 60 and g < 60 and b < 60
               for _n, (r, g, b, a) in img.getcolors(maxcolors=1_000_000))


def test_default_style_uses_bundled_pretendard_for_name_tag() -> None:
    style = load_style(STYLE)
    assert style.name_tag_font.name.startswith("Pretendard-")
    assert style.name_tag_role_font.name.startswith("Pretendard-")
    assert (style.name_tag_font.parent / "Pretendard-OFL.txt").is_file()


def test_name_tag_png_has_white_box_with_black_two_line_text(tmp_path: Path) -> None:
    style = load_style(STYLE)
    two = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", "YC 파트너"), style, tmp_path / "two.png")
    one = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", ""), style, tmp_path / "one.png")

    left, top, right, bottom = _white_box(two)
    img = Image.open(two).convert("RGBA")
    assert img.size == (right - left, bottom - top)  # PNG is only the tag
    assert img.getpixel((2, 2)) == (255, 255, 255, 255)
    assert _has_black_text(two)
    assert Image.open(one).height < img.height


def test_name_tag_from_app_override_wins_over_engine_speaker() -> None:
    tag = name_tag.resolve_name_tag(
        {"name": "에릭 미기코브스키", "role": "YC 파트너"}, GROUNDED)
    assert tag == name_tag.NameTag("에릭 미기코브스키", "YC 파트너")


def test_name_tag_uses_korean_transliteration_and_grounded_role() -> None:
    assert name_tag.resolve_name_tag(None, GROUNDED) == name_tag.NameTag(
        "에릭 미기코브스키", "Pebble 창업자")


def test_name_tag_keeps_original_name_without_transliteration() -> None:
    speaker = {"name": "Eric Migicovsky"}
    assert name_tag.resolve_name_tag(None, speaker) == name_tag.NameTag("Eric Migicovsky", "")


def test_name_tag_omits_role_without_supporting_evidence() -> None:
    speaker = {**GROUNDED, "evidence": "unrelated quote"}
    assert name_tag.resolve_name_tag(None, speaker) == name_tag.NameTag("에릭 미기코브스키", "")


def test_name_tag_is_absent_without_a_known_name() -> None:
    assert name_tag.resolve_name_tag(None, {"name": ""}) is None
    assert name_tag.resolve_name_tag({"name": " ", "role": "CEO"}, GROUNDED) is None


def test_group_identity_becomes_single_line_tag() -> None:
    speaker = {
        "name": "Dad Gang",
        "company": "Dad Gang",
        "role": "창업자",
        "identity_scope": "group",
        "evidence": "the founders of Dad Gang",
    }
    assert name_tag.resolve_name_tag(None, speaker) == name_tag.NameTag("Dad Gang 공동 창업자", "")


@pytest.mark.parametrize(
    ("t", "visible", "fully_in"),
    [(1.9, False, False), (2.15, True, False), (2.5, True, True),
     (3.9, True, True), (4.1, True, False), (4.4, False, False)],
)
def test_name_tag_slides_in_at_two_seconds_and_out_after_two_seconds(
        t: float, visible: bool, fully_in: bool) -> None:
    style = load_style(STYLE)
    width = 400
    x = name_tag.name_tag_x(t, width, style)
    if not visible:
        assert x is None
        return
    assert x is not None
    assert (x == style.name_tag_x) is fully_in
    assert -width < x <= style.name_tag_x


def test_overlay_filter_matches_python_timing() -> None:
    style = load_style(STYLE)
    filt = name_tag.overlay_filter("[v0]", 4, "[v1]", style)
    assert filt.startswith("[v0][4:v]overlay=")
    assert "enable='between(t,2.000,4.300)'" in filt
    assert f"y={style.name_tag_y}" in filt


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_overlay_filter_shows_tag_only_in_its_window(tmp_path: Path) -> None:
    style = load_style(STYLE)
    tag = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", "YC 파트너"), style, tmp_path / "tag.png")
    w, h = style.canvas
    filt = name_tag.overlay_filter("[0:v]", 1, "[out]", style)
    frames = {}
    for t in (1.9, 2.5, 4.4):
        out = tmp_path / f"f{t}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=black:s={w}x{h}:d=5:r=30",
             "-i", str(tag), "-filter_complex", filt, "-map", "[out]",
             "-ss", str(t), "-frames:v", "1", str(out)],
            check=True,
        )
        crop = Image.open(out).convert("L").crop(
            (style.name_tag_x, style.name_tag_y, style.name_tag_x + 40, style.name_tag_y + 20))
        frames[t] = max(crop.getdata())
    assert frames[1.9] < 30
    assert frames[2.5] > 220
    assert frames[4.4] < 30


def test_role_only_edit_keeps_grounded_korean_name() -> None:
    tag = name_tag.resolve_name_tag({"name": "Eric Migicovsky", "role": "YC 파트너"}, GROUNDED)
    assert tag == name_tag.NameTag("에릭 미기코브스키", "YC 파트너")
