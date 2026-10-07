from __future__ import annotations

from reels_editor import instagram_caption


def _valid_caption(episode: int = 2) -> str:
    return (
        f"Ep {episode}. 광고 없이 첫 고객을 만든 실험\n\n"
        "마루 창업자 김대표는 제품보다 고객 대화가 먼저라고 말한다.\n\n"
        "반복되는 불편 중 돈을 낼 문제 하나를 찾는 것이 핵심이다.\n\n"
        "고객은 어떤 문제에 돈을 내는가?\n"
        f"{instagram_caption.CTA}"
    )


def test_build_prompt_contains_only_reel_evidence() -> None:
    prompt = instagram_caption.build_prompt(
        episode_number=2,
        selected_title="광고 없이 첫 고객을 만든 방법",
        candidate={
            "content_type": "strategy",
            "title": "첫 고객 인터뷰",
            "summary": "잠재 고객을 직접 만났다",
            "takeaway": "광고보다 문제 검증이 먼저다",
        },
        doc={
            "speaker": {"name": "김대표", "role": "Founder"},
            "cuts": [{"beat": "전략", "seg_ids": ["s1"]}],
        },
        segments={"segments": [{"id": "s1", "text": "첫 고객을 직접 만났습니다"}]},
    )

    assert "Ep 2." in prompt
    assert "광고보다 문제 검증이 먼저다" in prompt
    assert "첫 고객을 직접 만났습니다" in prompt
    assert "300자 이내" in prompt
    assert "정확히 3문단" in prompt
    assert "~한다." in prompt


def test_generate_caption_returns_grounded_valid_format() -> None:
    caption = instagram_caption.generate_caption(
        episode_number=2,
        selected_title="첫 고객",
        candidate=None,
        doc={"cuts": []},
        segments={"segments": []},
        runner=lambda _prompt: _valid_caption(),
    )

    assert caption.startswith("Ep 2. ")
    assert caption.endswith(instagram_caption.CTA)
    assert instagram_caption.validate_caption(caption, 2) == []


def test_generate_caption_retries_invalid_structure() -> None:
    prompts: list[str] = []

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return "짧은 캡션" if len(prompts) == 1 else _valid_caption()

    caption = instagram_caption.generate_caption(
        episode_number=2,
        selected_title="첫 고객",
        candidate=None,
        doc={"cuts": []},
        segments={"segments": []},
        runner=runner,
    )

    assert caption == _valid_caption()
    assert len(prompts) == 2
    assert "이전 캡션이 검증에 실패했다" in prompts[1]


def test_append_source_credit_adds_normalized_channel_and_url_as_last_line() -> None:
    caption = instagram_caption.append_source_credit(
        _valid_caption(),
        channel_name="  Y   Combinator  ",
        source_url=" https://youtu.be/abc123 ",
    )

    assert caption.endswith("원본 출처: Y Combinator https://youtu.be/abc123")
    assert caption.splitlines()[-1] == "원본 출처: Y Combinator https://youtu.be/abc123"
    assert caption.count("원본 출처:") == 1


def test_rejects_old_polite_style_and_extra_paragraphs() -> None:
    assert instagram_caption.validate_caption(_valid_caption().replace("말한다.", "말합니다."), 2)
    assert instagram_caption.validate_caption(_valid_caption().replace("핵심이다.", "핵심이다.\n\n추가 문단이다."), 2)


def test_rejects_long_question() -> None:
    caption = _valid_caption().replace("고객은 어떤 문제에 돈을 내는가?", "지금 당신의 사업에서 고객이 돈을 내고 해결하고 싶은 문제는 무엇인가?")
    assert any("질문이 30자" in error for error in instagram_caption.validate_caption(caption, 2))


def test_source_credit_counts_toward_300_character_limit() -> None:
    import pytest
    with pytest.raises(ValueError, match="출처 포함"):
        instagram_caption.append_source_credit("가" * 280, channel_name="채널", source_url="https://youtu.be/abc123")


def test_generation_reserves_source_budget_and_requires_company() -> None:
    prompts = []
    def runner(prompt):
        prompts.append(prompt)
        return _valid_caption()
    caption = instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표", "company": "마루", "role": "창업자",
                         "evidence": "마루 창업자 김대표"}},
        segments={"segments": []}, runner=runner,
        channel_name="Y Combinator", source_url="https://youtu.be/abc123")
    full = instagram_caption.append_source_credit(caption, channel_name="Y Combinator", source_url="https://youtu.be/abc123")
    assert len(full) <= 300
    assert "마루 창업자" in prompts[0]
    budget = 300 - len("\n\n원본 출처: Y Combinator https://youtu.be/abc123")
    assert f"출력은 최대 {budget}자" in prompts[0]


def test_generation_retries_when_company_is_missing() -> None:
    calls = []
    def runner(prompt):
        calls.append(prompt)
        return _valid_caption().replace("마루 창업자", "창업자") if len(calls) == 1 else _valid_caption()
    instagram_caption.generate_caption(
        episode_number=2, selected_title="첫 고객", candidate=None,
        doc={"speaker": {"name": "김대표", "company": "마루", "role": "창업자",
                         "evidence": "마루 창업자 김대표"}},
        segments={"segments": []}, runner=runner)
    assert len(calls) == 2
    assert "기업명이 빠짐" in calls[1]
