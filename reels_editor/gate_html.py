"""게이트 페이지 HTML 빌드 (서버 로직은 gate.py). 계약은 tests/test_gate_html.py."""
from __future__ import annotations

import html as html_mod

from reels_editor.config import MAX_STORYLINES, PROVIDERS, AppConfig
from reels_editor.storyteller import StorylineResult

_SETTING_FIELDS = [   # (키, 라벨, input 타입, 속성)
    ("model", "모델명 (빈칸=기본)", "text", ""),
    ("base_url", "Base URL (custom 전용)", "text", ""),
    ("api_key", "API 키 (저장 시 credentials로)", "password", ""),
    ("n_storylines", "스토리라인 개수", "number", f'min="1" max="{MAX_STORYLINES}"'),
    ("sub_size", "자막 크기", "number", 'min="28" max="72"'),
    ("title_size", "타이틀 크기", "number", 'min="48" max="96"'),
    ("sub_highlight", "자막 포인트 컬러", "color", ""),
    ("title_highlight", "타이틀 포인트 컬러", "color", ""),
    ("sub_y_frac", "자막 위치(0~1)", "number", 'min="0.5" max="1" step="0.01"'),
    ("sub_box_alpha", "자막 박스 불투명도", "number", 'min="0" max="255"'),
    ("speed", "배속", "number", 'min="0.5" max="2" step="0.05"'),
]


def _title_html(t: dict) -> str:
    text = t["text"]
    keyword = t.get("keyword", "")
    escaped = html_mod.escape(text)
    if keyword:
        ek = html_mod.escape(keyword)
        escaped = escaped.replace(ek, f"<em>{ek}</em>")
    return f'<span class="title-preview" title="{html_mod.escape(text)}">{escaped}</span>'


def _beat_rows(doc: dict, segments: dict, thumbs: dict[int, str]) -> str:
    idx = {s["id"]: s for s in segments["segments"]}
    rows = []
    for i, cut in enumerate(doc["cuts"]):
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        img = (f'<img src="data:image/jpeg;base64,{thumbs[i]}" alt="">'
               if i in thumbs else "")
        rows.append(
            f'<div class="beat">{img}<div>'
            f'<h3>{html_mod.escape(cut.get("beat") or f"cut {i + 1}")}</h3>'
            f'<p>{html_mod.escape(text)}</p></div></div>')
    return "\n".join(rows)


def _storyline_card(r: StorylineResult, segments: dict,
                    thumbs: dict[int, str], duration_s: float | None,
                    target_s: int) -> str:
    si = r.index
    head = f"스토리라인 {si + 1} · {html_mod.escape(r.angle_name)}"
    if r.doc is None:
        return (f'<section class="card fail"><h2>{head} — 생성 실패</h2>'
                f'<p class="warn">{html_mod.escape(r.error or "")}</p>'
                f'<label><input type="checkbox" name="regen" value="{si}" checked>'
                f'재생성</label></section>')
    badge = ""
    if duration_s is not None:
        over = abs(duration_s - target_s) > target_s * 0.10
        badge = (f'<span class="warn">⚠️ {duration_s:.1f}초 (목표 {target_s}초 ±10% 벗어남)</span>'
                 if over else f"<span>총 {duration_s:.1f}초</span>")
    five = r.doc.get("story", {}).get("five_lines", {})
    skeleton = " → ".join(html_mod.escape(five.get(k, "")) for k in
                          ("situation", "desire", "conflict", "change", "result"))
    lens = html_mod.escape(r.doc.get("story", {}).get("lens", ""))
    titles = "".join(
        f'<label><input type="checkbox" name="combo" value="{si}-{ti}" '
        f'{"checked" if ti == 0 else ""}>{_title_html(t)}</label>'
        for ti, t in enumerate(r.doc["title_candidates"]))
    keywords = ", ".join(html_mod.escape(k)
                         for k in r.doc.get("subtitle_keywords", []))
    return f"""<section class="card"><h2>{head} {badge}</h2>
<p>{skeleton}</p><p>렌즈: {lens}</p>
<p>자막 강조: <span style="color:#ff3b30">{keywords}</span></p>
<h3>렌더할 타이틀 선택</h3>{titles}
{_beat_rows(r.doc, segments, thumbs)}
<label><input type="checkbox" name="regen" value="{si}">이 스토리라인 재생성</label>
</section>"""


def _settings_panel(cfg: AppConfig, key_status: dict[str, str]) -> str:
    provider_opts = "".join(
        f'<option value="{p}" {"selected" if p == cfg.provider else ""}>{p}</option>'
        for p in PROVIDERS)
    status = " · ".join(f"{p}: {s}" for p, s in key_status.items()) or "-"
    values = {"model": cfg.model, "base_url": cfg.base_url,
              "n_storylines": cfg.n_storylines, **cfg.style}
    fields = []
    for key, label, typ, attrs in _SETTING_FIELDS:
        val = html_mod.escape(str(values.get(key, "")))
        fields.append(f'<label class="set">{label}'
                      f'<input id="set-{key}" type="{typ}" value="{val}" {attrs}>'
                      f'</label>')
    return f"""<details class="card"><summary>⚙︎ 설정</summary>
<p class="hint">모델 변경은 재생성/다음 실행부터 적용됩니다. 키 상태 — {status}</p>
<label class="set">프로바이더<select id="set-provider">{provider_opts}</select></label>
{"".join(fields)}
<button type="button" id="preview-btn">프리뷰 갱신</button><br>
<img id="preview-img" alt="프리뷰">
</details>"""


def build_gate_html(storylines: list[StorylineResult], segments: dict,
                    thumbs: dict[int, dict[int, str]], durations: dict[int, float],
                    target_s: int, cfg: AppConfig,
                    key_status: dict[str, str]) -> str:
    cards = "\n".join(
        _storyline_card(r, segments, thumbs.get(r.index, {}),
                        durations.get(r.index), target_s)
        for r in storylines)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>대본 검토 — reels-editor</title><style>
body{{font-family:Pretendard,-apple-system,sans-serif;background:#111;color:#eee;
     max-width:820px;margin:2rem auto;padding:0 1rem}}
.warn{{color:#ff3b30;font-weight:700}}
.hint{{color:#999;font-size:.85rem}}
.card{{background:#1c1c1c;border-radius:12px;padding:1rem;margin:1rem 0}}
.card.fail{{border:1px solid #ff3b30}}
.title-preview{{font-weight:800;font-size:1.15rem;margin-left:.5rem}}
.title-preview em{{color:#ff7a00;font-style:normal}}
label{{display:block;margin:.4rem 0}}
label.set{{display:flex;justify-content:space-between;max-width:420px;gap:1rem}}
.beat{{display:flex;gap:1rem;background:#242424;border-radius:12px;
      padding:1rem;margin:.6rem 0}}
.beat img{{width:135px;border-radius:8px;align-self:center}}
.beat h3{{margin:0 0 .3rem;color:#ff7a00}}
#preview-img{{max-width:270px;margin-top:.6rem;border-radius:8px}}
textarea{{width:100%;background:#222;color:#eee;border:1px solid #444;
         border-radius:8px;min-height:70px}}
button{{font-size:1rem;padding:.6rem 1.4rem;border-radius:8px;border:0;
       cursor:pointer;margin-right:.6rem}}
#render{{background:#30d158}}#revise{{background:#ff9f0a}}
</style></head><body>
<h1>🎬 대본 검토</h1>
{_settings_panel(cfg, key_status)}
{cards}
<section class="card"><h2>결정</h2>
<textarea id="fb" placeholder="수정 요청 내용 (재생성 시에만)"></textarea><br><br>
<button id="render">✅ 선택한 조합 렌더</button>
<button id="revise">✏️ 선택한 스토리라인 재생성</button></section>
<script>
const SET_KEYS=["provider","model","base_url","api_key","n_storylines","sub_size",
 "title_size","sub_highlight","title_highlight","sub_y_frac","sub_box_alpha","speed"];
function settings(){{
  const o={{}};
  for(const k of SET_KEYS){{
    const el=document.getElementById("set-"+k);
    if(el && el.value!=="") o[k]=el.value;
  }}
  return o;
}}
function checkedVals(name){{
  return [...document.querySelectorAll(`input[name=${{name}}]:checked`)]
    .map(el=>el.value);
}}
document.getElementById("preview-btn").onclick=()=>{{
  const q=new URLSearchParams(settings());
  q.delete("api_key");
  document.getElementById("preview-img").src="/preview?"+q.toString()+"&_="+Date.now();
}};
function send(action){{
  const combos=checkedVals("combo").map(v=>v.split("-").map(Number));
  const regen=checkedVals("regen").map(Number);
  if(action==="render" && combos.length===0){{alert("렌더할 조합을 선택하세요");return;}}
  if(action==="revise" && regen.length===0){{alert("재생성할 스토리라인을 선택하세요");return;}}
  fetch("/decision",{{method:"POST",headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{action,combos,regen,
      feedback:document.getElementById("fb").value,settings:settings()}})}})
    .then(()=>document.body.innerHTML="<h1>전달됨 — 터미널로 돌아가세요</h1>");
}}
document.getElementById("render").onclick=()=>send("render");
document.getElementById("revise").onclick=()=>send("revise");
</script></body></html>"""
