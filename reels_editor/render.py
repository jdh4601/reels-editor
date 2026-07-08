"""EDL + 원본 → 릴스 mp4. 순수 함수(필터 문자열·레이아웃 계산)와
ffmpeg/Pillow 오케스트레이션(Task 5)을 분리한다.

이 환경 ffmpeg는 libass/drawtext가 없어 텍스트는 전부 Pillow PNG + overlay.
"""
from __future__ import annotations

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
    for a, b, t in items:
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


def build_base_filter(ordered: list[dict], speed: float, style: StylePreset,
                      in_size: tuple[int, int]) -> str:
    """트림+배속+concat → 영상영역 크롭·스케일 → 캔버스 pad(상하 블랙바)."""
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
    vid = (f"[vc]{_crop_expr(in_size[0], in_size[1], vw, vh)},scale={vw}:{vh},"
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
