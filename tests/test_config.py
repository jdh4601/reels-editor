"""config 3단 병합: 파일 없음 기본값 / 부분 오버라이드 / 스타일 병합 / 저장 왕복."""
import dataclasses
import os
import stat
from pathlib import Path

import pytest

from reels_editor import config as config_mod
from reels_editor.config import (
    AppConfig, load_config, merged_style, save_config,
    KEY_ENV_VARS, mask_key, resolve_api_key, save_credential,
)


def test_load_config_missing_file_returns_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "nope.yaml")
    assert cfg.provider == "claude-cli"
    assert cfg.model == ""
    assert cfg.n_storylines == 3
    assert cfg.style == {}


def test_load_config_partial_override(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("provider: kimi\nstyle:\n  sub_size: 52\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.provider == "kimi"
    assert cfg.n_storylines == 3          # 미지정은 기본값
    assert cfg.style == {"sub_size": 52}


def test_load_config_rejects_bad_values(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("n_storylines: 9\n", encoding="utf-8")
    with pytest.raises(ValueError, match="n_storylines"):
        load_config(p)


def test_save_config_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    cfg = AppConfig(provider="openai", model="gpt-4o",
                    style={"sub_highlight": "#00FF00"})
    save_config(cfg, p)
    assert load_config(p) == cfg


def test_merged_style_applies_known_keys(style_preset) -> None:
    merged = merged_style(style_preset, {"sub_size": 60, "title_highlight": "#123456"})
    assert merged.sub_size == 60
    assert merged.title_highlight == "#123456"
    assert merged.sub_font == style_preset.sub_font   # 나머지 필드 보존


def test_merged_style_ignores_unknown_keys(style_preset) -> None:
    merged = merged_style(style_preset, {"nonsense": 1})
    assert merged == style_preset


def test_mask_key() -> None:
    assert mask_key("sk-proj-abcdefgh1234") == "sk-…1234"
    assert mask_key("short") == "…"          # 8자 이하는 전부 가림


def test_save_credential_sets_0600(tmp_path: Path) -> None:
    p = tmp_path / "credentials.yaml"
    save_credential("openai", "sk-test-key", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert resolve_api_key("openai", p) == "sk-test-key"


def test_resolve_api_key_env_wins(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "credentials.yaml"
    save_credential("openai", "sk-file", p)
    monkeypatch.setenv(KEY_ENV_VARS["openai"], "sk-env")
    assert resolve_api_key("openai", p) == "sk-env"


def test_resolve_api_key_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(KEY_ENV_VARS["kimi"], raising=False)
    assert resolve_api_key("kimi", tmp_path / "none.yaml") is None
