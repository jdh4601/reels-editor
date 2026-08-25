"""자막 문장 경계 판별과 완결성 검증.

YouTube 자막은 한 문장이 여러 cue로 잘리는 경우가 많다. 이 모듈은 cue의
길이가 아니라 문장 종결과 큰따옴표의 닫힘을 기준으로 화면 자막을 묶는다.
"""
from __future__ import annotations

import re
from typing import Any


_SENTENCE_PUNCTUATION = ".!?。！？"
_CLOSING_MARKS = "\"'”’）)]"
_KOREAN_SENTENCE_ENDING = re.compile(
    r"(?:"
    r"습니다|습니까|입니다|아닙니다|합니다|됩니까|됩니다|"
    r"했어요|해요|돼요|예요|이에요|거예요|겁니다|"
    r"더라고요|잖아요|거든요|라고요|려고요|고요|"
    r"어요|아요|죠|네요|군요|나요|세요|래요|대요|데요|까요|"
    r"했다|한다|된다|있다|없다|이다|아니다|였다|이었다|"
    r"느냐|(?:해\s*)?봐라(?:\s*[ㅎㅋ]+)?"
    r")$"
)
_DANGLING_KOREAN_ENDING = re.compile(
    r"(?:"
    r"은|는|이|가|을|를|도|만|와|과|의|에|에서|에게|한테|로|으로|"
    r"부터|까지|보다|처럼|그리고|하지만|그러나|그래서|"
    r"때문에|위해|대해|통해|하면서|하고|하며|거나|"
    r"지만|는데|은데|인데|니까|해서|같고|싶고|했고|였고|됐고|되고"
    r")$"
)
_CLAUSE_ENDING = re.compile(
    r"(?:"
    r"고|며|면서|지만|는데|은데|인데|다가|거나|든지|"
    r"면|으면|라면|다면|니까|으니까|므로|으므로|"
    r"해서|하여|아서|어서|여서|때문에|반면|대신"
    r")$"
)
_CLAUSE_PUNCTUATION = ",;:，；："
_BOUND_NOUNS = {"것", "수", "때", "점", "만큼", "듯", "데", "바", "줄", "리", "뿐"}


def double_quotes_balanced(text: str) -> bool:
    """ASCII/curly 큰따옴표가 모두 짝을 이루는지 검사한다."""
    ascii_open = False
    curly_depth = 0
    for index, char in enumerate(text):
        if char == '"' and not _is_escaped(text, index):
            ascii_open = not ascii_open
        elif char == "“":
            curly_depth += 1
        elif char == "”":
            if curly_depth == 0:
                return False
            curly_depth -= 1
    return not ascii_open and curly_depth == 0


def is_complete_sentence(text: str) -> bool:
    """화면에 독립적으로 보여도 되는 완결 문장인지 판별한다."""
    normalized = " ".join(str(text).split())
    if not normalized or not double_quotes_balanced(normalized):
        return False
    semantic_tail = normalized.rstrip(_CLOSING_MARKS).rstrip()
    semantic_tail = semantic_tail.rstrip(_SENTENCE_PUNCTUATION).rstrip()
    semantic_tail = semantic_tail.rstrip(_CLOSING_MARKS).rstrip()
    if _DANGLING_KOREAN_ENDING.search(semantic_tail):
        return False
    if re.search(rf"[{re.escape(_SENTENCE_PUNCTUATION)}][{re.escape(_CLOSING_MARKS)}]*$", normalized):
        return True
    without_closers = normalized.rstrip(_CLOSING_MARKS).rstrip()
    return bool(_KOREAN_SENTENCE_ENDING.search(without_closers))


def sentence_chunks(text: str) -> list[str]:
    """큰따옴표 안의 문장은 닫는 따옴표까지 한 덩어리로 유지해 분리한다."""
    normalized = " ".join(str(text).split())
    if not normalized:
        return [""]

    chunks: list[str] = []
    start = 0
    ascii_open = False
    curly_depth = 0
    index = 0
    while index < len(normalized):
        char = normalized[index]
        if char == '"' and not _is_escaped(normalized, index):
            ascii_open = not ascii_open
        elif char == "“":
            curly_depth += 1
        elif char == "”" and curly_depth:
            curly_depth -= 1

        if char not in _SENTENCE_PUNCTUATION:
            index += 1
            continue

        boundary = index + 1
        while boundary < len(normalized) and normalized[boundary] in _SENTENCE_PUNCTUATION:
            boundary += 1
        while boundary < len(normalized) and normalized[boundary] in _CLOSING_MARKS:
            closing = normalized[boundary]
            if closing == '"' and not _is_escaped(normalized, boundary):
                ascii_open = not ascii_open
            elif closing == "”" and curly_depth:
                curly_depth -= 1
            boundary += 1

        next_is_boundary = boundary == len(normalized) or normalized[boundary].isspace()
        if not ascii_open and curly_depth == 0 and next_is_boundary:
            chunk = normalized[start:boundary].strip()
            if chunk:
                chunks.append(chunk)
            while boundary < len(normalized) and normalized[boundary].isspace():
                boundary += 1
            start = boundary
            index = boundary
            continue
        index += 1

    tail = normalized[start:].strip()
    if tail:
        chunks.append(tail)
    return chunks or [""]


def group_complete_sentences(items: list[list[Any]]) -> list[list[Any]]:
    """타임라인 cue를 완결 문장 단위로 병합하고 각 문장 시간을 보존한다."""
    expanded: list[list[Any]] = []
    for start, end, text in items:
        chunks = sentence_chunks(str(text))
        if len(chunks) <= 1:
            expanded.append([start, end, text])
            continue
        weights = [max(1, len(chunk.replace(" ", ""))) for chunk in chunks]
        total_weight = sum(weights)
        cursor = float(start)
        for chunk_index, (chunk, weight) in enumerate(zip(chunks, weights)):
            chunk_end = (
                float(end)
                if chunk_index == len(chunks) - 1
                else cursor + (float(end) - float(start)) * weight / total_weight
            )
            expanded.append([round(cursor, 3), round(chunk_end, 3), chunk])
            cursor = chunk_end

    groups: list[list[Any]] = []
    buffer: list[Any] | None = None
    for start, end, text in expanded:
        normalized = " ".join(str(text).split())
        if not normalized:
            if buffer:
                buffer[1] = end
            continue
        if buffer is None:
            buffer = [start, end, normalized]
        elif is_complete_sentence(str(buffer[2])):
            groups.append(buffer)
            buffer = [start, end, normalized]
        else:
            buffer[1] = end
            buffer[2] = f"{buffer[2]} {normalized}".strip()
    if buffer:
        groups.append(buffer)
    return groups


def completeness_errors(groups: list[list[Any]]) -> list[str]:
    """최종 자막 그룹에서 문장 중단과 열린 큰따옴표를 찾아낸다."""
    errors: list[str] = []
    for index, (_start, _end, text) in enumerate(groups, start=1):
        normalized = " ".join(str(text).split())
        if not double_quotes_balanced(normalized):
            errors.append(f"자막 {index}: 큰따옴표가 닫히지 않음")
        elif not is_complete_sentence(normalized):
            errors.append(f"자막 {index}: 문장이 중간에서 끊김")
    return errors


def split_display_phrases(
    groups: list[list[Any]],
    max_chars: int = 20,
    min_chars: int = 6,
) -> list[list[Any]]:
    """완결 문장을 한 줄에 맞는 의미 절로 나누고 시간을 비례 배분한다."""
    display_groups: list[list[Any]] = []
    for start, end, text in groups:
        chunks = semantic_phrase_chunks(str(text), max_chars=max_chars, min_chars=min_chars)
        if len(chunks) == 1:
            display_groups.append([start, end, chunks[0]])
            continue
        weights = [max(1, _visible_length(chunk)) for chunk in chunks]
        total_weight = sum(weights)
        cursor = float(start)
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            chunk_end = (
                float(end)
                if index == len(chunks) - 1
                else cursor + (float(end) - float(start)) * weight / total_weight
            )
            display_groups.append([round(cursor, 3), round(chunk_end, 3), chunk])
            cursor = chunk_end
    return display_groups


def semantic_phrase_chunks(text: str, max_chars: int = 20,
                           min_chars: int = 6) -> list[str]:
    """쉼표와 연결어미를 우선해 한 문장을 읽기 좋은 한 줄 조각으로 나눈다.

    긴 인용문도 같은 기준으로 나눈다. 의미 경계가 전혀 없는 매우 긴 문장만
    조사·의존명사 분리를 피한 공백 위치와 글자 경계를 최후 수단으로 사용한다.
    """
    normalized = " ".join(str(text).split())
    if not normalized or _visible_length(normalized) <= max_chars:
        return [normalized]
    if _is_outer_double_quote(normalized):
        normalized = normalized[1:-1].strip()

    semantic, fallback = _phrase_boundaries(normalized)
    if _visible_length(normalized) <= max_chars + 2 and not semantic:
        return [normalized]
    chunks: list[str] = []
    start = 0
    while _visible_length(normalized[start:]) > max_chars:
        semantic_choices = _eligible_boundaries(
            normalized, start, semantic, max_chars + 2, min_chars
        )
        if semantic_choices:
            boundary = _choose_semantic_boundary(normalized, semantic_choices, min_chars)
        else:
            safe_fallback = [
                boundary
                for boundary in _eligible_boundaries(
                    normalized, start, fallback, max_chars, min_chars
                )
                if _safe_fallback(normalized, start, boundary)
            ]
            choices = safe_fallback or _eligible_boundaries(
                normalized, start, fallback, max_chars, min_chars
            )
            if not choices:
                boundary = _hard_boundary(normalized, start, max_chars)
            else:
                boundary = choices[-1]
            if boundary <= start:
                break
        chunk = normalized[start:boundary].strip()
        if chunk:
            chunks.append(chunk)
        start = boundary
        while start < len(normalized) and normalized[start].isspace():
            start += 1

    tail = normalized[start:].strip()
    if tail:
        chunks.append(tail)
    cleaned = [_balance_display_quotes(chunk) for chunk in chunks]
    return [chunk for chunk in cleaned if chunk] or [normalized]


def _phrase_boundaries(text: str) -> tuple[list[int], list[int]]:
    semantic: list[int] = []
    fallback: list[int] = []
    token_start = 0
    for index, char in enumerate(text):
        if char in _CLAUSE_PUNCTUATION + _SENTENCE_PUNCTUATION:
            boundary = index + 1
            while boundary < len(text) and text[boundary] in _CLOSING_MARKS:
                boundary += 1
            semantic.append(boundary)
        if not char.isspace():
            continue
        fallback.append(index)
        token = text[token_start:index].rstrip(_CLAUSE_PUNCTUATION)
        if _CLAUSE_ENDING.search(token):
            semantic.append(index)
        token_start = index + 1
    return sorted(set(semantic)), sorted(set(fallback))


def _eligible_boundaries(text: str, start: int, boundaries: list[int],
                         max_chars: int, min_chars: int) -> list[int]:
    return [
        boundary
        for boundary in boundaries
        if boundary > start
        and _visible_length(text[start:boundary]) >= min_chars
        and _visible_length(text[start:boundary]) <= max_chars
    ]


def _choose_semantic_boundary(text: str, choices: list[int], min_chars: int) -> int:
    for boundary in reversed(choices):
        tail = text[boundary:].lstrip()
        if len(choices) > 1 and re.match(r"^(?:이?라고|이?라며|이?라는)", tail):
            continue
        if tail and _visible_length(tail) < min_chars:
            continue
        return boundary
    return choices[-1]


def _safe_fallback(text: str, start: int, boundary: int) -> bool:
    left = text[start:boundary].strip().rstrip(_CLAUSE_PUNCTUATION)
    right = text[boundary:].strip()
    if not left or not right:
        return False
    if _DANGLING_KOREAN_ENDING.search(left):
        return False
    first_right = right.split(maxsplit=1)[0].strip(_CLAUSE_PUNCTUATION)
    return first_right not in _BOUND_NOUNS


def _hard_boundary(text: str, start: int, max_chars: int) -> int:
    """공백이 없는 긴 문자열도 고정 폰트 폭을 넘지 않게 자른다."""
    boundary = start
    for index in range(start + 1, len(text) + 1):
        if _visible_length(text[start:index]) > max_chars:
            break
        boundary = index
    return boundary


def _is_outer_double_quote(text: str) -> bool:
    return (
        len(text) >= 2
        and ((text[0] == '"' and text[-1] == '"') or (text[0] == "“" and text[-1] == "”"))
    )


def _balance_display_quotes(text: str) -> str:
    normalized = text.strip()
    if double_quotes_balanced(normalized):
        return normalized
    open_curly = normalized.count("“")
    close_curly = normalized.count("”")
    if open_curly > close_curly:
        return normalized + "”" * (open_curly - close_curly)
    if close_curly > open_curly:
        return "“" * (close_curly - open_curly) + normalized
    if normalized.count('"') % 2:
        quote_index = normalized.find('"')
        before = normalized[:quote_index].rstrip()
        after = normalized[quote_index + 1:].lstrip()
        closing_suffix = re.match(r"^(?:이?라고|이?라며|이?라는)", after)
        if not after or closing_suffix or before.endswith(tuple(_SENTENCE_PUNCTUATION)):
            return '"' + normalized
        return normalized + '"'
    return normalized


def _visible_length(text: str) -> int:
    return len(text.translate(str.maketrans("", "", ",.")).strip())


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1
