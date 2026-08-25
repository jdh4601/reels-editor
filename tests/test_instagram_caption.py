from __future__ import annotations

from reels_editor import instagram_caption


def _valid_caption(episode: int = 2) -> str:
    return (
        f"Ep {episode}. 광고 없이 첫 고객을 만든 가장 작은 실험\n\n"
        "이 창업가는 제품을 완성한 뒤 고객을 찾지 않았습니다. 해결하려는 문제가 실제로 존재하는지 확인하기 위해 가장 가까운 잠재 고객부터 직접 만났습니다. 거창한 출시보다 대화가 먼저였습니다.\n\n"
        "첫 고객은 광고 예산에서 나오지 않았습니다. 반복해서 들리는 불편을 정리하고, 그중 비용을 지불할 만큼 큰 문제 하나에 집중한 결과였습니다. 기능을 더하는 대신 구매 이유를 선명하게 만들었습니다.\n\n"
        "1인 창업가에게 중요한 것은 많은 사람에게 알리는 속도보다 누구의 어떤 문제를 해결하는지 확인하는 순서입니다. 작은 인터뷰와 유료 제안은 제품 개발과 마케팅을 동시에 검증하는 가장 현실적인 방법이 될 수 있습니다.\n\n"
        "여러분은 지금 제품을 설명하고 있나요, 아니면 고객이 돈을 내고 해결하고 싶은 문제를 확인하고 있나요?\n\n"
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
    assert "Comfrt나 수치·사실은 절대 가져오지 않는다" in prompt


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
