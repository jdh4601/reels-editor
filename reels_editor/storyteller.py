"""LLM(claude -p) 1회 호출로 EDL 대본 생성. 검증 실패는 피드백 재시도 최대 2회."""
from __future__ import annotations

import json
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from reels_editor import edl as edl_mod
from reels_editor import processes

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "storytelling-30s.md"
DEFAULT_SPEED = 1.2
MAX_RETRIES = 2

ANGLES: list[tuple[str, str]] = [
    ("정면승부형", "창업가가 즉시 공감할 현실적인 문제나 결정 한 가지를 훅부터 직진으로 전개한다."),
    ("반전형", "예상을 뒤집는 실패담·솔직한 고백·웃긴 순간을 찾아 반전 문장을 축으로 전개한다."),
    ("감정선형", "불안·좌절·확신처럼 창업가가 겪는 감정 변화와 버틴 이유를 축으로 전개한다."),
]

_SCHEMA = json.dumps({
    "story": {"five_lines": {"situation": "…", "desire": "…", "conflict": "…",
                             "change": "…", "result": "…"}, "lens": "…"},
    "title_candidates": [{"text": "…", "keyword": "…"}],
    "subtitle_keywords": ["…"],
    "subtitle_translations": {"seg_id": "자연스러운 한국어 번역"},
    "cuts": [{"beat": "훅", "seg_ids": ["seg_id"], "broll_marker": None}],
}, ensure_ascii=False, indent=2)


def build_prompt(segments: dict, duration_s: int, feedback: str | None,
                 angle: str | None = None) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    listing = "\n".join(
        f"- [{_timestamp(s.get('source_start_us', 0))}] {s['id']}: {s['text']}"
        for s in segments["segments"]
    )
    fb = f"\n## 수정 피드백 (반드시 반영)\n{feedback}\n" if feedback else ""
    ab = f"\n## 스토리 각도 (이 각도로만)\n{angle}\n" if angle else ""
    language = str(segments.get("transcript_language", "")).lower()
    if language.startswith("en"):
        translation = (
            "\n## 영어 원문 → 한국어 릴스\n"
            "- 구간 선정과 의미 판단은 영어 원문으로 한다.\n"
            "- 선택한 모든 seg_id를 subtitle_translations에 빠짐없이 넣고, 값은 짧고 자연스러운 한국어 자막으로 번역한다.\n"
            "- 숫자·고유명사·사실관계를 보존하고 원문에 없는 내용을 추가하지 않는다.\n"
            "- title_candidates 3개와 subtitle_keywords는 한국어로 쓴다.\n"
        )
    else:
        translation = (
            "\n## 릴스 언어\n"
            "- title_candidates 3개는 한국어로 쓴다.\n"
            "- 영어 원문이 아니면 subtitle_translations는 빈 객체로 둔다.\n"
        )
    return (template
            .replace("{speed}", str(DEFAULT_SPEED))
            .replace("{duration_s}", str(duration_s))
            .replace("{source_budget_s}", str(round(duration_s * DEFAULT_SPEED)))
            .replace("{schema}", _SCHEMA)
            .replace("{segments_listing}", listing)
            .replace("{translation_block}", translation)
            .replace("{feedback_block}", fb)
            .replace("{angle_block}", ab))


def extract_json(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("응답에서 JSON 객체를 찾지 못함")
    candidate = text[a:b + 1]
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as original_error:
        # 모델이 JSON 구분자에 스마트 따옴표(“ ”)를 섞는 경우가 있다.
        # 문자열 내용 안의 인용부호는 건드리지 않고, 콜론·쉼표·괄호 바로
        # 뒤의 여는 구분자와 콜론·쉼표·괄호 바로 앞의 닫는 구분자만 복구한다.
        repaired = re.sub(r'(?P<prefix>[:\[,{}]\s*)[“”](?=\S)', r'\g<prefix>"', candidate)
        repaired = re.sub(r'[“”](?=\s*[:,}\]])', '"', repaired)
        if repaired == candidate:
            raise original_error
        return json.loads(repaired)


def validate_and_normalize_title_candidates(doc: dict[str, Any]) -> list[str]:
    """Desktop contract: exactly three non-empty AI title choices.

    A keyword that is not present in the title is not worth failing the whole
    storyline for, so it is downgraded to an empty highlight.
    """
    candidates = doc.get("title_candidates")
    if not isinstance(candidates, list) or len(candidates) != 3:
        return ["title_candidates는 정확히 3개여야 함"]
    errors: list[str] = []
    for i, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            errors.append(f"title_candidates[{i}]: 객체여야 함")
            continue
        text = str(candidate.get("text", "")).strip()
        if not text:
            errors.append(f"title_candidates[{i}].text 비어있음")
            continue
        keyword = str(candidate.get("keyword", "")).strip()
        candidate["text"] = text
        candidate["keyword"] = keyword if keyword and keyword in text else ""
    return errors


def _run_claude(prompt: str) -> str:
    try:
        r = processes.run(["claude", "-p", prompt], capture_output=True, text=True,
                           timeout=600)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"claude -p 타임아웃(600초): {e}") from e
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 실패:\n{r.stderr}")
    return r.stdout


def generate_script(segments: dict, duration_s: int = 30,
                    feedback: str | None = None, *,
                    runner: Callable[[str], str] | None = None,
                    raw_dump: Path | None = None,
                    angle: str | None = None) -> dict:
    run = runner or _run_claude
    last_raw = ""
    last_problem = "알 수 없는 생성 오류"
    for _attempt in range(1 + MAX_RETRIES):
        last_raw = run(build_prompt(segments, duration_s, feedback, angle))
        try:
            doc = extract_json(last_raw)
        except (ValueError, json.JSONDecodeError) as e:
            last_problem = f"JSON 파싱 실패: {e}"
            feedback = (
                f"이전 응답이 JSON 파싱에 실패했다: {e}. "
                "모든 JSON 키와 문자열의 시작·끝 구분자는 반드시 ASCII 큰따옴표(\")를 쓰고, "
                "문자열 안의 큰따옴표는 \\\"로 이스케이프한 유효한 JSON 하나만 출력할 것."
            )
            continue
        title_errs = validate_and_normalize_title_candidates(doc)
        errs = title_errs + validate_subtitle_translations(doc, segments) + edl_mod.validate_edl(doc, segments)
        if not errs:
            actual_duration = edl_mod.estimate_duration_s(doc, segments, DEFAULT_SPEED)
            if actual_duration > duration_s:
                errs.append(
                    f"완성 길이 {actual_duration:.1f}초가 최대 {duration_s}초를 초과함 — seg_ids를 줄일 것"
                )
        if not errs:
            doc.setdefault("selected_title", 0)
            return doc
        last_problem = "; ".join(errs)
        feedback = ("이전 EDL이 검증에 실패했다. 다음 오류를 고쳐라 "
                    "(title_candidates는 정확히 3개, seg_ids는 SEGMENTS의 id만, "
                    "영어 원문이면 선택한 모든 seg_id의 한국어 subtitle_translations 포함, "
                    "verbatim 유지):\n" + "\n".join(errs))
    hint = ""
    if raw_dump is not None:
        raw_dump.parent.mkdir(parents=True, exist_ok=True)
        raw_dump.write_text(last_raw, encoding="utf-8")
        hint = f" (원문 응답 저장됨: {raw_dump})"
    raise RuntimeError(f"대본 생성 3회 실패{hint} — 마지막 오류: {last_problem}")


def _timestamp(source_start_us: Any) -> str:
    try:
        total_s = max(0, int(source_start_us) // 1_000_000)
    except (TypeError, ValueError):
        total_s = 0
    hours, remainder = divmod(total_s, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def validate_subtitle_translations(doc: dict[str, Any], segments: dict[str, Any]) -> list[str]:
    language = str(segments.get("transcript_language", "")).lower()
    if not language.startswith("en"):
        doc.setdefault("subtitle_translations", {})
        return []
    translations = doc.get("subtitle_translations")
    if not isinstance(translations, dict):
        return ["영어 원문의 subtitle_translations는 객체여야 함"]
    selected_ids = {
        str(segment_id)
        for cut in doc.get("cuts", [])
        if isinstance(cut, dict)
        for segment_id in cut.get("seg_ids", [])
    }
    missing = [segment_id for segment_id in sorted(selected_ids) if not str(translations.get(segment_id, "")).strip()]
    if missing:
        return ["한국어 번역이 없는 선택 세그먼트: " + ", ".join(missing)]
    doc["subtitle_translations"] = {
        str(segment_id): str(text).strip()
        for segment_id, text in translations.items()
        if str(text).strip()
    }
    return []


@dataclass(frozen=True)
class StorylineResult:
    """병렬 생성 결과 하나."""
    index: int
    angle_name: str
    doc: dict | None
    error: str | None = None


def generate_many(segments: dict, n: int, duration_s: int = 30, *,
                  runner: Callable[[str], str] | None = None,
                  raw_dump_dir: Path | None = None,
                  feedback: str | None = None,
                  only_indices: list[int] | None = None) -> list[StorylineResult]:
    """스토리라인 n개를 병렬 생성. 개별 실패는 error로 담고 나머지는 살린다.

    러너(claude 바이너리 실행 등) 수준에서 터지는 환경/실행 오류
    (OSError·FileNotFoundError, RuntimeError, ValueError,
    subprocess.SubprocessError)는 해당 인덱스의 error로만 담아 격리한다.
    그 외 예외(TypeError, KeyError 등 프로그래밍 버그로 보이는 것)는
    격리 대상이 아니므로 그대로 전파시켜 디버깅 가능하게 둔다.
    """
    indices = only_indices if only_indices is not None else list(range(n))

    def one(i: int) -> StorylineResult:
        name, hint = ANGLES[i % len(ANGLES)]
        dump = (raw_dump_dir / f"llm_raw_s{i + 1}.txt") if raw_dump_dir else None
        try:
            doc = generate_script(segments, duration_s, feedback,
                                  runner=runner, raw_dump=dump, angle=hint)
            return StorylineResult(i, name, doc)
        except (RuntimeError, ValueError, OSError,
                subprocess.SubprocessError) as e:
            return StorylineResult(i, name, None, f"{type(e).__name__}: {e}")

    with ThreadPoolExecutor(max_workers=max(len(indices), 1)) as ex:
        return list(ex.map(one, indices))
