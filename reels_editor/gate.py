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

from reels_editor.capcut import US
from reels_editor.gate_html import build_gate_html  # noqa: F401 — 하위호환 재수출


@dataclass(frozen=True)
class GateDecision:
    action: str          # "approve" | "revise"
    title_index: int
    feedback: str = ""


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


def run_gate(html: str, *, open_browser: bool = True, port: int = 0) -> GateDecision:
    decision: list[GateDecision] = []
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length))
                d = GateDecision(body["action"], int(body["title_index"]),
                                 body.get("feedback", ""))
            except (TypeError, ValueError, KeyError):
                self.send_response(400)
                self.end_headers()
                return
            decision.append(d)
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args: object) -> None:
            pass  # 테스트/CLI 출력 오염 방지

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url)
    print(f"대본 검토 페이지: {url}")
    done.wait()
    server.shutdown()
    return decision[0]


def _ask_title_index(n: int, input_fn: Callable[[str], str]) -> int:
    while True:
        raw = input_fn("타이틀 번호 선택: ").strip() or "1"
        try:
            ti = int(raw) - 1
        except ValueError:
            print(f"1~{n} 사이 숫자를 입력하세요.")
            continue
        if 0 <= ti < n:
            return ti
        print(f"1~{n} 사이 숫자를 입력하세요.")


def run_gate_terminal(edl_doc: dict, segments: dict, duration_s: float,
                      target_s: int,
                      input_fn: Callable[[str], str] = input) -> GateDecision:
    idx = {s["id"]: s for s in segments["segments"]}
    warn = " ⚠️ ±10% 벗어남" if abs(duration_s - target_s) > target_s * 0.10 else ""
    print(f"\n=== 대본 검토 — 총 {duration_s:.1f}초 (목표 {target_s}초){warn} ===")
    for i, t in enumerate(edl_doc["title_candidates"], 1):
        print(f"  타이틀 {i}: {t['text']}  (강조: {t.get('keyword', '-')})")
    for cut in edl_doc["cuts"]:
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        print(f"  [{cut.get('beat', '?')}] {text}")
    ti = _ask_title_index(len(edl_doc["title_candidates"]), input_fn)
    ans = input_fn("[y] 승인 / 그 외 입력 = 수정 요청: ").strip()
    if ans.lower() == "y":
        return GateDecision("approve", ti)
    return GateDecision("revise", ti, ans)
