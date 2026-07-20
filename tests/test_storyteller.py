import json
from pathlib import Path

import pytest

from reels_editor import storyteller
from reels_editor.storyteller import ANGLES, StorylineResult, build_prompt, generate_many


def test_angles_has_three_named_hints() -> None:
    assert len(ANGLES) == 3
    names = [n for n, _ in ANGLES]
    assert names == ["정면승부형", "반전형", "감정선형"]


def test_build_prompt_injects_angle(segments: dict) -> None:
    name, hint = ANGLES[1]
    p = build_prompt(segments, 30, None, angle=hint)
    assert hint in p


def test_build_prompt_without_angle_has_no_block(segments: dict) -> None:
    p = build_prompt(segments, 30, None)
    assert "{angle_block}" not in p     # 플레이스홀더 잔존 금지


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


def test_generate_script_retries_on_parse_failure(segments: dict, edl_doc: dict) -> None:
    calls: list[str] = []

    def flaky_runner(prompt: str) -> str:
        calls.append(prompt)
        if len(calls) == 1:
            return "JSON 없음"
        return json.dumps(edl_doc, ensure_ascii=False)

    out = storyteller.generate_script(segments, runner=flaky_runner)
    assert out["cuts"]  # 두 번째 시도에서 성공
    assert len(calls) == 2
    assert "JSON 파싱에 실패" in calls[1]


def test_generate_script_dumps_raw_on_final_failure(segments: dict, tmp_path: Path) -> None:
    dump = tmp_path / "llm_raw.txt"
    with pytest.raises(RuntimeError, match="llm_raw"):
        storyteller.generate_script(
            segments, runner=lambda _p: "JSON 없음", raw_dump=dump)
    assert dump.read_text(encoding="utf-8") == "JSON 없음"


def _ok_doc(segments):
    sid = segments["segments"][0]["id"]
    return {"story": {"five_lines": {}, "lens": "l"},
            "title_candidates": [
                {"text": "첫 번째 제목", "keyword": "첫"},
                {"text": "두 번째 제목", "keyword": "두"},
                {"text": "세 번째 제목", "keyword": "세"},
            ],
            "subtitle_keywords": [],
            "cuts": [{"beat": "훅", "seg_ids": [sid]}]}


def test_generate_script_requires_exactly_three_title_candidates(
        segments: dict, edl_doc: dict) -> None:
    calls: list[str] = []
    bad = {**edl_doc, "title_candidates": edl_doc["title_candidates"][:2]}

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(bad if len(calls) == 1 else edl_doc, ensure_ascii=False)

    out = storyteller.generate_script(segments, runner=runner)

    assert len(calls) == 2
    assert "정확히 3개" in calls[1]
    assert len(out["title_candidates"]) == 3


def test_generate_script_normalizes_missing_title_keyword(
        segments: dict, edl_doc: dict) -> None:
    edl_doc["title_candidates"][0]["keyword"] = "없는키워드"

    out = storyteller.generate_script(
        segments,
        runner=lambda _p: json.dumps(edl_doc, ensure_ascii=False),
    )

    assert out["title_candidates"][0]["keyword"] == ""


def test_generate_many_runs_in_parallel(segments: dict) -> None:
    import threading
    barrier = threading.Barrier(3, timeout=5)   # 3개가 동시에 도달해야 통과

    def runner(prompt: str) -> str:
        barrier.wait()
        return json.dumps(_ok_doc(segments), ensure_ascii=False)

    results = storyteller.generate_many(segments, 3, runner=runner)
    assert [r.index for r in results] == [0, 1, 2]
    assert all(r.doc is not None and r.error is None for r in results)
    assert results[0].angle_name == "정면승부형"


def test_generate_many_isolates_failure(segments: dict) -> None:
    import threading
    calls = {"n": 0}
    lock = threading.Lock()

    def runner(prompt: str) -> str:
        with lock:
            calls["n"] += 1
        if "반전" in prompt:                # 두 번째 각도만 항상 실패
            raise RuntimeError("boom")
        return json.dumps(_ok_doc(segments), ensure_ascii=False)

    results = storyteller.generate_many(segments, 3, runner=runner)
    assert results[0].doc is not None
    assert results[1].doc is None and "boom" in results[1].error
    assert results[2].doc is not None


def test_generate_many_isolates_missing_binary_failure(segments: dict) -> None:
    """claude 바이너리가 PATH에 없는 경우(FileNotFoundError)도 격리돼야 한다."""

    def runner(prompt: str) -> str:
        if "반전" in prompt:                # 두 번째 각도만 바이너리 누락 시뮬레이션
            raise FileNotFoundError(2, "No such file or directory", "claude")
        return json.dumps(_ok_doc(segments), ensure_ascii=False)

    results = storyteller.generate_many(segments, 3, runner=runner)
    assert results[0].doc is not None and results[0].error is None
    assert results[1].doc is None
    assert results[1].error
    assert "FileNotFoundError" in results[1].error
    assert results[2].doc is not None and results[2].error is None


def test_generate_many_only_indices(segments: dict) -> None:
    def runner(prompt: str) -> str:
        return json.dumps(_ok_doc(segments), ensure_ascii=False)

    results = storyteller.generate_many(segments, 3, runner=runner, only_indices=[2])
    assert [r.index for r in results] == [2]
