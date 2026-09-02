from __future__ import annotations

from reels_editor import title_suggestion


def _doc() -> dict:
    return {
        "story": {"five_lines": {"situation": "회사가 빠르게 성장했다"}},
        "cuts": [{"beat": "이유", "seg_ids": ["seg1"]}],
        "subtitle_translations": {},
    }


def _segments() -> dict:
    return {"segments": [{"id": "seg1", "text": "성장하면서 회사와 나를 분리하지 못했습니다"}]}


def test_generate_title_suggestion_uses_reel_evidence_and_rejects_current_title() -> None:
    prompts: list[str] = []
    responses = iter(["기존 제목 그대로", "성장이 독이 된 순간"])

    def runner(prompt: str) -> str:
        prompts.append(prompt)
        return next(responses)

    result = title_suggestion.generate_title_suggestion(
        current_title="기존 제목 그대로",
        candidate={"content_type": "failure", "summary": "성장 과정의 리더십 실패"},
        doc=_doc(),
        segments=_segments(),
        runner=runner,
    )

    assert result == "성장이 독이 된 순간"
    assert "성장하면서 회사와 나를 분리하지 못했습니다" in prompts[0]
    assert "현재 제목과 같음" in prompts[1]


def test_generate_title_suggestion_normalizes_plain_title_response() -> None:
    result = title_suggestion.generate_title_suggestion(
        current_title="기존 제목 그대로",
        candidate=None,
        doc=_doc(),
        segments=_segments(),
        runner=lambda _prompt: '제목: "리더를 무너뜨린 성장"',
    )

    assert result == "리더를 무너뜨린 성장"
