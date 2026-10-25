"""LLM 프로바이더 러너 팩토리. storyteller의 runner 주입점에 꽂는다.

claude-cli: 로컬 Claude Code. codex-cli: OpenAI Codex CLI.
gemini-cli: Google Gemini CLI. openai/kimi/custom: OpenAI-호환 chat/completions.
"""
from __future__ import annotations

import subprocess
import base64
import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable

from reels_editor import processes
from reels_editor.config import PROVIDERS, AppConfig, resolve_api_key

TIMEOUT_S = 600
# Candidate scripts, topic reviews and speaker lookups share the same Codex
# account. Hold the slot through backoff so queued work cannot amplify a 429.
_CODEX_SLOT = threading.BoundedSemaphore(1)
_REVIEW_SLOT = threading.BoundedSemaphore(1)
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o"),
    "kimi": ("https://api.moonshot.ai/v1", "kimi-k2-0905-preview"),
}


class _CodexFailure(RuntimeError):
    def __init__(self, output: str):
        # Ignore echoed prompt content when deciding whether an error is retryable.
        errors = [line.strip() for line in output.splitlines()
                  if line.strip().lower().startswith(("error:", "error "))]
        diagnostics = "\n".join(dict.fromkeys(errors)) if errors else output.strip()[-500:]
        lowered = diagnostics.lower()
        quota = any(marker in lowered for marker in (
            "insufficient_quota", "usage_limit_reached", "usage limit",
            "quota exceeded", "exceeded your current quota", "billing hard limit",
        ))
        self.rate_limited = not quota and any(marker in lowered for marker in (
            "429", "too many requests", "rate_limit_exceeded", "rate limit",
        ))
        self.at_capacity = "selected model is at capacity" in lowered
        self.retryable = not quota and (self.rate_limited or self.at_capacity)
        if quota:
            detail = "Codex 사용 한도에 도달했습니다. 계정의 사용량·한도 초기화 시점을 확인한 뒤 다시 시도하세요."
        elif self.rate_limited:
            detail = "Codex 요청이 제한되었습니다(429 Too Many Requests). 잠시 후 다시 시도하세요."
        elif self.at_capacity:
            detail = "AI 모델의 처리 용량이 부족합니다. 잠시 후 이 클립만 다시 시도하세요."
        else:
            # Human CLI output echoes the entire input transcript before ERROR.
            # Surface diagnostics, never thousands of characters of source text.
            detail = "codex exec 실패:\n" + (diagnostics[-1000:] or "오류 출력 없음")
        super().__init__(detail)


def summarize_codex_error(error: str) -> str:
    """Also format failures persisted by older engines, without changing history."""
    prefix, marker, _ = error.partition("codex exec 실패:")
    if marker:
        return (prefix if len(prefix) < 150 else "") + str(_CodexFailure(error))
    return error


def claude_cli_args(model: str) -> list[str]:
    args = ["claude", "-p"]
    if model:
        args += ["--model", model]
    return args


def run_opus_review(prompt: str, images: list[Path]) -> str:
    """Send actual images to Opus; no file/code tools or inherited project setup."""
    content = [{"type": "text", "text": prompt}]
    for path in images:
        content.extend([
            {"type": "text", "text": f"SCREENSHOT SHEET: {path.name}"},
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
             "data": base64.b64encode(path.read_bytes()).decode('ascii')}},
        ])
    message = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + '\n'
    registry = processes.current_registry()
    while not _REVIEW_SLOT.acquire(timeout=0.1):
        if registry and registry.cancelled:
            raise RuntimeError('job was cancelled')
    try:
        for attempt in range(3):
            with tempfile.TemporaryDirectory(prefix='reels-opus-review-') as tmp:
                response = processes.run([
                    *claude_cli_args('opus'), '--input-format', 'stream-json',
                    '--output-format', 'stream-json', '--verbose', '--tools', '',
                    '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                    '--setting-sources', '', '--no-session-persistence',
                ], input=message, cwd=tmp, capture_output=True, text=True, timeout=TIMEOUT_S)
            events = []
            for line in response.stdout.splitlines():
                try:
                    event=json.loads(line)
                    if isinstance(event,dict):events.append(event)
                except ValueError:
                    continue
            result = next((event for event in reversed(events) if event.get('type') == 'result'), None)
            if not response.returncode and result and not result.get('is_error') and str(result.get('result','')).strip():
                return result['result']
            detail=(response.stderr or (result or {}).get('result') or '유효한 최종 응답 없음')[-500:]
            lowered=detail.lower()
            transient=any(marker in lowered for marker in ('429','rate_limit_error','overloaded','503','529'))
            quota=any(marker in lowered for marker in ('usage limit','quota','credit balance','billing'))
            if attempt==2 or not transient or quota:
                raise RuntimeError('Opus 영상 검수 호출 실패: '+detail)
            for _ in range(50 * (attempt+1)):
                if registry and registry.cancelled:raise RuntimeError('job was cancelled')
                time.sleep(.1)
        raise AssertionError('unreachable')
    except FileNotFoundError as exc:
        raise RuntimeError('Opus 검수에 필요한 Claude CLI를 찾을 수 없습니다.') from exc
    finally:
        _REVIEW_SLOT.release()


def codex_cli_args(model: str) -> list[str]:
    """스토리 생성 전용 Codex 호출 인자.

    사용자 config/프로젝트 규칙을 읽지 않고 임시 read-only 세션에서 실행해
    Codex가 영상 프로젝트나 저장소를 수정할 수 없도록 한다.
    """
    args = [
        "codex", "exec", "--ephemeral", "--skip-git-repo-check",
        "--sandbox", "read-only", "--ignore-user-config", "--ignore-rules",
        "--color", "never",
    ]
    if model:
        args += ["--model", model]
    return args


def gemini_cli_args(model: str) -> list[str]:
    """스토리 생성 전용 Gemini 호출 인자.

    plan 승인 모드로 도구가 파일을 수정할 수 없게 하고, 설치된 확장을 전부
    비활성화해 사용자 환경에 따라 결과가 달라지지 않도록 한다.
    """
    args = [
        "gemini", "--approval-mode", "plan",
        "--output-format", "text", "-e", "none",
    ]
    if model:
        args += ["--model", model]
    return args


def _claude_cli_runner(model: str) -> Callable[[str], str]:
    def run(prompt: str) -> str:
        try:
            r = processes.run([*claude_cli_args(model), prompt],
                              capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude -p 타임아웃({TIMEOUT_S}초): {e}") from e
        except FileNotFoundError as e:
            raise RuntimeError(
                "claude CLI를 찾을 수 없습니다 — Claude Code CLI가 설치되어 있고 "
                "PATH에 등록되어 있는지 확인하거나, 설정 패널에서 다른 프로바이더로 "
                f"전환하세요: {e}") from e
        if r.returncode != 0:
            detail = (r.stderr or r.stdout).strip()[-2000:]
            if not detail:
                detail = f"종료 코드 {r.returncode} (오류 출력 없음)"
            raise RuntimeError(f"claude -p 실패:\n{detail}")
        return r.stdout
    return run


def _codex_cli_runner(model: str, *, web_search: bool = False) -> Callable[[str], str]:
    def attempt(prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="reels-codex-") as tmp:
            output_path = Path(tmp) / "last-message.txt"
            args = [
                *codex_cli_args(model), "-C", tmp,
                "--output-last-message", str(output_path), "-",
            ]
            if web_search:
                args[2:2] = ["-c", 'web_search="live"']
            try:
                result = processes.run(
                    args, input=prompt, capture_output=True, text=True,
                    timeout=180 if web_search else TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"codex exec 타임아웃({TIMEOUT_S}초): {e}") from e
            except FileNotFoundError as e:
                raise RuntimeError(
                    "Codex CLI를 찾을 수 없습니다 — OpenAI Codex CLI가 설치되어 있고 "
                    f"PATH에 등록되어 있는지 확인하세요: {e}") from e
            if result.returncode != 0:
                raise _CodexFailure("\n".join((result.stderr or "", result.stdout or "")))
            output = (
                output_path.read_text(encoding="utf-8")
                if output_path.is_file()
                else ""
            )
            if output.strip():
                return output

            # In non-JSON mode Codex also writes the final answer to stdout.
            # Some successful CLI runs have omitted --output-last-message, so
            # retain that response instead of failing every selected reel.
            if result.stdout.strip():
                return result.stdout

            detail = result.stderr.strip()[-2000:]
            if not detail:
                detail = "종료 코드 0 (응답 및 오류 출력 없음)"
            raise RuntimeError(f"codex exec가 최종 응답을 생성하지 않았습니다.\n{detail}")

    def run(prompt: str) -> str:
        registry = processes.current_registry()

        def check_cancelled() -> None:
            if registry is not None and registry.cancelled:
                raise RuntimeError("job was cancelled")

        while not _CODEX_SLOT.acquire(timeout=0.1):
            check_cancelled()
        try:
            for retry in range(3):
                check_cancelled()
                try:
                    return attempt(prompt)
                except _CodexFailure as exc:
                    if not exc.retryable or retry == 2:
                        raise
                    # A CLI retry limit can exhaust before an upstream rate
                    # window resets. Wait longer for 429s, keeping the slot.
                    delay_s = (30 if exc.rate_limited else 5) * 2**retry
                    for _ in range(delay_s * 10):
                        check_cancelled()
                        time.sleep(0.1)
            raise AssertionError("unreachable")
        finally:
            _CODEX_SLOT.release()
    return run


def _gemini_cli_runner(model: str) -> Callable[[str], str]:
    def run(prompt: str) -> str:
        # 임시 디렉터리에서 실행해 영상 프로젝트의 GEMINI.md나 로컬 설정이
        # 스토리 생성 결과에 섞여 들어가지 않도록 한다.
        with tempfile.TemporaryDirectory(prefix="reels-gemini-") as tmp:
            args = [*gemini_cli_args(model), "-p", prompt]
            try:
                result = processes.run(
                    args, cwd=tmp, input="", capture_output=True, text=True,
                    timeout=TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"gemini 타임아웃({TIMEOUT_S}초): {e}") from e
            except FileNotFoundError as e:
                raise RuntimeError(
                    "Gemini CLI를 찾을 수 없습니다 — Google Gemini CLI가 설치되어 있고 "
                    f"PATH에 등록되어 있는지 확인하세요: {e}") from e
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-2000:]
                raise RuntimeError(f"gemini 실패:\n{detail}")
            return result.stdout
    return run


def build_runner(cfg: AppConfig,
                 credentials: Path | None = None) -> Callable[[str], str]:
    if cfg.provider == "claude-cli":
        return _claude_cli_runner(cfg.model)
    if cfg.provider == "codex-cli":
        return _codex_cli_runner(cfg.model)
    if cfg.provider == "gemini-cli":
        return _gemini_cli_runner(cfg.model)
    if cfg.provider == "custom":
        base_url, model = cfg.base_url, cfg.model
        if not base_url or not model:
            raise RuntimeError("custom 프로바이더는 base_url과 model이 필요합니다.")
    else:
        try:
            default_url, default_model = PROVIDER_DEFAULTS[cfg.provider]
        except KeyError as e:
            raise RuntimeError(
                f"알 수 없는 프로바이더 {cfg.provider!r} — "
                f"사용 가능한 프로바이더: {', '.join(PROVIDERS)}") from e
        base_url = cfg.base_url or default_url
        model = cfg.model or default_model
    key = resolve_api_key(cfg.provider, credentials)
    if not key:
        raise RuntimeError(
            f"{cfg.provider} API 키가 없습니다 — 환경변수 또는 게이트 설정에서 입력하세요.")
    from reels_editor.llm_http import openai_chat_runner  # Task 4
    return openai_chat_runner(base_url, key, model)


def build_speaker_search_runner() -> Callable[[str], str]:
    """Use the installed Codex CLI with live web search for identity lookup."""
    return _codex_cli_runner("", web_search=True)
