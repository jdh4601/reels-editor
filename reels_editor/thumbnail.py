"""영상 장면 위에 제목, 에피소드 번호, D.one 로고를 합성한다."""
from __future__ import annotations

import os
import json
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from reels_editor import render, speaker_focus
from reels_editor.style import StylePreset, TITLE_ORANGE
from reels_editor.title_rules import editor_title_lines


def thumbnail_path(video: Path) -> Path:
    return video.with_suffix(".jpg")


def metadata_label(style: StylePreset, speaker_text: str) -> str:
    number = re.search(r"\d+", style.episode_text)
    if number is None:
        raise ValueError("썸네일에 표시할 에피소드 번호가 없습니다.")
    return f"Episode {int(number.group())}"


def compose_thumbnail(frame: Image.Image, title: str, style: StylePreset, *,
                      title_upper: str | None = None,
                      title_lower: str | None = None,
                      speaker_text: str = "",
                      face: speaker_focus.FaceSignal | None = None) -> Image.Image:
    """Keep the headline inside both the vertical cover and center grid crop."""
    width, height = style.canvas
    crop_width = min(frame.width, round(frame.height * width / height))
    crop_height = min(frame.height, round(frame.width * height / width))
    left = round((face.x if face else 0.5) * frame.width - crop_width / 2)
    top = round(face.y * frame.height - crop_height * 0.3) if face else (frame.height - crop_height) // 2
    left = max(0, min(frame.width - crop_width, left))
    top = max(0, min(frame.height - crop_height, top))
    image = frame.crop((left, top, left + crop_width, top + crop_height))
    image = image.convert("RGBA").resize(style.canvas, Image.Resampling.LANCZOS)
    offset_y = round(10 * height / 1920)
    shifted = Image.new("RGBA", style.canvas)
    if offset_y:
        shifted.paste(image.crop((0, 0, width, 1)).resize((width, offset_y)), (0, 0))
    shifted.paste(image, (0, offset_y))
    image = shifted
    gradient = Image.new("RGBA", (1, height))
    gradient.putdata([
        (0, 0, 0, round(255 * max(0, min(1, (y / height - 0.73) / 0.27)) ** 0.65))
        for y in range(height)
    ])
    image = Image.alpha_composite(image, gradient.resize(style.canvas))
    draw = ImageDraw.Draw(image)
    upper, lower = editor_title_lines(title)
    lines = [line.strip() for line in (
        title_upper if title_upper is not None else upper,
        title_lower if title_lower is not None else lower,
    ) if line.strip()]
    label = metadata_label(style, speaker_text)
    info_font = render._fit_single_line_font(
        label, style.title_font,
        max(10, round(width * 44 / 1080)), round(width * 0.86), draw,
    )
    info_bbox = draw.textbbox((0, 0), label, font=info_font, anchor="mt")
    info_height = info_bbox[3] - info_bbox[1]
    title_height = 0
    if lines:
        max_width = round(width * 0.86)
        size = max(12, round(width * 0.075))
        font = ImageFont.truetype(str(style.title_font), size)
        while size > 8 and any(draw.textlength(line, font=font) > max_width for line in lines):
            size -= 1
            font = ImageFont.truetype(str(style.title_font), size)
        line_height = round(size * 1.25)
        last_bbox = draw.textbbox((0, 0), lines[-1], font=font, anchor="mt")
        title_height = (len(lines) - 1) * line_height + last_bbox[3] - last_bbox[1]
    gap = round(height * 0.018) if lines else 0
    group_height = info_height + gap + title_height
    group_top = round(height * 0.73 + offset_y - 20 * height / 1920 - group_height / 2)
    draw.text((width // 2, group_top), label,
              font=info_font, anchor="mt", fill=TITLE_ORANGE)
    if lines:
        top = group_top + info_height + gap
        for i, line in enumerate(lines):
            draw.text((width // 2, top + i * line_height), line, font=font,
                      anchor="mt", fill="white", stroke_width=max(1, size // 40),
                      stroke_fill=(0, 0, 0, 100))
    if style.watermark_image is not None:
        with Image.open(style.watermark_image) as source_logo:
            logo = source_logo.convert("RGBA")
        logo_width = round(width * 0.18)
        logo = logo.resize((logo_width, max(1, round(logo.height * logo_width / logo.width))),
                           Image.Resampling.LANCZOS)
        image.alpha_composite(logo, ((width - logo.width) // 2, round(height * 0.84)))
    elif style.watermark_text:
        font = ImageFont.truetype(str(style.watermark_font), max(10, round(width * 0.045)))
        draw.text((width // 2, round(height * 0.84)), style.watermark_text,
                  font=font, anchor="mt", fill="white")
    return image.convert("RGB")


def _closeup_window(assets: render.RenderAssets) -> tuple[float, float] | None:
    """Choose a single-person shot from the already analyzed EDL windows."""
    if assets.base_filter is None:
        return None
    plan = assets.base_filter.parent / "speaker-focus" / "plan.json"
    try:
        windows = json.loads(plan.read_text(encoding="utf-8")).get("windows", [])
        for window in windows:
            counts = window.get("face_counts", [])
            start, end = float(window["start_s"]), float(window["end_s"])
            if counts and counts.count(1) / len(counts) >= 0.9 and end > start:
                return start, min(0.6, end - start)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


def render_thumbnail(assets: render.RenderAssets, *, title_text: str,
                     style: StylePreset, out_path: Path,
                     speaker_text: str = "",
                     title_upper: str | None = None,
                     title_lower: str | None = None) -> Path:
    """Prefer an analyzed close-up and center its face in a clean portrait crop."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_path = assets.work / f"cover-frame-{out_path.stem}.png"
    tmp = out_path.with_name(f".{out_path.stem}.part.jpg")
    vw, vh = style.video_area()
    frame_filter = f"crop={vw}:{vh}:0:{style.top_bar},setsar=1,thumbnail=12"
    try:
        window = _closeup_window(assets) if assets.source is not None else None
        if window is not None:
            start, duration = window
            args = ["-ss", str(start), "-i", str(assets.source), "-t", str(duration),
                    "-vf", f"trim=duration={duration},setsar=1,thumbnail=12"]
        elif assets.source is not None and assets.base_filter is not None and assets.base_filter.is_file():
            base_filter = render.reposition_video_filter(
                assets.base_filter.read_text(encoding="utf-8").rstrip(";\n "), style,
            )
            args = ["-i", str(assets.source), "-filter_complex",
                    f"{base_filter};[a]anullsink;[v]{frame_filter}[cover]",
                    "-map", "[cover]"]
        else:
            args = ["-i", str(assets.base), "-vf", frame_filter]
        render._ffmpeg([*args, "-frames:v", "1", "-an", str(frame_path)])
        face = None
        if speaker_focus.vision_available():
            try:
                faces = speaker_focus._detect_faces(frame_path)
                face = max(faces, key=lambda item: item.width * item.height, default=None)
            except (ImportError, OSError, RuntimeError, ValueError):
                pass
        with Image.open(frame_path) as frame:
            image = compose_thumbnail(frame, title_text, style,
                                      title_upper=title_upper, title_lower=title_lower,
                                      speaker_text=speaker_text, face=face)
        image.save(tmp, "JPEG", quality=95, subsampling=0)
        os.replace(tmp, out_path)
    finally:
        frame_path.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
    return out_path
