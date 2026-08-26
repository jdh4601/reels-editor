import unicodedata

import pytest

from reels_editor.title_rules import (
    title_char_count,
    title_length_error,
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
