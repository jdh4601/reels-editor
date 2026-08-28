"""LLM 프로바이더 러너 팩토리. storyteller의 runner 주입점에 꽂는다.

claude-cli: 로컬 Claude Code. codex-cli: OpenAI Codex CLI.
gemini-cli: Google Gemini CLI. openai/kimi/custom: OpenAI-호환 chat/completions.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from reels_editor import processes
from reels_editor.config import PROVIDERS, AppConfig, resolve_api_key

TIMEOUT_S = 600
PROVIDER_DEFAULTS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o"),
    "kimi": ("https://api.moonshot.ai/v1", "kimi-k2-0905-preview"),
}


def claude_cli_args(model: str) -> list[str]:
    args = ["claude", "-p"]
    if model:
        args += ["--model", model]
    return args


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
            raise RuntimeError(f"claude -p 실패:\n{r.stderr}")
        return r.stdout
    return run


def _codex_cli_runner(model: str) -> Callable[[str], str]:
    def run(prompt: str) -> str:
        with tempfile.TemporaryDirectory(prefix="reels-codex-") as tmp:
            output_path = Path(tmp) / "last-message.txt"
            args = [
                *codex_cli_args(model), "-C", tmp,
                "--output-last-message", str(output_path), "-",
            ]
            try:
                result = processes.run(
                    args, input=prompt, capture_output=True, text=True,
                    timeout=TIMEOUT_S,
                )
            except subprocess.TimeoutExpired as e:
                raise RuntimeError(f"codex exec 타임아웃({TIMEOUT_S}초): {e}") from e
            except FileNotFoundError as e:
                raise RuntimeError(
                    "Codex CLI를 찾을 수 없습니다 — OpenAI Codex CLI가 설치되어 있고 "
                    f"PATH에 등록되어 있는지 확인하세요: {e}") from e
            if result.returncode != 0:
                detail = (result.stderr or result.stdout).strip()[-2000:]
                raise RuntimeError(f"codex exec 실패:\n{detail}")
            if not output_path.is_file():
                raise RuntimeError("codex exec가 최종 응답 파일을 생성하지 않았습니다.")
            return output_path.read_text(encoding="utf-8")
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
