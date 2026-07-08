import json

import pytest

from reels_editor import storyteller


def test_build_prompt_lists_segments_and_budget(segments: dict) -> None:
    p = storyteller.build_prompt(segments, duration_s=30, feedback=None)
    assert "t0: 저는 원래 대기업에 합격했어요" in p
    assert "약 30초" in p
    assert "36초" in p  # 소스 예산 = 30s * speed 1.2


def test_build_prompt_includes_feedback(segments: dict) -> None:
    p = storyteller.build_prompt(segments, 30, feedback="훅을 더 세게")
    assert "훅을 더 세게" in p


def test_extract_json_from_noisy_output() -> None:
    assert storyteller.extract_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    with pytest.raises(ValueError):
        storyteller.extract_json("JSON 없음")


def test_generate_script_returns_valid_edl(segments: dict, edl_doc: dict) -> None:
    out = storyteller.generate_script(
        segments, runner=lambda prompt: json.dumps(edl_doc, ensure_ascii=False))
    assert out["cuts"][0]["seg_ids"] == ["t1"]


def test_generate_script_retries_then_fails(segments: dict) -> None:
    calls: list[str] = []

    def bad_runner(prompt: str) -> str:
        calls.append(prompt)
        return '{"cuts": [{"beat": "훅", "seg_ids": ["없는id"]}]}'

    with pytest.raises(RuntimeError):
        storyteller.generate_script(segments, runner=bad_runner)
    assert len(calls) == 3  # 최초 1회 + 재시도 2회, 그 이상 금지
    assert "없는id" in calls[1]  # 검증 에러가 피드백으로 전달됨
