"""사용자 설정 로드/저장 + 스타일 오버라이드 병합.

병합 우선순위: styles/*.yaml(기본) ← 사용자 config ← CLI 옵션(호출부 책임).
"""
from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from reels_editor.style import StylePreset

PROVIDERS = ("claude-cli", "codex-cli", "openai", "kimi", "custom")
# StylePreset 필드 중 게이트 설정으로 조절 가능한 키
STYLE_OVERRIDE_KEYS = ("sub_size", "title_size", "sub_highlight",
                       "title_highlight", "sub_y_frac", "sub_box_alpha", "speed")
MAX_STORYLINES = 10
MIN_PLAYBACK_SPEED = 1.0
MAX_PLAYBACK_SPEED = 1.5
DEFAULT_PLAYBACK_SPEED = 1.2


@dataclass(frozen=True)
class AppConfig:
    provider: str = "claude-cli"
    model: str = ""            # 빈 문자열 = 프로바이더 기본 모델
    base_url: str = ""         # custom 프로바이더 전용
    n_storylines: int = 3
    voice_isolation: bool = False
    style: dict[str, Any] = field(default_factory=dict)


def user_config_path() -> Path:
    root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return root / "reels-editor" / "config.yaml"


def _validate(cfg: AppConfig) -> AppConfig:
    if cfg.provider not in PROVIDERS:
        raise ValueError(f"provider는 {PROVIDERS} 중 하나여야 함: {cfg.provider!r}")
    if not 1 <= cfg.n_storylines <= MAX_STORYLINES:
        raise ValueError(f"n_storylines는 1~{MAX_STORYLINES}: {cfg.n_storylines}")
    unknown = set(cfg.style) - set(STYLE_OVERRIDE_KEYS)
    if unknown:
        raise ValueError(f"알 수 없는 style 키: {sorted(unknown)}")
    if "speed" in cfg.style:
        speed = cfg.style["speed"]
        if (
            isinstance(speed, bool)
            or not isinstance(speed, (int, float))
            or not MIN_PLAYBACK_SPEED <= float(speed) <= MAX_PLAYBACK_SPEED
        ):
            raise ValueError(
                f"style.speed는 {MIN_PLAYBACK_SPEED:.1f}~{MAX_PLAYBACK_SPEED:.1f} 사이의 숫자여야 함: {speed!r}"
            )
    return cfg


def load_config(path: Path | None = None) -> AppConfig:
    p = path or user_config_path()
    if not p.is_file():
        return AppConfig()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(
            f"설정 파일 형식이 올바르지 않습니다 (key: value 형태여야 함): {p}"
        )
    defaults = AppConfig()
    try:
        n_storylines = int(raw.get("n_storylines", defaults.n_storylines))
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"n_storylines 값이 올바르지 않습니다 (정수여야 함): {raw.get('n_storylines')!r}"
        ) from exc
    return _validate(AppConfig(
        provider=raw.get("provider", defaults.provider),
        model=raw.get("model", defaults.model),
        base_url=raw.get("base_url", defaults.base_url),
        n_storylines=n_storylines,
        voice_isolation=bool(raw.get("voice_isolation", defaults.voice_isolation)),
        style={k: v for k, v in (raw.get("style") or {}).items()},
    ))


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    p = path or user_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(dataclasses.asdict(_validate(cfg)),
                                allow_unicode=True, sort_keys=False),
                 encoding="utf-8")
    return p


def merged_style(preset: StylePreset, overrides: dict[str, Any]) -> StylePreset:
    known = {k: v for k, v in overrides.items() if k in STYLE_OVERRIDE_KEYS}
    return dataclasses.replace(preset, **known) if known else preset


KEY_ENV_VARS = {
    "openai": "OPENAI_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "custom": "REELS_LLM_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def credentials_path() -> Path:
    return user_config_path().parent / "credentials.yaml"


def mask_key(key: str) -> str:
    """API 키를 `scheme-…끝4자리` 형태로 마스킹. 어떤 입력이든 끝 4자리 +
    (있다면) 4자 이하 스킴 접두사 이상은 노출하지 않는다.

    `-`가 없거나 첫 토큰이 긴 키(dashless/custom 프로바이더 등)는 접두사를
    생략해 전체 키가 노출되는 것을 막는다.
    """
    if len(key) <= 8:
        return "…"
    prefix, sep, _rest = key.partition("-")
    if sep and len(prefix) <= 4:
        return f"{prefix}-…{key[-4:]}"
    return f"…{key[-4:]}"


def save_credential(provider: str, key: str, path: Path | None = None) -> Path:
    p = path or credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.is_file():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data[provider] = key
    # 파일 생성과 권한 제한(0o600)을 원자적으로 수행 — write_text 후 chmod 순서로
    # 하면 그 사이 창에서 평문 키가 느슨한 umask에 노출될 수 있음.
    fd = os.open(p, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(yaml.safe_dump(data))
    p.chmod(0o600)  # 기존 파일이 더 느슨한 권한으로 이미 존재했던 경우 대비
    return p


def resolve_api_key(provider: str, path: Path | None = None) -> str | None:
    env = KEY_ENV_VARS.get(provider)
    if env and os.environ.get(env):
        return os.environ[env]
    p = path or credentials_path()
    if p.is_file():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data.get(provider)
    return None
