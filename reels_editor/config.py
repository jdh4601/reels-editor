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

PROVIDERS = ("claude-cli", "openai", "kimi", "custom")
# StylePreset 필드 중 게이트 설정으로 조절 가능한 키
STYLE_OVERRIDE_KEYS = ("sub_size", "title_size", "sub_highlight",
                       "title_highlight", "sub_y_frac", "sub_box_alpha", "speed")
MAX_STORYLINES = 3


@dataclass(frozen=True)
class AppConfig:
    provider: str = "claude-cli"
    model: str = ""            # 빈 문자열 = 프로바이더 기본 모델
    base_url: str = ""         # custom 프로바이더 전용
    n_storylines: int = 3
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
    return cfg


def load_config(path: Path | None = None) -> AppConfig:
    p = path or user_config_path()
    if not p.is_file():
        return AppConfig()
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    defaults = AppConfig()
    return _validate(AppConfig(
        provider=raw.get("provider", defaults.provider),
        model=raw.get("model", defaults.model),
        base_url=raw.get("base_url", defaults.base_url),
        n_storylines=int(raw.get("n_storylines", defaults.n_storylines)),
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
