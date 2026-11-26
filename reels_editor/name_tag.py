"""Speaker name tag: a white box with the Korean name and role that slides in
from the left two seconds into the reel and leaves two seconds later.

The tag only shows identity that is already grounded (``speaker`` in the EDL)
or that a person typed in the app (``speaker_override``). It never invents a
name, transliteration or role.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from reels_editor.storyteller import format_speaker_label, normalize_speaker_data
from reels_editor.style import StylePreset

_WHITE = (255, 255, 255, 255)
_BLACK = (0, 0, 0, 255)


@dataclass(frozen=True)
class NameTag:
    name: str
    role: str = ""

    def cache_text(self) -> str:
        return f"{self.name}\n{self.role}"


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def resolve_name_tag(speaker_override: dict[str, Any] | None, speaker: Any) -> NameTag | None:
    """Pick the tag text: the app's edited values first, then the grounded speaker."""
    normalized = normalize_speaker_data(speaker)
    transliterated = normalized.get("name_ko", "")
    if speaker_override is not None:
        name = _clean(speaker_override.get("name"))
        if not name:
            return None
        # An edit that only changed the role keeps the engine's original name;
        # show its grounded Korean form instead of the source spelling.
        if transliterated and name == normalized["name"]:
            name = transliterated
        return NameTag(name, _clean(speaker_override.get("role")))
    name = normalized["name"]
    if not name:
        return None
    label = format_speaker_label(speaker)
    prefix = f"{name} ("
    if label.startswith(prefix) and label.endswith(")"):
        role = label[len(prefix):-1]
    elif label != name:
        # A group identity ("Dad Gang 공동 창업자") has no individual name line.
        return NameTag(label, "")
    else:
        role = ""
    return NameTag(transliterated or name, role)


def render_name_tag_png(tag: NameTag, style: StylePreset, out_path: Path) -> Path:
    """Render only the tag box; ``overlay_filter`` positions and animates it."""
    name_font = ImageFont.truetype(str(style.name_tag_font), style.name_tag_size)
    role_font = ImageFont.truetype(str(style.name_tag_role_font), style.name_tag_role_size)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines = [(tag.name, name_font)] + ([(tag.role, role_font)] if tag.role else [])
    boxes = [probe.textbbox((0, 0), text, font=font) for text, font in lines]
    pad_x, pad_y, gap = style.name_tag_pad_x, style.name_tag_pad_y, style.name_tag_line_gap
    width = max(right - left for left, _t, right, _b in boxes) + 2 * pad_x
    height = sum(bottom - top for _l, top, _r, bottom in boxes) + gap * (len(lines) - 1) + 2 * pad_y
    img = Image.new("RGBA", (width, height), _WHITE)
    draw = ImageDraw.Draw(img)
    y = pad_y
    for (text, font), (left, top, _right, bottom) in zip(lines, boxes):
        draw.text((pad_x - left, y - top), text, font=font, fill=_BLACK)
        y += bottom - top + gap
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def _timing(style: StylePreset) -> tuple[float, float, float]:
    start = style.name_tag_start_s
    return start, start + style.name_tag_hold_s, style.name_tag_slide_s


def name_tag_x(t: float, width: int, style: StylePreset) -> float | None:
    """Left edge of the tag at time ``t``; ``None`` while it is hidden.

    Mirrors ``overlay_filter`` so timing can be tested without ffmpeg.
    """
    start, leave, slide = _timing(style)
    target = style.name_tag_x
    if t < start or t > leave + slide:
        return None
    if t < start + slide:
        progress = (t - start) / slide
        return -width + (target + width) * (1 - (1 - progress) ** 2)
    if t < leave:
        return float(target)
    progress = (t - leave) / slide
    return target - (target + width) * progress ** 2


def overlay_filter(base_label: str, input_index: int, out_label: str, style: StylePreset) -> str:
    start, leave, slide = _timing(style)
    target = style.name_tag_x
    x = (
        f"if(lt(t,{start + slide:.3f}),"
        f"-w+({target}+w)*(1-pow(1-(t-{start:.3f})/{slide:.3f},2)),"
        f"if(lt(t,{leave:.3f}),{target},"
        f"{target}-({target}+w)*pow((t-{leave:.3f})/{slide:.3f},2)))"
    )
    return (
        f"{base_label}[{input_index}:v]overlay=x='{x}':y={style.name_tag_y}:eval=frame:"
        f"enable='between(t,{start:.3f},{leave + slide:.3f})'{out_label}"
    )
