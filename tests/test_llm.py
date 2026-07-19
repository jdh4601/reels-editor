"""프로바이더 러너: claude-cli 인자 구성 / 미지정 모델 기본값 / 키 없음 오류."""
import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from reels_editor.config import AppConfig
from reels_editor.llm import (
    PROVIDER_DEFAULTS, build_runner, claude_cli_args, codex_cli_args,
)
from reels_editor.llm_http import openai_chat_runner


def test_claude_cli_args_default_model() -> None:
    assert claude_cli_args("") == ["claude", "-p"]


def test_claude_cli_args_with_model() -> None:
    assert claude_cli_args("opus") == ["claude", "-p", "--model", "opus"]


def test_codex_cli_args_are_ephemeral_and_read_only() -> None:
    args = codex_cli_args("")
    assert args[:2] == ["codex", "exec"]
    assert "--ephemeral" in args
    assert "--skip-git-repo-check" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args


def test_codex_cli_args_with_model() -> None:
    args = codex_cli_args("gpt-5.6-sol")
    assert args[-2:] == ["--model", "gpt-5.6-sol"]


def test_build_runner_openai_without_key_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = AppConfig(provider="openai")
    with pytest.raises(RuntimeError, match="API 키"):
        build_runner(cfg, credentials=tmp_path / "none.yaml")


def test_provider_defaults_shape() -> None:
    for name in ("openai", "kimi"):
        base_url, model = PROVIDER_DEFAULTS[name]
        assert base_url.startswith("https://") and model


def _mock_server(handler_cls):
    server = HTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/v1"


def test_openai_chat_runner_success() -> None:
    captured: dict = {}

    class OK(BaseHTTPRequestHandler):
        def do_POST(self):
            captured["path"] = self.path
            captured["auth"] = self.headers.get("Authorization")
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured["body"] = body
            out = json.dumps({"choices": [{"message": {"content": '{"ok": 1}'}}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(out.encode())
        def log_message(self, *a): pass

    server, base = _mock_server(OK)
    try:
        run = openai_chat_runner(base, "sk-test", "test-model")
        assert run("프롬프트") == '{"ok": 1}'
        assert captured["path"] == "/v1/chat/completions"
        assert captured["auth"] == "Bearer sk-test"
        assert captured["body"]["model"] == "test-model"
        assert captured["body"]["messages"][0]["content"] == "프롬프트"
    finally:
        server.shutdown()
        server.server_close()


def test_openai_chat_runner_http_error_masks_key() -> None:
    class Err(BaseHTTPRequestHandler):
        def do_POST(self):
            # 요청 바디를 다 읽지 않고 응답하면 클라이언트가 응답을 읽는 도중
            # TCP RST(ConnectionResetError)를 받을 수 있어 테스트가 간헐적으로
            # 실패한다 — 드레인해서 정상 종료(FIN)를 보장한다.
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error": "bad key"}')
        def log_message(self, *a): pass

    server, base = _mock_server(Err)
    try:
        run = openai_chat_runner(base, "sk-secret-key-1234", "m")
        with pytest.raises(RuntimeError) as ei:
            run("p")
        assert "401" in str(ei.value)
        assert "sk-secret-key-1234" not in str(ei.value)   # 키 노출 금지
    finally:
        server.shutdown()
        server.server_close()


def test_openai_chat_runner_non_json_body_raises_korean_error() -> None:
    class NonJson(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            if length:
                self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>upstream proxy error</html>")
        def log_message(self, *a): pass

    server, base = _mock_server(NonJson)
    try:
        run = openai_chat_runner(base, "sk-secret-key-1234", "m")
        with pytest.raises(RuntimeError) as ei:
            run("p")
        assert "LLM 응답 형식 오류" in str(ei.value)
        assert "upstream proxy error" in str(ei.value)
        assert "sk-secret-key-1234" not in str(ei.value)   # 키 노출 금지
    finally:
        server.shutdown()
        server.server_close()


def test_claude_cli_runner_missing_binary_raises_korean_error(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'claude'")

    monkeypatch.setattr(subprocess, "run", fake_run)
    cfg = AppConfig(provider="claude-cli")
    run = build_runner(cfg)
    with pytest.raises(RuntimeError, match="claude CLI를 찾을 수 없습니다") as ei:
        run("프롬프트")
    assert "No such file or directory" in str(ei.value)


def test_codex_cli_runner_returns_last_message(monkeypatch) -> None:
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        output_path = args[args.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('{"ok": 1}')
        return subprocess.CompletedProcess(args, 0, stdout="events", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = build_runner(AppConfig(provider="codex-cli", model="gpt-5.6-sol"))

    assert run("프롬프트") == '{"ok": 1}'
    assert captured["input"] == "프롬프트"
    assert captured["args"][-1] == "-"
    assert "--output-last-message" in captured["args"]


def test_codex_cli_runner_missing_binary_raises_korean_error(monkeypatch) -> None:
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'codex'")

    monkeypatch.setattr(subprocess, "run", fake_run)
    run = build_runner(AppConfig(provider="codex-cli"))
    with pytest.raises(RuntimeError, match="Codex CLI를 찾을 수 없습니다"):
        run("프롬프트")


def test_build_runner_unknown_provider_raises_korean_error() -> None:
    cfg = AppConfig(provider="typo")
    with pytest.raises(RuntimeError, match="알 수 없는 프로바이더"):
        build_runner(cfg)
