"""Shared validation and deterministic line wrapping for on-video titles."""
from __future__ import annotations

import unicodedata

MIN_TITLE_CHARS = 6
ONE_LINE_MAX_CHARS = 11
TWO_LINE_MIN_CHARS = 12
MAX_TITLE_CHARS = 24
MIN_GENERATED_TITLE_WORDS = 3

_VARIATION_SELECTORS = range(0xFE00, 0xFE10)
_SUPPLEMENTARY_VARIATION_SELECTORS = range(0xE0100, 0xE01F0)
_EMOJI_MODIFIERS = range(0x1F3FB, 0x1F400)
_REGIONAL_INDICATORS = range(0x1F1E6, 0x1F200)
_PHRASE_ENDINGS = frozenset(",.!?;:，。、！？；：·/|—–-")
_RHETORICAL_LINE_ENDINGS = (
    "는데",
    "지만",
    "보다",
    "들에게",
    "에게",
    "때",
    "해서",
    "아서",
    "어서",
    "명만",
    "개만",
    "원만",
    "앱도",
    "제품도",
    "서비스도",
    "마케팅도",
    "브랜드도",
    "아이디어도",
    "전략도",
    "팀도",
    "회사도",
    "창업자도",
    "대표도",
    "고객도",
    "성공도",
    "실패도",
    "해도",
    "인데도",
    "수록",
)


def normalize_title(text: str) -> str:
    """Compose canonically equivalent text and collapse whitespace."""
    return " ".join(unicodedata.normalize("NFC", str(text)).split())


def grapheme_like_clusters(text: str) -> tuple[str, ...]:
    """Split text into dependency-free, deterministic display-character clusters.

    This covers combining marks, variation selectors, emoji modifiers, regional
    indicator flags, and zero-width-joiner emoji sequences. It intentionally
    avoids a new regex/ICU dependency while matching the title editor's needs.
    """
    clusters: list[str] = []
    regional_run = 0
    for char in unicodedata.normalize("NFC", str(text)):
        codepoint = ord(char)
        is_regional = codepoint in _REGIONAL_INDICATORS
        extends_previous = (
            bool(clusters)
            and (
                unicodedata.combining(char) != 0
                or unicodedata.category(char) in {"Mc", "Me"}
                or codepoint in _VARIATION_SELECTORS
                or codepoint in _SUPPLEMENTARY_VARIATION_SELECTORS
                or codepoint in _EMOJI_MODIFIERS
                or char == "\u200d"
                or clusters[-1].endswith("\u200d")
                or (is_regional and regional_run % 2 == 1)
            )
        )
        if extends_previous:
            clusters[-1] += char
        else:
            clusters.append(char)
        regional_run = regional_run + 1 if is_regional else 0
    return tuple(clusters)


def title_char_count(text: str) -> int:
    """Count visible grapheme-like characters, excluding every whitespace cluster."""
    return sum(1 for cluster in grapheme_like_clusters(text) if not cluster.isspace())


def title_length_error(text: str) -> str | None:
    """Return a user-facing range error, or ``None`` when the title is valid."""
    length = title_char_count(text)
    if MIN_TITLE_CHARS <= length <= MAX_TITLE_CHARS:
        return None
    if length < MIN_TITLE_CHARS:
        return (
            f"공백 제외 {length}자로 최소 {MIN_TITLE_CHARS}자보다 짧음 — "
            "핵심 사실을 더 구체적으로 적을 것"
        )
    return (
        f"공백 제외 {length}자로 최대 {MAX_TITLE_CHARS}자를 초과함 — "
        "조사와 수식어를 덜어내고 명사구로 줄일 것"
    )


def generated_title_length_error(text: str) -> str | None:
    """Return an error when a newly generated title cannot render as two lines."""
    length = title_char_count(text)
    if length < TWO_LINE_MIN_CHARS:
        return (
            f"공백 제외 {length}자로 너무 짧음 — 생성 제목의 두 줄 표시를 위해 최소 "
            f"{TWO_LINE_MIN_CHARS}자가 필요함 — 맥락과 반전을 더 구체화할 것"
        )
    return title_length_error(text)


def generated_title_error(text: str) -> str | None:
    """Return an error when a newly generated title breaks the hook contract."""
    normalized = normalize_title(text)
    length_error = generated_title_length_error(normalized)
    if length_error:
        return length_error
    if len(normalized.split()) < MIN_GENERATED_TITLE_WORDS:
        return (
            "띄어쓰기가 부족함 — 두 의미 덩어리로 나뉘도록 자연스럽게 띄어쓴 "
            f"{MIN_GENERATED_TITLE_WORDS}어절 이상으로 쓸 것"
        )
    return None


def validate_title(text: str) -> str:
    """Normalize a title and raise ``ValueError`` when it violates the shared rule."""
    normalized = normalize_title(text)
    error = title_length_error(normalized)
    if error:
        raise ValueError(error)
    return normalized


def validate_generated_title(text: str) -> str:
    """Normalize and validate a newly generated two-line on-video title."""
    normalized = normalize_title(text)
    error = generated_title_error(normalized)
    if error:
        raise ValueError(error)
    return normalized


def wrap_title(text: str) -> tuple[str, ...]:
    """Return one 6–11-char line or two naturally balanced 12–24-char lines."""
    normalized = validate_title(text)
    if title_char_count(normalized) <= ONE_LINE_MAX_CHARS:
        return (normalized,)

    words = normalized.split(" ")
    natural: list[tuple[str, str]] = []
    for index in range(1, len(words)):
        natural.append((" ".join(words[:index]), " ".join(words[index:])))

    if not natural:
        clusters = grapheme_like_clusters(normalized)
        for index, cluster in enumerate(clusters[:-1], start=1):
            if cluster[-1] in _PHRASE_ENDINGS:
                natural.append(("".join(clusters[:index]), "".join(clusters[index:])))

    if natural:
        return min(natural, key=_balance_key)

    clusters = grapheme_like_clusters(normalized)
    midpoint = len(clusters) / 2
    split_at = min(range(1, len(clusters)), key=lambda index: (abs(index - midpoint), index))
    return "".join(clusters[:split_at]), "".join(clusters[split_at:])


def editor_title_lines(text: str) -> tuple[str, str]:
    """Return the editable white upper line and orange lower line.

    Older one-line titles remain orange by leaving the optional upper line empty.
    """
    try:
        lines = wrap_title(text)
    except ValueError:
        # Legacy/test fixtures can predate the current 6–24 character contract.
        # Keep those playable and editable as a single orange line.
        return "", normalize_title(text)
    if len(lines) == 1:
        return "", lines[0]
    return lines[0], lines[1]


def validate_editor_title_lines(upper: str, lower: str) -> tuple[str, str, str]:
    """Normalize explicit editor lines and validate their combined display title."""
    normalized_upper = normalize_title(upper)
    normalized_lower = normalize_title(lower)
    if not normalized_lower:
        raise ValueError("두 번째 제목을 입력하세요.")
    combined = validate_title(" ".join(part for part in (normalized_upper, normalized_lower) if part))
    return normalized_upper, normalized_lower, combined


def _balance_key(lines: tuple[str, str]) -> tuple[int, int, int, int]:
    left_count = title_char_count(lines[0])
    right_count = title_char_count(lines[1])
    rhetorical_rank = 0 if lines[0].endswith(_RHETORICAL_LINE_ENDINGS) else 1
    return rhetorical_rank, abs(left_count - right_count), max(left_count, right_count), left_count
