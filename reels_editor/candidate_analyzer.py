"""Find ten distinct, useful reel opportunities in a long-form video transcript."""
from __future__ import annotations

from reels_editor.languages import language_instruction, output_language, translation_required

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from reels_editor.storyteller import (
    StorylineResult,
    extract_json,
    generate_script,
    harmonize_speaker_metadata,
    is_declarative_sentence,
    text_hook_principles,
)
from reels_editor.title_rules import (
    generated_title_error,
    normalize_title,
)

if TYPE_CHECKING:
    from reels_editor.jobs.models import ContentCandidate

PROMPT_PATH = Path(__file__).parent / "resources" / "prompts" / "candidate-analysis.md"
CANDIDATE_COUNT = 10
TARGET_DURATION_S = 35
MAX_RETRIES = 1
CONTENT_TYPES: dict[str, dict[str, str]] = {
    "story": {
        "label": "Story",
        "example": "회사가 망하기 직전에 바꾼 한 가지",
        "guidance": "위기나 전환이 있는 실제 사건을 중심으로 상황, 선택, 결과, 교훈이 이어지는 내용",
    },
    "strategy": {
        "label": "Strategy",
        "example": "광고 없이 첫 고객을 만든 방법",
        "guidance": "마케팅, 판매, 제품, 운영에서 실제로 사용한 방법과 실행 과정을 배울 수 있는 내용",
    },
    "failure": {
        "label": "Failure analysis",
        "example": "6개월을 낭비하게 만든 잘못된 가정",
        "guidance": "잘못된 판단이나 가정, 손실, 원인, 이후 바꾼 행동이 구체적으로 드러나는 내용",
    },
    "principle": {
        "label": "Principle",
        "example": "확장보다 이것이 먼저입니다",
        "guidance": "화자의 의사결정 기준, 생존 원칙, 마인드셋이나 장기적인 관점을 설명하는 내용",
    },
}


def validate_content_types(values: list[str] | tuple[str, ...]) -> list[str]:
    selected = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not selected:
        raise ValueError("Select at least one content type.")
    unknown = [value for value in selected if value not in CONTENT_TYPES]
    if unknown:
        raise ValueError("Unsupported content type: " + ", ".join(unknown))
    return selected


def build_candidate_prompt(
    segments: dict[str, Any],
    content_types: list[str],
    *,
    feedback: str | None = None,
) -> str:
    selected = validate_content_types(content_types)
    type_listing = "\n".join(
        f"- {key} ({CONTENT_TYPES[key]['label']}): {CONTENT_TYPES[key]['guidance']}"
        for key in selected
    )
    segment_listing = "\n".join(
        f"- [{_timestamp(item.get('source_start_us', 0))}] {item['id']}: {item['text']}"
        for item in segments.get("segments", [])
    )
    correction = f"\n## Correction feedback\n{feedback}\n" if feedback else ""
    return language_instruction(segments) + (
        PROMPT_PATH.read_text(encoding="utf-8")
        .replace("{candidate_count}", str(CANDIDATE_COUNT))
        .replace("{text_hook_block}", text_hook_principles())
        .replace("{content_types}", type_listing)
        .replace("{segments_listing}", segment_listing)
        .replace("{feedback_block}", correction)
    )


def generate_candidates(
    segments: dict[str, Any],
    content_types: list[str],
    *,
    runner: Callable[[str], str],
    raw_dump: Path | None = None,
) -> list[ContentCandidate]:
    selected = validate_content_types(content_types)
    feedback: str | None = None
    last_raw = ""
    last_problem = "알 수 없는 후보 분석 오류"
    for _attempt in range(MAX_RETRIES + 1):
        last_raw = runner(build_candidate_prompt(segments, selected, feedback=feedback))
        try:
            payload = extract_json(last_raw)
            candidates, errors = _parse_candidates(payload, segments, selected)
        except (ValueError, json.JSONDecodeError) as exc:
            candidates = []
            errors = [f"JSON parsing failed: {exc}"]
        if not errors:
            return candidates
        last_problem = "; ".join(errors)
        feedback = (
            "이전 후보 목록이 검증에 실패했다. 정확히 10개의 서로 다른 후보를 만들고, "
            "허용된 content_type과 실제 SEGMENTS의 id만 사용하라. title은 릴스 화면에 "
            "그대로 박히는 텍스트 훅이므로 공백 제외 12~24자, 띄어쓴 3어절 이상으로 쓰라. 오류:\n"
            + "\n".join(errors)
        )
    if raw_dump is not None:
        raw_dump.parent.mkdir(parents=True, exist_ok=True)
        raw_dump.write_text(last_raw, encoding="utf-8")
    raise RuntimeError(f"Candidate analysis failed after 3 attempts — last error: {last_problem}")


def candidate_brief(candidate: ContentCandidate) -> str:
    definition = CONTENT_TYPES[candidate.content_type]
    return (
        f"Content type: {definition['label']}\n"
        f"구성 원칙: {definition['guidance']}\n"
        f"선택한 후보 제목: {candidate.title}\n"
        f"후보 내용: {candidate.summary}\n"
        f"1인 창업가가 얻을 교훈: {candidate.takeaway}\n"
        f"근거가 된 구간: {', '.join(candidate.segment_ids)}\n"
        "이 후보가 약속한 한 가지 내용만 다룬다. 근거 구간과 인접 구간에서 완결된 발화를 고르고, "
        "다른 주제로 확장하지 않는다. 스토리형이 아닌 유형을 억지 서사 구조로 바꾸지 않는다."
    )


def candidate_segments(segments: dict[str, Any], candidate: ContentCandidate) -> dict[str, Any]:
    """Keep evidence and 30s context on either side, with original IDs/times.

    Candidate discovery needs the whole interview; drafting an already selected
    topic does not. Include every evidence window even for noncontiguous cuts.
    """
    rows = segments.get("segments", [])
    by_id = {row["id"]: row for row in rows}
    if not candidate.segment_ids or any(sid not in by_id for sid in candidate.segment_ids):
        raise ValueError("The selected candidate source evidence is missing. Analyze again.")
    padding_us = 30_000_000
    windows = [(by_id[sid]["source_start_us"] - padding_us,
                by_id[sid]["source_end_us"] + padding_us) for sid in candidate.segment_ids]
    return {**segments, "segments": [row for row in rows if any(
        row["source_end_us"] >= start and row["source_start_us"] <= end
        for start, end in windows)]}


def generate_selected_candidates(
    segments: dict[str, Any],
    candidates: list[ContentCandidate],
    *,
    runner: Callable[[str], str],
    raw_dump_dir: Path | None = None,
    speed: float = 1.2,
) -> list[StorylineResult]:
    """Create one independently validated EDL for every selected candidate."""
    if not candidates:
        return []

    def one(item: tuple[int, ContentCandidate]) -> StorylineResult:
        index, candidate = item
        label = CONTENT_TYPES[candidate.content_type]["label"]
        raw_dump = raw_dump_dir / f"llm_raw_s{index + 1}.txt" if raw_dump_dir else None
        try:
            doc = generate_script(
                candidate_segments(segments, candidate),
                TARGET_DURATION_S,
                runner=runner,
                raw_dump=raw_dump,
                angle=candidate_brief(candidate),
                speed=speed,
                enforce_duration=False,
                fixed_title=candidate.title,
            )
            return StorylineResult(index, label, doc, title=candidate.title)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            return StorylineResult(
                index, label, None, f"Script generation failed: {exc}", title=candidate.title
            )

    with ThreadPoolExecutor(max_workers=len(candidates)) as executor:
        results = list(executor.map(one, enumerate(candidates)))
    harmonize_speaker_metadata(results)
    return results


def _parse_candidates(
    payload: dict[str, Any],
    segments: dict[str, Any],
    selected_types: list[str],
) -> tuple[list[ContentCandidate], list[str]]:
    # Import lazily so ``reels_editor.candidate_analyzer`` can also be imported
    # directly without triggering the eager public imports in ``jobs``.
    from reels_editor.jobs.models import ContentCandidate

    raw_candidates = payload.get("candidates")
    if not isinstance(raw_candidates, list):
        return [], ["candidates must be an array"]
    errors: list[str] = []
    if len(raw_candidates) != CANDIDATE_COUNT:
        errors.append(f"candidates must contain exactly {CANDIDATE_COUNT} items")
    valid_segment_ids = {
        str(item.get("id"))
        for item in segments.get("segments", [])
        if isinstance(item, dict) and item.get("id")
    }
    candidates: list[ContentCandidate] = []
    for index, item in enumerate(raw_candidates[:CANDIDATE_COUNT]):
        if not isinstance(item, dict):
            errors.append(f"candidates[{index}]: expected an object")
            continue
        content_type = str(item.get("content_type", "")).strip()
        title = normalize_title(str(item.get("title", "")))
        summary = " ".join(str(item.get("summary", "")).split())
        takeaway = " ".join(str(item.get("takeaway", "")).split())
        segment_ids = list(dict.fromkeys(str(value) for value in item.get("segment_ids", [])))
        if content_type not in selected_types:
            errors.append(f"candidates[{index}].content_type is not selected")
        if not title or not summary or not takeaway:
            errors.append(f"candidates[{index}]: title, summary or takeaway is empty")
        if not segment_ids or any(segment_id not in valid_segment_ids for segment_id in segment_ids):
            errors.append(f"candidates[{index}].segment_ids do not match actual source segments")
        candidates.append(ContentCandidate(
            id=f"c{index + 1}",
            content_type=content_type,
            title=title,
            summary=summary,
            takeaway=takeaway,
            segment_ids=segment_ids,
        ))
    from reels_editor.languages import text_language_error
    for candidate in candidates:
        problem = text_language_error(candidate.title, output_language(segments))
        if problem:
            errors.append(f"{candidate.id}: {problem}")
    errors.extend(_duplicate_errors(candidates))
    errors.extend(_text_hook_errors(candidates, output_language(segments)))
    from reels_editor.opening_hook import restore_opening_hook_evidence, opening_hook_errors
    restore_opening_hook_evidence(candidates, segments)
    errors.extend(opening_hook_errors(candidates, segments))
    return candidates, errors


def _text_hook_errors(candidates: list[ContentCandidate], language="ko") -> list[str]:
    """후보 제목이 곧 릴스 제목이므로 텍스트 훅 원칙을 여기서 검증한다."""
    errors: list[str] = []
    titled = [candidate for candidate in candidates if candidate.title]
    for index, candidate in enumerate(titled):
        hook_error = generated_title_error(candidate.title, language=language)
        if hook_error:
            errors.append(f"candidates[{index}].title: {hook_error}")
    if not errors and titled and all(is_declarative_sentence(c.title) for c in titled):
        errors.append(
            "At least one title must be a noun phrase rather than a complete declarative sentence"
        )
    return errors


def _duplicate_errors(candidates: list[ContentCandidate]) -> list[str]:
    errors: list[str] = []
    signatures: list[set[str]] = []
    for candidate in candidates:
        signature = set(_tokens(f"{candidate.title} {candidate.summary} {candidate.takeaway}"))
        for other_index, other in enumerate(signatures):
            union = signature | other
            similarity = len(signature & other) / len(union) if union else 1.0
            if similarity >= 0.72:
                errors.append(
                    f"Candidates {other_index + 1} and {len(signatures) + 1} are too similar"
                )
                break
        signatures.append(signature)
    return errors


def _tokens(value: str) -> list[str]:
    return [token for token in re.findall(r"[0-9A-Za-z가-힣]+", value.lower()) if len(token) > 1]


def _timestamp(source_start_us: Any) -> str:
    try:
        total_s = max(0, int(source_start_us) // 1_000_000)
    except (TypeError, ValueError):
        total_s = 0
    hours, remainder = divmod(total_s, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
