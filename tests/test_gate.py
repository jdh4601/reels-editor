import json
import threading
import time
import urllib.error
import urllib.request

from reels_editor import gate
from reels_editor.config import AppConfig
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


def test_run_gate_approve_roundtrip() -> None:
    html = "<html>ok</html>"  # run_gate는 html 내용을 검사하지 않음
    result: list[gate.GateDecision] = []

    def serve() -> None:
        result.append(gate.run_gate(html, open_browser=False, port=8765))

    t = threading.Thread(target=serve)
    t.start()
    body = json.dumps({"action": "approve", "title_index": 0, "feedback": ""}).encode()
    req = urllib.request.Request("http://127.0.0.1:8765/decision", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5)
    t.join(timeout=5)
    assert result and result[0].action == "approve" and result[0].title_index == 0


def test_terminal_gate_approve(edl_doc: dict, segments: dict) -> None:
    answers = iter(["1", "y"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "approve" and d.title_index == 0


def test_terminal_gate_revise(edl_doc: dict, segments: dict) -> None:
    answers = iter(["1", "훅을 더 강하게"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "revise" and d.feedback == "훅을 더 강하게"


def test_run_gate_ignores_malformed_post() -> None:
    html = "<html>ok</html>"  # run_gate는 html 내용을 검사하지 않음
    result: list[gate.GateDecision] = []

    def serve() -> None:
        result.append(gate.run_gate(html, open_browser=False, port=8767))

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    time.sleep(0.1)  # Let server start
    bad = urllib.request.Request("http://127.0.0.1:8767/decision", data=b"not json",
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(bad, timeout=5)
    except urllib.error.HTTPError as e:
        assert e.code == 400
    body = json.dumps({"action": "approve", "title_index": 0, "feedback": ""}).encode()
    req = urllib.request.Request("http://127.0.0.1:8767/decision", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5)
    t.join(timeout=5)
    assert result and result[0].action == "approve"


def test_terminal_gate_reprompts_on_invalid_title(edl_doc: dict, segments: dict) -> None:
    answers = iter(["abc", "9", "1", "y"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "approve" and d.title_index == 0
