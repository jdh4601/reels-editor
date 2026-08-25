from __future__ import annotations

import json

from reels_editor import candidate_analyzer


TOPICS = [
    "첫 고객 인터뷰",
    "가격 실험",
    "광고비 손실",
    "기능 삭제",
    "현금흐름 관리",
    "유료 전환",
    "창업자 번아웃",
    "제품 출시",
    "고객 이탈",
    "시장 선택",
]


def _payload(content_types: list[str]) -> dict:
    return {
        "candidates": [
            {
                "content_type": content_types[index % len(content_types)],
                "title": topic,
                "summary": f"{topic}에서 실제로 확인한 구체적인 과정 {index}",
                "takeaway": f"{topic}에 적용할 독립적인 행동 원칙 {index}",
                "segment_ids": ["t0"],
            }
            for index, topic in enumerate(TOPICS)
        ]
    }


def test_candidate_prompt_contains_only_selected_types(segments: dict) -> None:
    prompt = candidate_analyzer.build_candidate_prompt(
        segments,
        ["strategy", "failure"],
    )

    assert "strategy (전략형)" in prompt
    assert "failure (실패 분석형)" in prompt
    assert "story (스토리형)" not in prompt
    assert "정확히 10개" in prompt


def test_generate_candidates_returns_ten_grounded_distinct_items(segments: dict) -> None:
    candidates = candidate_analyzer.generate_candidates(
        segments,
        ["story", "principle"],
        runner=lambda _prompt: json.dumps(_payload(["story", "principle"]), ensure_ascii=False),
    )

    assert len(candidates) == 10
    assert [candidate.id for candidate in candidates] == [f"c{index}" for index in range(1, 11)]
    assert {candidate.content_type for candidate in candidates} == {"story", "principle"}
    assert all(candidate.segment_ids == ["t0"] for candidate in candidates)


def test_generate_candidates_retries_when_candidates_are_duplicates(segments: dict) -> None:
    calls: list[str] = []
    duplicate = _payload(["strategy"])
    for candidate in duplicate["candidates"]:
        candidate.update({
            "title": "같은 고객 확보 방법",
            "summary": "똑같은 고객 확보 과정을 설명합니다",
            "takeaway": "같은 실행 교훈입니다",
        })

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = duplicate if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidates = candidate_analyzer.generate_candidates(
        segments,
        ["strategy"],
        runner=runner,
    )

    assert len(calls) == 2
    assert "내용이 너무 비슷" in calls[1]
    assert len(candidates) == 10


def _payload_with_titles(titles: list[str]) -> dict:
    payload = _payload(["strategy"])
    for candidate, title in zip(payload["candidates"], titles):
        candidate["title"] = title
    return payload


def test_candidate_title_over_length_limit_is_rejected(segments: dict) -> None:
    long_title = "첫 고객이 없을 때 대표가 가장 먼저 한 일"
    titles = [long_title, *TOPICS[1:]]
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = _payload_with_titles(titles) if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidate_analyzer.generate_candidates(segments, ["strategy"], runner=runner)

    assert len(calls) == 2
    assert "14자" in calls[1]


def test_candidate_titles_all_declarative_are_rejected(segments: dict) -> None:
    declarative = [f"{topic} 했습니다" for topic in TOPICS]
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = _payload_with_titles(declarative) if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidate_analyzer.generate_candidates(segments, ["strategy"], runner=runner)

    assert len(calls) == 2
    assert "명사구" in calls[1]


def test_candidate_prompt_carries_text_hook_principles(segments: dict) -> None:
    prompt = candidate_analyzer.build_candidate_prompt(segments, ["strategy"])

    assert "스타카토" in prompt
    assert "14자" in prompt


def test_selected_candidate_result_carries_candidate_title(segments: dict) -> None:
    from reels_editor.jobs.models import ContentCandidate

    candidate = ContentCandidate(
        id="c1",
        content_type="strategy",
        title="광고비 0원, 첫 고객",
        summary="요약",
        takeaway="교훈",
        segment_ids=["t0"],
    )
    doc = {
        "story": {"five_lines": {}, "lens": "l"},
        "title_candidates": [
            {"text": "무시되는 제목 하나", "keyword": ""},
            {"text": "무시되는 제목 둘", "keyword": ""},
            {"text": "무시되는 제목 셋", "keyword": ""},
        ],
        "speaker": {"name": "화자", "role": ""},
        "subtitle_keywords": [],
        "cuts": [{"beat": "훅", "seg_ids": ["t0", "t1", "t2"]}],
    }

    results = candidate_analyzer.generate_selected_candidates(
        segments,
        [candidate],
        runner=lambda _p: json.dumps(doc, ensure_ascii=False),
    )

    assert results[0].title == "광고비 0원, 첫 고객"
