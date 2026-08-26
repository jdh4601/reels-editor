import json
from pathlib import Path

import pytest

from reels_editor import storyteller
from reels_editor.storyteller import ANGLES, build_prompt


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
    assert "절대 30초" in p
    assert "36초" in p  # 소스 예산 = 30s * speed 1.2


def test_build_prompt_allows_five_second_grace_for_long_reel(segments: dict) -> None:
    p = storyteller.build_prompt(segments, duration_s=60, feedback=None)

    assert "절대 65초" in p
    assert "78초" in p  # 소스 예산 = 65s * speed 1.2


def test_build_prompt_can_require_fixed_30_to_40_second_window(segments: dict) -> None:
    prompt = storyteller.build_prompt(
        segments,
        duration_s=35,
        feedback=None,
        min_duration_s=30,
        max_duration_s=40,
    )

    assert "반드시 30~40초" in prompt
    assert "목표는 35초" in prompt
    assert "최대 48초" in prompt


def test_build_prompt_requires_korean_captions_for_english_transcript(segments: dict) -> None:
    english_segments = {
        **segments,
        "transcript_language": "en-orig",
        "segments": [{**segments["segments"][0], "text": "Startups are brutally hard."}],
    }

    prompt = storyteller.build_prompt(english_segments, duration_s=30, feedback=None)

    assert "구간 선정과 의미 판단은 영어 원문" in prompt
    assert "선택한 모든 seg_id" in prompt
    assert "한국어 자막" in prompt
    assert "{translation_block}" not in prompt


def test_build_prompt_includes_youtube_context_and_speaker_contract(segments: dict) -> None:
    youtube_segments = {
        **segments,
        "source_title": "Sam Altman on Building OpenAI",
        "source_channel": "Y Combinator",
    }

    prompt = storyteller.build_prompt(youtube_segments, duration_s=60, feedback=None)

    assert "Sam Altman on Building OpenAI" in prompt
    assert "Y Combinator" in prompt
    assert '"speaker"' in prompt
    assert "한국어 이름" in prompt
    assert "evidence" in prompt
    assert "외부 지식으로 보충하지 않는다" in prompt
    assert "{source_context_block}" not in prompt


def test_build_prompt_includes_feedback(segments: dict) -> None:
    p = storyteller.build_prompt(segments, 30, feedback="훅을 더 세게")
    assert "훅을 더 세게" in p


def test_extract_json_from_noisy_output() -> None:
    assert storyteller.extract_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    with pytest.raises(ValueError):
        storyteller.extract_json("JSON 없음")


def test_extract_json_repairs_smart_quotes_used_as_structural_delimiters() -> None:
    raw = '''{
      "subtitle_translations": {
        "yt-1": “'내가 뭘 하는지 모르겠다.' 그게 제 순간이었습니다.",
        “yt-2”: “이제 무엇을 하지?”
      }
    }'''

    assert storyteller.extract_json(raw) == {
        "subtitle_translations": {
            "yt-1": "'내가 뭘 하는지 모르겠다.' 그게 제 순간이었습니다.",
            "yt-2": "이제 무엇을 하지?",
        }
    }


def test_generate_script_returns_valid_edl(segments: dict, edl_doc: dict) -> None:
    out = storyteller.generate_script(
        segments, runner=lambda prompt: json.dumps(edl_doc, ensure_ascii=False))
    assert out["cuts"][0]["seg_ids"] == ["t1"]


def test_generate_script_requires_translation_for_each_selected_english_segment(
        segments: dict, edl_doc: dict) -> None:
    english_segments = {**segments, "transcript_language": "en"}
    calls: list[str] = []
    translated = {
        **edl_doc,
        "subtitle_translations": {
            "t1": "하지만 꿈을 포기할 수 없었어요.",
            "t2": "그래서 바로 시작했죠.",
        },
    }

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(edl_doc if len(calls) == 1 else translated, ensure_ascii=False)

    out = storyteller.generate_script(english_segments, runner=runner)

    assert len(calls) == 2
    assert "subtitle_translations는 객체여야 함" in calls[1]
    assert out["subtitle_translations"]["t1"] == "하지만 꿈을 포기할 수 없었어요."


def test_generate_script_retries_when_translated_caption_ends_mid_quote(
        segments: dict, edl_doc: dict) -> None:
    english_segments = {**segments, "transcript_language": "en"}
    incomplete = {
        **edl_doc,
        "subtitle_translations": {
            "t1": '그는 "좋은 아이디어도',
            "t2": "포기해야 한다고 말했습니다.",
        },
    }
    complete = {
        **edl_doc,
        "subtitle_translations": {
            "t1": '그는 "좋은 아이디어도',
            "t2": '포기해야 한다"고 말했습니다.',
        },
    }
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(incomplete if len(calls) == 1 else complete, ensure_ascii=False)

    out = storyteller.generate_script(english_segments, runner=runner)

    assert len(calls) == 2
    assert "큰따옴표가 닫힐 때까지" in calls[1]
    assert out["subtitle_translations"]["t2"].startswith("포기해야 한다\"")


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


def test_generate_script_final_error_is_concise_and_keeps_raw_response_in_file(
        segments: dict, tmp_path: Path) -> None:
    dump = tmp_path / "llm_raw.txt"
    raw = "not json " + "sensitive model output " * 200

    with pytest.raises(RuntimeError) as exc_info:
        storyteller.generate_script(segments, runner=lambda _p: raw, raw_dump=dump)

    message = str(exc_info.value)
    assert "마지막 오류: JSON 파싱 실패" in message
    assert "sensitive model output" not in message
    assert dump.read_text(encoding="utf-8") == raw


def _ok_doc(segments):
    sid = segments["segments"][0]["id"]
    return {"story": {"five_lines": {}, "lens": "l"},
            "title_candidates": [
                {"text": "첫 번째 후킹 제목", "keyword": "첫"},
                {"text": "두 번째 후킹 제목", "keyword": "두"},
                {"text": "세 번째 후킹 제목", "keyword": "세"},
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


def test_generate_script_normalizes_title_to_one_line_and_speaker_label(
        segments: dict, edl_doc: dict) -> None:
    edl_doc["title_candidates"][0]["text"] = "좋은 아이디어를\n포기하는 법"
    edl_doc["speaker"] = {
        "name": " 샘  알트만 ",
        "company": "OpenAI",
        "role": "CEO",
        "alternate_role": "",
        "evidence": "OpenAI CEO 샘 알트만",
    }
    grounded_segments = {
        **segments,
        "source_title": "OpenAI CEO 샘 알트만 인터뷰",
    }

    out = storyteller.generate_script(
        grounded_segments,
        runner=lambda _p: json.dumps(edl_doc, ensure_ascii=False),
    )

    assert out["title_candidates"][0]["text"] == "좋은 아이디어를 포기하는 법"
    assert out["speaker"] == {
        "name": "샘 알트만",
        "company": "OpenAI",
        "role": "CEO",
        "alternate_role": "",
        "evidence": "OpenAI CEO 샘 알트만",
    }


def test_fresh_legacy_shaped_speaker_role_still_requires_direct_evidence(
        segments: dict) -> None:
    doc = {
        "speaker": {
            "name": "Synthetic Person",
            "role": "CEO of FictionalCo",
        }
    }
    source = {
        **segments,
        "source_title": "A generic interview",
        "source_channel": "Generic Channel",
    }

    errors = storyteller.validate_and_normalize_speaker(doc, source)

    assert errors == ["speaker의 기업/역할 evidence가 제공된 SEGMENTS 또는 영상 맥락에 직접 존재해야 함"]


def test_legacy_persisted_speaker_without_evidence_degrades_to_name_only() -> None:
    speaker = {"name": "Synthetic Person", "role": "CEO of FictionalCo"}

    assert storyteller.format_speaker_label(speaker) == "Synthetic Person"


def test_generate_script_retries_when_youtube_speaker_is_missing(
        segments: dict, edl_doc: dict) -> None:
    youtube_segments = {**segments, "source_title": "OpenAI CEO Sam Altman interview"}
    with_speaker = {
        **edl_doc,
        "speaker": {
            "name": "샘 알트만",
            "company": "OpenAI",
            "role": "CEO",
            "alternate_role": "",
            "evidence": "OpenAI CEO Sam Altman interview",
        },
    }
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(edl_doc if len(calls) == 1 else with_speaker, ensure_ascii=False)

    out = storyteller.generate_script(youtube_segments, runner=runner)

    assert len(calls) == 2
    assert "speaker는 name과 role" in calls[1]
    assert out["speaker"]["name"] == "샘 알트만"


def test_speaker_company_role_requires_script_evidence(segments: dict) -> None:
    grounded_segments = {
        **segments,
        "segments": [
            {**segments["segments"][0], "text": "저는 마루 공동 창업자 김지영입니다"},
        ],
    }
    doc = {
        "speaker": {
            "name": "김지영",
            "company": "마루",
            "role": "Founder",
            "alternate_role": "",
            "evidence": "마루 공동 창업자 김지영입니다",
        }
    }

    assert storyteller.validate_and_normalize_speaker(doc, grounded_segments) == []
    assert storyteller.format_speaker_label(doc["speaker"]) == "김지영 (마루 창업자)"


def test_speaker_ungrounded_descriptor_is_rejected(segments: dict) -> None:
    doc = {
        "speaker": {
            "name": "김지영",
            "company": "마루",
            "role": "CEO",
            "alternate_role": "",
            "evidence": "원문에 없는 설명",
        }
    }

    errors = storyteller.validate_and_normalize_speaker(doc, segments)

    assert errors == ["speaker의 기업/역할 evidence가 제공된 SEGMENTS 또는 영상 맥락에 직접 존재해야 함"]


def test_speaker_evidence_must_name_the_claimed_company_and_role(segments: dict) -> None:
    doc = {
        "speaker": {
            "name": "김지영",
            "company": "마루",
            "role": "CEO",
            "alternate_role": "",
            "evidence": "저는 원래 대기업에 합격했어요",
        }
    }

    assert storyteller.validate_and_normalize_speaker(doc, segments)


def test_generate_script_accepts_long_reel_within_five_second_grace(segments: dict, edl_doc: dict) -> None:
    grace_segments = {
        **segments,
        "segments": [
            {
                **segments["segments"][0],
                "source_start_us": 0,
                "source_end_us": 74_160_000,
            }
        ],
    }
    within_grace = {
        **edl_doc,
        "cuts": [{"beat": "훅", "seg_ids": [grace_segments["segments"][0]["id"]]}],
    }
    calls: list[str] = []

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(within_grace, ensure_ascii=False)

    result = storyteller.generate_script(grace_segments, duration_s=60, runner=runner)

    assert result["cuts"] == within_grace["cuts"]
    assert len(calls) == 1


def test_generate_script_duration_validation_uses_selected_playback_speed(segments: dict, edl_doc: dict) -> None:
    speed_sensitive_segments = {
        **segments,
        "segments": [
            {
                **segments["segments"][0],
                "source_start_us": 0,
                "source_end_us": 66_000_000,
            }
        ],
    }
    doc = {
        **edl_doc,
        "cuts": [{"beat": "훅", "seg_ids": [speed_sensitive_segments["segments"][0]["id"]]}],
    }
    def runner(_prompt: str) -> str:
        return json.dumps(doc, ensure_ascii=False)

    assert storyteller.generate_script(
        speed_sensitive_segments,
        duration_s=60,
        runner=runner,
        speed=1.2,
    )["cuts"] == doc["cuts"]
    with pytest.raises(RuntimeError, match="완성 길이 66.0초가 최대 65초"):
        storyteller.generate_script(
            speed_sensitive_segments,
            duration_s=60,
            runner=runner,
            speed=1.0,
        )


def test_generate_script_retries_when_clip_exceeds_relaxed_maximum(segments: dict, edl_doc: dict) -> None:
    calls: list[str] = []
    long_segments = {
        **segments,
        "segments": [
            {
                **segments["segments"][0],
                "source_start_us": 0,
                "source_end_us": 78_120_000,
            }
        ],
    }
    oversized = {
        **edl_doc,
        "cuts": [{"beat": "훅", "seg_ids": [long_segments["segments"][0]["id"]]}],
    }

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(oversized, ensure_ascii=False)

    with pytest.raises(RuntimeError):
        storyteller.generate_script(long_segments, duration_s=60, runner=runner)

    assert len(calls) == 3
    assert "완성 길이 65.1초" in calls[1]
    assert "최대 65초를 초과" in calls[1]


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


def test_title_candidate_over_length_limit_is_rejected() -> None:
    doc = {"title_candidates": [
        {"text": "가" * 25, "keyword": ""},
        {"text": "광고비 0원, 첫 고객", "keyword": "광고비"},
        {"text": "매출보다 먼저 무너진 것", "keyword": "매출"},
    ]}

    errors = storyteller.validate_and_normalize_title_candidates(doc)

    assert any("24자" in e for e in errors)


def test_title_candidates_that_are_all_declarative_sentences_are_rejected() -> None:
    doc = {"title_candidates": [
        {"text": "망하기 직전에 알았습니다", "keyword": "망하기"},
        {"text": "결국 저는 포기했어요", "keyword": "포기"},
        {"text": "그때 전부 바꿨다", "keyword": "전부"},
    ]}

    errors = storyteller.validate_and_normalize_title_candidates(doc)

    assert any("명사구" in e for e in errors)


def test_title_candidates_allow_one_declarative_sentence_among_noun_phrases() -> None:
    doc = {"title_candidates": [
        {"text": "망하기 직전에 알았습니다", "keyword": "망하기"},
        {"text": "광고비 0원, 첫 고객", "keyword": "광고비"},
        {"text": "매출보다 먼저 무너진 것", "keyword": "매출"},
    ]}

    assert storyteller.validate_and_normalize_title_candidates(doc) == []


def test_generate_script_retries_when_titles_are_too_long(
        segments: dict, edl_doc: dict) -> None:
    calls: list[str] = []
    verbose = {**edl_doc, "title_candidates": [
        {"text": "가" * 25, "keyword": ""},
        {"text": "나" * 25, "keyword": ""},
        {"text": "다" * 25, "keyword": ""},
    ]}

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(verbose if len(calls) == 1 else edl_doc, ensure_ascii=False)

    out = storyteller.generate_script(segments, runner=runner)

    assert len(calls) == 2
    assert "24자" in calls[1]
    assert out["title_candidates"][0]["text"] == "대기업을 버린 이유"


def test_generate_script_retries_short_titles_with_legacy_speaker_shape(
        segments: dict, edl_doc: dict) -> None:
    calls: list[str] = []
    too_short = {
        **edl_doc,
        "speaker": {"name": "김지영", "role": ""},
        "title_candidates": [
            {"text": "짧은말", "keyword": ""},
            {"text": "또짧음", "keyword": ""},
            {"text": "너무짧다", "keyword": ""},
        ],
    }

    def runner(prompt: str) -> str:
        calls.append(prompt)
        return json.dumps(too_short if len(calls) == 1 else edl_doc, ensure_ascii=False)

    out = storyteller.generate_script(segments, runner=runner)

    assert len(calls) == 2
    assert "최소 6자" in calls[1]
    assert out["title_candidates"][0]["text"] == "대기업을 버린 이유"
