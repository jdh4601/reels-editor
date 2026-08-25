"""config 3단 병합: 파일 없음 기본값 / 부분 오버라이드 / 스타일 병합 / 저장 왕복."""
import stat
from pathlib import Path

import pytest

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


@pytest.mark.parametrize("speed", [1.0, 1.5])
def test_load_config_accepts_playback_speed_boundaries(tmp_path: Path, speed: float) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(f"style:\n  speed: {speed}\n", encoding="utf-8")

    assert load_config(p).style["speed"] == speed


@pytest.mark.parametrize("speed", [0.95, 1.55, "fast", True])
def test_load_config_rejects_invalid_playback_speed(tmp_path: Path, speed: object) -> None:
    p = tmp_path / "config.yaml"
    p.write_text(f"style:\n  speed: {str(speed).lower()}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="style.speed"):
        load_config(p)


def test_load_config_accepts_codex_cli_provider(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("provider: codex-cli\nmodel: gpt-5.6-sol\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg.provider == "codex-cli"
    assert cfg.model == "gpt-5.6-sol"


def test_load_config_accepts_max_storyline_count(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("n_storylines: 10\n", encoding="utf-8")

    assert load_config(p).n_storylines == 10


def test_load_config_rejects_storyline_count_above_max(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("n_storylines: 11\n", encoding="utf-8")
    with pytest.raises(ValueError, match="n_storylines"):
        load_config(p)


def test_load_config_rejects_non_mapping_yaml(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("- 1\n- 2\n", encoding="utf-8")  # YAML 리스트
    with pytest.raises(ValueError, match="설정 파일 형식"):
        load_config(p)


def test_load_config_rejects_scalar_yaml(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("just-a-string\n", encoding="utf-8")  # YAML 스칼라
    with pytest.raises(ValueError, match="설정 파일 형식"):
        load_config(p)


def test_load_config_rejects_non_numeric_n_storylines(tmp_path: Path) -> None:
    p = tmp_path / "config.yaml"
    p.write_text("n_storylines: abc\n", encoding="utf-8")
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


def test_mask_key_dashless_key_never_leaks_full_key() -> None:
    # custom 프로바이더는 `-`가 없는 임의 형식 키를 허용할 수 있음.
    # split("-", 1)[0] 방식은 이 경우 전체 키를 "접두사"로 반환해 노출시켰던 버그.
    key = "abcdefghijklmnopqrstuvwxyz123456"
    masked = mask_key(key)
    assert key not in masked
    assert masked == "…3456"


def test_mask_key_long_dashless_key_never_leaks_full_key() -> None:
    key = "z" * 200
    masked = mask_key(key)
    assert key not in masked
    assert masked == "…" + key[-4:]


def test_mask_key_long_pre_dash_token_not_used_as_prefix() -> None:
    # "-"는 있지만 첫 토큰이 길면(스킴처럼 보이지 않으면) 접두사로 노출하지 않음.
    key = "abcdefghijklmnop-1234"
    masked = mask_key(key)
    assert key not in masked
    assert "abcdefghijklmnop" not in masked
    assert masked == "…1234"


def test_save_credential_sets_0600(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(KEY_ENV_VARS["openai"], raising=False)
    p = tmp_path / "credentials.yaml"
    save_credential("openai", "sk-test-key", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert resolve_api_key("openai", p) == "sk-test-key"


def test_save_credential_preserves_existing_entries(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv(KEY_ENV_VARS["openai"], raising=False)
    monkeypatch.delenv(KEY_ENV_VARS["kimi"], raising=False)
    p = tmp_path / "credentials.yaml"
    save_credential("openai", "sk-openai-key", p)
    save_credential("kimi", "sk-kimi-key", p)
    assert stat.S_IMODE(p.stat().st_mode) == 0o600
    assert resolve_api_key("openai", p) == "sk-openai-key"
    assert resolve_api_key("kimi", p) == "sk-kimi-key"


def test_resolve_api_key_env_wins(tmp_path: Path, monkeypatch) -> None:
    p = tmp_path / "credentials.yaml"
    save_credential("openai", "sk-file", p)
    monkeypatch.setenv(KEY_ENV_VARS["openai"], "sk-env")
    assert resolve_api_key("openai", p) == "sk-env"


def test_resolve_api_key_missing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(KEY_ENV_VARS["kimi"], raising=False)
    assert resolve_api_key("kimi", tmp_path / "none.yaml") is None
