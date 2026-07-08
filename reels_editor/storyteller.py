"""LLM(claude -p) 1회 호출로 EDL 대본 생성. 검증 실패는 피드백 재시도 최대 2회."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from reels_editor import edl as edl_mod

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "storytelling-30s.md"
DEFAULT_SPEED = 1.2
MAX_RETRIES = 2

_SCHEMA = json.dumps({
    "story": {"five_lines": {"situation": "…", "desire": "…", "conflict": "…",
                             "change": "…", "result": "…"}, "lens": "…"},
    "title_candidates": [{"text": "…", "keyword": "…"}],
    "subtitle_keywords": ["…"],
    "cuts": [{"beat": "훅", "seg_ids": ["seg_id"], "broll_marker": None}],
}, ensure_ascii=False, indent=2)


def build_prompt(segments: dict, duration_s: int, feedback: str | None) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    listing = "\n".join(f"- {s['id']}: {s['text']}" for s in segments["segments"])
    fb = f"\n## 수정 피드백 (반드시 반영)\n{feedback}\n" if feedback else ""
    return (template
            .replace("{speed}", str(DEFAULT_SPEED))
            .replace("{duration_s}", str(duration_s))
            .replace("{source_budget_s}", str(round(duration_s * DEFAULT_SPEED)))
            .replace("{schema}", _SCHEMA)
            .replace("{segments_listing}", listing)
            .replace("{feedback_block}", fb))


def extract_json(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError(f"응답에서 JSON을 찾지 못함:\n{text[:500]}")
    return json.loads(text[a:b + 1])


def _run_claude(prompt: str) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                       timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 실패:\n{r.stderr}")
    return r.stdout


def generate_script(segments: dict, duration_s: int = 30,
                    feedback: str | None = None, *,
                    runner: Callable[[str], str] | None = None) -> dict:
    run = runner or _run_claude
    last_raw = ""
    for _attempt in range(1 + MAX_RETRIES):
        last_raw = run(build_prompt(segments, duration_s, feedback))
        try:
            doc = extract_json(last_raw)
        except ValueError as e:
            feedback = f"이전 응답이 JSON 파싱에 실패했다: {e}. JSON 하나만 출력할 것."
            continue
        errs = edl_mod.validate_edl(doc, segments)
        if not errs:
            doc.setdefault("selected_title", 0)
            return doc
        feedback = ("이전 EDL이 검증에 실패했다. 다음 오류를 고쳐라 "
                    "(seg_ids는 SEGMENTS의 id만, verbatim 유지):\n" + "\n".join(errs))
    raise RuntimeError(
        "대본 생성 3회 실패 — 마지막 응답을 확인하세요:\n" + last_raw[:2000])
