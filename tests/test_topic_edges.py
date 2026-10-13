import json
from copy import deepcopy

import pytest

from reels_editor.topic_edges import trim_topic_edges
from reels_editor.edl import ordered_segments


def fixture():
    texts = ['Thanks for coming.', 'Customer feedback beats opinions.', 'Tomorrow we discuss hiring.']
    segments = {'transcript_language': 'en', 'segments': [
        {'id': f's{i}', 'text': text, 'source_start_us': i * 1_000_000, 'source_end_us': (i + 1) * 1_000_000}
        for i, text in enumerate(texts)
    ]}
    doc = {'cuts': [{'beat': '훅', 'seg_ids': ['s0']}, {'beat': '핵심', 'seg_ids': ['s1']}, {'beat': '끝', 'seg_ids': ['s2']}],
           'subtitle_translations': {'s0': '와주셔서 감사합니다.', 's1': '고객 피드백이 의견보다 중요합니다.', 's2': '내일은 채용을 이야기합니다.'}}
    return doc, segments


def runner(verdicts):
    return lambda prompt: json.dumps({'core_topic': '고객 피드백', 'segments': [
        {'id': sid, 'verdict': verdict, 'reason': '원문 발언을 평가한 근거'} for sid, verdict in verdicts.items()
    ]})


def test_one_second_off_topic_edges_trim_video_and_translations_and_empty_beats():
    doc, segments = fixture()
    original = deepcopy(doc)
    result = trim_topic_edges(doc, segments, title='고객 피드백', runner=runner({'s0': 'off_topic', 's1': 'relevant', 's2': 'off_topic'}))
    assert result['cuts'] == [{'beat': '핵심', 'seg_ids': ['s1']}]
    assert result['subtitle_translations'] == {'s1': '고객 피드백이 의견보다 중요합니다.'}
    assert ordered_segments(result, segments)[0]['source_start_us'] == 1_000_000
    assert ordered_segments(result, segments)[0]['source_end_us'] == 2_000_000
    assert result['topic_edge_review']['removed_source_us'] == 2_000_000
    assert doc == original
    assert trim_topic_edges(result, segments, title='고객 피드백', runner=lambda _: pytest.fail('already reviewed')) == result


def test_required_context_and_internal_segments_remain():
    doc, segments = fixture()
    result = trim_topic_edges(doc, segments, title='고객 피드백', runner=runner({'s0': 'context', 's1': 'off_topic', 's2': 'relevant'}))
    assert result['cuts'] == doc['cuts']
    assert result['topic_edge_review']['removed_seg_ids'] == []


@pytest.mark.parametrize('verdicts', [{}, {'s0': 'off_topic', 's1': 'off_topic', 's2': 'off_topic'}])
def test_incomplete_or_all_unrelated_review_fails_without_mutating_doc(verdicts):
    doc, segments = fixture()
    original = deepcopy(doc)
    with pytest.raises(ValueError):
        trim_topic_edges(doc, segments, title='고객 피드백', runner=runner(verdicts))
    assert doc == original


def test_trimming_cannot_leave_dependent_opener():
    doc, segments = fixture()
    doc['subtitle_translations']['s1'] = '그래서 바로 시작했습니다.'
    with pytest.raises(ValueError, match='문장 검증 실패'):
        trim_topic_edges(doc, segments, title='고객 피드백', runner=runner({'s0': 'off_topic', 's1': 'relevant', 's2': 'off_topic'}))
