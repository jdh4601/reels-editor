"""LLM 프로바이더 러너 팩토리. storyteller의 runner 주입점에 꽂는다.

claude-cli: 로컬 Claude Code. openai/kimi/custom: OpenAI-호환 chat/completions.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable

from reels_editor.config import AppConfig, resolve_api_key

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


def _claude_cli_runner(model: str) -> Callable[[str], str]:
    def run(prompt: str) -> str:
        try:
            r = subprocess.run([*claude_cli_args(model), prompt],
                               capture_output=True, text=True, timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"claude -p 타임아웃({TIMEOUT_S}초): {e}") from e
        if r.returncode != 0:
            raise RuntimeError(f"claude -p 실패:\n{r.stderr}")
        return r.stdout
    return run


def build_runner(cfg: AppConfig,
                 credentials: Path | None = None) -> Callable[[str], str]:
    if cfg.provider == "claude-cli":
        return _claude_cli_runner(cfg.model)
    if cfg.provider == "custom":
        base_url, model = cfg.base_url, cfg.model
        if not base_url or not model:
            raise RuntimeError("custom 프로바이더는 base_url과 model이 필요합니다.")
    else:
        default_url, default_model = PROVIDER_DEFAULTS[cfg.provider]
        base_url = cfg.base_url or default_url
        model = cfg.model or default_model
    key = resolve_api_key(cfg.provider, credentials)
    if not key:
        raise RuntimeError(
            f"{cfg.provider} API 키가 없습니다 — 환경변수 또는 게이트 설정에서 입력하세요.")
    from reels_editor.llm_http import openai_chat_runner  # Task 4
    return openai_chat_runner(base_url, key, model)
