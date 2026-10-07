"""Generate a grounded Korean Instagram caption for one finished reel."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable

from reels_editor.storyteller import format_speaker_label, normalize_speaker_data

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "instagram-caption.md"
MAX_RETRIES = 2
MAX_CAPTION_CHARS = 1000
MIN_SUMMARY_CHARS = 270
MAX_SUMMARY_CHARS = 300
CTA_PATTERN = re.compile(
    r"^영상에서 .+?[이가] 알려주는 .+?에 대해 궁금하다면 댓글로 "
    r"'(?P<keyword>[가-힣A-Za-z0-9]{2,10})'[을를] 남겨주세요\.\s*"
    r".+?에 대해 정리한 .+?[을를] 보내드립니다\.$"
)
SOURCE_CREDIT_PREFIX = "원본 출처:"
UNKNOWN_CHANNEL = "채널 정보 없음"


def build_prompt(
    *,
    episode_number: int,
    selected_title: str,
    candidate: dict[str, Any] | None,
    doc: dict[str, Any],
    segments: dict[str, Any],
    feedback: str | None = None,
    output_budget: int = MAX_CAPTION_CHARS,
    comment_keyword: str | None = None,
) -> str:
    context = _reel_context(selected_title, candidate, doc, segments)
    feedback_block = f"# 수정 피드백\n\n{feedback}\n" if feedback else ""
    return (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{episode_number}", str(max(1, episode_number)))
        .replace("{reel_context}", context)
        .replace("{output_budget}", str(output_budget))
        .replace("{comment_keyword}", comment_keyword or _comment_keyword(selected_title))
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
    channel_name: str = "",
    source_url: str = "",
) -> str:
    output_budget = MAX_CAPTION_CHARS
    if source_url:
        output_budget -= len(append_source_credit("", channel_name=channel_name, source_url=source_url))
    comment_keyword = _comment_keyword(selected_title)
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
            output_budget=output_budget,
            comment_keyword=comment_keyword,
        ))
        caption = _normalize(last_raw)
        errors = validate_caption(caption, episode_number, max_chars=output_budget, comment_keyword=comment_keyword)
        speaker = normalize_speaker_data(doc.get("speaker"))
        paragraphs = caption.split("\n\n")
        if speaker["name"] and speaker["name"] not in {"창업자", "화자"}:
            if speaker["name"] not in (paragraphs[1] if len(paragraphs) > 1 else ""):
                errors.append("첫 문단에 확인된 화자 이름이 빠짐")
            if speaker["name"] not in (paragraphs[-1] if paragraphs else ""):
                errors.append("댓글 안내에 확인된 화자 이름이 빠짐")
        if format_speaker_label(speaker) != speaker["name"]:
            paragraphs = caption.split("\n\n")
            introduction = paragraphs[1] if len(paragraphs) > 1 else ""
            if speaker["company"] and speaker["company"] not in introduction:
                errors.append("첫 문단에 확인된 기업명이 빠짐")
            if speaker["role"] and speaker["role"] not in introduction:
                errors.append("첫 문단에 확인된 화자 직책이 빠짐")
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


def validate_caption(caption: str, episode_number: int, *, max_chars: int = MAX_CAPTION_CHARS,
                     comment_keyword: str | None = None) -> list[str]:
    errors: list[str] = []
    if not caption.startswith(f"Ep {max(1, episode_number)}. "):
        errors.append(f"첫 줄은 'Ep {max(1, episode_number)}. '로 시작해야 함")
    if len(caption) > max_chars:
        errors.append(f"캡션이 {max_chars}자를 초과함 (현재 {len(caption)}자)")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", caption) if part.strip()]
    if len(paragraphs) != 4:
        errors.append("제목 뒤 빈 줄 하나와 정확히 3개의 본문 문단이 필요함")
    else:
        if "\n" in paragraphs[0]:
            errors.append("제목은 첫 줄에만 쓰고 본문과 빈 줄로 구분해야 함")
        for paragraph in paragraphs[1:3]:
            if not paragraph.endswith("다.") or re.search(r"(?:[습합입]니다|해요|네요|세요)[.!?]", paragraph):
                errors.append("설명 문장은 '~한다.', '~이다.'의 평서체로 써야 함")
        summary = "\n\n".join(paragraphs[1:3])
        if not MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS:
            errors.append(f"요약 본문은 {MIN_SUMMARY_CHARS}~{MAX_SUMMARY_CHARS}자여야 함 (현재 {len(summary)}자)")
        cta = CTA_PATTERN.fullmatch(paragraphs[3])
        if cta is None:
            errors.append("마지막 문단은 화자·주제·댓글 키워드·정리 자료를 포함한 댓글 안내 두 문장이어야 함")
        elif comment_keyword is not None and cta["keyword"] != comment_keyword:
            errors.append(f"댓글 키워드는 '{comment_keyword}' 그대로 써야 함")
    if "창업자 창업자" in caption:
        errors.append("창업자 직책을 중복해서 쓰면 안 됨")
    if "원본 출처:" in caption:
        errors.append("출처는 앱이 붙이므로 직접 출력하면 안 됨")
    if "```" in caption or re.search(r"(?m)^\s*#{1,6}\s", caption):
        errors.append("Markdown 또는 해시태그를 포함함")
    return errors


def append_source_credit(
    caption: str,
    *,
    channel_name: str,
    source_url: str,
) -> str:
    """Append trusted YouTube credit as the final line."""
    normalized_caption = _normalize(caption)
    normalized_channel = " ".join(str(channel_name or "").split()) or UNKNOWN_CHANNEL
    normalized_url = "".join(str(source_url or "").split())
    if not normalized_url:
        raise ValueError("원본 YouTube URL을 찾지 못했습니다.")

    # Keep the trusted video source as the last line, including on regeneration.
    normalized_caption = re.sub(
        rf"(?m)^{re.escape(SOURCE_CREDIT_PREFIX)}[^\n]*(?:\n|$)",
        "", normalized_caption,
    )
    normalized_caption = _normalize(normalized_caption)
    credit = f"{SOURCE_CREDIT_PREFIX} {normalized_channel} {normalized_url}"
    result = f"{normalized_caption}\n\n{credit}"
    if len(result) > MAX_CAPTION_CHARS:
        raise ValueError(f"출처 포함 캡션이 {MAX_CAPTION_CHARS}자를 초과합니다 (현재 {len(result)}자).")
    return result


def _comment_keyword(selected_title: str) -> str:
    """Keep a predictable trigger across regenerations of the same reel title."""
    for keyword in ("고객", "마케팅", "콘텐츠", "제품", "채용", "투자", "출시", "판매", "성장", "실패"):
        if keyword in selected_title:
            return keyword
    return "정리"


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
        lines.append(f"- 검증된 화자 소개: {format_speaker_label(speaker)}")
        if speaker.get("source_url"):
            lines.append(f"- 화자 직책 확인 출처 (캡션에 URL 출력하지 않음): {speaker['source_url']}")
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
