from __future__ import annotations


def test_selected_candidate_keeps_all_evidence_windows_and_context_without_mutating_source(monkeypatch):
    from reels_editor import candidate_analyzer
    from reels_editor.jobs import ContentCandidate
    source = {'source_title': 'interview', 'video_path': '/video.mp4', 'transcript_language': 'en',
              'segments': [{'id': f's{i}', 'text': f'line {i}',
                            'source_start_us': i * 10_000_000, 'source_end_us': (i + 1) * 10_000_000}
                           for i in range(200)]}
    candidate = ContentCandidate(id='c1', content_type='story', title='title', summary='summary',
                                 takeaway='lesson', segment_ids=['s50', 's150'])
    narrowed = candidate_analyzer.candidate_segments(source, candidate)
    ids = {row['id'] for row in narrowed['segments']}
    assert {'s47', 's50', 's53', 's147', 's150', 's153'} <= ids
    assert not {'s1', 's100', 's199'} & ids
    assert narrowed['source_title'] == source['source_title']
    assert narrowed['video_path'] == source['video_path']
    assert narrowed['transcript_language'] == 'en'
    assert len(narrowed['segments']) < 20
    assert len(source['segments']) == 200
    assert next(row for row in narrowed['segments'] if row['id'] == 's50')['source_start_us'] == 500_000_000
    seen = []
    def generate_script(selected, *args, **kwargs):
        seen.append(selected)
        return {}
    monkeypatch.setattr(candidate_analyzer, 'generate_script', generate_script)
    result = candidate_analyzer.generate_selected_candidates(source, [candidate], runner=lambda _: '')
    assert seen == [narrowed]
    assert result[0].doc is not None


def test_selected_candidate_with_missing_evidence_is_rejected():
    import pytest
    from reels_editor import candidate_analyzer
    from reels_editor.jobs import ContentCandidate
    candidate = ContentCandidate(id='c1', content_type='story', title='title', summary='summary',
                                 takeaway='lesson', segment_ids=['missing'])
    with pytest.raises(ValueError, match='근거 자막'):
        candidate_analyzer.candidate_segments({'segments': []}, candidate)

import json

from reels_editor import candidate_analyzer


TOPICS = [
    "첫 고객을 만든 인터뷰의 결정적 질문",
    "가격 실험으로 확인한 고객의 진짜 기준",
    "광고비 손실을 키운 잘못된 타깃 선택",
    "기능을 덜어내고 되찾은 핵심 고객",
    "현금흐름 위기를 넘긴 비용 관리 원칙",
    "무료 사용자를 유료 고객으로 바꾼 순간",
    "창업자 번아웃을 막은 업무 중단 기준",
    "제품 출시 전에 반드시 버려야 할 기능",
    "고객 이탈을 막아낸 한 문장의 힘",
    "시장 선택 하나가 바꾼 회사의 생존 방식",
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
    long_title = "가" * 25
    titles = [long_title, *TOPICS[1:]]
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = _payload_with_titles(titles) if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidate_analyzer.generate_candidates(segments, ["strategy"], runner=runner)

    assert len(calls) == 2
    assert "24자" in calls[1]


def test_candidate_title_that_is_too_short_is_rejected(segments: dict) -> None:
    calls: list[str] = []
    titles = ["첫 고객 확보", *TOPICS[1:]]

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = _payload_with_titles(titles) if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidate_analyzer.generate_candidates(segments, ["strategy"], runner=runner)

    assert len(calls) == 2
    assert "너무 짧음" in calls[1]


def test_candidate_title_without_natural_spacing_is_rejected(segments: dict) -> None:
    calls: list[str] = []
    titles = ["첫고객을만든인터뷰의결정적질문", *TOPICS[1:]]

    def runner(prompt: str) -> str:
        calls.append(prompt)
        payload = _payload_with_titles(titles) if len(calls) == 1 else _payload(["strategy"])
        return json.dumps(payload, ensure_ascii=False)

    candidate_analyzer.generate_candidates(segments, ["strategy"], runner=runner)

    assert len(calls) == 2
    assert "띄어쓰기가 부족" in calls[1]


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
    assert "12~24자" in prompt
    assert "3어절 이상" in prompt


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


def test_selected_candidates_accept_18_second_clip_without_retry(segments, edl_doc):
    from reels_editor.jobs.models import ContentCandidate
    from reels_editor import edl
    candidate = ContentCandidate(id="c1", content_type="strategy", title=TOPICS[0],
                                 summary="요약", takeaway="교훈", segment_ids=["t1", "t2"])
    calls = []
    def runner(prompt):
        calls.append(prompt)
        return json.dumps(edl_doc, ensure_ascii=False)
    results = candidate_analyzer.generate_selected_candidates(segments, [candidate], runner=runner, speed=1.0)
    assert results[0].doc is not None, results[0].error
    assert edl.estimate_duration_s(results[0].doc, segments, 1.0) == 18
    assert len(calls) == 1
    assert "길이 제한은 없다" in calls[0]


import pytest


@pytest.mark.parametrize("duration", [15, 18, 49, 50])
def test_selected_candidate_duration_boundaries(segments, edl_doc, duration):
    from copy import deepcopy
    from reels_editor.jobs.models import ContentCandidate
    from reels_editor import edl
    source = deepcopy(segments)
    source["segments"][1]["source_end_us"] = (5 + duration / 2) * 1_000_000
    source["segments"][2]["source_start_us"] = (5 + duration / 2) * 1_000_000
    source["segments"][2]["source_end_us"] = (5 + duration) * 1_000_000
    candidate = ContentCandidate(id="c1", content_type="strategy", title=TOPICS[0],
                                 summary="요약", takeaway="교훈", segment_ids=["t1", "t2"])
    result = candidate_analyzer.generate_selected_candidates(source, [candidate],
        runner=lambda _p: json.dumps(edl_doc, ensure_ascii=False), speed=1.0)[0]
    assert result.doc is not None, result.error
    assert edl.estimate_duration_s(result.doc, source, 1.0) == duration


@pytest.mark.parametrize("duration", [14, 14.5, 51, 75])
def test_selected_candidate_has_no_duration_rejection_or_trimming(segments, edl_doc, duration):
    from copy import deepcopy
    from reels_editor.jobs.models import ContentCandidate
    from reels_editor import edl
    source = deepcopy(segments)
    source["segments"][1]["source_start_us"] = 0
    source["segments"][1]["source_end_us"] = duration * 1_000_000
    doc = deepcopy(edl_doc)
    doc["cuts"] = [{"beat": "완결된 답", "seg_ids": ["t1"]}]
    candidate = ContentCandidate(id="c1", content_type="strategy", title=TOPICS[0],
                                 summary="요약", takeaway="교훈", segment_ids=["t1"])
    result = candidate_analyzer.generate_selected_candidates(source, [candidate],
        runner=lambda _p: json.dumps(doc, ensure_ascii=False), speed=1.0)[0]
    assert result.doc is not None, result.error
    assert edl.estimate_duration_s(result.doc, source, 1.0) == duration
    assert result.doc['cuts'] == doc['cuts']
