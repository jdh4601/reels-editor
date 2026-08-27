"""Find ten distinct, useful reel opportunities in a founder interview transcript."""
from __future__ import annotations

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
from reels_editor.title_rules import MAX_TITLE_CHARS, normalize_title, title_char_count

if TYPE_CHECKING:
    from reels_editor.jobs.models import ContentCandidate

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "candidate-analysis.md"
CANDIDATE_COUNT = 10
TARGET_DURATION_S = 35
MIN_DURATION_S = 30
MAX_DURATION_S = 40
MAX_RETRIES = 2
MIN_CANDIDATE_TITLE_CHARS = 12
MIN_CANDIDATE_TITLE_WORDS = 3

CONTENT_TYPES: dict[str, dict[str, str]] = {
    "story": {
        "label": "스토리형",
        "example": "회사가 망하기 직전에 바꾼 한 가지",
        "guidance": "위기나 전환이 있는 실제 사건을 중심으로 상황, 선택, 결과, 교훈이 이어지는 내용",
    },
    "strategy": {
        "label": "전략형",
        "example": "광고 없이 첫 고객을 만든 방법",
        "guidance": "마케팅, 판매, 제품, 운영에서 실제로 사용한 방법과 실행 과정을 배울 수 있는 내용",
    },
    "failure": {
        "label": "실패 분석형",
        "example": "6개월을 낭비하게 만든 잘못된 가정",
        "guidance": "잘못된 판단이나 가정, 손실, 원인, 이후 바꾼 행동이 구체적으로 드러나는 내용",
    },
    "principle": {
        "label": "원칙형",
        "example": "확장보다 이것이 먼저입니다",
        "guidance": "창업가의 의사결정 기준, 생존 원칙, 마인드셋이나 장기적인 관점을 설명하는 내용",
    },
}


def validate_content_types(values: list[str] | tuple[str, ...]) -> list[str]:
    selected = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not selected:
        raise ValueError("콘텐츠 유형을 하나 이상 선택하세요.")
    unknown = [value for value in selected if value not in CONTENT_TYPES]
    if unknown:
        raise ValueError("지원하지 않는 콘텐츠 유형: " + ", ".join(unknown))
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
    correction = f"\n## 수정 피드백\n{feedback}\n" if feedback else ""
    return (
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
            errors = [f"JSON 파싱 실패: {exc}"]
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
    raise RuntimeError(f"콘텐츠 후보 분석 3회 실패 — 마지막 오류: {last_problem}")


def candidate_brief(candidate: ContentCandidate) -> str:
    definition = CONTENT_TYPES[candidate.content_type]
    return (
        f"콘텐츠 유형: {definition['label']}\n"
        f"구성 원칙: {definition['guidance']}\n"
        f"선택한 후보 제목: {candidate.title}\n"
        f"후보 내용: {candidate.summary}\n"
        f"1인 창업가가 얻을 교훈: {candidate.takeaway}\n"
        f"근거가 된 구간: {', '.join(candidate.segment_ids)}\n"
        "이 후보가 약속한 한 가지 내용만 다룬다. 근거 구간과 인접 구간에서 완결된 발화를 고르고, "
        "다른 주제로 확장하지 않는다. 스토리형이 아닌 유형을 억지 서사 구조로 바꾸지 않는다."
    )


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
                segments,
                TARGET_DURATION_S,
                runner=runner,
                raw_dump=raw_dump,
                angle=candidate_brief(candidate),
                speed=speed,
                min_duration_s=MIN_DURATION_S,
                max_duration_s=MAX_DURATION_S,
            )
            return StorylineResult(index, label, doc, title=candidate.title)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as exc:
            return StorylineResult(
                index, label, None, f"{type(exc).__name__}: {exc}", title=candidate.title
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
        return [], ["candidates는 배열이어야 함"]
    errors: list[str] = []
    if len(raw_candidates) != CANDIDATE_COUNT:
        errors.append(f"candidates는 정확히 {CANDIDATE_COUNT}개여야 함")
    valid_segment_ids = {
        str(item.get("id"))
        for item in segments.get("segments", [])
        if isinstance(item, dict) and item.get("id")
    }
    candidates: list[ContentCandidate] = []
    for index, item in enumerate(raw_candidates[:CANDIDATE_COUNT]):
        if not isinstance(item, dict):
            errors.append(f"candidates[{index}]는 객체여야 함")
            continue
        content_type = str(item.get("content_type", "")).strip()
        title = normalize_title(str(item.get("title", "")))
        summary = " ".join(str(item.get("summary", "")).split())
        takeaway = " ".join(str(item.get("takeaway", "")).split())
        segment_ids = list(dict.fromkeys(str(value) for value in item.get("segment_ids", [])))
        if content_type not in selected_types:
            errors.append(f"candidates[{index}].content_type이 선택 유형이 아님")
        if not title or not summary or not takeaway:
            errors.append(f"candidates[{index}]의 title/summary/takeaway가 비어 있음")
        if not segment_ids or any(segment_id not in valid_segment_ids for segment_id in segment_ids):
            errors.append(f"candidates[{index}].segment_ids가 실제 자막 구간과 맞지 않음")
        candidates.append(ContentCandidate(
            id=f"c{index + 1}",
            content_type=content_type,
            title=title,
            summary=summary,
            takeaway=takeaway,
            segment_ids=segment_ids,
        ))
    errors.extend(_duplicate_errors(candidates))
    errors.extend(_text_hook_errors(candidates))
    return candidates, errors


def _text_hook_errors(candidates: list[ContentCandidate]) -> list[str]:
    """후보 제목이 곧 릴스 제목이므로 텍스트 훅 원칙을 여기서 검증한다."""
    errors: list[str] = []
    titled = [candidate for candidate in candidates if candidate.title]
    for index, candidate in enumerate(titled):
        length = title_char_count(candidate.title)
        if length < MIN_CANDIDATE_TITLE_CHARS:
            errors.append(
                f"candidates[{index}].title이 공백 제외 {length}자로 너무 짧음 — "
                f"최소 {MIN_CANDIDATE_TITLE_CHARS}자로 구체화할 것"
            )
        elif length > MAX_TITLE_CHARS:
            errors.append(
                f"candidates[{index}].title이 공백 제외 {length}자로 최대 "
                f"{MAX_TITLE_CHARS}자를 초과함"
            )
        words = candidate.title.split()
        if len(words) < MIN_CANDIDATE_TITLE_WORDS:
            errors.append(
                f"candidates[{index}].title에 띄어쓰기가 부족함 — "
                f"자연스럽게 띄어쓴 {MIN_CANDIDATE_TITLE_WORDS}어절 이상으로 쓸 것"
            )
    if not errors and titled and all(is_declarative_sentence(c.title) for c in titled):
        errors.append(
            "모든 title이 서술형 완결 문장임 — 최소 1개는 명사구로 끝맺을 것"
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
                    f"후보 {other_index + 1}과 {len(signatures) + 1}의 내용이 너무 비슷함"
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
