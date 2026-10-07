from __future__ import annotations

import json

import pytest

from reels_editor import title_suggestion


def _doc() -> dict:
    return {
        "story": {"five_lines": {"situation": "회사가 빠르게 성장했다"}},
        "cuts": [{"beat": "이유", "seg_ids": ["seg1"]}],
        "subtitle_translations": {},
    }


def _segments() -> dict:
    return {"segments": [{"id": "seg1", "text": "성장하면서 회사와 나를 분리하지 못했습니다"}]}


TITLES = [
    "성공한 성장이 오히려 회사를 망치는 이유",
    "성장할수록 더 조심해야 하는 창업가의 이유",
    "리더를 무너뜨린 성장의 뜻밖의 대가",
    "회사가 커질수록 대표가 외로워지는 이유",
    "성공을 붙잡다가 팀을 놓치는 대표들",
]


def test_generates_five_ranked_titles_in_one_call_without_losing_evidence():
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return json.dumps({"titles": TITLES}, ensure_ascii=False)
    result = title_suggestion.generate_title_suggestion(current_title="기존 제목 그대로", candidate=None,
        doc=_doc(), segments=_segments(), runner=runner)
    assert result == TITLES
    assert len(prompts) == 1
    assert "성장하면서 회사와 나를 분리하지 못했습니다" in prompts[0]
    assert "첫 번째 후보가 최종 추천" in prompts[0]


@pytest.mark.parametrize("invalid,error", [
    (["기존 제목 그대로", *TITLES[1:]], "최소 12자"),
    ([TITLES[0]] * 5, "중복"),
    (TITLES[:4], "정확히 5개"),
    (["짧은 제목", *TITLES[1:]], "최소 12자"),
    ([123, *TITLES[1:]], "정확히 5개"),
])
def test_invalid_batch_retries_as_a_whole(invalid,error):
    prompts=[]
    responses=iter([json.dumps({"titles":invalid}),json.dumps({"titles":TITLES})])
    def runner(prompt):
        prompts.append(prompt)
        return next(responses)
    result=title_suggestion.generate_title_suggestion(current_title="기존 제목 그대로",candidate=None,
        doc=_doc(),segments=_segments(),runner=runner)
    assert result == TITLES
    assert error in prompts[1]


def test_current_title_cannot_be_in_batch():
    responses=iter([json.dumps({"titles":TITLES}),json.dumps({"titles":["창업자가 성장하면서 놓치는 위험 신호",*TITLES[1:]]})])
    result=title_suggestion.generate_title_suggestion(current_title=TITLES[0],candidate=None,
        doc=_doc(),segments=_segments(),runner=lambda _:next(responses))
    assert TITLES[0] not in result


def test_invalid_json_reports_failure_and_saves_raw_response(tmp_path):
    raw=tmp_path/'raw.txt'
    with pytest.raises(RuntimeError,match="3회 실패"):
        title_suggestion.generate_title_suggestion(current_title="기존 제목",candidate=None,
            doc=_doc(),segments=_segments(),runner=lambda _:"not json",raw_dump=raw)
    assert raw.read_text() == "not json"


def test_title_prompt_prioritizes_self_recognition_and_grounded_sharing():
    prompt = title_suggestion.build_prompt(current_title='기존 제목', candidate=None, doc=_doc(), segments=_segments())
    assert '혹시 나도 해당하나?' in prompt and '이거 내 친구 얘기다' in prompt
    assert '구체적인 행동·막힘·실패 상황' in prompt
    assert '수사적 `99%`는 허용한다' in prompt
