# 다중 스토리라인·게이트 설정·병렬 렌더 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `make` 1회 실행으로 스토리라인 3개를 병렬 생성 → 게이트에서 스토리라인×타이틀 조합 선택·설정 조정 → 선택 조합을 병렬 렌더해 여러 mp4를 산출한다.

**Architecture:** 기존 파이프라인(capcut→storyteller→gate→render)을 유지하며 확장. LLM 호출은 `runner` 주입점에 프로바이더 팩토리(`llm.py`)를 꽂고, 렌더는 base(무거움)/타이틀 오버레이(가벼움) 2단계로 분리해 스토리라인 단위 병렬화. 게이트는 stdlib http.server 그대로, HTML 빌드(`gate_html.py`)와 프리뷰 합성(`preview.py`)을 분리.

**Tech Stack:** Python 3.11+, typer, Pillow, PyYAML, ffmpeg, stdlib(urllib·http.server·concurrent.futures), 신규 의존성 `rich` 1개.

**Spec:** `docs/superpowers/specs/2026-07-18-multi-storyline-workflow-design.md`

## Global Constraints

- Python `>=3.11`, 새 의존성은 `rich` 하나만. HTTP는 stdlib `urllib` 사용.
- API 키는 로그·manifest·edl.json에 절대 기록 금지. UI 표시는 `sk-…abcd` 마스킹.
- credentials 파일은 `~/.config/reels-editor/credentials.yaml`, 권한 0o600.
- 설정 병합 우선순위: `styles/done.yaml`(기본) ← 사용자 config ← CLI 옵션.
- LLM 타임아웃 600초, 재시도 최대 2회(기존 `MAX_RETRIES` 재사용).
- 스토리라인 기본 3개(1~3), 동시 ffmpeg base 렌더 최대 2개.
- 산출물: `out/<프로젝트-날짜>/s{n}/reel-t{m}.mp4` + `manifest.json`.
- 모든 사용자 노출 문자열은 한국어. 파일 800줄 초과 금지(CLAUDE.md).
- TDD: 각 태스크는 실패 테스트 먼저. 기존 테스트 전부 그린 유지.
- 테스트 실행: `.venv/bin/pytest -q` (venv 없으면 `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`).

---

### Task 1: config.py — 3단 설정 병합

**Files:**
- Create: `reels_editor/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `AppConfig` dataclass, `load_config(path: Path | None) -> AppConfig`, `save_config(cfg: AppConfig, path: Path | None) -> Path`, `merged_style(preset: StylePreset, overrides: dict) -> StylePreset`, `user_config_path() -> Path`
- Consumes: `reels_editor.style.StylePreset`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_config.py
"""config 3단 병합: 파일 없음 기본값 / 부분 오버라이드 / 스타일 병합 / 저장 왕복."""
import dataclasses
from pathlib import Path

import pytest

from reels_editor import config as config_mod
from reels_editor.config import AppConfig, load_config, merged_style, save_config


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
```

`style_preset` 픽스처가 `tests/conftest.py`에 없으면 추가한다 (기존 test_render가 쓰는 방식을 확인해 동일 픽스처 재사용 — 이미 있으면 이 단계 생략):

```python
# tests/conftest.py 에 추가 (기존에 동등 픽스처가 없을 때만)
import pytest
from reels_editor.style import StylePreset

@pytest.fixture
def style_preset(tmp_path):
    font = tmp_path / "f.otf"
    # Pillow 기본 폰트 파일이 없어도 StylePreset은 Path만 담으므로 더미 파일로 충분
    font.write_bytes(b"")
    return StylePreset(
        canvas=(1080, 1920), top_bar=300, bottom_bar=380,
        title_font=font, title_size=72, title_color="#FFFFFF",
        title_highlight="#FF7A00", title_max_lines=2,
        sub_font=font, sub_size=44, sub_color="#FFFFFF",
        sub_highlight="#FF3B30", sub_box_alpha=200, sub_y_frac=0.85,
        watermark_text="D.one", watermark_font=font, watermark_size=48,
        speed=1.2)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv/bin/pytest tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: reels_editor.config`

- [ ] **Step 3: 구현**

```python
# reels_editor/config.py
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
```

주의: `load_config`의 style 키 검증은 `_validate`가 수행하므로 알 수 없는 키가 있으면 ValueError. 테스트의 `merged_style` unknown-key 무시는 **게이트가 보낸 임의 dict**에 대한 방어이므로 별도 동작(검증 없이 필터링)이 맞다.

- [ ] **Step 4: 통과 확인** — Run: `.venv/bin/pytest tests/test_config.py -q` → PASS. 전체 회귀: `.venv/bin/pytest -q` → PASS

- [ ] **Step 5: Commit** — `git add reels_editor/config.py tests/test_config.py tests/conftest.py && git commit -m "feat(config): 사용자 설정 로드·저장 + 스타일 3단 병합"`

---

### Task 2: config.py — credentials(키 저장·해석·마스킹)

**Files:**
- Modify: `reels_editor/config.py` (Task 1 결과에 이어서)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `credentials_path() -> Path`, `save_credential(provider: str, key: str, path: Path | None) -> Path`, `resolve_api_key(provider: str, path: Path | None) -> str | None`, `mask_key(key: str) -> str`, `KEY_ENV_VARS: dict[str, str]`

- [ ] **Step 1: 실패 테스트 작성** (tests/test_config.py 에 추가)

```python
import os
import stat

from reels_editor.config import (
    KEY_ENV_VARS, mask_key, resolve_api_key, save_credential,
)


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
```

- [ ] **Step 2: 실패 확인** — Run: `.venv/bin/pytest tests/test_config.py -q` → FAIL (ImportError)

- [ ] **Step 3: 구현** (config.py 에 추가)

```python
KEY_ENV_VARS = {"openai": "OPENAI_API_KEY", "kimi": "MOONSHOT_API_KEY",
                "custom": "REELS_LLM_API_KEY"}


def credentials_path() -> Path:
    return user_config_path().parent / "credentials.yaml"


def mask_key(key: str) -> str:
    prefix = key.split("-", 1)[0]
    return f"{prefix}-…{key[-4:]}" if len(key) > 8 else "…"


def save_credential(provider: str, key: str, path: Path | None = None) -> Path:
    p = path or credentials_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.is_file():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    data[provider] = key
    p.write_text(yaml.safe_dump(data), encoding="utf-8")
    p.chmod(0o600)
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
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_config.py -q` → PASS

- [ ] **Step 5: Commit** — `git commit -am "feat(config): API 키 저장(0600)·env 우선 해석·마스킹"`

---

### Task 3: llm.py — 프로바이더 러너 팩토리 (claude-cli)

**Files:**
- Create: `reels_editor/llm.py`
- Test: `tests/test_llm.py`

**Interfaces:**
- Produces: `build_runner(cfg: AppConfig, credentials: Path | None = None) -> Callable[[str], str]`, `PROVIDER_DEFAULTS: dict[str, tuple[str, str]]` (base_url, 기본 모델), `claude_cli_args(model: str) -> list[str]`
- Consumes: Task 1-2의 `AppConfig`, `resolve_api_key`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_llm.py
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
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_llm.py -q` → FAIL (ModuleNotFoundError)

- [ ] **Step 3: 구현**

```python
# reels_editor/llm.py
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
```

Task 4 전까지 `llm_http` import는 openai 경로 테스트에서만 도달하는데, 위 테스트는 키 없음에서 먼저 실패하므로 통과한다.

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_llm.py -q` → PASS

- [ ] **Step 5: Commit** — `git add reels_editor/llm.py tests/test_llm.py && git commit -m "feat(llm): 프로바이더 러너 팩토리 + claude-cli 러너"`

---

### Task 4: llm_http.py — OpenAI-호환 HTTP 러너

**Files:**
- Create: `reels_editor/llm_http.py`
- Test: `tests/test_llm.py` (추가)

**Interfaces:**
- Produces: `openai_chat_runner(base_url: str, api_key: str, model: str) -> Callable[[str], str]`
- HTTP: `POST {base_url}/chat/completions`, body `{"model", "messages":[{"role":"user","content":prompt}]}`, 응답 `choices[0].message.content`

- [ ] **Step 1: 실패 테스트 작성** (tests/test_llm.py 에 추가 — stdlib mock 서버)

```python
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from reels_editor.llm_http import openai_chat_runner


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


def test_openai_chat_runner_http_error_masks_key() -> None:
    class Err(BaseHTTPRequestHandler):
        def do_POST(self):
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
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_llm.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# reels_editor/llm_http.py
"""OpenAI-호환 chat/completions 러너 (stdlib urllib — 의존성 無)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Callable

TIMEOUT_S = 600


def openai_chat_runner(base_url: str, api_key: str,
                       model: str) -> Callable[[str], str]:
    url = base_url.rstrip("/") + "/chat/completions"

    def run(prompt: str) -> str:
        body = json.dumps({"model": model,
                           "messages": [{"role": "user", "content": prompt}]})
        req = urllib.request.Request(
            url, data=body.encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
                data = json.loads(resp.read())
        except urllib.error.HTTPError as e:
            detail = e.read()[:300].decode(errors="replace")
            raise RuntimeError(
                f"LLM API 오류 {e.code} ({model}): {detail}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"LLM API 연결 실패 ({url}): {e}") from e
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as e:
            raise RuntimeError(f"LLM 응답 형식 오류: {str(data)[:300]}") from e
    return run
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_llm.py -q` → PASS

- [ ] **Step 5: Commit** — `git add reels_editor/llm_http.py tests/test_llm.py && git commit -m "feat(llm): OpenAI-호환 HTTP 러너 (kimi·gpt·custom)"`

---

### Task 5: storyteller — 각도 힌트

**Files:**
- Modify: `reels_editor/storyteller.py`, `prompts/storytelling-30s.md`
- Test: `tests/test_storyteller.py` (추가)

**Interfaces:**
- Produces: `ANGLES: list[tuple[str, str]]` (이름, 힌트), `build_prompt(segments, duration_s, feedback, angle: str | None = None) -> str`

- [ ] **Step 1: 실패 테스트 작성** (tests/test_storyteller.py 에 추가)

```python
from reels_editor.storyteller import ANGLES, build_prompt


def test_angles_has_three_named_hints() -> None:
    assert len(ANGLES) == 3
    names = [n for n, _ in ANGLES]
    assert names == ["정면승부형", "반전형", "감정선형"]


def test_build_prompt_injects_angle(sample_segments) -> None:
    name, hint = ANGLES[1]
    p = build_prompt(sample_segments, 30, None, angle=hint)
    assert hint in p


def test_build_prompt_without_angle_has_no_block(sample_segments) -> None:
    p = build_prompt(sample_segments, 30, None)
    assert "{angle_block}" not in p     # 플레이스홀더 잔존 금지
```

`sample_segments` 픽스처는 기존 test_storyteller.py에 있는 세그먼트 dict를 재사용 (없으면 `{"segments": [{"id": "s1", "text": "안녕", "source_start_us": 0, "source_end_us": 1000000}], "video_path": "v.mp4"}` 형태로 conftest에 추가).

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_storyteller.py -q` → FAIL

- [ ] **Step 3: 구현**

`prompts/storytelling-30s.md`의 `## 출력` 섹션 바로 앞에 한 줄 추가:

```
{angle_block}
```

`storyteller.py` 수정:

```python
ANGLES: list[tuple[str, str]] = [
    ("정면승부형", "주제를 정면으로 드러내는 각도 — 훅부터 핵심 사건을 직진으로 전개한다."),
    ("반전형", "예상을 뒤집는 각도 — 통념/실패를 먼저 세우고 반전 문장을 축으로 전개한다."),
    ("감정선형", "감정의 흐름 각도 — 불안·좌절·확신 같은 감정 변화 문장을 축으로 전개한다."),
]


def build_prompt(segments: dict, duration_s: int, feedback: str | None,
                 angle: str | None = None) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    listing = "\n".join(f"- {s['id']}: {s['text']}" for s in segments["segments"])
    fb = f"\n## 수정 피드백 (반드시 반영)\n{feedback}\n" if feedback else ""
    ab = f"\n## 스토리 각도 (이 각도로만)\n{angle}\n" if angle else ""
    return (template
            .replace("{speed}", str(DEFAULT_SPEED))
            .replace("{duration_s}", str(duration_s))
            .replace("{source_budget_s}", str(round(duration_s * DEFAULT_SPEED)))
            .replace("{schema}", _SCHEMA)
            .replace("{segments_listing}", listing)
            .replace("{feedback_block}", fb)
            .replace("{angle_block}", ab))
```

`generate_script`에 `angle: str | None = None` 파라미터를 추가하고 내부 `build_prompt(segments, duration_s, feedback)` 호출을 `build_prompt(segments, duration_s, feedback, angle)`로 변경.

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_storyteller.py -q` → PASS

- [ ] **Step 5: Commit** — `git commit -am "feat(storyteller): 스토리 각도 힌트 3종 프롬프트 주입"`

---

### Task 6: storyteller.generate_many — 병렬 생성 + 실패 격리

**Files:**
- Modify: `reels_editor/storyteller.py`
- Test: `tests/test_storyteller.py` (추가)

**Interfaces:**
- Produces: `@dataclass StorylineResult(index: int, angle_name: str, doc: dict | None, error: str | None)`, `generate_many(segments, n: int, duration_s: int = 30, *, runner=None, raw_dump_dir: Path | None = None, feedback: str | None = None, only_indices: list[int] | None = None) -> list[StorylineResult]`
- `only_indices`: 재생성 시 해당 인덱스만 다시 생성 (병렬), 나머지는 결과에 포함하지 않음.

- [ ] **Step 1: 실패 테스트 작성**

```python
import threading

from reels_editor.storyteller import StorylineResult, generate_many


def _ok_doc(segments):
    sid = segments["segments"][0]["id"]
    return {"story": {"five_lines": {}, "lens": "l"},
            "title_candidates": [{"text": "t", "keyword": "t"}],
            "subtitle_keywords": [],
            "cuts": [{"beat": "훅", "seg_ids": [sid]}]}


def test_generate_many_runs_in_parallel(sample_segments) -> None:
    import json, time
    barrier = threading.Barrier(3, timeout=5)   # 3개가 동시에 도달해야 통과

    def runner(prompt: str) -> str:
        barrier.wait()
        return json.dumps(_ok_doc(sample_segments), ensure_ascii=False)

    results = generate_many(sample_segments, 3, runner=runner)
    assert [r.index for r in results] == [0, 1, 2]
    assert all(r.doc is not None and r.error is None for r in results)
    assert results[0].angle_name == "정면승부형"


def test_generate_many_isolates_failure(sample_segments) -> None:
    import json
    calls = {"n": 0}
    lock = threading.Lock()

    def runner(prompt: str) -> str:
        with lock:
            calls["n"] += 1
            mine = calls["n"]
        if "반전" in prompt:                # 두 번째 각도만 항상 실패
            raise RuntimeError("boom")
        return json.dumps(_ok_doc(sample_segments), ensure_ascii=False)

    results = generate_many(sample_segments, 3, runner=runner)
    assert results[0].doc is not None
    assert results[1].doc is None and "boom" in results[1].error
    assert results[2].doc is not None


def test_generate_many_only_indices(sample_segments) -> None:
    import json

    def runner(prompt: str) -> str:
        return json.dumps(_ok_doc(sample_segments), ensure_ascii=False)

    results = generate_many(sample_segments, 3, runner=runner, only_indices=[2])
    assert [r.index for r in results] == [2]
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_storyteller.py -q` → FAIL

- [ ] **Step 3: 구현** (storyteller.py 에 추가)

```python
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


@dataclass(frozen=True)
class StorylineResult:
    index: int
    angle_name: str
    doc: dict | None
    error: str | None = None


def generate_many(segments: dict, n: int, duration_s: int = 30, *,
                  runner: Callable[[str], str] | None = None,
                  raw_dump_dir: Path | None = None,
                  feedback: str | None = None,
                  only_indices: list[int] | None = None) -> list[StorylineResult]:
    """스토리라인 n개를 병렬 생성. 개별 실패는 error로 담고 나머지는 살린다."""
    indices = only_indices if only_indices is not None else list(range(n))

    def one(i: int) -> StorylineResult:
        name, hint = ANGLES[i % len(ANGLES)]
        dump = (raw_dump_dir / f"llm_raw_s{i + 1}.txt") if raw_dump_dir else None
        try:
            doc = generate_script(segments, duration_s, feedback,
                                  runner=runner, raw_dump=dump, angle=hint)
            return StorylineResult(i, name, doc)
        except RuntimeError as e:
            return StorylineResult(i, name, None, str(e))

    with ThreadPoolExecutor(max_workers=max(len(indices), 1)) as ex:
        return list(ex.map(one, indices))
```

`generate_script` 시그니처에 `angle: str | None = None` 추가는 Task 5에서 완료됨.

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_storyteller.py -q` → PASS. 전체: `.venv/bin/pytest -q` → PASS

- [ ] **Step 5: Commit** — `git commit -am "feat(storyteller): generate_many 병렬 생성 + 실패 격리 + 부분 재생성"`

---

### Task 7: render — base/타이틀 오버레이 분리 + ffmpeg 진행률

**Files:**
- Modify: `reels_editor/render.py`
- Test: `tests/test_render.py` (추가)

**Interfaces:**
- Produces:
  - `@dataclass RenderAssets(base: Path, wm_png: Path, sub_pngs: list[Path], groups: list[list], work: Path, keywords: list[str])`
  - `render_base_and_assets(video_path, segments, edl_doc, style, work_dir: Path, speed: float, progress_cb: Callable[[float], None] | None = None) -> RenderAssets`
  - `render_with_title(assets: RenderAssets, title_text: str, keyword: str, style, out_path: Path) -> Path`
  - `parse_progress_line(line: str) -> float | None` (out_time_us→초, 순수 함수)
  - 기존 `render_reel(...)`은 위 둘을 조합하는 래퍼로 유지 (기존 테스트 그린)

- [ ] **Step 1: 실패 테스트 작성** (tests/test_render.py 에 추가)

```python
from reels_editor.render import parse_progress_line


def test_parse_progress_line() -> None:
    assert parse_progress_line("out_time_us=1500000") == 1.5
    assert parse_progress_line("frame=42") is None
    assert parse_progress_line("out_time_us=N/A") is None
```

분리 함수의 동작 자체는 기존 `render_reel` 경유 테스트(합성 영상 통합 테스트)가 커버하므로, 이 태스크의 신규 단위 테스트는 순수 함수만. `render_reel` 리팩터링 후 **기존 테스트 전체가 그린인 것**이 리팩터링 검증이다.

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_render.py -q` → FAIL (ImportError)

- [ ] **Step 3: 구현** — render.py의 `render_reel`을 아래처럼 분해 (기존 본문 재배치, 로직 변경 없음):

```python
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class RenderAssets:
    base: Path
    wm_png: Path
    sub_pngs: list[Path]
    groups: list[list]
    work: Path
    keywords: list[str]


def parse_progress_line(line: str) -> float | None:
    if not line.startswith("out_time_us="):
        return None
    try:
        return int(line.split("=", 1)[1]) / 1_000_000
    except ValueError:
        return None


def _ffmpeg_progress(args: list[str], total_s: float,
                     cb: Callable[[float], None] | None) -> None:
    """-progress pipe:1 로 진행률을 cb(0.0~1.0)에 보고하며 실행."""
    if cb is None:
        _ffmpeg(args)
        return
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-progress", "pipe:1", *args],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert proc.stdout is not None
    for line in proc.stdout:
        t = parse_progress_line(line.strip())
        if t is not None and total_s > 0:
            cb(min(t / total_s, 1.0))
    proc.wait()
    if proc.returncode != 0:
        err = proc.stderr.read() if proc.stderr else ""
        raise RuntimeError(f"ffmpeg 실패:\n{err}")


def render_base_and_assets(video_path: Path, segments: dict, edl_doc: dict,
                           style: StylePreset, work_dir: Path, speed: float,
                           progress_cb: Callable[[float], None] | None = None,
                           ) -> RenderAssets:
    from reels_editor import edl as edl_mod
    ordered = edl_mod.ordered_segments(edl_doc, segments)
    work_dir.mkdir(parents=True, exist_ok=True)
    content = detect_content_crop(video_path, ordered[0]["source_start_us"] / US)
    filt = build_base_filter(ordered, speed, style, _probe_size(video_path),
                             content_crop=content)
    fpath = work_dir / "base_filter.txt"
    fpath.write_text(filt)
    base = work_dir / "base.mp4"
    total_s = sum(s["source_end_us"] - s["source_start_us"]
                  for s in ordered) / US / speed
    _ffmpeg_progress(["-i", str(video_path), "-filter_complex_script", str(fpath),
                      "-map", "[v]", "-map", "[a]", "-c:v", "libx264",
                      "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                      str(base)], total_s, progress_cb)
    wm_png = render_watermark_png(style, work_dir / "wm.png")
    items = [[a, b, apply_text_fixes(t, DEFAULT_TEXT_FIXES)]
             for a, b, t in timeline_items(ordered, speed)]
    groups = group_captions(items)
    keywords = edl_doc.get("subtitle_keywords", [])
    sub_paths = render_subtitle_pngs(groups, keywords, style, work_dir / "subs")
    return RenderAssets(base, wm_png, sub_paths, groups, work_dir, keywords)


def render_with_title(assets: RenderAssets, title_text: str, keyword: str,
                      style: StylePreset, out_path: Path) -> Path:
    title_png = render_title_png(title_text, keyword, style,
                                 assets.work / f"title-{out_path.stem}.png")
    filt2, last = build_overlay_filter(n_static=2, groups=assets.groups)
    args = ["-i", str(assets.base), "-i", str(title_png), "-i", str(assets.wm_png)]
    for p in assets.sub_pngs:
        args += ["-i", str(p)]
    args += ["-filter_complex", filt2, "-map", last, "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "copy", str(out_path)]
    _ffmpeg(args)
    return out_path


def render_reel(video_path: Path, segments: dict, edl_doc: dict, style: StylePreset,
                out_path: Path, speed: float | None = None,
                work_dir: Path | None = None) -> Path:
    speed = speed if speed is not None else style.speed
    work = work_dir or Path(tempfile.mkdtemp(prefix="reels_render_"))
    assets = render_base_and_assets(video_path, segments, edl_doc, style, work, speed)
    title = edl_doc["title_candidates"][edl_doc.get("selected_title", 0)]
    return render_with_title(assets, title["text"], title.get("keyword", ""),
                             style, out_path)
```

기존 `render_reel` 본문은 삭제하고 위 구조로 대체 (오버레이 필터·인코딩 인자는 그대로).

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_render.py tests/test_render_images.py -q` → PASS. 통합 포함 전체: `.venv/bin/pytest -q` → PASS (합성 영상 테스트가 리팩터링 검증)

- [ ] **Step 5: Commit** — `git commit -am "refactor(render): base/타이틀 오버레이 분리 + ffmpeg 진행률 콜백"`

---

### Task 8: preview.py — 정지 프레임 프리뷰 합성

**Files:**
- Create: `reels_editor/preview.py`
- Test: `tests/test_preview.py`

**Interfaces:**
- Produces: `extract_frame(video_path: Path, at_s: float, out: Path) -> Path | None`, `compose_preview(frame: Path | None, title_text: str, title_keyword: str, sub_text: str, sub_keywords: list[str], style: StylePreset) -> bytes`
- `compose_preview`는 캔버스(1080×1920) PNG 바이트 반환. frame이 None이면 회색 플레이스홀더 위에 합성 (게이트는 죽지 않는다).

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_preview.py
"""프리뷰 합성: 캔버스 크기 / frame 없음 폴백 / 실제 렌더 코드 경로 재사용."""
import io

from PIL import Image

from reels_editor.preview import compose_preview


def test_compose_preview_returns_canvas_png(style_preset) -> None:
    png = compose_preview(None, "타이틀 텍스트", "타이틀", "자막 샘플입니다",
                          ["샘플"], style_preset)
    img = Image.open(io.BytesIO(png))
    assert img.size == tuple(style_preset.canvas)
    assert img.format == "PNG"


def test_compose_preview_empty_texts_still_works(style_preset) -> None:
    png = compose_preview(None, "", "", "", [], style_preset)
    assert Image.open(io.BytesIO(png)).size == tuple(style_preset.canvas)
```

주의: `style_preset` 픽스처의 더미 폰트(빈 파일)로는 `ImageFont.truetype`이 실패한다. conftest의 픽스처를 실제 설치 폰트가 있으면 그걸 쓰고 없으면 `pytest.skip`하도록 조정하거나, 기존 test_render_images.py가 쓰는 폰트 해결 방식을 그대로 따른다 (**기존 conftest를 먼저 읽고 동일 패턴 재사용** — 렌더 이미지 테스트가 이미 폰트 문제를 풀어놨다).

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_preview.py -q` → FAIL

- [ ] **Step 3: 구현**

```python
# reels_editor/preview.py
"""게이트 설정 프리뷰: 추출 프레임 위에 타이틀·자막·워터마크 합성 PNG.

렌더와 동일한 draw 코드(render_*_png)를 재사용해 프리뷰=결과를 보장한다.
"""
from __future__ import annotations

import io
import subprocess
import tempfile
from pathlib import Path

from PIL import Image

from reels_editor.render import (
    render_subtitle_pngs, render_title_png, render_watermark_png,
)
from reels_editor.style import StylePreset


def extract_frame(video_path: Path, at_s: float, out: Path) -> Path | None:
    out.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{at_s:.3f}",
         "-i", str(video_path), "-frames:v", "1", str(out)],
        capture_output=True)
    return out if r.returncode == 0 and out.is_file() else None


def compose_preview(frame: Path | None, title_text: str, title_keyword: str,
                    sub_text: str, sub_keywords: list[str],
                    style: StylePreset) -> bytes:
    W, H = style.canvas
    vw, vh = style.video_area()
    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    if frame is not None:
        video = Image.open(frame).convert("RGBA")
        ratio = max(vw / video.width, vh / video.height)
        video = video.resize((round(video.width * ratio),
                              round(video.height * ratio)))
        x = (video.width - vw) // 2
        y = (video.height - vh) // 2
        canvas.paste(video.crop((x, y, x + vw, y + vh)), (0, style.top_bar))
    else:
        canvas.paste(Image.new("RGBA", (vw, vh), (60, 60, 60, 255)),
                     (0, style.top_bar))
    with tempfile.TemporaryDirectory(prefix="reels_preview_") as td:
        tdir = Path(td)
        overlays: list[Path] = []
        if title_text:
            overlays.append(render_title_png(title_text, title_keyword, style,
                                             tdir / "title.png"))
        overlays.append(render_watermark_png(style, tdir / "wm.png"))
        if sub_text:
            overlays += render_subtitle_pngs([[0.0, 1.0, sub_text]],
                                             sub_keywords, style, tdir / "subs")
        for p in overlays:
            canvas.alpha_composite(Image.open(p).convert("RGBA"))
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG")
    return buf.getvalue()
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_preview.py -q` → PASS

- [ ] **Step 5: Commit** — `git add reels_editor/preview.py tests/test_preview.py && git commit -m "feat(preview): 정지 프레임 위 스타일 프리뷰 합성 (렌더 코드 재사용)"`

---

### Task 9: gate_html.py — 다중 스토리라인 게이트 페이지

**Files:**
- Create: `reels_editor/gate_html.py` (기존 gate.py의 `_beat_rows`·`_title_html`·`build_gate_html` 이동·확장)
- Modify: `reels_editor/gate.py` (HTML 함수 제거, gate_html 재수출로 하위호환)
- Test: `tests/test_gate_html.py`

**Interfaces:**
- Consumes: `StorylineResult`(Task 6), `AppConfig`(Task 1)
- Produces: `build_gate_html(storylines: list[StorylineResult], segments: dict, thumbs: dict[int, dict[int, str]], durations: dict[int, float], target_s: int, cfg: AppConfig, key_status: dict[str, str]) -> str`
  - `thumbs[si][cut_i]` = base64 jpg, `durations[si]` = 예상 길이(초)
  - `key_status` 예: `{"openai": "✓ 환경변수", "kimi": "✗ 없음"}`
- HTML 계약 (gate.py 서버와 브라우저 JS가 공유):
  - 조합 체크박스: `<input type="checkbox" name="combo" value="{si}-{ti}">`
  - 재생성 체크박스: `<input type="checkbox" name="regen" value="{si}">`
  - 설정 입력 id: `set-provider, set-model, set-base_url, set-api_key, set-n_storylines, set-sub_size, set-title_size, set-sub_highlight, set-title_highlight, set-sub_y_frac, set-sub_box_alpha, set-speed`
  - 프리뷰 이미지: `<img id="preview-img">`, 버튼 `#preview-btn` → `GET /preview?{설정 쿼리}`
  - 결정 POST `/decision` body: `{"action": "render"|"revise", "combos": [[si, ti], …], "regen": [si, …], "feedback": str, "settings": {id 접두사 뗀 키: 값}}`

- [ ] **Step 1: 실패 테스트 작성**

```python
# tests/test_gate_html.py
"""게이트 HTML: 스토리라인 카드·조합 체크박스·설정 필드·경고 배지."""
from reels_editor.config import AppConfig
from reels_editor.gate_html import build_gate_html
from reels_editor.storyteller import StorylineResult


def _doc(title_texts):
    return {"story": {"five_lines": {"situation": "상황"}, "lens": "렌즈"},
            "title_candidates": [{"text": t, "keyword": t[:2]} for t in title_texts],
            "subtitle_keywords": ["키워드"],
            "cuts": [{"beat": "훅", "seg_ids": ["s1"]}]}


def _segments():
    return {"segments": [{"id": "s1", "text": "안녕하세요",
                          "source_start_us": 0, "source_end_us": 1_000_000}],
            "video_path": "v.mp4"}


def test_html_renders_combo_checkboxes_per_storyline_title() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc(["타이틀A", "타이틀B"])),
          StorylineResult(1, "반전형", _doc(["타이틀C"]))]
    html = build_gate_html(sl, _segments(), {}, {0: 29.0, 1: 31.0}, 30,
                           AppConfig(), {})
    for v in ("0-0", "0-1", "1-0"):
        assert f'name="combo" value="{v}"' in html
    assert 'name="regen" value="0"' in html
    assert "정면승부형" in html and "반전형" in html


def test_html_shows_failed_storyline_error() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc(["타이틀A"])),
          StorylineResult(1, "반전형", None, "boom 오류")]
    html = build_gate_html(sl, _segments(), {}, {0: 29.0}, 30, AppConfig(), {})
    assert "boom 오류" in html
    assert 'name="combo" value="1-0"' not in html   # 실패분엔 조합 없음


def test_html_settings_fields_reflect_config() -> None:
    cfg = AppConfig(provider="kimi", model="kimi-k2-0905-preview")
    html = build_gate_html(
        [StorylineResult(0, "정면승부형", _doc(["티"]))],
        _segments(), {}, {0: 30.0}, 30, cfg, {"kimi": "✓ 환경변수"})
    assert 'id="set-provider"' in html and 'id="set-sub_size"' in html
    assert "✓ 환경변수" in html
    assert 'id="preview-img"' in html


def test_html_duration_warning_badge() -> None:
    html = build_gate_html(
        [StorylineResult(0, "정면승부형", _doc(["티"]))],
        _segments(), {}, {0: 40.0}, 30, AppConfig(), {})
    assert "±10%" in html
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_gate_html.py -q` → FAIL

- [ ] **Step 3: 구현** — `gate_html.py` 신규. 기존 gate.py의 `_beat_rows`/`_title_html`/CSS를 옮기고 다중 스토리라인·설정 패널·프리뷰·결정 JS를 추가한 전체 코드:

```python
# reels_editor/gate_html.py
"""게이트 페이지 HTML 빌드 (서버 로직은 gate.py). 계약은 tests/test_gate_html.py."""
from __future__ import annotations

import html as html_mod

from reels_editor.config import PROVIDERS, AppConfig
from reels_editor.storyteller import StorylineResult

_SETTING_FIELDS = [   # (키, 라벨, input 타입, 속성)
    ("model", "모델명 (빈칸=기본)", "text", ""),
    ("base_url", "Base URL (custom 전용)", "text", ""),
    ("api_key", "API 키 (저장 시 credentials로)", "password", ""),
    ("n_storylines", "스토리라인 개수", "number", 'min="1" max="3"'),
    ("sub_size", "자막 크기", "number", 'min="28" max="72"'),
    ("title_size", "타이틀 크기", "number", 'min="48" max="96"'),
    ("sub_highlight", "자막 포인트 컬러", "color", ""),
    ("title_highlight", "타이틀 포인트 컬러", "color", ""),
    ("sub_y_frac", "자막 위치(0~1)", "number", 'min="0.5" max="1" step="0.01"'),
    ("sub_box_alpha", "자막 박스 불투명도", "number", 'min="0" max="255"'),
    ("speed", "배속", "number", 'min="0.5" max="2" step="0.05"'),
]


def _title_html(t: dict) -> str:
    text = t["text"]
    keyword = t.get("keyword", "")
    escaped = html_mod.escape(text)
    if keyword:
        ek = html_mod.escape(keyword)
        escaped = escaped.replace(ek, f"<em>{ek}</em>")
    return f'<span class="title-preview" title="{html_mod.escape(text)}">{escaped}</span>'


def _beat_rows(doc: dict, segments: dict, thumbs: dict[int, str]) -> str:
    idx = {s["id"]: s for s in segments["segments"]}
    rows = []
    for i, cut in enumerate(doc["cuts"]):
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        img = (f'<img src="data:image/jpeg;base64,{thumbs[i]}" alt="">'
               if i in thumbs else "")
        rows.append(
            f'<div class="beat">{img}<div>'
            f'<h3>{html_mod.escape(cut.get("beat") or f"cut {i + 1}")}</h3>'
            f'<p>{html_mod.escape(text)}</p></div></div>')
    return "\n".join(rows)


def _storyline_card(r: StorylineResult, segments: dict,
                    thumbs: dict[int, str], duration_s: float | None,
                    target_s: int) -> str:
    si = r.index
    head = f"스토리라인 {si + 1} · {html_mod.escape(r.angle_name)}"
    if r.doc is None:
        return (f'<section class="card fail"><h2>{head} — 생성 실패</h2>'
                f'<p class="warn">{html_mod.escape(r.error or "")}</p>'
                f'<label><input type="checkbox" name="regen" value="{si}" checked>'
                f'재생성</label></section>')
    badge = ""
    if duration_s is not None:
        over = abs(duration_s - target_s) > target_s * 0.10
        badge = (f'<span class="warn">⚠️ {duration_s:.1f}초 (목표 {target_s}초 ±10% 벗어남)</span>'
                 if over else f"<span>총 {duration_s:.1f}초</span>")
    five = r.doc.get("story", {}).get("five_lines", {})
    skeleton = " → ".join(html_mod.escape(five.get(k, "")) for k in
                          ("situation", "desire", "conflict", "change", "result"))
    lens = html_mod.escape(r.doc.get("story", {}).get("lens", ""))
    titles = "".join(
        f'<label><input type="checkbox" name="combo" value="{si}-{ti}" '
        f'{"checked" if ti == 0 else ""}>{_title_html(t)}</label>'
        for ti, t in enumerate(r.doc["title_candidates"]))
    keywords = ", ".join(html_mod.escape(k)
                         for k in r.doc.get("subtitle_keywords", []))
    return f"""<section class="card"><h2>{head} {badge}</h2>
<p>{skeleton}</p><p>렌즈: {lens}</p>
<p>자막 강조: <span style="color:#ff3b30">{keywords}</span></p>
<h3>렌더할 타이틀 선택</h3>{titles}
{_beat_rows(r.doc, segments, thumbs)}
<label><input type="checkbox" name="regen" value="{si}">이 스토리라인 재생성</label>
</section>"""


def _settings_panel(cfg: AppConfig, key_status: dict[str, str]) -> str:
    provider_opts = "".join(
        f'<option value="{p}" {"selected" if p == cfg.provider else ""}>{p}</option>'
        for p in PROVIDERS)
    status = " · ".join(f"{p}: {s}" for p, s in key_status.items()) or "-"
    values = {"model": cfg.model, "base_url": cfg.base_url,
              "n_storylines": cfg.n_storylines, **cfg.style}
    fields = []
    for key, label, typ, attrs in _SETTING_FIELDS:
        val = html_mod.escape(str(values.get(key, "")))
        fields.append(f'<label class="set">{label}'
                      f'<input id="set-{key}" type="{typ}" value="{val}" {attrs}>'
                      f'</label>')
    return f"""<details class="card"><summary>⚙︎ 설정</summary>
<p class="hint">모델 변경은 재생성/다음 실행부터 적용됩니다. 키 상태 — {status}</p>
<label class="set">프로바이더<select id="set-provider">{provider_opts}</select></label>
{"".join(fields)}
<button type="button" id="preview-btn">프리뷰 갱신</button><br>
<img id="preview-img" alt="프리뷰">
</details>"""


def build_gate_html(storylines: list[StorylineResult], segments: dict,
                    thumbs: dict[int, dict[int, str]], durations: dict[int, float],
                    target_s: int, cfg: AppConfig,
                    key_status: dict[str, str]) -> str:
    cards = "\n".join(
        _storyline_card(r, segments, thumbs.get(r.index, {}),
                        durations.get(r.index), target_s)
        for r in storylines)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>대본 검토 — reels-editor</title><style>
body{{font-family:Pretendard,-apple-system,sans-serif;background:#111;color:#eee;
     max-width:820px;margin:2rem auto;padding:0 1rem}}
.warn{{color:#ff3b30;font-weight:700}}
.hint{{color:#999;font-size:.85rem}}
.card{{background:#1c1c1c;border-radius:12px;padding:1rem;margin:1rem 0}}
.card.fail{{border:1px solid #ff3b30}}
.title-preview{{font-weight:800;font-size:1.15rem;margin-left:.5rem}}
.title-preview em{{color:#ff7a00;font-style:normal}}
label{{display:block;margin:.4rem 0}}
label.set{{display:flex;justify-content:space-between;max-width:420px;gap:1rem}}
.beat{{display:flex;gap:1rem;background:#242424;border-radius:12px;
      padding:1rem;margin:.6rem 0}}
.beat img{{width:135px;border-radius:8px;align-self:center}}
.beat h3{{margin:0 0 .3rem;color:#ff7a00}}
#preview-img{{max-width:270px;margin-top:.6rem;border-radius:8px}}
textarea{{width:100%;background:#222;color:#eee;border:1px solid #444;
         border-radius:8px;min-height:70px}}
button{{font-size:1rem;padding:.6rem 1.4rem;border-radius:8px;border:0;
       cursor:pointer;margin-right:.6rem}}
#render{{background:#30d158}}#revise{{background:#ff9f0a}}
</style></head><body>
<h1>🎬 대본 검토</h1>
{_settings_panel(cfg, key_status)}
{cards}
<section class="card"><h2>결정</h2>
<textarea id="fb" placeholder="수정 요청 내용 (재생성 시에만)"></textarea><br><br>
<button id="render">✅ 선택한 조합 렌더</button>
<button id="revise">✏️ 선택한 스토리라인 재생성</button></section>
<script>
const SET_KEYS=["provider","model","base_url","api_key","n_storylines","sub_size",
 "title_size","sub_highlight","title_highlight","sub_y_frac","sub_box_alpha","speed"];
function settings(){{
  const o={{}};
  for(const k of SET_KEYS){{
    const el=document.getElementById("set-"+k);
    if(el && el.value!=="") o[k]=el.value;
  }}
  return o;
}}
function checkedVals(name){{
  return [...document.querySelectorAll(`input[name=${{name}}]:checked`)]
    .map(el=>el.value);
}}
document.getElementById("preview-btn").onclick=()=>{{
  const q=new URLSearchParams(settings());
  q.delete("api_key");
  document.getElementById("preview-img").src="/preview?"+q.toString()+"&_="+Date.now();
}};
function send(action){{
  const combos=checkedVals("combo").map(v=>v.split("-").map(Number));
  const regen=checkedVals("regen").map(Number);
  if(action==="render" && combos.length===0){{alert("렌더할 조합을 선택하세요");return;}}
  if(action==="revise" && regen.length===0){{alert("재생성할 스토리라인을 선택하세요");return;}}
  fetch("/decision",{{method:"POST",headers:{{"Content-Type":"application/json"}},
    body:JSON.stringify({{action,combos,regen,
      feedback:document.getElementById("fb").value,settings:settings()}})}})
    .then(()=>document.body.innerHTML="<h1>전달됨 — 터미널로 돌아가세요</h1>");
}}
document.getElementById("render").onclick=()=>send("render");
document.getElementById("revise").onclick=()=>send("revise");
</script></body></html>"""
```

gate.py에서는 `build_gate_html`·`_beat_rows`·`_title_html`(구버전 단일 스토리라인용)을 삭제하고, 이를 참조하던 기존 테스트(test_gate.py)가 있으면 새 시그니처 기준으로 수정한다 (단일→다중 래핑: `StorylineResult(0, "정면승부형", edl_doc)`).

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_gate_html.py tests/test_gate.py -q` → PASS

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(gate): 다중 스토리라인 카드·조합 체크박스·설정 패널 HTML"`

---

### Task 10: gate.py — 서버 v2 (/decision·/preview) + MultiGateDecision

**Files:**
- Modify: `reels_editor/gate.py`
- Test: `tests/test_gate.py` (추가)

**Interfaces:**
- Produces:
  - `@dataclass MultiGateDecision(action: str, combos: list[tuple[int, int]], regen: list[int], feedback: str, settings: dict)`
  - `parse_decision(body: dict) -> MultiGateDecision` (검증 실패 시 ValueError)
  - `run_gate_v2(html: str, preview_fn: Callable[[dict], bytes], *, open_browser: bool = True, port: int = 0) -> MultiGateDecision`
  - `preview_fn`: 쿼리 파라미터 dict(str→str)를 받아 PNG 바이트 반환. 예외 시 500 + 짧은 에러.
- 기존 `run_gate`/`GateDecision`은 삭제 (사용처는 cli.py뿐 — Task 12에서 교체).

- [ ] **Step 1: 실패 테스트 작성** (tests/test_gate.py 에 추가)

```python
import json
import urllib.request
import threading

from reels_editor.gate import MultiGateDecision, parse_decision, run_gate_v2


def test_parse_decision_valid() -> None:
    d = parse_decision({"action": "render", "combos": [[0, 1], [2, 0]],
                        "regen": [], "feedback": "", "settings": {"sub_size": "52"}})
    assert d.combos == [(0, 1), (2, 0)]
    assert d.settings["sub_size"] == "52"


def test_parse_decision_rejects_bad_action() -> None:
    import pytest
    with pytest.raises(ValueError):
        parse_decision({"action": "nope", "combos": [], "regen": [],
                        "feedback": "", "settings": {}})


def test_run_gate_v2_serves_preview_and_decision() -> None:
    calls = {}

    def preview_fn(params: dict) -> bytes:
        calls["params"] = params
        return b"\x89PNG fake"

    result: list[MultiGateDecision] = []

    def client(url: str) -> None:
        # 프리뷰 요청
        with urllib.request.urlopen(url + "preview?sub_size=50") as r:
            assert r.read() == b"\x89PNG fake"
        # 결정 POST
        body = json.dumps({"action": "render", "combos": [[0, 0]], "regen": [],
                           "feedback": "", "settings": {}}).encode()
        req = urllib.request.Request(url + "decision", data=body,
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req)

    # run_gate_v2는 블로킹이므로 클라이언트를 별도 스레드에서 실행
    import queue
    q: queue.Queue = queue.Queue()

    def serve():
        q_url = q.get()
        client(q_url)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    d = run_gate_v2("<html>ok</html>", preview_fn, open_browser=False,
                    port=0, on_url=q.put)
    assert d.action == "render" and d.combos == [(0, 0)]
    assert calls["params"] == {"sub_size": "50"}
```

`on_url: Callable[[str], None] | None = None` 파라미터를 인터페이스에 추가한다 (테스트가 포트를 알 수 있는 유일한 통로. 기존 run_gate의 print 위치에서 호출).

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_gate.py -q` → FAIL

- [ ] **Step 3: 구현** (gate.py — 기존 run_gate 대체)

```python
from urllib.parse import parse_qsl, urlparse


@dataclass(frozen=True)
class MultiGateDecision:
    action: str                       # "render" | "revise"
    combos: list[tuple[int, int]]     # (storyline_index, title_index)
    regen: list[int]
    feedback: str = ""
    settings: dict = None             # type: ignore[assignment]


def parse_decision(body: dict) -> MultiGateDecision:
    action = body.get("action")
    if action not in ("render", "revise"):
        raise ValueError(f"알 수 없는 action: {action!r}")
    combos = [(int(a), int(b)) for a, b in body.get("combos", [])]
    regen = [int(i) for i in body.get("regen", [])]
    settings = body.get("settings") or {}
    if not isinstance(settings, dict):
        raise ValueError("settings는 객체여야 함")
    return MultiGateDecision(action, combos, regen,
                             str(body.get("feedback", "")), settings)


def run_gate_v2(html: str, preview_fn: Callable[[dict], bytes], *,
                open_browser: bool = True, port: int = 0,
                on_url: Callable[[str], None] | None = None) -> MultiGateDecision:
    decision: list[MultiGateDecision] = []
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/preview":
                try:
                    png = preview_fn(dict(parse_qsl(parsed.query)))
                except Exception as e:  # noqa: BLE001 — 프리뷰 실패는 게이트를 죽이면 안 됨
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e)[:200].encode())
                    return
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.end_headers()
                self.wfile.write(png)
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length") or 0)
                d = parse_decision(json.loads(self.rfile.read(length)))
            except (TypeError, ValueError, KeyError):
                self.send_response(400)
                self.end_headers()
                return
            decision.append(d)
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args: object) -> None:
            pass

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    if on_url:
        on_url(url)
    if open_browser:
        webbrowser.open(url)
    print(f"대본 검토 페이지: {url}")
    done.wait()
    server.shutdown()
    return decision[0]
```

구 `GateDecision`·`run_gate`는 삭제, `extract_thumbs`는 유지. test_gate.py의 구버전 테스트는 신 시그니처로 이관.

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_gate.py -q` → PASS

- [ ] **Step 5: Commit** — `git commit -am "feat(gate): 서버 v2 — 조합 결정·설정 수신·/preview 엔드포인트"`

---

### Task 11: gate.py — 터미널 폴백 조합 선택

**Files:**
- Modify: `reels_editor/gate.py`
- Test: `tests/test_gate.py` (추가)

**Interfaces:**
- Produces: `parse_combo_selection(raw: str, storylines: list[StorylineResult]) -> list[tuple[int, int]]` ("1-2,3-1" 1-기반 → 0-기반, 검증 실패 ValueError), `run_gate_terminal_v2(storylines, segments, durations: dict[int, float], target_s: int, input_fn=input) -> MultiGateDecision`

- [ ] **Step 1: 실패 테스트 작성**

```python
from reels_editor.gate import parse_combo_selection, run_gate_terminal_v2
from reels_editor.storyteller import StorylineResult


def test_parse_combo_selection() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc2()),
          StorylineResult(1, "반전형", _doc2())]
    assert parse_combo_selection("1-2, 2-1", sl) == [(0, 1), (1, 0)]


def test_parse_combo_selection_rejects_out_of_range() -> None:
    import pytest
    sl = [StorylineResult(0, "정면승부형", _doc2())]
    with pytest.raises(ValueError):
        parse_combo_selection("2-1", sl)
    with pytest.raises(ValueError):
        parse_combo_selection("1-9", sl)
    with pytest.raises(ValueError):
        parse_combo_selection("난수", sl)


def _doc2():
    return {"story": {"five_lines": {}, "lens": ""},
            "title_candidates": [{"text": "가", "keyword": ""},
                                 {"text": "나", "keyword": ""}],
            "subtitle_keywords": [],
            "cuts": [{"beat": "훅", "seg_ids": ["s1"]}]}


def test_run_gate_terminal_v2_render_flow() -> None:
    sl = [StorylineResult(0, "정면승부형", _doc2())]
    answers = iter(["1-1", "y"])
    d = run_gate_terminal_v2(sl, _segments_fixture(), {0: 30.0}, 30,
                             input_fn=lambda _: next(answers))
    assert d.action == "render" and d.combos == [(0, 0)]


def _segments_fixture():
    return {"segments": [{"id": "s1", "text": "안녕",
                          "source_start_us": 0, "source_end_us": 1_000_000}],
            "video_path": "v.mp4"}
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_gate.py -q` → FAIL

- [ ] **Step 3: 구현** (gate.py 에 추가; 구 `run_gate_terminal`·`_ask_title_index`는 삭제하고 대체)

```python
def parse_combo_selection(raw: str,
                          storylines: list) -> list[tuple[int, int]]:
    by_index = {r.index: r for r in storylines if r.doc is not None}
    combos: list[tuple[int, int]] = []
    for token in raw.split(","):
        token = token.strip()
        parts = token.split("-")
        if len(parts) != 2:
            raise ValueError(f"형식 오류: {token!r} (예: 1-2,3-1)")
        try:
            si, ti = int(parts[0]) - 1, int(parts[1]) - 1
        except ValueError as e:
            raise ValueError(f"숫자가 아님: {token!r}") from e
        if si not in by_index:
            raise ValueError(f"스토리라인 {si + 1} 없음")
        if not 0 <= ti < len(by_index[si].doc["title_candidates"]):
            raise ValueError(f"타이틀 {ti + 1} 없음 (스토리라인 {si + 1})")
        combos.append((si, ti))
    if not combos:
        raise ValueError("조합이 비어 있음")
    return combos


def run_gate_terminal_v2(storylines: list, segments: dict,
                         durations: dict[int, float], target_s: int,
                         input_fn: Callable[[str], str] = input):
    idx = {s["id"]: s for s in segments["segments"]}
    for r in storylines:
        if r.doc is None:
            print(f"\n=== 스토리라인 {r.index + 1} ({r.angle_name}) — 생성 실패: {r.error}")
            continue
        dur = durations.get(r.index)
        warn = (" ⚠️ ±10% 벗어남"
                if dur is not None and abs(dur - target_s) > target_s * 0.10 else "")
        print(f"\n=== 스토리라인 {r.index + 1} ({r.angle_name}) — "
              f"{dur:.1f}초/목표 {target_s}초{warn} ===")
        for ti, t in enumerate(r.doc["title_candidates"], 1):
            print(f"  타이틀 {ti}: {t['text']}")
        for cut in r.doc["cuts"]:
            text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
            print(f"  [{cut.get('beat', '?')}] {text}")
    while True:
        raw = input_fn("렌더할 조합 (예 1-2,3-1): ").strip()
        try:
            combos = parse_combo_selection(raw, storylines)
            break
        except ValueError as e:
            print(f"입력 오류: {e}")
    ans = input_fn("[y] 렌더 / 그 외 입력 = 전체 재생성 피드백: ").strip()
    if ans.lower() == "y":
        return MultiGateDecision("render", combos, [], "", {})
    regen = [r.index for r in storylines]
    return MultiGateDecision("revise", combos, regen, ans, {})
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_gate.py -q` → PASS

- [ ] **Step 5: Commit** — `git commit -am "feat(gate): 터미널 폴백 조합 선택 (1-2,3-1)"`

---

### Task 12: cli.py — 다중 스토리라인 오케스트레이션 + 병렬 렌더 + manifest

**Files:**
- Modify: `reels_editor/cli.py`, `pyproject.toml` (`rich>=13` 의존성 추가)
- Test: `tests/test_cli.py` (추가)

**Interfaces:**
- Consumes: 모든 이전 태스크 산출물
- Produces:
  - `make` 옵션 추가: `--storylines N`(기본 config), `--config PATH`(테스트용)
  - `render_combos(video, segments, storylines, combos, style, work, speed, progress=None) -> list[dict]` — 조합 병렬 렌더(base는 스토리라인당 1회, `ThreadPoolExecutor(max_workers=2)`), 반환은 manifest outputs 항목 리스트 `{"storyline": si+1, "title_index": ti+1, "title": str, "file": "s1/reel-t2.mp4", "error": str | None}`
  - `write_manifest(work: Path, cfg: AppConfig, outputs: list[dict]) -> Path` — api_key 절대 미포함
  - `apply_gate_settings(decision_settings: dict, cfg: AppConfig, config_path, credentials_path) -> AppConfig` — 문자열 값을 타입 변환해 AppConfig 갱신·저장, api_key는 credentials에 저장 후 폐기
- 산출물 레이아웃: `work/s{si+1}/` 아래 `edl.json`(selected_title 없음 — 조합별이므로), `segments.json`, `reel-t{ti+1}.mp4`, `reel.srt`, `cuts/`

- [ ] **Step 1: 실패 테스트 작성** (tests/test_cli.py 에 추가 — 순수 부분만; ffmpeg 통합은 Task 13)

```python
from reels_editor.cli import apply_gate_settings, write_manifest
from reels_editor.config import AppConfig, load_config, resolve_api_key


def test_apply_gate_settings_types_and_persists(tmp_path) -> None:
    cfgp, credp = tmp_path / "c.yaml", tmp_path / "cred.yaml"
    cfg = apply_gate_settings(
        {"provider": "kimi", "n_storylines": "2", "sub_size": "52",
         "sub_y_frac": "0.9", "api_key": "sk-new-key-abcd"},
        AppConfig(), cfgp, credp)
    assert cfg.provider == "kimi" and cfg.n_storylines == 2
    assert cfg.style["sub_size"] == 52 and cfg.style["sub_y_frac"] == 0.9
    assert load_config(cfgp) == cfg                      # 저장됨
    assert resolve_api_key("kimi", credp) == "sk-new-key-abcd"


def test_write_manifest_excludes_secrets(tmp_path) -> None:
    import json
    p = write_manifest(tmp_path, AppConfig(provider="openai"),
                       [{"storyline": 1, "title_index": 1, "title": "티",
                         "file": "s1/reel-t1.mp4", "error": None}])
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["outputs"][0]["file"] == "s1/reel-t1.mp4"
    assert "api_key" not in json.dumps(data)
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_cli.py -q` → FAIL

- [ ] **Step 3: 구현** — cli.py 재작성. 전체 코드:

```python
"""reels-editor CLI — make(다중 스토리라인 파이프라인) / render(재렌더)."""
from __future__ import annotations

import dataclasses
import datetime as dt
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn

from reels_editor import capcut, edl, export, gate, gate_html, preview, render
from reels_editor.config import (
    STYLE_OVERRIDE_KEYS, AppConfig, credentials_path, load_config,
    mask_key, resolve_api_key, save_config, save_credential, merged_style,
    user_config_path,
)
from reels_editor.llm import build_runner
from reels_editor.storyteller import StorylineResult, generate_many
from reels_editor.style import StylePreset, load_style

app = typer.Typer(help="창업가 인터뷰 → 30초 스토리텔링 릴스")
console = Console()
DEFAULT_STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"
MAX_PARALLEL_RENDERS = 2

_INT_KEYS = {"n_storylines", "sub_size", "title_size", "sub_box_alpha"}
_FLOAT_KEYS = {"sub_y_frac", "speed"}


def preflight(project: str | None, style_path: Path) -> list[str]:
    problems: list[str] = []
    for binname, hint in (("ffmpeg", "brew install ffmpeg"),
                          ("ffprobe", "brew install ffmpeg")):
        if not shutil.which(binname):
            problems.append(f"{binname} 없음 — {hint}")
    try:
        load_style(style_path)
    except (FileNotFoundError, KeyError) as e:
        problems.append(f"스타일 로드 실패: {e}")
    if project is not None:
        try:
            pdir = capcut.find_project(project)
            segs = capcut.build_segments(capcut.load_project(pdir))
            if not segs["segments"]:
                problems.append("자동자막이 없습니다 — CapCut에서 Text → 자동자막을 먼저 생성하세요.")
        except (FileNotFoundError, ValueError, KeyError) as e:
            problems.append(str(e))
    return problems


def _fail_if_problems(problems: list[str]) -> None:
    if problems:
        for p in problems:
            console.print(f"[red]✗[/] {p}")
        raise typer.Exit(1)


def apply_gate_settings(settings: dict, cfg: AppConfig,
                        config_path: Path | None = None,
                        creds_path: Path | None = None) -> AppConfig:
    """게이트가 보낸 문자열 설정을 타입 변환해 저장. api_key는 credentials로 분리."""
    s = dict(settings)
    api_key = s.pop("api_key", None)
    style = dict(cfg.style)
    top: dict = {}
    for k, v in s.items():
        if k in _INT_KEYS:
            v = int(v)
        elif k in _FLOAT_KEYS:
            v = float(v)
        if k in STYLE_OVERRIDE_KEYS:
            style[k] = v
        elif k in ("provider", "model", "base_url", "n_storylines"):
            top[k] = v
    new = dataclasses.replace(cfg, style=style, **top)
    save_config(new, config_path)
    if api_key:
        save_credential(new.provider, api_key, creds_path)
    return new


def write_manifest(work: Path, cfg: AppConfig, outputs: list[dict]) -> Path:
    doc = {"created": dt.datetime.now().isoformat(timespec="seconds"),
           "provider": cfg.provider, "model": cfg.model,
           "n_storylines": cfg.n_storylines, "style": cfg.style,
           "outputs": outputs}
    p = work / "manifest.json"
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def _storyline_outputs(work: Path, si: int, segments: dict, doc: dict,
                       style: StylePreset, speed: float) -> Path:
    """스토리라인 폴더에 수정용 재료(edl/segments/srt/cuts) 기록."""
    sdir = work / f"s{si + 1}"
    export.write_outputs(sdir, doc, segments)
    ordered = edl.ordered_segments(doc, segments)
    groups = render.group_captions([
        [a, b, render.apply_text_fixes(t, render.DEFAULT_TEXT_FIXES)]
        for a, b, t in render.timeline_items(ordered, speed)])
    export.write_srt(groups, sdir / "reel.srt")
    cuts_dir = sdir / "cuts"
    if cuts_dir.is_dir():
        for old in cuts_dir.glob("*.mp4"):
            old.unlink()
    export.export_cuts(Path(segments["video_path"]), doc, segments, cuts_dir, speed)
    return sdir


def render_combos(video: Path, segments: dict,
                  storylines: list[StorylineResult],
                  combos: list[tuple[int, int]], style: StylePreset,
                  work: Path, speed: float,
                  progress: Progress | None = None) -> list[dict]:
    """base는 스토리라인당 1회(병렬 2), 타이틀 오버레이는 조합별."""
    docs = {r.index: r.doc for r in storylines if r.doc is not None}
    by_story: dict[int, list[int]] = {}
    for si, ti in combos:
        by_story.setdefault(si, []).append(ti)
    outputs: list[dict] = []

    def one_storyline(si: int) -> list[dict]:
        doc = docs[si]
        sdir = _storyline_outputs(work, si, segments, doc, style, speed)
        task_id = (progress.add_task(f"s{si + 1} base 렌더", total=1.0)
                   if progress else None)
        cb = ((lambda f: progress.update(task_id, completed=f))
              if progress else None)
        rows: list[dict] = []
        try:
            assets = render.render_base_and_assets(
                video, segments, doc, style, sdir / ".render", speed,
                progress_cb=cb)
        except (RuntimeError, ValueError) as e:
            return [{"storyline": si + 1, "title_index": ti + 1,
                     "title": doc["title_candidates"][ti]["text"],
                     "file": None, "error": str(e)} for ti in by_story[si]]
        for ti in by_story[si]:
            t = doc["title_candidates"][ti]
            out = sdir / f"reel-t{ti + 1}.mp4"
            try:
                render.render_with_title(assets, t["text"],
                                         t.get("keyword", ""), style, out)
                rows.append({"storyline": si + 1, "title_index": ti + 1,
                             "title": t["text"],
                             "file": str(out.relative_to(work)), "error": None})
            except RuntimeError as e:
                rows.append({"storyline": si + 1, "title_index": ti + 1,
                             "title": t["text"], "file": None, "error": str(e)})
        if progress and task_id is not None:
            progress.update(task_id, completed=1.0)
        return rows

    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_RENDERS) as ex:
        for rows in ex.map(one_storyline, sorted(by_story)):
            outputs.extend(rows)
    return outputs


def _key_status(cfg: AppConfig) -> dict[str, str]:
    status = {}
    for p in ("openai", "kimi", "custom"):
        key = resolve_api_key(p)
        status[p] = f"✓ {mask_key(key)}" if key else "✗ 없음"
    return status


@app.command()
def make(project: str,
         speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
         duration: int = typer.Option(30, help="목표 길이(초)"),
         style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
         storylines: int = typer.Option(None, help="스토리라인 개수 (기본: 설정)"),
         no_ui: bool = typer.Option(False, "--no-ui", help="터미널 게이트 사용"),
         out: Path = typer.Option(Path("out"), help="산출물 루트")) -> None:
    """CapCut 프로젝트 → 다중 스토리라인 게이트 → 조합별 릴스."""
    _fail_if_problems(preflight(project, style))
    cfg = load_config()
    if storylines is not None:
        cfg = dataclasses.replace(cfg, n_storylines=storylines)
    preset = merged_style(load_style(style), cfg.style)
    spd = speed if speed is not None else preset.speed
    pdir = capcut.find_project(project)
    segments = capcut.build_segments(capcut.load_project(pdir))
    video = Path(segments["video_path"])
    work = out / f"{pdir.name}-{dt.date.today():%Y%m%d}"
    work.mkdir(parents=True, exist_ok=True)
    console.print(f"[green]✓[/] 자막 {len(segments['segments'])}개 로드")

    results: dict[int, StorylineResult] = {}
    feedback: str | None = None
    todo: list[int] | None = None      # None = 전체 생성
    while True:
        runner = build_runner(cfg)
        with console.status(f"🧠 대본 생성 중 ({cfg.provider}) — "
                            f"스토리라인 {cfg.n_storylines}개 병렬…"):
            fresh = generate_many(segments, cfg.n_storylines, duration,
                                  runner=runner, raw_dump_dir=work,
                                  feedback=feedback, only_indices=todo)
        for r in fresh:
            results[r.index] = r
            mark = "[green]✓[/]" if r.doc else f"[red]✗ {r.error}[/]"
            console.print(f"  스토리라인 {r.index + 1} ({r.angle_name}) {mark}")
        alive = [results[i] for i in sorted(results)]
        if all(r.doc is None for r in alive):
            console.print("[red]✗ 모든 스토리라인 생성 실패[/] — "
                          f"원문 응답: {work}/llm_raw_s*.txt")
            raise typer.Exit(1)
        durations = {r.index: edl.estimate_duration_s(r.doc, segments, spd)
                     for r in alive if r.doc is not None}
        if no_ui:
            decision = gate.run_gate_terminal_v2(alive, segments, durations,
                                                 duration)
        else:
            thumbs = {r.index: gate.extract_thumbs(video, r.doc, segments,
                                                   work / f".thumbs/s{r.index + 1}")
                      for r in alive if r.doc is not None}
            html = gate_html.build_gate_html(alive, segments, thumbs, durations,
                                             duration, cfg, _key_status(cfg))

            def preview_fn(params: dict) -> bytes:
                p_style = merged_style(preset, {
                    k: (int(v) if k in _INT_KEYS else
                        float(v) if k in _FLOAT_KEYS else v)
                    for k, v in params.items() if k in STYLE_OVERRIDE_KEYS})
                first = next(r for r in alive if r.doc is not None)
                t0 = first.doc["title_candidates"][0]
                sub = first.doc["cuts"][0]
                idx = {s["id"]: s for s in segments["segments"]}
                sub_text = " ".join(idx[sid]["text"]
                                    for sid in sub["seg_ids"] if sid in idx)[:20]
                frame = preview.extract_frame(
                    video,
                    idx[sub["seg_ids"][0]]["source_start_us"] / capcut.US,
                    work / ".thumbs" / "preview_frame.png")
                return preview.compose_preview(
                    frame, t0["text"], t0.get("keyword", ""), sub_text,
                    first.doc.get("subtitle_keywords", []), p_style)

            console.print("⏳ 브라우저에서 검토를 완료하세요…")
            decision = gate.run_gate_v2(html, preview_fn)
        if decision.settings:
            cfg = apply_gate_settings(decision.settings, cfg)
            preset = merged_style(load_style(style), cfg.style)
            spd = speed if speed is not None else preset.speed
        if decision.action == "render":
            break
        feedback = decision.feedback or None
        todo = decision.regen

    with Progress(SpinnerColumn(), TextColumn("{task.description}"),
                  BarColumn(), console=console) as progress:
        outputs = render_combos(video, segments, alive, decision.combos,
                                preset, work, spd, progress)
    write_manifest(work, cfg, outputs)
    failed = [o for o in outputs if o["error"]]
    for o in outputs:
        mark = "[green]✅[/]" if not o["error"] else f"[red]✗ {o['error']}[/]"
        target = o["file"] or f"s{o['storyline']}/reel-t{o['title_index']}.mp4"
        console.print(f"{mark} {target} — {o['title']}")
    console.print(f"📄 manifest: {work}/manifest.json")
    if failed:
        raise typer.Exit(1)


@app.command("render")
def render_cmd(workdir: Path,
               speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
               style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
               title: int = typer.Option(1, help="타이틀 번호(1-기반)")) -> None:
    """수동 수정한 s*/edl.json으로 재렌더 (게이트·LLM 없이)."""
    edl_path, seg_path = workdir / "edl.json", workdir / "segments.json"
    if not edl_path.is_file() or not seg_path.is_file():
        console.print(f"[red]✗[/] {workdir}에 edl.json/segments.json이 없습니다.")
        raise typer.Exit(1)
    _fail_if_problems(preflight(None, style))
    cfg = load_config()
    preset = merged_style(load_style(style), cfg.style)
    spd = speed if speed is not None else preset.speed
    edl_doc = json.loads(edl_path.read_text(encoding="utf-8"))
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    errs = edl.validate_edl(edl_doc, segments)
    if errs:
        console.print("[red]✗ EDL 검증 실패:[/]\n" + "\n".join(errs))
        raise typer.Exit(1)
    video = Path(segments["video_path"])
    assets = render.render_base_and_assets(video, segments, edl_doc, preset,
                                           workdir / ".render", spd)
    t = edl_doc["title_candidates"][title - 1]
    out_path = workdir / f"reel-t{title}.mp4"
    render.render_with_title(assets, t["text"], t.get("keyword", ""), preset,
                             out_path)
    console.print(f"[green]✅ 완료:[/] {out_path}")


if __name__ == "__main__":
    app()
```

pyproject.toml: `dependencies = ["typer>=0.12", "Pillow>=10", "PyYAML>=6", "rich>=13"]` 로 변경 후 `.venv/bin/pip install -e ".[dev]"` 재실행.

preflight에서 `claude` 바이너리 검사는 제거됨에 유의 — 프로바이더가 claude-cli일 때만 필요하므로 `build_runner` 시점 오류로 충분하지만, `make` 시작 시 `cfg.provider == "claude-cli" and not shutil.which("claude")`면 preflight 문제로 추가하는 분기를 넣는다:

```python
    cfg = load_config()
    if cfg.provider == "claude-cli" and not shutil.which("claude"):
        _fail_if_problems(["claude 없음 — Claude Code CLI 설치 또는 게이트에서 프로바이더 변경"])
```

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest tests/test_cli.py -q` → PASS. 전체: `.venv/bin/pytest -q` → PASS (기존 test_cli의 구 흐름 테스트는 신 흐름 기준으로 이관)

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(cli): 다중 스토리라인 오케스트레이션 + 조합 병렬 렌더 + rich 진행 표시 + manifest"`

---

### Task 13: 통합 테스트 — 합성 영상 다중 조합 렌더

**Files:**
- Modify: `tests/test_integration.py` (기존 합성 영상 픽스처 재사용)

**Interfaces:**
- Consumes: 전체 파이프라인. 기존 통합 테스트의 합성 영상 생성 픽스처(ffmpeg lavfi)와 fake runner 패턴을 그대로 따른다 — **먼저 기존 test_integration.py를 읽고 픽스처를 재사용할 것.**

- [ ] **Step 1: 실패 테스트 작성** (기존 픽스처명은 실제 파일 확인 후 맞춤)

```python
def test_multi_combo_render(synthetic_project, tmp_path):
    """스토리라인 2개 × 조합 3개: base 2회만 렌더되고 mp4 3개·manifest 생성."""
    import json
    from reels_editor.cli import render_combos, write_manifest
    from reels_editor.config import AppConfig
    from reels_editor.storyteller import StorylineResult

    segments, video, style = synthetic_project   # 기존 픽스처 형태에 맞춤
    sids = [s["id"] for s in segments["segments"]]
    doc1 = {"story": {"five_lines": {}, "lens": ""},
            "title_candidates": [{"text": "타이틀 하나", "keyword": "하나"},
                                 {"text": "타이틀 둘", "keyword": "둘"}],
            "subtitle_keywords": [], "cuts": [{"beat": "훅", "seg_ids": sids[:1]}]}
    doc2 = {**doc1, "cuts": [{"beat": "훅", "seg_ids": sids[-1:]}]}
    storylines = [StorylineResult(0, "정면승부형", doc1),
                  StorylineResult(1, "반전형", doc2)]
    combos = [(0, 0), (0, 1), (1, 0)]
    work = tmp_path / "work"
    work.mkdir()
    outputs = render_combos(video, segments, storylines, combos, style,
                            work, speed=1.2)
    assert [o["error"] for o in outputs] == [None, None, None]
    assert (work / "s1" / "reel-t1.mp4").stat().st_size > 0
    assert (work / "s1" / "reel-t2.mp4").stat().st_size > 0
    assert (work / "s2" / "reel-t1.mp4").stat().st_size > 0
    assert (work / "s1" / "reel.srt").is_file()
    manifest = write_manifest(work, AppConfig(), outputs)
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(data["outputs"]) == 3
```

- [ ] **Step 2: 실패 확인** — `.venv/bin/pytest tests/test_integration.py -q` → 신규 테스트 FAIL

- [ ] **Step 3: 구현** — Task 12까지 완료면 통과해야 함. 실패 시 render_combos 경로 수정.

- [ ] **Step 4: 통과 확인** — `.venv/bin/pytest -q` → 전체 PASS

- [ ] **Step 5: Commit** — `git commit -am "test(integration): 스토리라인 2×조합 3 병렬 렌더·manifest 검증"`

---

### Task 14: 문서 갱신

**Files:**
- Modify: `README.md`, `styles/done.yaml` (주석에 설정 오버라이드 안내 1줄)

- [ ] **Step 1: README 사용법 갱신**

```markdown
## 사용
```bash
.venv/bin/reels-editor make "<CapCut 프로젝트명>"   # 스토리라인 3개 병렬 생성 → 브라우저 게이트에서 조합 선택·설정 → 병렬 렌더
.venv/bin/reels-editor render out/<작업폴더>/s1 --title 2   # edl.json 수정 후 재렌더
```

산출물: `out/<프로젝트-날짜>/s{n}/reel-t{m}.mp4`, `reel.srt`, `edl.json`, `cuts/`, `manifest.json`

## 설정
게이트 ⚙︎ 설정에서 AI 프로바이더(claude-cli/openai/kimi/custom)·모델·자막 크기·포인트 컬러를
조절하면 `~/.config/reels-editor/config.yaml`에 저장된다. API 키는 환경변수
(`OPENAI_API_KEY`, `MOONSHOT_API_KEY`) 우선, 게이트 입력 시 credentials.yaml(0600)에 저장.
```

- [ ] **Step 2: 전체 테스트** — `.venv/bin/pytest -q` → PASS

- [ ] **Step 3: Commit** — `git commit -am "docs: 다중 스토리라인 워크플로우 사용법·설정 안내"`

---

## Self-Review 결과

- 스펙 커버리지: 다중 스토리라인(T5-6), 조합 게이트(T9-11), 설정+프리뷰(T1-2, T8-10, T12), LLM 프로바이더(T3-4), 병렬 렌더+진행률(T7, T12), rich CLI(T12), manifest(T12), 문서(T14) — 전 항목 태스크 존재.
- 타입 일관성: `StorylineResult`(T6)를 T9-13이 동일 시그니처로 소비. `MultiGateDecision.combos: list[tuple[int,int]]` 0-기반 통일 (터미널 입력만 1-기반 표기, 파서에서 변환).
- 기존 테스트 이관 필요 지점 명시: test_gate.py(T9-10), test_cli.py(T12), test_integration.py(T13).
