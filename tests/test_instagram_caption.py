from __future__ import annotations

import pytest

from reels_editor import instagram_caption



def _valid_caption(episode: int = 2) -> str:
    return (
        "기능을 늘리기 전에 고객의 불편부터 확인한다\n\n"
        "마루 창업자 김대표는 제품보다 고객 대화가 먼저라고 말한다. 만들고 싶은 기능을 늘리는 동안 고객이 실제로 겪는 문제를 놓칠 수 있다. 제품을 완성한 뒤 판매를 시작하기보다, 잠재 고객을 만나 어떤 상황에서 불편을 느끼고 어떻게 해결하는지 먼저 확인해야 한다.\n\n"
        "반복되는 불편 중 돈을 낼 문제 하나를 찾는 것이 핵심이다. 고객의 칭찬만으로 수요를 판단하지 않고 실제 행동을 살펴야 한다. 대화에서 확인한 문제를 기준으로 제품의 우선순위를 정하면, 기능을 더 만드는 데 몰두하기보다 고객이 필요로 하는 해결책에 집중할 수 있다."
    )


def test_build_prompt_contains_only_selected_reel_evidence_and_new_rules():
    prompt = instagram_caption.build_prompt(
        episode_number=2, selected_title="광고 없이 첫 고객을 만든 방법",
        candidate={"summary": "잠재 고객을 직접 만났다", "takeaway": "문제 검증이 먼저다"},
        doc={"speaker": {"name": "김대표"}, "cuts": [{"seg_ids": ["s1"]}]},
        segments={"segments": [{"id": "s1", "text": "첫 고객을 직접 만났습니다"},
                               {"id": "s2", "text": "선택하지 않은 비밀 내용"}]})
    assert "첫 고객을 직접 만났습니다" in prompt
    assert "선택하지 않은 비밀 내용" not in prompt
    assert "270~300자" in prompt and "정확히 2문단" in prompt
    assert "제목에는 Ep" in prompt


def test_generate_caption_has_title_two_insights_and_no_offer():
    caption = instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표"}, "cuts": []}, segments={"segments": []},
        runner=lambda _prompt: _valid_caption())
    assert len(caption.split("\n\n")) == 3
    assert instagram_caption.validate_caption(caption, 2) == []


def test_generation_retries_episode_offer_and_duplicate_thumbnail():
    invalids = ["Ep 2. " + _valid_caption(),
                _valid_caption().replace("핵심이다.", "댓글을 남기면 자료를 드립니다."),
                _valid_caption().replace(_valid_caption().split("\n")[0], "첫 고객")]
    for invalid in invalids:
        prompts = []
        answers = iter([invalid, _valid_caption()])
        def runner(prompt):
            prompts.append(prompt)
            return next(answers)
        assert instagram_caption.generate_caption(
            episode_number=2, selected_title="첫 고객", candidate=None, doc={"cuts": []},
            segments={"segments": []}, runner=runner) == _valid_caption()
        assert len(prompts) == 2


def test_rejects_same_thumbnail_with_only_spacing_or_punctuation_changes():
    caption = _valid_caption()
    assert instagram_caption.validate_caption(caption, 2, thumbnail_title=caption.split("\n")[0] + "!")


def test_source_credit_is_last_and_is_idempotent():
    full = instagram_caption.append_source_credit(_valid_caption(), channel_name="  Y   Combinator ",
                                                  source_url=" https://youtu.be/abc123 ")
    assert full.endswith("🎥 Y Combinator")
    assert len(full.split("\n\n")) == 4
    assert "https://" not in full
    assert instagram_caption.append_source_credit(full, channel_name="Y Combinator",
                                                  source_url="https://youtu.be/abc123") == full


def test_summary_length_and_polite_voice_are_checked():
    paragraphs = _valid_caption().split("\n\n")
    assert 270 <= len("\n\n".join(paragraphs[1:])) <= 300
    for invalid in ("\n\n".join([paragraphs[0], "김대표는 말한다.", "고객을 만난다."]),
                    _valid_caption().replace("말한다.", "말합니다.")):
        assert instagram_caption.validate_caption(invalid, 2)


def test_source_credit_still_enforces_total_guardrail():
    with pytest.raises(ValueError, match="출처 포함"):
        instagram_caption.append_source_credit("가"*998, channel_name="채널", source_url="https://youtu.be/abc123")


def test_generation_requires_verified_company_in_first_insight():
    prompts = []
    answers = iter([_valid_caption().replace("마루 창업자", "창업자"), _valid_caption()])
    def runner(prompt):
        prompts.append(prompt)
        return next(answers)
    caption = instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표", "company": "마루", "role": "창업자", "evidence": "마루 창업자 김대표"}},
        segments={"segments": []}, runner=runner, channel_name="채널", source_url="https://youtu.be/abc123")
    assert caption == _valid_caption()
    assert "기업명이 빠짐" in prompts[1]
