"""스타일 프리셋 로딩. 렌더가 참조하는 모든 시각 파라미터의 단일 출처."""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import yaml

TITLE_ORANGE = "#FF7A00"
EPISODE_TOTAL = 1000


def episode_label(episode_number: int) -> str:
    """Return the product's job-level episode label."""
    if isinstance(episode_number, bool) or int(episode_number) < 1:
        raise ValueError("episode_number must be a positive integer")
    return f"에피소드 {int(episode_number)} / {EPISODE_TOTAL}"


@dataclass(frozen=True)
class StylePreset:
    canvas: tuple[int, int]
    top_bar: int
    bottom_bar: int
    title_font: Path
    title_size: int
    title_color: str
    title_highlight: str
    title_max_lines: int
    sub_font: Path
    sub_size: int
    sub_color: str
    sub_highlight: str
    sub_box_alpha: int
    sub_y_frac: float
    watermark_text: str
    watermark_font: Path
    watermark_size: int
    speed: float
    title_emphasis_size: int | None = None
    title_line_gap: int | None = None
    sub_opacity: int = 255
    sub_y: int | None = None
    watermark_opacity: int = 230
    watermark_y: int | None = None
    title_y: int | None = None
    video_aspect: tuple[int, int] = (9, 16)
    video_zoom: float = 1.3
    title_speaker_size: int = 30
    title_speaker_color: str = "#FFFFFF"
    title_speaker_gap: int = 18
    title_anchor_y: int | None = None
    title_upper_size: int = 70
    title_upper_color: str = "#FFFFFF"
    watermark_image: Path | None = None
    watermark_width: int | None = None
    episode_text: str = "에피소드 1 / 1000"
    episode_size: int = 30
    episode_color: str = "#FFFFFF"
    episode_opacity: int = 255
    episode_gap: int = 18
    episode_y: int | None = None

    def video_area(self) -> tuple[int, int]:
        return self.canvas[0], self.canvas[1] - self.top_bar - self.bottom_bar

    def for_episode(self, episode_number: int) -> "StylePreset":
        """Create a render-ready copy carrying one job's episode number."""
        return replace(self, episode_text=episode_label(episode_number))


def _font(font_dir: Path, name: str) -> Path:
    p = (font_dir / name).expanduser()
    if not p.is_file():
        raise FileNotFoundError(
            f"폰트 없음: {p}\nPretendard를 설치하거나 style yaml의 font_dir를 수정하세요.")
    return p


def _asset(style_dir: Path, name: str | None) -> Path | None:
    if not name:
        return None
    p = Path(name).expanduser()
    if not p.is_absolute():
        p = style_dir / p
    p = p.resolve()
    if not p.is_file():
        raise FileNotFoundError(f"스타일 이미지 없음: {p}")
    return p


def load_style(path: Path) -> StylePreset:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    font_dir = Path(raw["font_dir"]).expanduser()
    t, s, w = raw["title"], raw["subtitle"], raw["watermark"]
    video = raw.get("video", {})
    return StylePreset(
        canvas=tuple(raw["canvas"]),
        top_bar=raw["top_bar"], bottom_bar=raw["bottom_bar"],
        title_font=_font(font_dir, t["font"]), title_size=t["size"],
        title_color=str(t.get("color", TITLE_ORANGE)).upper(),
        title_highlight=str(t.get("highlight", TITLE_ORANGE)).upper(),
        title_max_lines=t["max_lines"],
        sub_font=_font(font_dir, s["font"]), sub_size=s["size"],
        sub_color=s["color"], sub_highlight=s["highlight"],
        sub_box_alpha=s["box_alpha"], sub_y_frac=float(s["y_frac"]),
        watermark_text=w["text"], watermark_font=_font(font_dir, w["font"]),
        watermark_size=w["size"],
        speed=float(raw["speed"]),
        title_emphasis_size=t.get("emphasis_size"),
        title_line_gap=int(t["line_gap"]) if "line_gap" in t else None,
        sub_opacity=int(s.get("opacity", 255)),
        sub_y=int(s["y"]) if "y" in s else None,
        watermark_opacity=int(w.get("opacity", 230)),
        watermark_y=int(w["y"]) if "y" in w else None,
        title_y=int(t["y"]) if "y" in t else None,
        video_aspect=tuple(video.get("aspect", (9, 16))),
        video_zoom=float(video.get("zoom", 1.3)),
        title_speaker_size=int(t.get("speaker_size", 30)),
        title_speaker_color=str(t.get("speaker_color", "#FFFFFF")),
        title_speaker_gap=int(t.get("speaker_gap", 18)),
        title_anchor_y=int(t["anchor_y"]) if "anchor_y" in t else None,
        title_upper_size=int(t.get("upper_size", 70)),
        title_upper_color=str(t.get("upper_color", "#FFFFFF")),
        watermark_image=_asset(path.parent, w.get("image")),
        watermark_width=int(w["width"]) if "width" in w else None,
        episode_text=str(w.get("episode_text", "에피소드 1 / 1000")),
        episode_size=int(w.get("episode_size", 30)),
        episode_color=str(w.get("episode_color", "#FFFFFF")),
        episode_opacity=int(w.get("episode_opacity", 255)),
        episode_gap=int(w.get("episode_gap", 18)),
        episode_y=int(w["episode_y"]) if "episode_y" in w else None,
    )
