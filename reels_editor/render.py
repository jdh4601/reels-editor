"""EDL + 원본 → 릴스 mp4. 순수 함수(필터 문자열·레이아웃 계산)와
ffmpeg/Pillow 오케스트레이션(Task 5)을 분리한다.

이 환경 ffmpeg는 libass/drawtext가 없어 텍스트는 전부 Pillow PNG + overlay.
"""
from __future__ import annotations

import re
import subprocess
import tempfile
import threading
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

from PIL import Image, ImageDraw, ImageFont

from reels_editor import captions, processes
from reels_editor.capcut import US
from reels_editor.style import StylePreset

# 자동자막(STT) 흔한 오인식 보정. 필요 시 확장.
DEFAULT_TEXT_FIXES = {
    "추준생": "취준생", "주중생": "취준생", "로션": "노션",
    "임플란서": "인플루언서", "바이러를": "바이럴을", "서법": "서버비",
}
_SUBTITLE_PUNCTUATION_TO_HIDE = str.maketrans("", "", ",.")


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
    """파편 cue를 길이 제한보다 문장 완결성을 우선해 자막으로 묶는다.

    ``max_dur``와 ``max_chars``는 이전 API와의 호환을 위해 유지한다. 완결되지
    않은 문장은 이 제한을 넘어도 다음 cue와 합쳐 화면에서 중간에 끊지 않는다.
    """
    _ = max_dur, max_chars
    groups = captions.group_complete_sentences(items)
    errors = captions.completeness_errors(groups)
    if errors:
        raise ValueError(
            "자막 완결성 검사 실패 — 다음 seg_id까지 포함해 문장과 큰따옴표를 "
            "완성해야 합니다:\n" + "\n".join(errors)
        )
    display_groups: list[list] = []
    for a, b, text in groups:
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


def video_crop_box(in_size: tuple[int, int],
                   style: StylePreset) -> tuple[int, int, int, int]:
    """9:16 캔버스의 영상창에 맞춘 원본 중앙 크롭 영역."""
    in_w, in_h = in_size
    video_w, video_h = style.video_area()
    frame_w, frame_h, frame_x, frame_y = _center_crop_box(
        in_w, in_h, video_w, video_h)

    zoom = max(style.video_zoom, 1.0)
    crop_w = _even_crop_size(frame_w / zoom, frame_w)
    crop_h = _even_crop_size(frame_h / zoom, frame_h)
    crop_x = frame_x + (frame_w - crop_w) // 2
    crop_y = frame_y + (frame_h - crop_h) // 2
    return crop_w, crop_h, crop_x, crop_y


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
    for i, s in enumerate(ordered):
        a = s["source_start_us"] / US
        b = s["source_end_us"] / US
        parts.append(f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed}[v{i}];")
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,atempo={speed}[a{i}];")
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][a];"
    src_w, src_h = in_size
    pre = ""
    if content_crop:
        c_w, c_h, c_x, c_y = content_crop
        pre = f"crop={c_w}:{c_h}:{c_x}:{c_y},"
        src_w, src_h = c_w, c_h
    crop_w, crop_h, crop_x, crop_y = video_crop_box((src_w, src_h), style)
    vid = (f"[vc]{pre}crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={vw}:{vh},"
           f"pad={cw}:{ch}:0:{style.top_bar}:black[v]")
    return "".join(parts) + concat + vid


def build_overlay_filter(n_static: int, groups: list[list]) -> tuple[str, str]:
    """오버레이 체인. 입력 1..n_static은 상시(타이틀·워터마크),
    이후 len(groups)개는 시간창 자막. (filter_complex, 마지막 라벨) 반환."""
    parts: list[str] = []
    prev = "[0:v]"
    idx = 0
    for i in range(n_static):
        out = f"[o{idx}]"
        parts.append(f"{prev}[{i + 1}:v]overlay=0:0{out}")
        prev = out
        idx += 1
    for j, (a, b, _t) in enumerate(groups):
        out = f"[o{idx}]"
        parts.append(
            f"{prev}[{n_static + j + 1}:v]overlay=enable='between(t,{a:.3f},{b:.3f})'{out}")
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


def _wrap_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int,
                d: ImageDraw.ImageDraw) -> list[str]:
    """공백 단위 그리디 줄바꿈."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        if d.textlength(word, font=font) > max_w:
            if cur:
                lines.append(cur)
                cur = ""
            piece = ""
            for char in word:
                candidate_piece = piece + char
                if piece and d.textlength(candidate_piece, font=font) > max_w:
                    lines.append(piece)
                    piece = char
                else:
                    piece = candidate_piece
            cur = piece
            continue
        cand = f"{cur} {word}".strip()
        if cur and d.textlength(cand, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def _fit_wrapped_caption(
    text: str,
    font_path: Path,
    max_size: int,
    max_width: int,
    d: ImageDraw.ImageDraw,
    max_lines: int = 2,
) -> tuple[ImageFont.FreeTypeFont, list[str]]:
    """완전한 문장을 동시에 표시할 수 있는 가장 큰 1~2줄 폰트를 고른다."""
    low, high = 18, max(18, max_size)
    best_font = ImageFont.truetype(str(font_path), low)
    best_lines = _wrap_lines(text, best_font, max_width, d)
    while low <= high:
        size = (low + high) // 2
        candidate = ImageFont.truetype(str(font_path), size)
        lines = _wrap_lines(text, candidate, max_width, d)
        if len(lines) <= max_lines:
            best_font, best_lines = candidate, lines
            low = size + 1
        else:
            high = size - 1
    return best_font, best_lines


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


def render_title_png(
    title: str,
    keyword: str,
    style: StylePreset,
    out: Path,
    speaker_text: str = "",
) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    title = " ".join(title.split())
    speaker_text = " ".join(speaker_text.split())
    safe_width = W - 120
    font = _fit_single_line_font(
        title,
        style.title_font,
        style.title_size,
        safe_width,
        d,
    )
    title_left, title_top, title_right, title_bottom = _ink_bbox(d, title, font)
    title_height = title_bottom - title_top
    speaker_font = ImageFont.truetype(str(style.title_font), style.title_speaker_size)
    speaker_height = 0
    if speaker_text:
        _left, speaker_top, _right, speaker_bottom = _ink_bbox(d, speaker_text, speaker_font)
        speaker_height = speaker_bottom - speaker_top
    gap = style.title_speaker_gap if speaker_text else 0
    group_height = title_height + gap + speaker_height
    group_center_y = (
        style.top_bar / 2
        if style.title_y is None
        else _editor_y_to_canvas(style.title_y, H)
    )
    title_center_y = round(group_center_y - group_height / 2 + title_height / 2)
    title_origin = _centered_text_origin(d, title, font, (W // 2, title_center_y))
    _draw_highlighted_line(
        d,
        (round(title_origin[0]), round(title_origin[1])),
        title,
        [keyword] if keyword else [],
        font,
        _hex_rgba(style.title_color),
        _hex_rgba(style.title_highlight),
    )
    if speaker_text:
        speaker_center_y = round(
            group_center_y + group_height / 2 - speaker_height / 2
        )
        d.text(
            _centered_text_origin(d, speaker_text, speaker_font, (W // 2, speaker_center_y)),
            speaker_text,
            font=speaker_font,
            fill=_hex_rgba(style.title_speaker_color),
        )
    img.save(out)
    return out


def render_watermark_png(style: StylePreset, out: Path) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(style.watermark_font), style.watermark_size)
    if style.watermark_y is None:
        center_y = H - style.bottom_bar + style.bottom_bar // 2
    else:
        center_y = _editor_y_to_canvas(style.watermark_y, H)
    watermark_origin = _centered_text_origin(
        d,
        style.watermark_text,
        font,
        (W // 2, center_y),
    )
    d.text(watermark_origin,
           style.watermark_text, font=font,
           fill=(255, 255, 255, style.watermark_opacity))
    if style.episode_text:
        episode_font = ImageFont.truetype(str(style.watermark_font), style.episode_size)
        _wl, watermark_top, _wr, _wb = _ink_bbox(d, style.watermark_text, font)
        watermark_ink_top = watermark_origin[1] + watermark_top
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
    for i, (_a, _b, t) in enumerate(groups):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        font, lines = _fit_wrapped_caption(
            t,
            style.sub_font,
            style.sub_size,
            W - 120 - pad_x * 2,
            d,
        )
        if style.sub_y is None:
            _vw, vh = style.video_area()
            center_y = style.top_bar + int(vh * style.sub_y_frac) - style.sub_size // 2
        else:
            center_y = _editor_y_to_canvas(style.sub_y, H)
        metrics = [_ink_bbox(d, line, font) for line in lines]
        heights = [bottom - top for _left, top, _right, bottom in metrics]
        line_gap = max(4, round(font.size * 0.18))
        group_height = sum(heights) + line_gap * max(0, len(lines) - 1)
        cursor_y = center_y - group_height / 2
        origins: list[tuple[float, float]] = []
        ink_boxes: list[tuple[float, float, float, float]] = []
        for line, (left, top, right, bottom), height in zip(lines, metrics, heights):
            origin_x = W / 2 - (left + right) / 2
            origin_y = cursor_y - top
            origins.append((origin_x, origin_y))
            ink_boxes.append((origin_x + left, origin_y + top,
                              origin_x + right, origin_y + bottom))
            cursor_y += height + line_gap
        ink_box = (
            min(box[0] for box in ink_boxes),
            min(box[1] for box in ink_boxes),
            max(box[2] for box in ink_boxes),
            max(box[3] for box in ink_boxes),
        )
        d.rectangle((ink_box[0] - pad_x, ink_box[1] - pad_y,
                     ink_box[2] + pad_x, ink_box[3] + pad_y),
                    fill=(0, 0, 0, style.sub_box_alpha))
        for origin, line in zip(origins, lines):
            _draw_highlighted_line(
                d,
                (round(origin[0]), round(origin[1])),
                line,
                keywords,
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

    def to_dict(self) -> dict[str, Any]:
        return {
            "base": str(self.base),
            "wm_png": str(self.wm_png),
            "sub_pngs": [str(path) for path in self.sub_pngs],
            "groups": self.groups,
            "work": str(self.work),
            "keywords": self.keywords,
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
) -> str:
    payload = json.dumps(
        {
            "storyline_id": storyline_id,
            "title_text": title_text,
            "speaker_text": speaker_text,
            "subtitles_enabled": subtitles_enabled,
            "style_hash": style_hash_value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def speaker_label(edl_doc: dict[str, Any]) -> str:
    speaker = edl_doc.get("speaker")
    if isinstance(speaker, str):
        return " ".join(speaker.split())
    if not isinstance(speaker, dict):
        return ""
    name = " ".join(str(speaker.get("name") or "").split())
    role = " ".join(str(speaker.get("role") or "").split())
    if name and role:
        return f"{name} ({role})"
    return name or role


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


def render_base_and_assets(video_path: Path, segments: dict, edl_doc: dict,
                           style: StylePreset, work_dir: Path, speed: float,
                           progress_cb: Callable[[float], None] | None = None,
                           ) -> RenderAssets:
    from reels_editor import edl as edl_mod
    ordered = edl_mod.ordered_segments(edl_doc, segments)
    work_dir.mkdir(parents=True, exist_ok=True)
    # 콘텐츠 크롭은 첫 세그먼트 시점 기준(v0: 컷 전체가 같은 레이아웃 가정)
    content = detect_content_crop(video_path, ordered[0]["source_start_us"] / US)
    filt = build_base_filter(ordered, speed, style, _probe_size(video_path),
                             content_crop=content)
    fpath = work_dir / "base_filter.txt"
    fpath.write_text(filt)
    base = work_dir / "base.mp4"
    total_s = sum(s["source_end_us"] - s["source_start_us"]
                  for s in ordered) / US / speed
    _ffmpeg_progress(["-i", str(video_path), "-filter_complex_script", str(fpath),
                      "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                      "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                      str(base)], total_s, progress_cb)
    wm_png = render_watermark_png(style, work_dir / "wm.png")
    items = [[a, b, apply_text_fixes(t, DEFAULT_TEXT_FIXES)]
             for a, b, t in timeline_items(ordered, speed)]
    groups = group_captions(items)
    keywords = edl_doc.get("subtitle_keywords", [])
    sub_paths = render_subtitle_pngs(groups, keywords, style, work_dir / "subs")
    return RenderAssets(base, wm_png, sub_paths, groups, work_dir, keywords)


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
                           speaker_text: str = "") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title_png = render_title_png(
        title_text,
        keyword,
        style,
        assets.work / f"title-{out_path.stem}.png",
        speaker_text=speaker_text,
    )
    groups = assets.groups if subtitles_enabled else []
    sub_pngs = assets.sub_pngs if subtitles_enabled else []
    filt2, last = build_overlay_filter(n_static=2, groups=groups)
    args = ["-i", str(assets.base), "-i", str(title_png), "-i", str(assets.wm_png)]
    for p in sub_pngs:
        args += ["-i", str(p)]
    tmp = out_path.with_name(f".{out_path.stem}.part{out_path.suffix}")
    args += ["-filter_complex", filt2, "-map", last, "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "copy", str(tmp)]
    try:
        _ffmpeg(args)
        os.replace(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return out_path


def render_reel(video_path: Path, segments: dict, edl_doc: dict, style: StylePreset,
                out_path: Path, speed: float | None = None,
                work_dir: Path | None = None) -> Path:
    speed = speed if speed is not None else style.speed
    work = work_dir or Path(tempfile.mkdtemp(prefix="reels_render_"))
    assets = render_base_and_assets(video_path, segments, edl_doc, style, work, speed)
    title = edl_doc["title_candidates"][edl_doc.get("selected_title", 0)]
    return render_with_title(assets, title["text"], title.get("keyword", ""),
                             style, out_path,
                             speaker_text=speaker_label(edl_doc))
