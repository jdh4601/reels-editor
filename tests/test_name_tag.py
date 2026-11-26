import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
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


def _has_color(img: Image.Image, color: tuple[int, int, int]) -> bool:
    return any(pixel == (*color, 255)
               for _n, pixel in img.getcolors(maxcolors=1_000_000))


def _style_with_tag(tmp_path: Path, **tag_keys: object) -> Path:
    raw = yaml.safe_load(STYLE.read_text(encoding="utf-8"))
    raw["font_dir"] = str((STYLE.parent / raw["font_dir"]).resolve())
    for section in ("watermark",):
        image = raw[section].get("image")
        if image:
            raw[section]["image"] = str((STYLE.parent / image).resolve())
    raw["name_tag"].update(tag_keys)
    path = tmp_path / "style.yaml"
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")
    return path


def test_default_style_uses_bundled_pretendard_for_name_tag() -> None:
    style = load_style(STYLE)
    assert style.name_tag_font.name.startswith("Pretendard-")
    assert style.name_tag_role_font.name.startswith("Pretendard-")
    assert (style.name_tag_font.parent / "Pretendard-OFL.txt").is_file()


def test_default_name_tag_is_black_with_white_text_from_the_first_frame() -> None:
    style = load_style(STYLE)
    assert style.name_tag_box_color == "#000000"
    assert style.name_tag_text_color == "#FFFFFF"
    assert style.name_tag_start_s == 0.0


def test_name_tag_defaults_apply_when_the_style_omits_the_keys(tmp_path: Path) -> None:
    path = _style_with_tag(tmp_path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key in ("box_color", "text_color", "start_s"):
        raw["name_tag"].pop(key, None)
    path.write_text(yaml.safe_dump(raw, allow_unicode=True), encoding="utf-8")

    style = load_style(path)

    assert style.name_tag_box_color == "#000000"
    assert style.name_tag_text_color == "#FFFFFF"
    assert style.name_tag_start_s == 0.0


def test_style_parses_name_tag_colors(tmp_path: Path) -> None:
    style = load_style(_style_with_tag(tmp_path, box_color="#112233", text_color="#aabbcc"))
    assert style.name_tag_box_color == "#112233"
    assert style.name_tag_text_color == "#AABBCC"


@pytest.mark.parametrize("key", ["box_color", "text_color"])
@pytest.mark.parametrize("value", ["black", "#FFF", "000000", "#GGGGGG"])
def test_style_rejects_name_tag_color_that_is_not_hex(
        tmp_path: Path, key: str, value: str) -> None:
    with pytest.raises(ValueError, match=f"name_tag.{key}"):
        load_style(_style_with_tag(tmp_path, **{key: value}))


def test_name_tag_png_applies_style_colors_to_box_and_both_lines(tmp_path: Path) -> None:
    style = load_style(_style_with_tag(tmp_path, box_color="#102030", text_color="#F0E0D0"))
    two = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", "YC 파트너"), style, tmp_path / "two.png")
    one = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", ""), style, tmp_path / "one.png")

    img = Image.open(two).convert("RGBA")
    name_bottom = Image.open(one).height - style.name_tag_pad_y
    assert img.getchannel("A").getbbox() == (0, 0, *img.size)  # PNG is only the tag
    assert img.getpixel((2, 2)) == (0x10, 0x20, 0x30, 255)
    text = (0xF0, 0xE0, 0xD0)
    assert _has_color(img.crop((0, 0, img.width, name_bottom)), text)
    assert _has_color(img.crop((0, name_bottom, img.width, img.height)), text)
    assert Image.open(one).height < img.height


def test_default_name_tag_png_is_white_text_on_black(tmp_path: Path) -> None:
    path = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", "YC 파트너"), load_style(STYLE), tmp_path / "tag.png")
    img = Image.open(path).convert("RGBA")
    assert img.getpixel((2, 2)) == (0, 0, 0, 255)
    assert _has_color(img, (255, 255, 255))


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
    [(0.15, True, False), (0.3, True, True), (1.9, True, True),
     (2.15, True, False), (2.6, False, False)],
)
def test_name_tag_slides_in_at_the_start_and_out_after_two_seconds(
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


def test_name_tag_starts_off_screen_on_the_first_frame() -> None:
    assert name_tag.name_tag_x(0.0, 400, load_style(STYLE)) == -400


def test_overlay_filter_matches_python_timing() -> None:
    style = load_style(STYLE)
    filt = name_tag.overlay_filter("[v0]", 4, "[v1]", style)
    assert filt.startswith("[v0][4:v]overlay=")
    assert "enable='between(t,0.000,2.300)'" in filt
    assert f"y={style.name_tag_y}" in filt


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_overlay_filter_shows_tag_only_in_its_window(tmp_path: Path) -> None:
    style = load_style(STYLE)
    tag = name_tag.render_name_tag_png(
        name_tag.NameTag("에릭 미기코브스키", "YC 파트너"), style, tmp_path / "tag.png")
    w, h = style.canvas
    filt = name_tag.overlay_filter("[0:v]", 1, "[out]", style)
    frames = {}
    for t in (0.0, 0.3, 1.9, 2.6):
        out = tmp_path / f"f{t}.png"
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-f", "lavfi", "-i", f"color=gray:s={w}x{h}:d=5:r=30",
             "-i", str(tag), "-filter_complex", filt, "-map", "[out]",
             "-ss", str(t), "-frames:v", "1", str(out)],
            check=True,
        )
        # Padding area of the box: no text reaches it.
        crop = Image.open(out).convert("L").crop(
            (style.name_tag_x, style.name_tag_y, style.name_tag_x + 20, style.name_tag_y + 10))
        frames[t] = max(crop.getdata())
    assert frames[0.0] > 100
    assert frames[0.3] < 30
    assert frames[1.9] < 30
    assert frames[2.6] > 100


def test_role_only_edit_keeps_grounded_korean_name() -> None:
    tag = name_tag.resolve_name_tag({"name": "Eric Migicovsky", "role": "YC 파트너"}, GROUNDED)
    assert tag == name_tag.NameTag("에릭 미기코브스키", "YC 파트너")
