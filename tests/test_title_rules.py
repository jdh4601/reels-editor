import unicodedata

import pytest

from reels_editor.title_rules import (
    title_char_count,
    title_length_error,
    validate_generated_title,
    validate_title,
    wrap_title,
)


@pytest.mark.parametrize(
    ("text", "expected_lines"),
    [
        ("가나다라마바사", ("가나다라마바사",)),
        ("가나다라마바사아자차카", ("가나다라마바사아자차카",)),
        ("가나다라마바사아자차카타", ("가나다라마바", "사아자차카타")),
        ("가" * 24, ("가" * 12, "가" * 12)),
    ],
)
def test_title_boundaries_choose_required_line_count(
    text: str,
    expected_lines: tuple[str, ...],
) -> None:
    assert wrap_title(text) == expected_lines
    assert all(expected_lines)


@pytest.mark.parametrize("text", ["가나다라마", "가" * 25, "   "])
def test_invalid_title_lengths_are_rejected(text: str) -> None:
    assert title_length_error(text)
    with pytest.raises(ValueError):
        validate_title(text)


def test_generated_titles_must_fill_two_lines() -> None:
    with pytest.raises(ValueError, match="두 줄 표시를 위해 최소 12자"):
        validate_generated_title("짧지만 유효한 제목")
    with pytest.raises(ValueError, match="3어절 이상"):
        validate_generated_title("가" * 12)

    title = validate_generated_title("마케팅은 훌륭한데 망하는 브랜드의 특징")

    assert len(wrap_title(title)) == 2


@pytest.mark.parametrize(
    ("text", "expected_lines"),
    [
        ("마케팅은 훌륭한데 망하는 브랜드의 특징", ("마케팅은 훌륭한데", "망하는 브랜드의 특징")),
        ("제품을 만드는 것보다 훨씬 중요한 창업가의 자질", ("제품을 만드는 것보다", "훨씬 중요한 창업가의 자질")),
        ("1인 창업가들에게 가장 과대평가된 조언", ("1인 창업가들에게", "가장 과대평가된 조언")),
        ("공동창업자를 찾을 때 가장 먼저 봐야하는 것", ("공동창업자를 찾을 때", "가장 먼저 봐야하는 것")),
        ("미친듯이 만들어서 뭐라도 보여줘야 한다", ("미친듯이 만들어서", "뭐라도 보여줘야 한다")),
        ("고객 딱 100명만 확실히 만족시키자", ("고객 딱 100명만", "확실히 만족시키자")),
        ("완벽한 앱도 마케팅이 최악이면 끝이다", ("완벽한 앱도", "마케팅이 최악이면 끝이다")),
        ("창업자가 성공할수록 조심해야 하는 이유", ("창업자가 성공할수록", "조심해야 하는 이유")),
    ],
)
def test_proven_hooks_wrap_at_their_curiosity_turn(
    text: str,
    expected_lines: tuple[str, str],
) -> None:
    assert wrap_title(text) == expected_lines


def test_whitespace_is_excluded_and_natural_boundary_is_balanced() -> None:
    title = "첫 고객 없이 버틴 창업자의 선택"

    assert title_char_count(title) == 13
    assert wrap_title(title) == ("첫 고객 없이 버틴", "창업자의 선택")


def test_punctuation_latin_and_no_space_strings_are_deterministic() -> None:
    assert title_char_count("A\u0301BC-12") == 6
    assert wrap_title("ABCDEF-GHIJK") == ("ABCDEF-", "GHIJK")
    assert wrap_title("가나다라마바사아자차카타") == ("가나다라마바", "사아자차카타")


def test_canonically_equivalent_korean_titles_count_wrap_and_persist_identically() -> None:
    composed = "가나다라마바"
    decomposed = unicodedata.normalize("NFD", composed)

    assert title_char_count(decomposed) == title_char_count(composed) == 6
    assert wrap_title(decomposed) == wrap_title(composed) == (composed,)
    assert validate_title(decomposed) == composed
