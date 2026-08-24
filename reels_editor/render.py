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

from reels_editor import processes
from reels_editor.capcut import US
from reels_editor.style import StylePreset

# 자동자막(STT) 흔한 오인식 보정. 필요 시 확장.
DEFAULT_TEXT_FIXES = {
    "추준생": "취준생", "주중생": "취준생", "로션": "노션",
    "임플란서": "인플루언서", "바이러를": "바이럴을", "서법": "서버비",
}


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
    """파편 자막을 읽기 좋은 덩어리로 병합. 빈 텍스트는 앞 그룹 시간에 흡수."""
    groups: list[list] = []
    buf: list | None = None
    expanded: list[list] = []
    for a, b, t in items:
        chunks = _caption_chunks(str(t), max_chars)
        if len(chunks) <= 1:
            expanded.append([a, b, t])
            continue
        weights = [max(1, len(chunk.replace(" ", ""))) for chunk in chunks]
        total_weight = sum(weights)
        cursor = float(a)
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            end = float(b) if index == len(chunks) - 1 else cursor + (float(b) - float(a)) * weight / total_weight
            expanded.append([round(cursor, 3), round(end, 3), chunk])
            cursor = end

    for a, b, t in expanded:
        if not t:
            if buf:
                buf[1] = b
            continue
        if buf and (b - buf[0] <= max_dur) and (len(buf[2] + " " + t) <= max_chars):
            buf[1] = b
            buf[2] = (buf[2] + " " + t).strip()
        else:
            if buf:
                groups.append(buf)
            buf = [a, b, t]
    if buf:
        groups.append(buf)
    return groups


def _caption_chunks(text: str, max_chars: int) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized or len(normalized) <= max_chars:
        return [normalized]
    words = normalized.split(" ")
    chunks: list[str] = []
    current = ""
    for word in words:
        pieces = [word[i:i + max_chars] for i in range(0, len(word), max_chars)] or [""]
        for piece in pieces:
            candidate = f"{current} {piece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = piece
            else:
                current = candidate
    if current:
        chunks.append(current)
    return chunks


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
        cand = f"{cur} {word}".strip()
        if cur and d.textlength(cand, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


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


def _split_title_lines(title: str, top_font: ImageFont.FreeTypeFont,
                       bottom_font: ImageFont.FreeTypeFont,
                       d: ImageDraw.ImageDraw, max_w: int) -> tuple[str, str]:
    """서로 다른 글자 크기를 고려해 제목을 폭이 균형 잡힌 두 줄로 나눈다."""
    explicit = [line.strip() for line in title.splitlines() if line.strip()]
    if len(explicit) >= 2:
        return explicit[0], " ".join(explicit[1:])

    words = title.split()
    if len(words) < 2:
        chars = list(title.strip())
        if len(chars) < 2:
            return title.strip(), ""
        candidates = [("".join(chars[:i]), "".join(chars[i:]))
                      for i in range(1, len(chars))]
    else:
        candidates = [(" ".join(words[:i]), " ".join(words[i:]))
                      for i in range(1, len(words))]

    def score(lines: tuple[str, str]) -> float:
        top_w = d.textlength(lines[0], font=top_font)
        bottom_w = d.textlength(lines[1], font=bottom_font)
        overflow = max(0, top_w - max_w) + max(0, bottom_w - max_w)
        return overflow * 10 + abs(top_w - bottom_w)

    return min(candidates, key=score)


def render_title_png(title: str, keyword: str, style: StylePreset, out: Path) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(style.title_font), style.title_size)
    if style.title_emphasis_size is not None:
        emphasis_font = ImageFont.truetype(
            str(style.title_font), style.title_emphasis_size)
        top, bottom = _split_title_lines(title, font, emphasis_font, d, W - 120)
        rows = [(top, font, _hex_rgba(style.title_color))]
        if bottom:
            rows.append((bottom, emphasis_font,
                         _hex_rgba(style.title_highlight)))
        heights = []
        for text, row_font, _color in rows:
            _left, row_top, _right, row_bottom = _ink_bbox(d, text, row_font)
            heights.append(row_bottom - row_top)
        default_gap = round(style.title_size * 0.15)
        gap = (style.title_line_gap
               if style.title_line_gap is not None else default_gap) if len(rows) > 1 else 0
        group_h = sum(heights) + gap * (len(rows) - 1)
        if style.title_y is None:
            group_center_y = style.top_bar / 2
        else:
            group_center_y = _editor_y_to_canvas(style.title_y, H)
        top_y = group_center_y - group_h / 2
        for (text, row_font, color), height in zip(rows, heights):
            center = (W // 2, round(top_y + height / 2))
            d.text(_centered_text_origin(d, text, row_font, center), text,
                   font=row_font, fill=color)
            top_y += height + gap
    else:
        lines = _wrap_lines(title, font, max_w=W - 120, d=d)[:style.title_max_lines]
        line_h = int(style.title_size * 1.25)
        y0 = (style.top_bar - line_h * len(lines)) // 2
        for i, line in enumerate(lines):
            lw = int(d.textlength(line, font=font))
            _draw_highlighted_line(d, ((W - lw) // 2, y0 + i * line_h), line,
                                   [keyword] if keyword else [], font,
                                   _hex_rgba(style.title_color),
                                   _hex_rgba(style.title_highlight))
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
    d.text(_centered_text_origin(d, style.watermark_text, font,
                                 (W // 2, center_y)),
           style.watermark_text, font=font,
           fill=(255, 255, 255, style.watermark_opacity))
    img.save(out)
    return out


def render_subtitle_pngs(groups: list[list], keywords: list[str],
                         style: StylePreset, out_dir: Path) -> list[Path]:
    W, H = style.canvas
    font = ImageFont.truetype(str(style.sub_font), style.sub_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    pad_x, pad_y = 24, 12
    paths: list[Path] = []
    for i, (_a, _b, t) in enumerate(groups):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        left, top, right, bottom = _ink_bbox(d, t, font)
        if style.sub_y is None:
            _vw, vh = style.video_area()
            center_y = style.top_bar + int(vh * style.sub_y_frac) - style.sub_size // 2
        else:
            center_y = _editor_y_to_canvas(style.sub_y, H)
        origin_x, origin_y = _centered_text_origin(d, t, font,
                                                    (W // 2, center_y))
        ink_box = (origin_x + left, origin_y + top,
                   origin_x + right, origin_y + bottom)
        d.rectangle((ink_box[0] - pad_x, ink_box[1] - pad_y,
                     ink_box[2] + pad_x, ink_box[3] + pad_y),
                    fill=(0, 0, 0, style.sub_box_alpha))
        _draw_highlighted_line(d, (origin_x, origin_y), t, keywords, font,
                               _hex_rgba(style.sub_color, style.sub_opacity),
                               _hex_rgba(style.sub_highlight, style.sub_opacity))
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
) -> str:
    payload = json.dumps(
        {
            "storyline_id": storyline_id,
            "title_text": title_text,
            "subtitles_enabled": subtitles_enabled,
            "style_hash": style_hash_value,
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


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
                      style: StylePreset, out_path: Path) -> Path:
    return render_overlay_variant(
        assets,
        title_text=title_text,
        keyword=keyword,
        style=style,
        out_path=out_path,
        subtitles_enabled=True,
    )


def render_overlay_variant(assets: RenderAssets, *, title_text: str, keyword: str,
                           style: StylePreset, out_path: Path,
                           subtitles_enabled: bool) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    title_png = render_title_png(title_text, keyword, style,
                                 assets.work / f"title-{out_path.stem}.png")
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
                             style, out_path)
