"""Generate a grounded Korean Instagram caption for one finished reel."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "instagram-caption.md"
MAX_RETRIES = 2
MIN_CAPTION_CHARS = 350
MAX_CAPTION_CHARS = 1_200
CTA = "다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀"


def build_prompt(
    *,
    episode_number: int,
    selected_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
    feedback: str | None = None,
) -> str:
    context = _reel_context(selected_title, candidate, doc, segments)
    feedback_block = f"# 수정 피드백\n\n{feedback}\n" if feedback else ""
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{episode_number}", str(max(1, episode_number)))
        .replace("{reel_context}", context)
        .replace("{feedback_block}", feedback_block)
    )


def generate_caption(
    *,
    episode_number: int,
    selected_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
    runner: Callable[[str], str],
    raw_dump: Path | None = None,
) -> str:
    feedback: str | None = None
    last_raw = ""
    last_errors: list[str] = ["알 수 없는 캡션 생성 오류"]
    for _attempt in range(MAX_RETRIES + 1):
        last_raw = runner(build_prompt(
            episode_number=episode_number,
            selected_title=selected_title,
            candidate=candidate,
            doc=doc,
            segments=segments,
            feedback=feedback,
        ))
        caption = _normalize(last_raw)
        errors = validate_caption(caption, episode_number)
        if not errors:
            return caption
        last_errors = errors
        feedback = (
            "이전 캡션이 검증에 실패했다. 릴스 근거는 유지하면서 아래 오류를 모두 수정하라:\n- "
            + "\n- ".join(errors)
        )
    if raw_dump is not None:
        raw_dump.parent.mkdir(parents=True, exist_ok=True)
        raw_dump.write_text(last_raw, encoding="utf-8")
    raise RuntimeError("Instagram 캡션 생성 3회 실패 — " + "; ".join(last_errors))


def validate_caption(caption: str, episode_number: int) -> list[str]:
    errors: list[str] = []
    if not caption.startswith(f"Ep {max(1, episode_number)}. "):
        errors.append(f"첫 줄은 'Ep {max(1, episode_number)}. '로 시작해야 함")
    if len(caption) < MIN_CAPTION_CHARS:
        errors.append(f"캡션이 {MIN_CAPTION_CHARS}자보다 짧음")
    if len(caption) > MAX_CAPTION_CHARS:
        errors.append(f"캡션이 {MAX_CAPTION_CHARS}자를 초과함")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", caption) if part.strip()]
    if len(paragraphs) < 5:
        errors.append("빈 줄로 구분된 문단이 5개보다 적음")
    if not caption.endswith(CTA):
        errors.append("지정된 디원 팔로우 문장으로 끝나지 않음")
    if len(paragraphs) >= 2 and not paragraphs[-2].endswith("?"):
        errors.append("마지막 질문 문단이 물음표로 끝나지 않음")
    if "```" in caption or re.search(r"(?m)^\s*#{1,6}\s", caption):
        errors.append("Markdown 또는 해시태그를 포함함")
    return errors


def _normalize(raw: str) -> str:
    value = raw.strip()
    if value.startswith("```") and value.endswith("```"):
        value = re.sub(r"^```(?:text|markdown)?\s*", "", value)
        value = re.sub(r"\s*```$", "", value)
    value = re.sub(r"^\s*(?:캡션|Instagram 캡션|인스타그램 캡션)\s*:\s*", "", value, flags=re.I)
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+\n", "\n", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def _reel_context(
    selected_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
) -> str:
    lines = [f"- 선택된 릴스 제목: {selected_title}"]
    if candidate:
        lines.extend([
            f"- 콘텐츠 유형: {candidate.get('content_type', '')}",
            f"- 분석 후보 제목: {candidate.get('title', '')}",
            f"- 분석 요약: {candidate.get('summary', '')}",
            f"- 1인 창업가를 위한 핵심 도움: {candidate.get('takeaway', '')}",
        ])
    speaker = doc.get("speaker")
    if isinstance(speaker, dict):
        lines.append(
            f"- 화자: {' '.join(str(speaker.get('name', '')).split())}"
            f" ({' '.join(str(speaker.get('role', '')).split())})"
        )
    story = doc.get("story")
    if isinstance(story, dict):
        five_lines = story.get("five_lines")
        if isinstance(five_lines, dict):
            for key, value in five_lines.items():
                text = " ".join(str(value).split())
                if text:
                    lines.append(f"- 구성 {key}: {text}")
        lens = " ".join(str(story.get("lens", "")).split())
        if lens:
            lines.append(f"- 핵심 관점: {lens}")

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
            evidence = translated or original
            if evidence:
                lines.append(f"- 실제 발화 ({beat}): {evidence}")
    return "\n".join(lines)
