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


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1
