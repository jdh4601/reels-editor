from dataclasses import replace
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageChops
import pytest

from reels_editor import render, thumbnail, speaker_focus


def test_cover_keeps_title_inside_center_grid_crop(style_preset):
    frame = Image.new("RGB", style_preset.canvas, (100, 150, 180))
    plain = thumbnail.compose_thumbnail(frame, "", replace(style_preset, watermark_image=None))
    cover = thumbnail.compose_thumbnail(frame, "", replace(style_preset, watermark_image=None),
                                        title_upper="1년 뒤 돈이 몰릴", title_lower="투자 트렌드 3가지")
    bbox = ImageChops.difference(plain, cover).getbbox()
    assert bbox is not None
    w, h = style_preset.canvas
    assert bbox[0] >= w * 0.07 and bbox[2] <= w * 0.93
    assert h * 0.5 < bbox[1] < bbox[3] < h * 0.82
    assert cover.getpixel((0, h - 1))[0] < cover.getpixel((0, 0))[0]
    changed = thumbnail.compose_thumbnail(frame, "", replace(style_preset, watermark_image=None),
                                          title_upper="첫 고객이 떠난", title_lower="진짜 이유")
    assert ImageChops.difference(cover, changed).getbbox() is not None


@pytest.mark.parametrize("single_pass", [True, False])
def test_real_thumbnail_uses_clean_frame_without_black_bars(tmp_path, style_preset, single_pass):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required")
    style = replace(style_preset, canvas=(360, 640), top_bar=180, bottom_bar=190)
    source = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=green:s=320x240:r=10:d=0.4",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=0.4",
        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source),
    ], check=True)
    ordered = [{"source_start_us": 0, "source_end_us": 400_000}]
    filt = render.build_base_filter(ordered, 1.0, style, (320, 240))
    fpath = tmp_path / "filter.txt"
    fpath.write_text(filt)
    base = source
    if not single_pass:
        base = tmp_path / "base.mp4"
        render._ffmpeg(["-i", str(source), "-filter_complex", filt,
                        "-map", "[v]", "-map", "[a]", str(base)])
    assets = render.RenderAssets(base, tmp_path / "unused.png", [], [], tmp_path, [],
                                source=source if single_pass else None,
                                base_filter=fpath if single_pass else None, total_s=0.4)
    path = thumbnail.render_thumbnail(assets, title_text="고객이 떠난 진짜 이유", style=style,
                                      out_path=tmp_path / "reel.jpg")
    with Image.open(path) as image:
        assert image.format == "JPEG" and image.size == style.canvas
        # Clean footage reaches the top edge; the reel's title bar is absent.
        red, green, blue = image.getpixel((10, 10))
        assert green > 90 and red < 10 and blue < 10
    assert not list(tmp_path.glob("cover-frame-*.png"))
    assert not (tmp_path / ".reel.part.jpg").exists()


def test_failed_thumbnail_preserves_previous_cover(tmp_path, style_preset, monkeypatch):
    out = tmp_path / "reel.jpg"
    out.write_bytes(b"previous cover")
    def fail(_args):
        raise RuntimeError("frame extraction failed")
    monkeypatch.setattr(render, "_ffmpeg", fail)
    assets = render.RenderAssets(tmp_path / "base.mp4", tmp_path / "wm.png", [], [], tmp_path, [])
    with pytest.raises(RuntimeError, match="frame extraction failed"):
        thumbnail.render_thumbnail(assets, title_text="새로운 제목", style=style_preset, out_path=out)
    assert out.read_bytes() == b"previous cover"


def test_portrait_crop_centers_off_center_face(style_preset):
    frame = Image.new("RGB", (1000, 600), "red")
    frame.paste("green", (650, 0, 1000, 600))
    face = speaker_focus.FaceSignal(x=0.85, width=0.1, mouth_open=0, y=0.4, height=0.2)
    cover = thumbnail.compose_thumbnail(frame, "", style_preset, face=face)
    # Center cropping would show the red background and cut away the subject.
    assert cover.getpixel((0, 0)) == (0, 128, 0)
    assert cover.getpixel((style_preset.canvas[0] - 1, 0)) == (0, 128, 0)


def test_cover_prefers_single_person_edl_window(tmp_path):
    import json
    fpath = tmp_path / "base_filter.txt"
    directory = tmp_path / "speaker-focus"
    directory.mkdir()
    plan = directory / "plan.json"
    plan.write_text(json.dumps({"windows": [
        {"start_s": 0, "end_s": 2, "face_counts": [2, 2, 2]},
        {"start_s": 3, "end_s": 4, "face_counts": [1, 1, 1]},
    ]}))
    assets = render.RenderAssets(tmp_path / "base.mp4", tmp_path / "wm.png", [], [], tmp_path, [],
                                base_filter=fpath)
    assert thumbnail._closeup_window(assets) == (3, 0.6)
    plan.write_text("invalid json")
    assert thumbnail._closeup_window(assets) is None


def test_thumbnail_metadata_uses_actual_episode_without_speaker(style_preset):
    assert thumbnail.metadata_label(style_preset.for_episode(14), "아이반 자오 (Notion CEO)") == "Episode 14"
    assert thumbnail.metadata_label(style_preset.for_episode(27), "다른 창업자 (다른 회사 CEO)") == "Episode 27"
    assert thumbnail.metadata_label(style_preset.for_episode(27), "직책 없는 창업자") == "Episode 27"


def test_thumbnail_orange_episode_sits_above_lowered_title_and_bottom_fades_to_black(style_preset):
    frame = Image.new("RGB", style_preset.canvas, (200, 200, 200))
    cover = thumbnail.compose_thumbnail(frame, "회사를 만드는 건 스포츠를 하는 것과 같다",
                                        style_preset.for_episode(14), speaker_text="아이반 자오 (Notion CEO)")
    w, h = style_preset.canvas
    orange = Image.new("L", cover.size)
    orange.putdata([255 if pixel == (240, 100, 0) else 0 for pixel in cover.get_flattened_data()])
    bbox = orange.getbbox()
    assert bbox is not None
    assert h * 0.65 < bbox[1] < bbox[3] < h * 0.73
    white = Image.new("L", cover.size)
    white.putdata([255 if pixel == (255, 255, 255) else 0 for pixel in cover.get_flattened_data()])
    title_bbox = white.crop((0, 0, w, round(h * 0.82))).getbbox()
    assert title_bbox is not None and bbox[3] < title_bbox[1]
    assert h * 0.71 < (title_bbox[1] + title_bbox[3]) / 2 < h * 0.82
    assert bbox[0] > w * 0.07 and bbox[2] < w * 0.93
    assert cover.getpixel((0, round(h * 0.70))) == (200, 200, 200)
    assert cover.getpixel((0, h - 1))[0] < 3
    assert cover.getpixel((0, round(h * 0.85)))[0] < 120
