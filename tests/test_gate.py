import json
import queue
import threading
import urllib.error
import urllib.request

from reels_editor import gate
from reels_editor.config import AppConfig
from reels_editor.gate import MultiGateDecision, parse_decision, run_gate_v2
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


def test_terminal_gate_reprompts_on_invalid_title(edl_doc: dict, segments: dict) -> None:
    answers = iter(["abc", "9", "1", "y"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "approve" and d.title_index == 0
