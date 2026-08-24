"""게이트 설정 프리뷰: 추출 프레임 위에 타이틀·자막·워터마크 합성 PNG.

렌더와 동일한 draw 코드(render_*_png)를 재사용해 프리뷰=결과를 보장한다.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from reels_editor.render import (
    render_subtitle_pngs, render_title_png, render_watermark_png,
    video_crop_box,
)
from reels_editor.style import StylePreset


def extract_frame(video_path: Path, at_s: float, out: Path) -> Path | None:
    """ffmpeg로 지정 시각의 프레임 1장을 추출한다. 실패/타임아웃 시 None."""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at_s:.3f}",
             "-i", str(video_path), "-frames:v", "1", str(out)],
            capture_output=True, timeout=30)
    except subprocess.TimeoutExpired:
        return None
    return out if r.returncode == 0 and out.is_file() else None


def compose_preview(frame: Path | None, title_text: str, title_keyword: str,
                    sub_text: str, sub_keywords: list[str],
                    style: StylePreset) -> bytes:
    """추출 프레임(또는 회색 placeholder) 위에 타이틀·자막·워터마크를 합성해 PNG 바이트를 반환한다."""
    W, H = style.canvas
    vw, vh = style.video_area()
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    if frame is not None:
        video = Image.open(frame).convert("RGBA")
        crop_w, crop_h, crop_x, crop_y = video_crop_box(
            (video.width, video.height), style)
        video = video.crop((crop_x, crop_y,
                            crop_x + crop_w, crop_y + crop_h))
        canvas.paste(video.resize((vw, vh)), (0, style.top_bar))
    else:
        canvas.paste(Image.new("RGBA", (vw, vh), (60, 60, 60, 255)),
                     (0, style.top_bar))
    with tempfile.TemporaryDirectory(prefix="reels_preview_") as td:
        tdir = Path(td)
        overlays: list[Path] = []
        if title_text:
            overlays.append(render_title_png(title_text, title_keyword, style,
                                             tdir / "title.png"))
        overlays.append(render_watermark_png(style, tdir / "wm.png"))
        if sub_text:
            overlays += render_subtitle_pngs([[0.0, 1.0, sub_text]],
                                             sub_keywords, style, tdir / "subs")
        for p in overlays:
            canvas.alpha_composite(Image.open(p).convert("RGBA"))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
