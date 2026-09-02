"""Generate one grounded replacement title for a finished reel."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from reels_editor.storyteller import text_hook_principles
from reels_editor.title_rules import normalize_title, validate_title

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "title-suggestion.md"
MAX_RETRIES = 2


def build_prompt(
    *,
    current_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
    feedback: str | None = None,
) -> str:
    feedback_block = f"\n## 수정 피드백\n{feedback}\n" if feedback else ""
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{current_title}", normalize_title(current_title))
        .replace("{reel_context}", _reel_context(candidate, doc, segments))
        .replace("{text_hook_principles}", text_hook_principles())
        .replace("{feedback_block}", feedback_block)
    )


def generate_title_suggestion(
    *,
    current_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
    runner: Callable[[str], str],
    raw_dump: Path | None = None,
) -> str:
    feedback: str | None = None
    last_raw = ""
    last_error = "알 수 없는 제목 생성 오류"
    normalized_current = normalize_title(current_title)
    for _attempt in range(MAX_RETRIES + 1):
        last_raw = runner(build_prompt(
            current_title=normalized_current,
            candidate=candidate,
            doc=doc,
            segments=segments,
            feedback=feedback,
        ))
        suggestion = _normalize_response(last_raw)
        try:
            suggestion = validate_title(suggestion)
            if suggestion == normalized_current:
                raise ValueError("현재 제목과 같음 — 다른 관점과 표현으로 다시 쓸 것")
            return suggestion
        except ValueError as exc:
            last_error = str(exc)
            feedback = f"이전 제목이 검증에 실패했다: {last_error}"
    if raw_dump is not None:
        raw_dump.parent.mkdir(parents=True, exist_ok=True)
        raw_dump.write_text(last_raw, encoding="utf-8")
    raise RuntimeError(f"새 화면 제목 생성 3회 실패 — {last_error}")


def _normalize_response(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```") and value.endswith("```"):
        value = re.sub(r"^```(?:text|markdown)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"^\s*(?:새 제목|제목|title)\s*:\s*", "", value, flags=re.I)
    value = value.strip().strip('"\'“”‘’')
    return normalize_title(value)


def _reel_context(
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
) -> str:
    lines: list[str] = []
    if candidate:
        lines.extend([
            f"- 콘텐츠 유형: {candidate.get('content_type', '')}",
            f"- 분석 후보: {candidate.get('title', '')}",
            f"- 핵심 내용: {candidate.get('summary', '')}",
            f"- 적용점: {candidate.get('takeaway', '')}",
        ])
    story = doc.get("story")
    if isinstance(story, dict):
        five_lines = story.get("five_lines")
        if isinstance(five_lines, dict):
            for value in five_lines.values():
                text = " ".join(str(value).split())
                if text:
                    lines.append(f"- 구성: {text}")

    segment_map = {
        str(item.get("id")): item
        for item in segments.get("segments", [])
        if isinstance(item, dict) and item.get("id")
    }
    translations = doc.get("subtitle_translations", {})
    if not isinstance(translations, dict):
        translations = {}
    used: set[str] = set()
    for cut in doc.get("cuts", []):
        if not isinstance(cut, dict):
            continue
        beat = " ".join(str(cut.get("beat", "구간")).split())
        for segment_id in cut.get("seg_ids", []):
            key = str(segment_id)
            if key in used or key not in segment_map:
                continue
            used.add(key)
            original = " ".join(str(segment_map[key].get("text", "")).split())
            translated = " ".join(str(translations.get(key, "")).split())
            if translated or original:
                lines.append(f"- 실제 발화 ({beat}): {translated or original}")
    return "\n".join(lines) or "- 저장된 릴스 대본의 제목만 새로 제안한다."
