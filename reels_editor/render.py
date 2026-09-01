"""EDL + 원본 → 릴스 mp4. 순수 함수(필터 문자열·레이아웃 계산)와
ffmpeg/Pillow 오케스트레이션(Task 5)을 분리한다.

이 환경 ffmpeg는 libass/drawtext가 없어 텍스트는 전부 Pillow PNG + overlay.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from reels_editor import captions, processes
from reels_editor.storyteller import format_speaker_label
from reels_editor.style import StylePreset
from reels_editor.timebase import US
from reels_editor.title_rules import normalize_title, wrap_title

# 자동자막(STT) 흔한 오인식 보정. 필요 시 확장.
DEFAULT_TEXT_FIXES = {
    "추준생": "취준생", "주중생": "취준생", "로션": "노션",
    "임플란서": "인플루언서", "바이러를": "바이럴을", "서법": "서버비",
}
_SUBTITLE_PUNCTUATION_TO_HIDE = str.maketrans("", "", ",.")
_VIDEOTOOLBOX_ENCODER = "h264_videotoolbox"
_SOFTWARE_ENCODER = "libx264"
_VIDEOTOOLBOX_SLOTS = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class VideoEncoder:
    name: str
    args: tuple[str, ...]

    @property
    def hardware_accelerated(self) -> bool:
        return self.name == _VIDEOTOOLBOX_ENCODER


def _software_encoder() -> VideoEncoder:
    return VideoEncoder(
        _SOFTWARE_ENCODER,
        (
            "-c:v", _SOFTWARE_ENCODER,
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-tag:v", "avc1",
        ),
    )


@lru_cache(maxsize=1)
def select_video_encoder() -> VideoEncoder:
    """Select the measured-fast default and keep VideoToolbox as an opt-in.

    On this app's 1080x1920 CPU-filtered graph, M4 Pro benchmarks favor
    ``libx264 -preset veryfast``. Set
    ``REELS_EDITOR_VIDEO_ENCODER=h264_videotoolbox`` to compare or use the
    hardware path on another Mac; an unavailable encoder falls back safely.
    """
    forced = os.environ.get("REELS_EDITOR_VIDEO_ENCODER", "").strip().lower()
    if forced != _VIDEOTOOLBOX_ENCODER:
        return _software_encoder()
    if sys.platform == "darwin" and shutil.which("ffmpeg"):
        result = processes.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and _VIDEOTOOLBOX_ENCODER in result.stdout:
            return VideoEncoder(
                _VIDEOTOOLBOX_ENCODER,
                (
                    "-c:v", _VIDEOTOOLBOX_ENCODER,
                    "-profile:v", "high",
                    "-b:v", "8M",
                    "-maxrate", "12M",
                    "-bufsize", "16M",
                    "-pix_fmt", "yuv420p",
                    "-tag:v", "avc1",
                    "-allow_sw", "0",
                    "-realtime", "0",
                ),
            )
    return _software_encoder()


def apply_text_fixes(text: str, fixes: dict[str, str]) -> str:
    for a, b in fixes.items():
        text = text.replace(a, b)
    return text.strip()


def timeline_items(ordered: list[dict], speed: float) -> list[list]:
    """각 세그먼트의 결과물 타임라인 위치(초). [[start_s, end_s, text], …]."""
    items: list[list] = []
    cur = 0.0
    for s in ordered:
        dur = (s["source_end_us"] - s["source_start_us"]) / US / speed
        items.append([round(cur, 3), round(cur + dur, 3), s["text"]])
        cur += dur
    return items


def group_captions(items: list[list], max_dur: float = 2.4,
                   max_chars: int = 20) -> list[list]:
    """파편 cue의 문장 완결성을 검사한 뒤 한 줄 의미 절로 나눈다.

    완결되지 않은 문장은 다음 cue와 먼저 합치며, 검사를 통과한 전체 문장만
    쉼표·연결어미를 기준으로 ``max_chars`` 안팎의 표시 자막으로 분할한다.
    """
    _ = max_dur
    groups = captions.group_complete_sentences(items)
    errors = captions.completeness_errors(groups)
    if errors:
        raise ValueError(
            "자막 완결성 검사 실패 — 다음 seg_id까지 포함해 문장과 큰따옴표를 "
            "완성해야 합니다:\n" + "\n".join(errors)
        )
    display_groups: list[list] = []
    for a, b, text in captions.split_display_phrases(groups, max_chars=max_chars):
        display_text = hide_subtitle_punctuation(str(text))
        if display_text:
            display_groups.append([a, b, display_text])
        elif display_groups:
            display_groups[-1][1] = b
    return display_groups


def hide_subtitle_punctuation(text: str) -> str:
    """Remove comma and period only from the final on-screen subtitle text."""
    return " ".join(text.translate(_SUBTITLE_PUNCTUATION_TO_HIDE).split())


def split_by_keywords(text: str, keywords: list[str]) -> list[tuple[str, bool]]:
    """텍스트를 (조각, 강조여부) 시퀀스로 분리. 먼저 매칭되는 키워드 우선."""
    for kw in keywords:
        if not kw:
            continue
        i = text.find(kw)
        if i < 0:
            continue
        head = split_by_keywords(text[:i], keywords) if text[:i] else []
        tail = split_by_keywords(text[i + len(kw):], keywords) if text[i + len(kw):] else []
        return head + [(kw, True)] + tail
    return [(text, False)]


def sparse_subtitle_highlights(groups: list[list], keywords: list[str]) -> list[list[str]]:
    """강조를 최대 3회로 제한하고 강조 자막 사이에 두 자막을 비운다."""
    plan: list[list[str]] = [[] for _group in groups]
    candidates = list(dict.fromkeys(keyword.strip() for keyword in keywords if keyword.strip()))
    if not candidates or not groups:
        return plan
    budget = min(3, max(1, (len(groups) + 5) // 6))
    used: set[str] = set()
    last_index = -3
    count = 0
    for index, (_start, _end, text) in enumerate(groups):
        if count >= budget or index - last_index < 3:
            continue
        matches = [keyword for keyword in candidates if keyword in str(text)]
        if not matches:
            continue
        keyword = next((item for item in matches if item not in used), matches[0])
        plan[index] = [keyword]
        used.add(keyword)
        last_index = index
        count += 1
    return plan


def _crop_expr(in_w: int, in_h: int, aspect_w: int, aspect_h: int) -> str:
    """중앙 크롭 영역을 숫자로 계산(식 안 쉼표는 필터 구분자로 오해되므로 금지)."""
    cw = min(in_w, int(round(in_h * aspect_w / aspect_h)))
    ch = min(in_h, int(round(in_w * aspect_h / aspect_w)))
    x = (in_w - cw) // 2
    y = (in_h - ch) // 2
    return f"crop={cw}:{ch}:{x}:{y}"


def _even_crop_size(value: float, limit: int) -> int:
    size = min(limit, max(2, int(round(value))))
    return size if size % 2 == 0 else size - 1


def _center_crop_box(in_w: int, in_h: int,
                     aspect_w: int, aspect_h: int) -> tuple[int, int, int, int]:
    crop_w = _even_crop_size(min(in_w, in_h * aspect_w / aspect_h), in_w)
    crop_h = _even_crop_size(min(in_h, in_w * aspect_h / aspect_w), in_h)
    return crop_w, crop_h, (in_w - crop_w) // 2, (in_h - crop_h) // 2


def video_crop_box(
    in_size: tuple[int, int],
    style: StylePreset,
) -> tuple[int, int, int, int]:
    """영상 중앙을 기준으로 고정 확대한 크롭 영역을 반환한다."""
    in_w, in_h = in_size
    video_w, video_h = style.video_area()
    frame_w, frame_h, _frame_x, _frame_y = _center_crop_box(
        in_w, in_h, video_w, video_h)

    zoom = max(style.video_zoom, 1.0)
    crop_w = _even_crop_size(frame_w / zoom, frame_w)
    crop_h = _even_crop_size(frame_h / zoom, frame_h)
    return crop_w, crop_h, (in_w - crop_w) // 2, (in_h - crop_h) // 2


def parse_cropdetect(lines: list[str]) -> tuple[int, int, int, int] | None:
    """ffmpeg cropdetect 로그에서 최빈 crop=w:h:x:y를 (w,h,x,y)로 반환."""
    found = re.findall(r"crop=(\d+):(\d+):(\d+):(\d+)", "\n".join(lines))
    if not found:
        return None
    w, h, x, y = Counter(found).most_common(1)[0][0]
    return int(w), int(h), int(x), int(y)


def detect_content_crop(video_path: Path, at_s: float,
                        dur: float = 2.0) -> tuple[int, int, int, int] | None:
    """원본의 레터/필러박스를 제외한 실제 콘텐츠 영역 탐지. 실패 시 None."""
    r = processes.run(
        ["ffmpeg", "-v", "info", "-ss", str(at_s), "-t", str(dur),
         "-i", str(video_path), "-vf", "cropdetect=24:2:0", "-f", "null", "-"],
        capture_output=True, text=True)
    return parse_cropdetect(r.stderr.splitlines())


def build_base_filter(ordered: list[dict], speed: float, style: StylePreset,
                      in_size: tuple[int, int],
                      content_crop: tuple[int, int, int, int] | None = None) -> str:
    """트림+배속+concat → (콘텐츠 크롭) → 영상영역 크롭·스케일 → 캔버스 pad."""
    vw, vh = style.video_area()
    cw, ch = style.canvas
    parts: list[str] = []
    n = len(ordered)
    src_w, src_h = in_size
    pre = ""
    if content_crop:
        c_w, c_h, c_x, c_y = content_crop
        pre = f"crop={c_w}:{c_h}:{c_x}:{c_y},"
        src_w, src_h = c_w, c_h
    for i, s in enumerate(ordered):
        a = s["source_start_us"] / US
        b = s["source_end_us"] / US
        # YouTube sources can carry different sample/pixel aspect ratios per
        # segment. Normalize before concat; equal width/height alone is not
        # enough for FFmpeg's concat filter.
        parts.append(f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed},setsar=1[v{i}];")
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,atempo={speed}[a{i}];")
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][a];"
    crop_w, crop_h, crop_x, crop_y = video_crop_box((src_w, src_h), style)
    vid = (f"[vc]{pre}crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={vw}:{vh},"
           f"pad={cw}:{ch}:0:{style.top_bar}:black[v]")
    return "".join(parts) + concat + vid


def build_overlay_filter(
    n_static: int,
    groups: list[list],
    *,
    base_label: str = "[0:v]",
    first_overlay_input: int = 1,
) -> tuple[str, str]:
    """오버레이 체인. 입력 1..n_static은 상시(타이틀·워터마크),
    이후 len(groups)개는 시간창 자막. (filter_complex, 마지막 라벨) 반환."""
    parts: list[str] = []
    prev = base_label
    idx = 0
    for i in range(n_static):
        out = f"[o{idx}]"
        parts.append(f"{prev}[{first_overlay_input + i}:v]overlay=0:0{out}")
        prev = out
        idx += 1
    for j, (a, b, _t) in enumerate(groups):
        out = f"[o{idx}]"
        parts.append(
            f"{prev}[{first_overlay_input + n_static + j}:v]"
            f"overlay=enable='between(t,{a:.3f},{b:.3f})'{out}"
        )
        prev = out
        idx += 1
    return ";".join(parts), prev


def _hex_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def _draw_highlighted_line(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                           keywords: list[str], font: ImageFont.FreeTypeFont,
                           base: tuple, highlight: tuple) -> None:
    """키워드 조각만 강조색으로, 좌→우 이어 그린다."""
    x, y = xy
    for part, hl in split_by_keywords(text, keywords):
        d.text((x, y), part, font=font, fill=highlight if hl else base)
        x += int(d.textlength(part, font=font))


def _editor_y_to_canvas(y: int, canvas_h: int) -> int:
    """중앙 원점 편집 좌표를 1080×1920 렌더 캔버스의 y 중심점으로 변환."""
    return round(canvas_h / 2 - y / 2)


def _ink_bbox(d: ImageDraw.ImageDraw, text: str,
              font: ImageFont.FreeTypeFont) -> tuple[int, int, int, int]:
    return d.textbbox((0, 0), text, font=font)


def _centered_text_origin(d: ImageDraw.ImageDraw, text: str,
                          font: ImageFont.FreeTypeFont, center: tuple[int, int]
                          ) -> tuple[float, float]:
    left, top, right, bottom = _ink_bbox(d, text, font)
    return center[0] - (left + right) / 2, center[1] - (top + bottom) / 2


def _fit_single_line_font(
    text: str,
    font_path: Path,
    max_size: int,
    max_width: int,
    d: ImageDraw.ImageDraw,
) -> ImageFont.FreeTypeFont:
    """Find the largest font that keeps one line inside the horizontal safe area."""
    low, high = 1, max(1, max_size)
    best = ImageFont.truetype(str(font_path), low)
    while low <= high:
        size = (low + high) // 2
        candidate = ImageFont.truetype(str(font_path), size)
        left, _top, right, _bottom = _ink_bbox(d, text, candidate)
        if right - left <= max_width:
            best = candidate
            low = size + 1
        else:
            high = size - 1
    return best


def _fit_title_font(
    lines: tuple[str, ...],
    font_path: Path,
    max_size: int,
    max_width: int,
    d: ImageDraw.ImageDraw,
) -> ImageFont.FreeTypeFont:
    """Find one font size that keeps every wrapped title line in the safe area."""
    return min(
        (_fit_single_line_font(line, font_path, max_size, max_width, d) for line in lines),
        key=lambda font: font.size,
    )


def render_title_png(
    title: str,
    keyword: str,
    style: StylePreset,
    out: Path,
    speaker_text: str = "",
    title_upper: str | None = None,
    title_lower: str | None = None,
) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    title = normalize_title(title)
    if title_upper is not None or title_lower is not None:
        upper = normalize_title(title_upper or "")
        lower = normalize_title(title_lower or "")
        lines = tuple(line for line in (upper, lower) if line) or (title,)
    else:
        try:
            lines = wrap_title(title)
        except ValueError:
            # Persisted pre-upgrade EDLs can contain shorter/longer titles. New model
            # output and manual edits are rejected by the shared validator upstream,
            # while legacy jobs must remain playable.
            lines = (title,)
    speaker_text = " ".join(speaker_text.split())
    safe_width = W - 120
    if len(lines) == 2:
        fonts = (
            _fit_single_line_font(lines[0], style.title_font, style.title_upper_size, safe_width, d),
            _fit_single_line_font(lines[1], style.title_font, style.title_size, safe_width, d),
        )
        colors = (_hex_rgba(style.title_upper_color), _hex_rgba(style.title_color))
    else:
        font = _fit_title_font(lines, style.title_font, style.title_size, safe_width, d)
        fonts = tuple(font for _line in lines)
        colors = tuple(_hex_rgba(style.title_color) for _line in lines)
    line_heights = []
    for line, font in zip(lines, fonts):
        _left, line_top, _right, line_bottom = _ink_bbox(d, line, font)
        line_heights.append(line_bottom - line_top)
    line_gap = style.title_line_gap if style.title_line_gap is not None else 12
    title_height = sum(line_heights) + line_gap * (len(lines) - 1)
    speaker_font = ImageFont.truetype(str(style.title_font), style.title_speaker_size)
    speaker_height = 0
    if speaker_text:
        _left, speaker_top, _right, speaker_bottom = _ink_bbox(d, speaker_text, speaker_font)
        speaker_height = speaker_bottom - speaker_top
    group_center_y = (
        style.top_bar / 2
        if style.title_y is None
        else _editor_y_to_canvas(style.title_y, H)
    )
    if speaker_text and style.title_anchor_y is not None:
        title_center_y = _editor_y_to_canvas(style.title_anchor_y, H)
    else:
        gap = style.title_speaker_gap if speaker_text else 0
        group_height = title_height + gap + speaker_height
        title_center_y = round(group_center_y - group_height / 2 + title_height / 2)
    if len(lines) == 2 and speaker_text and style.title_anchor_y is not None:
        lower_center_y = _editor_y_to_canvas(style.title_anchor_y, H)
        centers = (
            round(lower_center_y - line_heights[1] / 2 - line_gap - line_heights[0] / 2),
            lower_center_y,
        )
        title_center_y = round((centers[0] - line_heights[0] / 2 + centers[1] + line_heights[1] / 2) / 2)
    else:
        line_center_y = title_center_y - title_height / 2
        centers_list: list[int] = []
        for line_height in line_heights:
            centers_list.append(round(line_center_y + line_height / 2))
            line_center_y += line_height + line_gap
        centers = tuple(centers_list)
    for line, font, color, center_y in zip(lines, fonts, colors, centers):
        title_origin = _centered_text_origin(d, line, font, (W // 2, center_y))
        _draw_highlighted_line(
            d,
            (round(title_origin[0]), round(title_origin[1])),
            line,
            [keyword] if keyword else [],
            font,
            color,
            color,
        )
    if speaker_text:
        title_bottom = max(center + height / 2 for center, height in zip(centers, line_heights))
        speaker_center_y = round(
            title_bottom + style.title_speaker_gap + speaker_height / 2
        )
        d.text(
            _centered_text_origin(d, speaker_text, speaker_font, (W // 2, speaker_center_y)),
            speaker_text,
            font=speaker_font,
            fill=_hex_rgba(style.title_speaker_color),
        )
    img.save(out)
    return out


def render_watermark_png(
    style: StylePreset,
    out: Path,
    *,
    episode_number: int | None = None,
) -> Path:
    if episode_number is not None:
        style = style.for_episode(episode_number)
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if style.watermark_y is None:
        center_y = H - style.bottom_bar + style.bottom_bar // 2
    else:
        center_y = _editor_y_to_canvas(style.watermark_y, H)
    if style.watermark_image is not None:
        logo = Image.open(style.watermark_image).convert("RGBA")
        logo_width = style.watermark_width or logo.width
        logo_height = round(logo.height * logo_width / logo.width)
        logo = logo.resize((logo_width, logo_height), Image.Resampling.LANCZOS)
        if style.watermark_opacity < 255:
            alpha = logo.getchannel("A").point(
                lambda value: round(value * style.watermark_opacity / 255)
            )
            logo.putalpha(alpha)
        logo_x = round((W - logo_width) / 2)
        logo_y = round(center_y - logo_height / 2)
        img.alpha_composite(logo, (logo_x, logo_y))
        logo_alpha_bbox = logo.getchannel("A").getbbox()
        watermark_ink_top = (
            logo_y
            if logo_alpha_bbox is None
            else logo_y + logo_alpha_bbox[1]
        )
    else:
        font = ImageFont.truetype(str(style.watermark_font), style.watermark_size)
        watermark_origin = _centered_text_origin(
            d,
            style.watermark_text,
            font,
            (W // 2, center_y),
        )
        d.text(watermark_origin,
               style.watermark_text, font=font,
               fill=(255, 255, 255, style.watermark_opacity))
        _wl, watermark_top, _wr, _wb = _ink_bbox(d, style.watermark_text, font)
        watermark_ink_top = watermark_origin[1] + watermark_top
    if style.episode_text:
        episode_font = ImageFont.truetype(str(style.watermark_font), style.episode_size)
        _el, episode_top, _er, episode_bottom = _ink_bbox(
            d,
            style.episode_text,
            episode_font,
        )
        episode_height = episode_bottom - episode_top
        episode_center_y = (
            round(watermark_ink_top - style.episode_gap - episode_height / 2)
            if style.episode_y is None
            else _editor_y_to_canvas(style.episode_y, H)
        )
        d.text(
            _centered_text_origin(
                d,
                style.episode_text,
                episode_font,
                (W // 2, episode_center_y),
            ),
            style.episode_text,
            font=episode_font,
            fill=_hex_rgba(style.episode_color, style.episode_opacity),
        )
    img.save(out)
    return out


def render_subtitle_pngs(groups: list[list], keywords: list[str],
                         style: StylePreset, out_dir: Path) -> list[Path]:
    W, H = style.canvas
    out_dir.mkdir(parents=True, exist_ok=True)
    pad_x, pad_y = 24, 12
    paths: list[Path] = []
    highlight_plan = sparse_subtitle_highlights(groups, keywords)
    for i, (_a, _b, t) in enumerate(groups):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        font = ImageFont.truetype(str(style.sub_font), style.sub_size)
        if style.sub_y is None:
            _vw, vh = style.video_area()
            center_y = style.top_bar + int(vh * style.sub_y_frac) - style.sub_size // 2
        else:
            center_y = _editor_y_to_canvas(style.sub_y, H)
        left, top, right, bottom = _ink_bbox(d, t, font)
        origin_x, origin_y = _centered_text_origin(d, t, font, (W // 2, center_y))
        ink_box = (origin_x + left, origin_y + top,
                   origin_x + right, origin_y + bottom)
        d.rectangle((ink_box[0] - pad_x, ink_box[1] - pad_y,
                     ink_box[2] + pad_x, ink_box[3] + pad_y),
                    fill=(0, 0, 0, style.sub_box_alpha))
        _draw_highlighted_line(
            d,
            (round(origin_x), round(origin_y)),
            t,
            highlight_plan[i],
            font,
            _hex_rgba(style.sub_color, style.sub_opacity),
            _hex_rgba(style.sub_highlight, style.sub_opacity),
        )
        p = out_dir / f"s{i:03d}.png"
        img.save(p)
        paths.append(p)
    return paths


def _probe_size(video_path: Path) -> tuple[int, int]:
    out = processes.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
         str(video_path)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def verify_render_output(
    video_path: Path,
    expected_size: tuple[int, int],
    expected_duration_s: float,
) -> None:
    """Final gate for generated MP4s before exposing them as ready."""
    if not video_path.is_file() or video_path.stat().st_size == 0:
        raise RuntimeError("최종 영상 검수 실패: 출력 MP4가 비어 있음")
    width, height = _probe_size(video_path)
    if (width, height) != expected_size:
        raise RuntimeError(
            f"최종 영상 검수 실패: 해상도 {width}x{height}, 기대값 {expected_size[0]}x{expected_size[1]}"
        )
    duration = float(processes.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(video_path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip())
    if abs(duration - expected_duration_s) > 1.0:
        raise RuntimeError(
            f"최종 영상 검수 실패: 길이 {duration:.1f}초, 기대값 {expected_duration_s:.1f}초"
        )
    audio = processes.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type", "-of", "default=nw=1:nk=1",
         str(video_path)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    if audio != "audio":
        raise RuntimeError("최종 영상 검수 실패: 오디오 트랙이 없음")


def _ffmpeg(args: list[str]) -> None:
    r = processes.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                      capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패:\n{r.stderr}")


@dataclass(frozen=True)
class RenderAssets:
    base: Path
    wm_png: Path
    sub_pngs: list[Path]
    groups: list[list]
    work: Path
    keywords: list[str]
    source: Path | None = None
    base_filter: Path | None = None
    total_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": str(self.base),
            "wm_png": str(self.wm_png),
            "sub_pngs": [str(path) for path in self.sub_pngs],
            "groups": self.groups,
            "work": str(self.work),
            "keywords": self.keywords,
            "source": str(self.source) if self.source is not None else None,
            "base_filter": str(self.base_filter) if self.base_filter is not None else None,
            "total_s": self.total_s,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RenderAssets":
        return cls(
            base=Path(data["base"]),
            wm_png=Path(data["wm_png"]),
            sub_pngs=[Path(path) for path in data.get("sub_pngs", [])],
            groups=list(data.get("groups", [])),
            work=Path(data["work"]),
            keywords=[str(item) for item in data.get("keywords", [])],
            source=Path(data["source"]) if data.get("source") else None,
            base_filter=Path(data["base_filter"]) if data.get("base_filter") else None,
            total_s=float(data.get("total_s", 0.0)),
        )

    def write_manifest(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".part")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return path

    @classmethod
    def read_manifest(cls, path: Path) -> "RenderAssets":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))


def style_hash(style: StylePreset) -> str:
    data = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in asdict(style).items()
    }
    payload = json.dumps(data, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def variant_cache_key(
    *,
    storyline_id: str,
    title_text: str,
    subtitles_enabled: bool,
    style_hash_value: str,
    speaker_text: str = "",
    title_upper: str | None = None,
    title_lower: str | None = None,
) -> str:
    title_text = normalize_title(title_text)
    payload = json.dumps(
        {
            "storyline_id": storyline_id,
            "title_text": title_text,
            "title_upper": normalize_title(title_upper) if title_upper is not None else None,
            "title_lower": normalize_title(title_lower) if title_lower is not None else None,
            "speaker_text": speaker_text,
            "subtitles_enabled": subtitles_enabled,
            "style_hash": style_hash_value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def speaker_label(edl_doc: dict[str, Any]) -> str:
    return format_speaker_label(edl_doc.get("speaker"))


def parse_progress_line(line: str) -> float | None:
    if not line.startswith("out_time_us="):
        return None
    try:
        return int(line.split("=", 1)[1]) / 1_000_000
    except ValueError:
        return None


def _ffmpeg_progress(args: list[str], total_s: float,
                     cb: Callable[[float], None] | None) -> None:
    """-progress pipe:1 로 진행률을 cb(0.0~1.0)에 보고하며 실행.

    stdout(진행률)과 stderr를 동시에 비우지 않으면, ffmpeg가 stderr에 OS 파이프
    버퍼(약 64KB)를 채울 만큼 쓰는 순간 자식은 stderr 쓰기에서, 부모는 stdout
    읽기에서 서로 블록되는 교착 상태가 된다. stderr는 별도 스레드에서 동시에
    드레인한다.
    """
    if cb is None:
        _ffmpeg(args)
        return
    proc = processes.popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    assert proc.stderr is not None

    stderr_chunks: list[str] = []

    def _drain_stderr() -> None:
        for chunk in proc.stderr:  # type: ignore[union-attr]
            stderr_chunks.append(chunk)

    stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
    stderr_thread.start()

    try:
        for line in proc.stdout:
            t = parse_progress_line(line.strip())
            if t is not None and total_s > 0:
                cb(max(0.0, min(t / total_s, 1.0)))

        proc.wait()
        stderr_thread.join()
        if proc.returncode != 0:
            raise RuntimeError(f"ffmpeg 실패:\n{''.join(stderr_chunks)}")
    finally:
        registry = processes.current_registry()
        if registry is not None:
            registry.unregister(proc)


def _encode_video(
    args_before_encoder: list[str],
    args_after_encoder: list[str],
    *,
    total_s: float = 0.0,
    progress_cb: Callable[[float], None] | None = None,
) -> VideoEncoder:
    """Run one H.264 encode, serializing VideoToolbox and retrying in software."""
    selected = select_video_encoder()

    def run(encoder: VideoEncoder) -> None:
        _ffmpeg_progress(
            [
                *args_before_encoder,
                *encoder.args,
                "-movflags", "+faststart",
                *args_after_encoder,
            ],
            total_s,
            progress_cb,
        )

    if not selected.hardware_accelerated:
        run(selected)
        return selected
    with _VIDEOTOOLBOX_SLOTS:
        try:
            run(selected)
            return selected
        except RuntimeError:
            fallback = _software_encoder()
            run(fallback)
            return fallback


def render_base_and_assets(video_path: Path, segments: dict, edl_doc: dict,
                           style: StylePreset, work_dir: Path, speed: float,
                           progress_cb: Callable[[float], None] | None = None,
                           episode_number: int | None = None,
                           ) -> RenderAssets:
    from reels_editor import edl as edl_mod
    ordered = edl_mod.ordered_segments(edl_doc, segments)
    work_dir.mkdir(parents=True, exist_ok=True)
    # 레터박스를 제거한 후 전체 컷에 같은 중앙 130% 확대를 적용한다.
    source_size = _probe_size(video_path)
    content = detect_content_crop(video_path, ordered[0]["source_start_us"] / US)
    filt = build_base_filter(
        ordered,
        speed,
        style,
        source_size,
        content_crop=content,
    )
    fpath = work_dir / "base_filter.txt"
    fpath.write_text(filt)
    total_s = sum(s["source_end_us"] - s["source_start_us"]
                  for s in ordered) / US / speed
    wm_png = render_watermark_png(
        style,
        work_dir / "wm.png",
        episode_number=episode_number,
    )
    items = [[a, b, apply_text_fixes(t, DEFAULT_TEXT_FIXES)]
             for a, b, t in timeline_items(ordered, speed)]
    groups = group_captions(items)
    keywords = edl_doc.get("subtitle_keywords", [])
    sub_paths = render_subtitle_pngs(groups, keywords, style, work_dir / "subs")
    if progress_cb is not None:
        progress_cb(1.0)
    # Keep ``base`` populated for manifests created by older releases. New
    # manifests include the source + crop filter and render the final reel in
    # one pass instead of creating and re-encoding an intermediate MP4.
    return RenderAssets(
        video_path,
        wm_png,
        sub_paths,
        groups,
        work_dir,
        keywords,
        source=video_path,
        base_filter=fpath,
        total_s=total_s,
    )


def render_with_title(assets: RenderAssets, title_text: str, keyword: str,
                      style: StylePreset, out_path: Path,
                      *, speaker_text: str = "") -> Path:
    return render_overlay_variant(
        assets,
        title_text=title_text,
        keyword=keyword,
        style=style,
        out_path=out_path,
        subtitles_enabled=True,
        speaker_text=speaker_text,
    )


def render_overlay_variant(assets: RenderAssets, *, title_text: str, keyword: str,
                           style: StylePreset, out_path: Path,
                           subtitles_enabled: bool,
                           speaker_text: str = "",
                           title_upper: str | None = None,
                           title_lower: str | None = None) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title_png = render_title_png(
        title_text,
        keyword,
        style,
        assets.work / f"title-{out_path.stem}.png",
        speaker_text=speaker_text,
        title_upper=title_upper,
        title_lower=title_lower,
    )
    groups = assets.groups if subtitles_enabled else []
    sub_pngs = assets.sub_pngs if subtitles_enabled else []
    single_pass = (
        assets.source is not None
        and assets.base_filter is not None
        and assets.base_filter.is_file()
    )
    filt2, last = build_overlay_filter(
        n_static=2,
        groups=groups,
        base_label="[v]" if single_pass else "[0:v]",
    )
    video_input = assets.source if single_pass else assets.base
    args = ["-i", str(video_input), "-i", str(title_png), "-i", str(assets.wm_png)]
    for p in sub_pngs:
        args += ["-i", str(p)]
    tmp = out_path.with_name(f".{out_path.stem}.part{out_path.suffix}")
    if single_pass:
        base_filter = assets.base_filter.read_text(encoding="utf-8").rstrip(";\n ")
        full_filter = f"{base_filter};{filt2};{last}format=yuv420p[vout]"
        args += [
            "-filter_complex", full_filter,
            "-map", "[vout]",
            "-map", "[a]",
        ]
        audio_args = ["-c:a", "aac", "-b:a", "192k", str(tmp)]
    else:
        args += ["-filter_complex", filt2, "-map", last, "-map", "0:a"]
        audio_args = ["-c:a", "copy", str(tmp)]
    try:
        _encode_video(
            args,
            audio_args,
            total_s=assets.total_s,
        )
        os.replace(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out_path


def render_reel(video_path: Path, segments: dict, edl_doc: dict, style: StylePreset,
                out_path: Path, speed: float | None = None,
                work_dir: Path | None = None,
                episode_number: int | None = None) -> Path:
    speed = speed if speed is not None else style.speed
    work = work_dir or Path(tempfile.mkdtemp(prefix="reels_render_"))
    assets = render_base_and_assets(
        video_path,
        segments,
        edl_doc,
        style,
        work,
        speed,
        episode_number=episode_number,
    )
    title = edl_doc["title_candidates"][edl_doc.get("selected_title", 0)]
    return render_with_title(assets, title["text"], title.get("keyword", ""),
                             style, out_path,
                             speaker_text=speaker_label(edl_doc))
