import json
import threading
import urllib.request

from reels_editor import gate


def test_html_contains_titles_beats_and_warning(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, thumbs={},
                                duration_s=34.2, target_s=30)
    assert "대기업을 버린 이유" in html          # 타이틀 후보
    assert "훅" in html and "라스트 답" in html  # 비트
    assert "그래서 바로 시작했습니다" in html      # 자막 원문
    assert "⚠️" in html                          # 30s ±10% 초과 경고


def test_html_no_warning_within_tolerance(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, {}, duration_s=31.0, target_s=30)
    assert "⚠️" not in html


def test_run_gate_approve_roundtrip(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, {}, 30.0, 30)
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
