"""영상 장면 위에 제목, 에피소드 번호, D.one 로고를 합성한다."""
from __future__ import annotations

import os
import hashlib
import json
import re
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageStat

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
        max(10, round(width * 52 / 1080)), round(width * 0.86), draw,
    )
    info_bbox = draw.textbbox((0, 0), label, font=info_font, anchor="mt")
    info_height = info_bbox[3] - info_bbox[1]
    title_height = 0
    if lines:
        max_width = round(width * 0.86)
        size = max(12, round(width * 0.083))
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
                      anchor="mt", fill="white")
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
                return start, min(2.5, end - start)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return None


MIN_EYE_OPENNESS = 0.18


def open_eye_face(path: Path) -> speaker_focus.FaceSignal | None:
    """Reject blinks, uncertain landmarks, and group photos from cover candidates."""
    faces = speaker_focus._detect_faces(path)
    if len(faces) != 1:
        return None
    face = faces[0]
    return face if face.eye_open is not None and face.eye_open >= MIN_EYE_OPENNESS else None


def choose_cover_frame(paths: list[Path], *, require_open_eyes: bool = True) -> tuple[Path, speaker_focus.FaceSignal | None]:
    available = speaker_focus.vision_available()
    if require_open_eyes and not available:
        raise RuntimeError("눈 개폐 확인 기능을 사용할 수 없습니다. macOS Vision 설치를 확인하세요.")
    candidates = []
    for path in paths:
        face = None
        if available:
            try:
                face = open_eye_face(path)
            except (ImportError, OSError, RuntimeError, ValueError):
                continue
            if face is None and require_open_eyes:
                continue
        with Image.open(path) as frame:
            gray = frame.convert('L')
            if face is not None:
                w, h = gray.size
                gray = gray.crop((max(0, int((face.x - face.width / 2) * w)),
                                  max(0, int((face.y - face.height / 2) * h)),
                                  min(w, int((face.x + face.width / 2) * w)),
                                  min(h, int((face.y + face.height / 2) * h))))
            clarity = ImageStat.Stat(gray.resize((128, 128)).filter(ImageFilter.FIND_EDGES)).var[0]
        score = (min(face.eye_open, 0.4) + min(clarity, 1000) / 1000 * 0.03 - face.mouth_open * 0.01) if face else clarity
        candidates.append((score, path, face))
    if not candidates:
        raise RuntimeError("눈을 뜬 선명한 단독 장면을 찾지 못했습니다. 다른 장면이나 검색 사진으로 다시 시도하세요.")
    _, path, face = max(candidates, key=lambda item: item[0])
    return path, face


def render_thumbnail(assets: render.RenderAssets, *, title_text: str,
                     style: StylePreset, out_path: Path,
                     speaker_text: str = "",
                     title_upper: str | None = None,
                     title_lower: str | None = None,
                     frame_time_s: float | None = None,
                     require_open_eyes: bool = True) -> Path:
    """Prefer an analyzed close-up and center its face in a clean portrait crop."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frame_key = hashlib.sha256(str(out_path.resolve()).encode()).hexdigest()[:12]
    assets.work.mkdir(parents=True, exist_ok=True)
    samples = tempfile.TemporaryDirectory(prefix=f"cover-frame-{frame_key}-", dir=assets.work)
    sample_dir = Path(samples.name)
    frame_pattern = sample_dir / "frame-%03d.png"
    tmp = out_path.with_name(f".{out_path.stem}.part.jpg")
    vw, vh = style.video_area()
    sample_duration = max(1.0, assets.total_s - (frame_time_s or 0.0))
    sample_fps = min(4.0, 32 / sample_duration)
    frame_filter = f"crop={vw}:{vh}:0:{style.top_bar},setsar=1,fps={sample_fps}"
    try:
        window = _closeup_window(assets) if assets.source is not None else None
        if window is not None and frame_time_s is None:
            start, duration = window
            args = ["-ss", str(start), "-i", str(assets.source), "-t", str(duration),
                    "-vf", f"trim=duration={duration},setsar=1,fps=8"]
        elif assets.source is not None and assets.base_filter is not None and assets.base_filter.is_file():
            base_filter = render.reposition_video_filter(
                assets.base_filter.read_text(encoding="utf-8").rstrip(";\n "), style,
            )
            args = ["-i", str(assets.source), "-filter_complex",
                    f"{base_filter};[a]anullsink;[v]"
                    + (f"trim=start={frame_time_s},setpts=PTS-STARTPTS," if frame_time_s is not None else "")
                    + f"{frame_filter}[cover]",
                    "-map", "[cover]"]
        else:
            args = (["-ss", str(frame_time_s)] if frame_time_s is not None else []) + ["-i", str(assets.base), "-vf", frame_filter]
        render._ffmpeg([*args, "-frames:v", "32", "-an", str(frame_pattern)])
        def write_checked_cover(paths):
            remaining = list(paths)
            while remaining:
                frame_path, face = choose_cover_frame(remaining, require_open_eyes=require_open_eyes)
                with Image.open(frame_path) as frame:
                    image = compose_thumbnail(frame, title_text, style,
                        title_upper=title_upper, title_lower=title_lower,
                        speaker_text=speaker_text, face=face)
                image.save(tmp, "JPEG", quality=95, subsampling=0)
                if not require_open_eyes or open_eye_face(tmp) is not None:
                    os.replace(tmp, out_path)
                    return
                remaining.remove(frame_path)
            raise RuntimeError("최종 썸네일에서 눈을 뜬 얼굴을 확인하지 못했습니다.")

        paths = sorted(sample_dir.glob("frame-*.png"))
        try:
            write_checked_cover(paths)
        except RuntimeError:
            if frame_time_s is not None:
                raise
            # Try later footage on a denser sample grid before rejecting an automatic cover.
            for path in paths:
                path.unlink()
            later_s = max(0, assets.total_s * 0.55)
            later_fps = min(4.0, 32 / max(1.0, assets.total_s - later_s))
            later_filter = f"crop={vw}:{vh}:0:{style.top_bar},setsar=1,fps={later_fps}"
            if assets.source is not None and assets.base_filter is not None and assets.base_filter.is_file():
                base_filter = render.reposition_video_filter(assets.base_filter.read_text().rstrip(";\n "), style)
                retry_args = ["-i", str(assets.source), "-filter_complex",
                    f"{base_filter};[a]anullsink;[v]trim=start={later_s},setpts=PTS-STARTPTS,{later_filter}[cover]",
                    "-map", "[cover]"]
            else:
                retry_args = ["-ss", str(later_s), "-i", str(assets.base), "-vf", later_filter]
            render._ffmpeg([*retry_args, "-frames:v", "32", "-an", str(frame_pattern)])
            write_checked_cover(sorted(sample_dir.glob("frame-*.png")))
    finally:
        samples.cleanup()
        tmp.unlink(missing_ok=True)
    return out_path
