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
)
from reels_editor.style import StylePreset


def extract_frame(video_path: Path, at_s: float, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at_s:.3f}",
         "-i", str(video_path), "-frames:v", "1", str(out)],
        capture_output=True)
    return out if r.returncode == 0 and out.is_file() else None


def compose_preview(frame: Path | None, title_text: str, title_keyword: str,
                    sub_text: str, sub_keywords: list[str],
                    style: StylePreset) -> bytes:
    W, H = style.canvas
    vw, vh = style.video_area()
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    if frame is not None:
        video = Image.open(frame).convert("RGBA")
        ratio = max(vw / video.width, vh / video.height)
        video = video.resize((round(video.width * ratio),
                              round(video.height * ratio)))
        x = (video.width - vw) // 2
        y = (video.height - vh) // 2
        canvas.paste(video.crop((x, y, x + vw, y + vh)), (0, style.top_bar))
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
