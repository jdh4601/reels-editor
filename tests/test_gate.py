import json
import queue
import threading
import urllib.error
import urllib.request

from reels_editor import gate
from reels_editor.config import AppConfig
from reels_editor.gate import (
    MultiGateDecision, parse_combo_selection, parse_decision,
    run_gate_terminal_v2, run_gate_v2,
)
from reels_editor.storyteller import StorylineResult


def test_html_contains_titles_beats_and_warning(edl_doc: dict, segments: dict) -> None:
    sl = [StorylineResult(0, "정면승부형", edl_doc)]
    html = gate.build_gate_html(sl, segments, {}, {0: 34.2}, 30, AppConfig(), {})
    assert "대기업을 버린 이유" in html          # 타이틀 후보
    assert "훅" in html and "라스트 답" in html  # 비트
    assert "그래서 바로 시작했습니다" in html      # 자막 원문
    assert "⚠️" in html                          # 30s ±10% 초과 경고


def test_html_no_warning_within_tolerance(edl_doc: dict, segments: dict) -> None:
    sl = [StorylineResult(0, "정면승부형", edl_doc)]
    html = gate.build_gate_html(sl, segments, {}, {0: 31.0}, 30, AppConfig(), {})
    assert "⚠️" not in html


def test_parse_decision_valid() -> None:
    d = parse_decision({"action": "render", "combos": [[0, 1], [2, 0]],
                        "regen": [], "feedback": "", "settings": {"sub_size": "52"}})
    assert d.combos == [(0, 1), (2, 0)]
    assert d.settings["sub_size"] == "52"


def test_parse_decision_rejects_bad_action() -> None:
    import pytest
    with pytest.raises(ValueError):
        parse_decision({"action": "nope", "combos": [], "regen": [],
                        "feedback": "", "settings": {}})


def test_run_gate_v2_serves_preview_and_decision() -> None:
    calls = {}

    def preview_fn(params: dict) -> bytes:
        calls["params"] = params
        return b"\x89PNG fake"

    def client(url: str) -> None:
        # 프리뷰 요청
        with urllib.request.urlopen(url + "preview?sub_size=50") as r:
            assert r.read() == b"\x89PNG fake"
        # 결정 POST
        body = json.dumps({"action": "render", "combos": [[0, 0]], "regen": [],
                           "feedback": "", "settings": {}}).encode()
        req = urllib.request.Request(url + "decision", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)

    # run_gate_v2는 블로킹이므로 클라이언트를 별도 스레드에서 실행
    q: queue.Queue = queue.Queue()

    def serve():
        q_url = q.get()
        client(q_url)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    d = run_gate_v2("<html>ok</html>", preview_fn, open_browser=False,
                    port=0, on_url=q.put)
    assert d.action == "render" and d.combos == [(0, 0)]
    assert calls["params"] == {"sub_size": "50"}


def test_run_gate_v2_ignores_malformed_post() -> None:
    """구 test_run_gate_ignores_malformed_post을 run_gate_v2/MultiGateDecision으로 이관."""
    def preview_fn(params: dict) -> bytes:
        return b""

    def client(url: str) -> None:
        bad = urllib.request.Request(url + "decision", data=b"not json",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(bad, timeout=5)
        except urllib.error.HTTPError as e:
            assert e.code == 400
        body = json.dumps({"action": "render", "combos": [[0, 0]], "regen": [],
                           "feedback": "", "settings": {}}).encode()
        req = urllib.request.Request(url + "decision", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)

    q: queue.Queue = queue.Queue()

    def serve():
        client(q.get())

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    d = run_gate_v2("<html>ok</html>", preview_fn, open_browser=False,
                    port=0, on_url=q.put)
    assert d.action == "render" and d.combos == [(0, 0)]


def _doc2():
    return {"story": {"five_lines": {}, "lens": ""},
            "title_candidates": [{"text": "가", "keyword": ""},
                                 {"text": "나", "keyword": ""}],
            "subtitle_keywords": [],
            "cuts": [{"beat": "훅", "seg_ids": ["s1"]}]}


def _segments_fixture():
    return {"segments": [{"id": "s1", "text": "안녕",
                          "source_start_us": 0, "source_end_us": 1_000_000}],
            "video_path": "v.mp4"}


def test_parse_combo_selection() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc2()),
          StorylineResult(1, "반전형", _doc2())]
    assert parse_combo_selection("1-2, 2-1", sl) == [(0, 1), (1, 0)]


def test_parse_combo_selection_rejects_out_of_range() -> None:
    import pytest
    sl = [StorylineResult(0, "정면승부형", _doc2())]
    with pytest.raises(ValueError):
        parse_combo_selection("2-1", sl)
    with pytest.raises(ValueError):
        parse_combo_selection("1-9", sl)
    with pytest.raises(ValueError):
        parse_combo_selection("난수", sl)


def test_run_gate_terminal_v2_render_flow() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc2())]
    answers = iter(["1-1", "y"])
    d = run_gate_terminal_v2(sl, _segments_fixture(), {0: 30.0}, 30,
                             input_fn=lambda _: next(answers))
    assert d.action == "render" and d.combos == [(0, 0)]


def test_terminal_gate_approve(edl_doc: dict, segments: dict) -> None:
    sl = [StorylineResult(0, "정면승부형", edl_doc)]
    answers = iter(["1-1", "y"])
    d = run_gate_terminal_v2(sl, segments, {0: 30.0}, 30,
                             input_fn=lambda _p: next(answers))
    assert d.action == "render" and d.combos == [(0, 0)]


def test_terminal_gate_revise(edl_doc: dict, segments: dict) -> None:
    sl = [StorylineResult(0, "정면승부형", edl_doc)]
    answers = iter(["1-1", "훅을 더 강하게"])
    d = run_gate_terminal_v2(sl, segments, {0: 30.0}, 30,
                             input_fn=lambda _p: next(answers))
    assert d.action == "revise" and d.feedback == "훅을 더 강하게" and d.regen == [0]


def test_terminal_gate_reprompts_on_invalid_combo(edl_doc: dict, segments: dict) -> None:
    """구 test_terminal_gate_reprompts_on_invalid_title을 조합 선택 방식으로 이관.

    비숫자 입력("abc")과 범위 밖 스토리라인 인덱스("9-1") 모두 재입력을
    유발한 뒤, 유효한 조합("1-1")으로 렌더가 진행되는지 검증한다.
    """
    sl = [StorylineResult(0, "정면승부형", edl_doc)]
    answers = iter(["abc", "9-1", "1-1", "y"])
    d = run_gate_terminal_v2(sl, segments, {0: 30.0}, 30,
                             input_fn=lambda _p: next(answers))
    assert d.action == "render" and d.combos == [(0, 0)]
