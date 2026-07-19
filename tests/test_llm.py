"""프로바이더 러너: claude-cli 인자 구성 / 미지정 모델 기본값 / 키 없음 오류."""
import pytest

from reels_editor.config import AppConfig
from reels_editor.llm import PROVIDER_DEFAULTS, build_runner, claude_cli_args


def test_claude_cli_args_default_model() -> None:
    assert claude_cli_args("") == ["claude", "-p"]


def test_claude_cli_args_with_model() -> None:
    assert claude_cli_args("opus") == ["claude", "-p", "--model", "opus"]


def test_build_runner_openai_without_key_raises(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    cfg = AppConfig(provider="openai")
    with pytest.raises(RuntimeError, match="API 키"):
        build_runner(cfg, credentials=tmp_path / "none.yaml")


def test_provider_defaults_shape() -> None:
    for name in ("openai", "kimi"):
        base_url, model = PROVIDER_DEFAULTS[name]
        assert base_url.startswith("https://") and model
