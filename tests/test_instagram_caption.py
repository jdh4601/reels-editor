from __future__ import annotations

import pytest

from reels_editor import instagram_caption

CTA = "영상에서 김대표가 알려주는 첫 고객을 찾는 방법에 대해 궁금하다면 댓글로 '고객'을 남겨주세요. 고객 문제를 검증하는 방법에 대해 정리한 실행 가이드를 보내드립니다."


def _valid_caption(episode: int = 2) -> str:
    return (
        f"Ep {episode}. 광고 없이 첫 고객을 만든 실험\n\n"
        "마루 창업자 김대표는 제품보다 고객 대화가 먼저라고 말한다. 만들고 싶은 기능을 늘리는 동안 고객이 실제로 겪는 문제를 놓칠 수 있다. 제품을 완성한 뒤 판매를 시작하기보다, 잠재 고객을 만나 어떤 상황에서 불편을 느끼고 어떻게 해결하는지 먼저 확인해야 한다.\n\n"
        "반복되는 불편 중 돈을 낼 문제 하나를 찾는 것이 핵심이다. 고객의 칭찬만으로 수요를 판단하지 않고 실제 행동을 살펴야 한다. 대화에서 확인한 문제를 기준으로 제품의 우선순위를 정하면, 기능을 더 만드는 데 몰두하기보다 고객이 필요로 하는 해결책에 집중할 수 있다.\n\n"
        + CTA
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
    assert "270~300자" in prompt and "정확히 3문단" in prompt
    assert "댓글로 '고객'" in prompt
    assert "{comment_keyword}" not in prompt


def test_generate_caption_validates_summary_and_cta():
    caption = instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표"}, "cuts": []}, segments={"segments": []},
        runner=lambda _prompt: _valid_caption())
    assert caption.endswith(CTA)
    assert instagram_caption.validate_caption(caption, 2, comment_keyword="고객") == []


def test_generation_retries_invalid_structure_and_wrong_trigger():
    prompts = []
    answers = iter(["짧은 캡션", _valid_caption().replace("'고객'", "'제품'"), _valid_caption()])
    def runner(prompt):
        prompts.append(prompt)
        return next(answers)
    assert instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None, doc={"cuts": []},
        segments={"segments": []}, runner=runner) == _valid_caption()
    assert "댓글 키워드는 '고객'" in prompts[-1]


def test_source_credit_is_last_after_cta_and_is_idempotent():
    full = instagram_caption.append_source_credit(_valid_caption(), channel_name="  Y   Combinator ",
                                                  source_url=" https://youtu.be/abc123 ")
    assert full.endswith("원본 출처: Y Combinator https://youtu.be/abc123")
    assert CTA + "\n\n원본 출처:" in full
    assert instagram_caption.append_source_credit(full, channel_name="Y Combinator",
                                                  source_url="https://youtu.be/abc123") == full


def test_summary_length_is_separate_from_cta_title_and_credit():
    full = instagram_caption.append_source_credit(_valid_caption(), channel_name="채널", source_url="https://youtu.be/abc123")
    assert len(full) > 300
    paragraphs = _valid_caption().split("\n\n")
    assert 270 <= len("\n\n".join(paragraphs[1:3])) <= 300
    short = "\n\n".join([paragraphs[0], "김대표는 말한다.", "고객을 만난다.", CTA])
    assert any("요약 본문" in e for e in instagram_caption.validate_caption(short, 2))
    long = _valid_caption().replace("집중할 수 있다.", "집중할 수 있다. " + "더 긴 설명이다. "*10)
    assert any("요약 본문" in e for e in instagram_caption.validate_caption(long, 2))


def test_rejects_old_follow_cta_missing_resource_and_polite_summary():
    for invalid in (_valid_caption().replace(CTA, "다음 이야기가 궁금하다면 디원을 팔로우해주세요 🚀"),
                    _valid_caption().replace(" 실행 가이드를 보내드립니다.", " 보내드립니다."),
                    _valid_caption().replace("말한다.", "말합니다.")):
        assert instagram_caption.validate_caption(invalid, 2)


def test_source_credit_still_enforces_total_guardrail():
    with pytest.raises(ValueError, match="출처 포함"):
        instagram_caption.append_source_credit("가"*990, channel_name="채널", source_url="https://youtu.be/abc123")


def test_generation_requires_verified_company_and_speaker_in_cta():
    prompts = []
    answers = iter([_valid_caption().replace("마루 창업자", "창업자"),
                    _valid_caption().replace("영상에서 김대표가", "영상에서 다른사람이"), _valid_caption()])
    def runner(prompt):
        prompts.append(prompt)
        return next(answers)
    caption = instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표", "company": "마루", "role": "창업자", "evidence": "마루 창업자 김대표"}},
        segments={"segments": []}, runner=runner, channel_name="채널", source_url="https://youtu.be/abc123")
    assert caption == _valid_caption()
    assert "기업명이 빠짐" in prompts[1] and "댓글 안내에 확인된 화자 이름이 빠짐" in prompts[2]


def test_trigger_is_repeatable_and_topic_specific():
    kwargs = dict(episode_number=1, selected_title="고객 만나기를 미루는 대표들", candidate=None,
                  doc={}, segments={})
    assert "댓글로 '고객'" in instagram_caption.build_prompt(**kwargs)
    assert "댓글로 '고객'" in instagram_caption.build_prompt(**kwargs, feedback="다시 써라")
