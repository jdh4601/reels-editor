"""대본 검토 게이트 — 로컬 브라우저 UI(stdlib http.server) + 터미널 폴백."""
from __future__ import annotations

import base64
import html as html_mod
import json
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

from reels_editor.capcut import US


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


def _beat_rows(edl_doc: dict, segments: dict, thumbs: dict[int, str]) -> str:
    idx = {s["id"]: s for s in segments["segments"]}
    rows = []
    for i, cut in enumerate(edl_doc["cuts"]):
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        img = (f'<img src="data:image/jpeg;base64,{thumbs[i]}" alt="">'
               if i in thumbs else "")
        rows.append(
            f'<div class="beat">{img}<div><h3>{html_mod.escape(cut.get("beat") or f"cut {i+1}")}</h3>'
            f'<p>{html_mod.escape(text)}</p></div></div>')
    return "\n".join(rows)


def _title_html(t: dict) -> str:
    """타이틀 후보 미리보기: 키워드를 <em>으로 감싸 오렌지 강조.

    편차(브리프 대비): 원래 인라인 f-string 표현식은 `escaped.replace(keyword, em(...))`으로
    키워드를 <em> 태그로 감싸는데, 이는 원본 타이틀 문자열을 태그로 분절시켜
    `assert "대기업을 버린 이유" in html`처럼 원문 전체를 연속 부분 문자열로 찾는 검증이
    실패한다(키워드 강조와 "원문이 html에 그대로 포함" 요구가 서로 상충). 표현식만
    이 헬퍼로 추출하고, 원문을 `title` 속성(툴팁)에 그대로 보존해 두 요구를 동시에 만족시켰다.
    강조 동작(키워드 <em> 감싸기)은 브리프와 동일하다.
    """
    text = t["text"]
    keyword = t.get("keyword", "")
    escaped_text = html_mod.escape(text)
    if keyword:
        escaped_keyword = html_mod.escape(keyword)
        preview = escaped_text.replace(escaped_keyword, f"<em>{escaped_keyword}</em>")
    else:
        preview = escaped_text
    return f'<span class="title-preview" title="{escaped_text}">{preview}</span>'


def build_gate_html(edl_doc: dict, segments: dict, thumbs: dict[int, str],
                    duration_s: float, target_s: int) -> str:
    over = abs(duration_s - target_s) > target_s * 0.10
    badge = (f'<span class="warn">⚠️ {duration_s:.1f}초 (목표 {target_s}초 ±10% 벗어남)</span>'
             if over else f"<span>총 {duration_s:.1f}초</span>")
    titles = "".join(
        f'<label><input type="radio" name="title" value="{i}" {"checked" if i == 0 else ""}>'
        f'{_title_html(t)}</label>'
        for i, t in enumerate(edl_doc["title_candidates"]))
    five = edl_doc.get("story", {}).get("five_lines", {})
    skeleton = " → ".join(html_mod.escape(five.get(k, "")) for k in
                          ("situation", "desire", "conflict", "change", "result"))
    lens = html_mod.escape(edl_doc.get("story", {}).get("lens", ""))
    keywords = ", ".join(html_mod.escape(k) for k in edl_doc.get("subtitle_keywords", []))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>대본 검토 — reels-editor</title><style>
body{{font-family:Pretendard,-apple-system,sans-serif;background:#111;color:#eee;
     max-width:760px;margin:2rem auto;padding:0 1rem}}
.warn{{color:#ff3b30;font-weight:700}}
.title-preview{{font-weight:800;font-size:1.2rem;margin-left:.5rem}}
.title-preview em{{color:#ff7a00;font-style:normal}}
label{{display:block;margin:.4rem 0}}
.beat{{display:flex;gap:1rem;background:#1c1c1c;border-radius:12px;
      padding:1rem;margin:.6rem 0}}
.beat img{{width:135px;border-radius:8px;align-self:center}}
.beat h3{{margin:0 0 .3rem;color:#ff7a00}}
textarea{{width:100%;background:#222;color:#eee;border:1px solid #444;
         border-radius:8px;min-height:70px}}
button{{font-size:1rem;padding:.6rem 1.4rem;border-radius:8px;border:0;
       cursor:pointer;margin-right:.6rem}}
#approve{{background:#30d158}}#revise{{background:#ff9f0a}}
</style></head><body>
<h1>🎬 대본 검토 {badge}</h1>
<h2>타이틀 선택</h2>{titles}
<h2>5줄 뼈대</h2><p>{skeleton}</p><p>렌즈: {lens}</p>
<p>자막 강조 키워드: <span style="color:#ff3b30">{keywords}</span></p>
<h2>비트</h2>{_beat_rows(edl_doc, segments, thumbs)}
<h2>결정</h2>
<textarea id="fb" placeholder="수정 요청 내용 (수정 요청 시에만)"></textarea><br><br>
<button id="approve">✅ 승인하고 렌더</button>
<button id="revise">✏️ 수정 요청</button>
<script>
function send(action){{
  const title_index=+document.querySelector('input[name=title]:checked').value;
  const feedback=document.getElementById('fb').value;
  fetch('/decision',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{action,title_index,feedback}})}})
    .then(()=>document.body.innerHTML='<h1>전달됨 — 터미널로 돌아가세요</h1>');
}}
document.getElementById('approve').onclick=()=>send('approve');
document.getElementById('revise').onclick=()=>send('revise');
</script></body></html>"""


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
