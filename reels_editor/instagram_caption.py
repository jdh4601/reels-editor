"""Generate a grounded Korean Instagram caption for one finished reel."""
from __future__ import annotations

from reels_editor.languages import language_instruction, output_language, translation_required

import re
from pathlib import Path
from typing import Any, Callable

from reels_editor.storyteller import format_speaker_label, normalize_speaker_data

PROMPT_PATH = Path(__file__).parent / "resources" / "prompts" / "instagram-caption.md"
MAX_RETRIES = 2
MAX_CAPTION_CHARS = 1000
MIN_SUMMARY_CHARS = 270
MAX_SUMMARY_CHARS = 300
SOURCE_CREDIT_PREFIX = "🎥"
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
) -> str:
    context = _reel_context(selected_title, candidate, doc, segments)
    feedback_block = f"# Correction feedback\n\n{feedback}\n" if feedback else ""
    return language_instruction(segments) + (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{reel_context}", context)
        .replace("{output_budget}", str(output_budget))
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
        ))
        caption = _normalize(last_raw)
        errors = validate_caption(caption, episode_number, max_chars=output_budget, selected_title=selected_title,
                                  thumbnail_title=" ".join(str(doc.get(k) or "") for k in ("title_upper", "title_lower")),
                                  language=output_language(segments))
        speaker = normalize_speaker_data(doc.get("speaker"))
        paragraphs = caption.split("\n\n")
        if speaker["name"] and speaker["name"] not in {"창업자", "화자"}:
            if speaker["name"] not in (paragraphs[1] if len(paragraphs) > 1 else ""):
                errors.append("첫 문단에 확인된 화자 이름이 빠짐")
        if format_speaker_label(speaker) != speaker["name"]:
            paragraphs = caption.split("\n\n")
            introduction = paragraphs[1] if len(paragraphs) > 1 else ""
            if speaker["company"] and speaker["company"] not in introduction:
                errors.append("첫 문단에 확인된 기업명이 빠짐")
            if output_language(segments) == "ko" and speaker["role"] and speaker["role"] not in introduction:
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
    raise RuntimeError("Instagram caption generation failed after 3 attempts — " + "; ".join(last_errors))


def validate_caption(caption: str, episode_number: int, *, max_chars: int = MAX_CAPTION_CHARS,
                     selected_title: str = "",
                     thumbnail_title: str = "", language: str = "ko") -> list[str]:
    errors: list[str] = []
    if re.search(r"(?i)(?:\bep(?:isode)?\.?\s*\d+|에피소드\s*\d+|제\s*\d+\s*화)", caption.split("\n", 1)[0]):
        errors.append("Do not include sequence numbers in the heading")
    if len(caption) > max_chars:
        errors.append(f"Caption exceeds {max_chars} characters (currently {len(caption)} characters)")
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", caption) if part.strip()]
    if len(paragraphs) != 3:
        errors.append("Provide one heading line and exactly two insight paragraphs")
    else:
        if "\n" in paragraphs[0]:
            errors.append("Use one heading line separated from the body by a blank line")
        title_key = lambda value: re.sub(r"[^\w]", "", value).casefold()
        if any(title_key(paragraphs[0]) == title_key(title) for title in (selected_title, thumbnail_title) if title_key(title)):
            errors.append("The caption heading must differ from the cover and video title")
        for paragraph in paragraphs[1:]:
            if language == "ko" and (not paragraph.endswith("다.") or re.search(r"(?:[습합입]니다|해요|네요|세요)[.!?]", paragraph)):
                errors.append("Use plain declarative Korean sentences ending in da.")
        summary = "\n\n".join(paragraphs[1:])
        if not MIN_SUMMARY_CHARS <= len(summary) <= MAX_SUMMARY_CHARS:
            errors.append(f"Summary body must be {MIN_SUMMARY_CHARS}~{MAX_SUMMARY_CHARS} characters (currently {len(summary)} characters)")
    if re.search(r"\bfollow\b|\bsubscribe\b|\bDM\b|关注|订阅|私信|댓글|팔로우|구독|(?:보내|제공해|드|드리|드립|받아|받으|받을|증정)[가-힣]*(?:니다|세요|게요)|DM|디엠", caption, re.I):
        errors.append("Do not solicit comments or follows, or promise rewards or resources")
    if "창업자 창업자" in caption:
        errors.append("Do not duplicate the speaker role")
    if "원본 출처:" in caption or re.search(r"(?m)^🎥\s", caption):
        errors.append("The app adds source credit; do not generate it")
    if "```" in caption or re.search(r"(?m)^\s*#{1,6}\s", caption):
        errors.append("Markdown or hashtags are not allowed")
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
        raise ValueError("The original YouTube URL could not be found.")

    # Keep the trusted video source as the last line, including on regeneration.
    normalized_caption = re.sub(
        rf"(?m)^(?:{re.escape(SOURCE_CREDIT_PREFIX)}|원본 출처:)[^\n]*(?:\n|$)",
        "", normalized_caption,
    )
    normalized_caption = _normalize(normalized_caption)
    credit = f"{SOURCE_CREDIT_PREFIX} {normalized_channel}"
    result = f"{normalized_caption}\n\n{credit}"
    if len(result) > MAX_CAPTION_CHARS:
        raise ValueError(f"Caption including source credit exceeds {MAX_CAPTION_CHARS} characters (currently {len(result)} characters).")
    return result


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
    lines = [f"- Selected reel title: {selected_title}",
             f"- Cover and on-screen title (write a different caption heading): {doc.get('title_upper', '')} {doc.get('title_lower', '')}"]
    if candidate:
        lines.extend([
            f"- Content type: {candidate.get('content_type', '')}",
            f"- Selected idea title: {candidate.get('title', '')}",
            f"- Analysis summary: {candidate.get('summary', '')}",
            f"- Key takeaway for the viewer: {candidate.get('takeaway', '')}",
        ])
    speaker = doc.get("speaker")
    if isinstance(speaker, dict):
        lines.append(f"- Verified speaker introduction: {format_speaker_label(speaker)}")
        if speaker.get("source_url"):
            lines.append(f"- Speaker verification source (do not include the URL in the caption): {speaker['source_url']}")
    story = doc.get("story")
    if isinstance(story, dict):
        five_lines = story.get("five_lines")
        if isinstance(five_lines, dict):
            for key, value in five_lines.items():
                text = " ".join(str(value).split())
                if text:
                    lines.append(f"- Structure {key}: {text}")
        lens = " ".join(str(story.get("lens", "")).split())
        if lens:
            lines.append(f"- Main perspective: {lens}")

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
                lines.append(f"- Original speech ({beat}): {evidence}")
    return "\n".join(lines)
