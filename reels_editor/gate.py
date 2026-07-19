"""대본 검토 게이트 — 로컬 브라우저 UI(stdlib http.server) + 터미널 폴백."""
from __future__ import annotations

import base64
import json
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlparse

from reels_editor.capcut import US
from reels_editor.gate_html import build_gate_html  # noqa: F401 — 하위호환 재수출


def extract_thumbs(video_path: Path, edl_doc: dict, segments: dict,
                   out_dir: Path) -> dict[int, str]:
    """각 cut 시작 프레임 → base64 jpg. 실패한 컷은 조용히 건너뛴다(썸네일은 장식)."""
    idx = {s["id"]: s for s in segments["segments"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs: dict[int, str] = {}
    for i, cut in enumerate(edl_doc["cuts"]):
        first = idx.get(cut["seg_ids"][0]) if cut.get("seg_ids") else None
        if not first:
            continue
        p = out_dir / f"thumb{i:02d}.jpg"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{first['source_start_us'] / US:.3f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale=270:-2", str(p)],
            capture_output=True)
        if r.returncode == 0 and p.is_file():
            thumbs[i] = base64.b64encode(p.read_bytes()).decode()
    return thumbs


@dataclass(frozen=True)
class MultiGateDecision:
    action: str                       # "render" | "revise"
    combos: list[tuple[int, int]]     # (storyline_index, title_index)
    regen: list[int]
    feedback: str = ""
    settings: dict = None             # type: ignore[assignment]


def parse_decision(body: dict) -> MultiGateDecision:
    action = body.get("action")
    if action not in ("render", "revise"):
        raise ValueError(f"알 수 없는 action: {action!r}")
    combos = [(int(a), int(b)) for a, b in body.get("combos", [])]
    regen = [int(i) for i in body.get("regen", [])]
    settings = body.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("settings는 객체여야 함")
    return MultiGateDecision(action, combos, regen,
                             str(body.get("feedback", "")), settings)


def run_gate_v2(html: str, preview_fn: Callable[[dict], bytes], *,
                open_browser: bool = True, port: int = 0,
                on_url: Callable[[str], None] | None = None) -> MultiGateDecision:
    decision: list[MultiGateDecision] = []
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/preview":
                try:
                    png = preview_fn(dict(parse_qsl(parsed.query)))
                except Exception as e:  # noqa: BLE001 — 프리뷰 실패는 게이트를 죽이면 안 됨
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e)[:200].encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(png)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
                d = parse_decision(json.loads(self.rfile.read(length)))
            except (TypeError, ValueError, KeyError):
                self.send_response(400)
                self.end_headers()
                return
            decision.append(d)
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if on_url:
        on_url(url)
    if open_browser:
        webbrowser.open(url)
    print(f"대본 검토 페이지: {url}")
    done.wait()
    server.shutdown()
    return decision[0]


def parse_combo_selection(raw: str,
                          storylines: list) -> list[tuple[int, int]]:
    by_index = {r.index: r for r in storylines if r.doc is not None}
    combos: list[tuple[int, int]] = []
    for token in raw.split(","):
        token = token.strip()
        parts = token.split("-")
        if len(parts) != 2:
            raise ValueError(f"형식 오류: {token!r} (예: 1-2,3-1)")
        try:
            si, ti = int(parts[0]) - 1, int(parts[1]) - 1
        except ValueError as e:
            raise ValueError(f"숫자가 아님: {token!r}") from e
        if si not in by_index:
            raise ValueError(f"스토리라인 {si + 1} 없음")
        if not 0 <= ti < len(by_index[si].doc["title_candidates"]):
            raise ValueError(f"타이틀 {ti + 1} 없음 (스토리라인 {si + 1})")
        combos.append((si, ti))
    if not combos:
        raise ValueError("조합이 비어 있음")
    return combos


def run_gate_terminal_v2(storylines: list, segments: dict,
                         durations: dict[int, float], target_s: int,
                         input_fn: Callable[[str], str] = input) -> MultiGateDecision:
    idx = {s["id"]: s for s in segments["segments"]}
    for r in storylines:
        if r.doc is None:
            print(f"\n=== 스토리라인 {r.index + 1} ({r.angle_name}) — 생성 실패: {r.error}")
            continue
        dur = durations.get(r.index)
        warn = (" ⚠️ ±10% 벗어남"
                if dur is not None and abs(dur - target_s) > target_s * 0.10 else "")
        print(f"\n=== 스토리라인 {r.index + 1} ({r.angle_name}) — "
              f"{dur:.1f}초/목표 {target_s}초{warn} ===")
        for ti, t in enumerate(r.doc["title_candidates"], 1):
            print(f"  타이틀 {ti}: {t['text']}")
        for cut in r.doc["cuts"]:
            text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
            print(f"  [{cut.get('beat', '?')}] {text}")
    while True:
        raw = input_fn("렌더할 조합 (예 1-2,3-1): ").strip()
        try:
            combos = parse_combo_selection(raw, storylines)
            break
        except ValueError as e:
            print(f"입력 오류: {e}")
    ans = input_fn("[y] 렌더 / 그 외 입력 = 전체 재생성 피드백: ").strip()
    if ans.lower() == "y":
        return MultiGateDecision("render", combos, [], "", {})
    regen = [r.index for r in storylines]
    return MultiGateDecision("revise", combos, regen, ans, {})
