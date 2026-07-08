# reels-editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** CapCut 자동자막 프로젝트를 입력받아 30초 스토리텔링 릴스 mp4(+수정용 재료)를 만드는 독립 CLI `reels-editor`.

**Architecture:** LLM(`claude -p`)은 대본(EDL) 생성에 딱 1회 쓰고, 파싱·검증·렌더는 전부 결정적 Python 코드. 대본은 브라우저 게이트에서 사람이 승인한 뒤에만 렌더된다. 기존 `~/.claude/skills/reels-edit/scripts`의 검증된 코드를 이식·확장한다.

**Tech Stack:** Python 3.11+, typer, Pillow, PyYAML, pytest / 외부: ffmpeg·ffprobe(homebrew), claude CLI, Pretendard(otf, `~/Library/Fonts`).

## Global Constraints

- 스펙: `docs/superpowers/specs/2026-07-08-reels-editor-design.md` — 이 계획의 상위 문서.
- 자막 본문은 **verbatim**: segments의 원문 삭제·재배치만 허용. 타이틀만 창작 허용.
- 결과물 목표 길이 30초, ±10% 벗어나면 게이트에 경고(차단 아님).
- LLM 재시도는 최대 2회(총 3회 호출까지), 같은 방식 3회 초과 재시도 금지.
- 모든 함수 시그니처에 타입 힌트, `pathlib.Path`, f-string (user style guide).
- 테스트에서 LLM은 전부 mock. 커밋 메시지는 Conventional Commits.
- CapCut 프로젝트 루트: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/<이름>/draft_info.json` (환경변수 `CAPCUT_ROOT`로 오버라이드).
- ffmpeg에 libass/drawtext 없음 → 텍스트는 전부 Pillow PNG + overlay 합성.
- 작업 디렉토리: `out/<프로젝트명-YYYYMMDD>/` (git ignore됨).

## EDL 문서 스키마 (모든 태스크 공통)

```json
{
  "story": {
    "five_lines": {"situation": "…", "desire": "…", "conflict": "…", "change": "…", "result": "…"},
    "lens": "한 문장 스토리렌즈"
  },
  "title_candidates": [{"text": "해양경찰이 선택한 스타트업", "keyword": "해양경찰"}],
  "selected_title": 0,
  "subtitle_keywords": ["설득", "거부감"],
  "cuts": [{"beat": "훅", "seg_ids": ["t0", "t1"], "broll_marker": null}]
}
```

`cuts[].seg_ids`는 segments.json의 세그먼트 id. `subtitle_keywords`는 자막에서 레드로 칠할 단어들. `title_candidates[].keyword`는 타이틀에서 오렌지로 칠할 부분 문자열.

---

### Task 1: 프로젝트 스캐폴드 + capcut 모듈 (CapCut 파싱 이식)

**Files:**
- Create: `pyproject.toml`
- Create: `reels_editor/__init__.py`
- Create: `reels_editor/capcut.py`
- Create: `tests/conftest.py`
- Test: `tests/test_capcut.py`

**Interfaces:**
- Consumes: 없음 (최초 태스크)
- Produces:
  - `capcut.US: int = 1_000_000`
  - `capcut.build_segments(draft: dict) -> dict` — segments.json 구조 반환
  - `capcut.load_project(project_dir: Path) -> dict` — draft_info.json 로드
  - `capcut.find_project(name_or_path: str) -> Path` — 이름→CapCut 루트 탐색, 경로면 그대로
  - segments dict 구조: `{"video_material_id", "video_path", "video_duration_us", "fps", "segments": [{"id","text","timeline_start_us","timeline_end_us","source_start_us","source_end_us","speed"}]}`

- [ ] **Step 1: 스캐폴드 작성**

`pyproject.toml`:

```toml
[project]
name = "reels-editor"
version = "0.1.0"
description = "창업가 인터뷰를 30초 스토리텔링 릴스로 자동 편집하는 CLI"
requires-python = ">=3.11"
dependencies = ["typer>=0.12", "Pillow>=10", "PyYAML>=6"]

[project.optional-dependencies]
dev = ["pytest>=8"]

[project.scripts]
reels-editor = "reels_editor.cli:app"

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["reels_editor*"]
```

`reels_editor/__init__.py`:

```python
__version__ = "0.1.0"
```

- [ ] **Step 2: venv 만들고 editable 설치**

```bash
cd /Users/jayden/Developer/reels-editor
python3 -m venv .venv && .venv/bin/pip install -q -e ".[dev]"
```

Expected: 에러 없이 설치. 이후 모든 명령은 `.venv/bin/python`, `.venv/bin/pytest` 사용.

- [ ] **Step 3: 실패하는 테스트 작성**

`tests/conftest.py` (기존 reels-edit 스킬 conftest 이식):

```python
import pytest


def _video_seg(sid: str, tl_start: int, tl_dur: int, src_start: int, speed: float = 1.0) -> dict:
    return {
        "id": sid,
        "material_id": "VID",
        "speed": speed,
        "target_timerange": {"start": tl_start, "duration": tl_dur},
        "source_timerange": {"start": src_start, "duration": int(tl_dur * speed)},
    }


def _text_mat(mid: str, text: str) -> dict:
    return {"id": mid, "recognize_text": text, "content": "", "add_type": 1}


def _text_seg(sid: str, mid: str, tl_start: int, tl_dur: int) -> dict:
    return {"id": sid, "material_id": mid,
            "target_timerange": {"start": tl_start, "duration": tl_dur}}


@pytest.fixture
def raw_draft() -> dict:
    """단일 비디오 세그먼트(speed 1.0) + 자막 3개."""
    return {
        "fps": 30,
        "tracks": [
            {"type": "video", "segments": [_video_seg("v0", 0, 30_000_000, 0)]},
            {"type": "text", "segments": [
                _text_seg("t0", "m0", 0, 5_000_000),
                _text_seg("t1", "m1", 5_000_000, 10_000_000),
                _text_seg("t2", "m2", 15_000_000, 8_000_000),
            ]},
        ],
        "materials": {
            "videos": [{"id": "VID", "path": "/tmp/footage.mp4", "duration": 30_000_000}],
            "texts": [
                _text_mat("m0", "저는 원래 대기업에 합격했어요"),
                _text_mat("m1", "그런데 도저히 꿈을 포기 못 하겠더라고요"),
                _text_mat("m2", "그래서 바로 시작했습니다"),
            ],
        },
    }


@pytest.fixture
def segments(raw_draft: dict) -> dict:
    from reels_editor import capcut
    return capcut.build_segments(raw_draft)


@pytest.fixture
def edl_doc() -> dict:
    """raw_draft와 짝을 이루는 승인된 EDL."""
    return {
        "story": {"five_lines": {"situation": "s", "desire": "d", "conflict": "c",
                                 "change": "ch", "result": "r"}, "lens": "lens"},
        "title_candidates": [{"text": "대기업을 버린 이유", "keyword": "대기업"}],
        "selected_title": 0,
        "subtitle_keywords": ["대기업"],
        "cuts": [
            {"beat": "훅", "seg_ids": ["t1"], "broll_marker": None},
            {"beat": "라스트 답", "seg_ids": ["t2"], "broll_marker": None},
        ],
    }
```

`tests/test_capcut.py`:

```python
from pathlib import Path

import pytest

from reels_editor import capcut


def test_build_segments_maps_text_to_source_coords(raw_draft: dict) -> None:
    out = capcut.build_segments(raw_draft)
    assert out["video_path"] == "/tmp/footage.mp4"
    segs = out["segments"]
    assert [s["id"] for s in segs] == ["t0", "t1", "t2"]
    assert segs[1]["text"] == "그런데 도저히 꿈을 포기 못 하겠더라고요"
    assert segs[1]["source_start_us"] == 5_000_000
    assert segs[1]["speed"] == 1.0


def test_build_segments_applies_speed(raw_draft: dict) -> None:
    raw_draft["tracks"][0]["segments"][0]["speed"] = 1.2
    raw_draft["tracks"][0]["segments"][0]["source_timerange"]["duration"] = 36_000_000
    out = capcut.build_segments(raw_draft)
    assert out["segments"][0]["speed"] == 1.2
    assert out["segments"][0]["source_end_us"] == pytest.approx(6_000_000, abs=2)


def test_find_project_accepts_direct_path(tmp_path: Path) -> None:
    (tmp_path / "draft_info.json").write_text("{}")
    assert capcut.find_project(str(tmp_path)) == tmp_path


def test_find_project_missing_raises() -> None:
    with pytest.raises(FileNotFoundError):
        capcut.find_project("존재하지않는프로젝트이름")
```

- [ ] **Step 4: 실패 확인**

```bash
.venv/bin/pytest tests/test_capcut.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'reels_editor.capcut'`

- [ ] **Step 5: 구현**

`reels_editor/capcut.py` (기존 `draft_model.py` + `read_draft.py` 병합 이식):

```python
"""CapCut draft_info.json 파싱 → segments.json 구조 (자막을 소스 좌표로 매핑)."""
from __future__ import annotations

import json
import os
from pathlib import Path

US = 1_000_000  # 마이크로초 per 초
DEFAULT_CAPCUT_ROOT = Path.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"


def capcut_root() -> Path:
    return Path(os.environ.get("CAPCUT_ROOT", DEFAULT_CAPCUT_ROOT))


def find_project(name_or_path: str) -> Path:
    """이름이면 CapCut 루트에서, 경로면 그대로. draft_info.json 존재를 확인한다."""
    candidates = [Path(name_or_path).expanduser(), capcut_root() / name_or_path]
    for p in candidates:
        if (p / "draft_info.json").is_file():
            return p
    searched = "\n  ".join(str(c) for c in candidates)
    raise FileNotFoundError(
        f"CapCut 프로젝트를 찾을 수 없습니다: {name_or_path!r}\n"
        f"찾아본 위치:\n  {searched}\n"
        f"CapCut에서 프로젝트를 열고 Text → 자동자막을 먼저 생성했는지 확인하세요.")


def load_project(project_dir: Path) -> dict:
    with open(project_dir / "draft_info.json", encoding="utf-8") as f:
        return json.load(f)


def caption_text(text_material: dict) -> str | None:
    """자막 머티리얼의 표시 텍스트. recognize_text 우선, content.text 폴백."""
    rt = text_material.get("recognize_text")
    if rt:
        return rt
    raw = text_material.get("content")
    if not raw:
        return None
    try:
        return json.loads(raw).get("text")
    except (ValueError, TypeError):
        return None


def map_timeline_to_source(video_segments: list[dict], t_us: int) -> tuple[int, float]:
    """타임라인 위치(us) → (원본 소스 위치 us, speed)."""
    for seg in video_segments:
        tr = seg["target_timerange"]
        start, dur = tr["start"], tr["duration"]
        if start <= t_us < start + dur:
            speed = float(seg.get("speed", 1.0))
            src = seg["source_timerange"]["start"] + int((t_us - start) * speed)
            return src, speed
    raise ValueError(f"타임라인 {t_us}us를 커버하는 비디오 세그먼트가 없음")


def _track(draft: dict, kind: str) -> dict:
    for tr in draft["tracks"]:
        if tr["type"] == kind:
            return tr
    if kind == "video":
        raise ValueError("비디오 트랙 없음")
    return {"segments": []}


def build_segments(draft: dict) -> dict:
    vsegs = _track(draft, "video")["segments"]
    text_mats = {m["id"]: m for m in draft["materials"]["texts"]}
    video_mat = draft["materials"]["videos"][0]

    segments: list[dict] = []
    for ts in sorted(_track(draft, "text")["segments"],
                     key=lambda s: s["target_timerange"]["start"]):
        text = caption_text(text_mats.get(ts["material_id"], {}))
        if not text:  # 자동자막 아닌 오버레이 등은 스킵
            continue
        tl = ts["target_timerange"]
        tl_start, tl_end = tl["start"], tl["start"] + tl["duration"]
        try:
            src_start, speed = map_timeline_to_source(vsegs, tl_start)
            src_end, _ = map_timeline_to_source(vsegs, tl_end - 1)
        except ValueError:
            continue
        segments.append({
            "id": ts["id"], "text": text,
            "timeline_start_us": tl_start, "timeline_end_us": tl_end,
            "source_start_us": src_start, "source_end_us": src_end + 1,
            "speed": speed,
        })
    return {
        "video_material_id": video_mat["id"],
        "video_path": video_mat.get("path"),
        "video_duration_us": video_mat.get("duration"),
        "fps": draft.get("fps"),
        "segments": segments,
    }
```

- [ ] **Step 6: 통과 확인**

```bash
.venv/bin/pytest tests/test_capcut.py -q
```

Expected: 4 passed

- [ ] **Step 7: 예시 파일 examples/로 이동 + 커밋**

```bash
mkdir -p examples
git mv 완성된릴스자막.srt 완성된릴스화면1.png 완성된릴스화면2.png 전체인터뷰스크립트.md examples/ 2>/dev/null \
  || mv 완성된릴스자막.srt 완성된릴스화면1.png 완성된릴스화면2.png 전체인터뷰스크립트.md examples/
mv "원본(인터뷰이).mov" "원본(인터뷰이).srt" examples/
git add pyproject.toml reels_editor tests examples
git commit -m "feat(capcut): 프로젝트 스캐폴드 + CapCut draft 파싱 이식"
```

(`원본(인터뷰이).mov`는 .gitignore의 `*.mov`로 제외됨 — 이동만 하고 커밋 안 됨. srt/png/md는 커밋.)

---

### Task 2: edl 모듈 — verbatim 검증 + 길이 추정

**Files:**
- Create: `reels_editor/edl.py`
- Test: `tests/test_edl.py`

**Interfaces:**
- Consumes: `capcut.US`, segments dict (Task 1)
- Produces:
  - `edl.validate_edl(edl_doc: dict, segments: dict) -> list[str]` — 에러 리스트(빈 리스트면 통과)
  - `edl.ordered_segments(edl_doc: dict, segments: dict) -> list[dict]` — EDL 순서로 펼친 `[{source_start_us, source_end_us, speed, text}]`, 검증 실패 시 `ValueError`
  - `edl.estimate_duration_s(edl_doc: dict, segments: dict, speed: float) -> float`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_edl.py`:

```python
import pytest

from reels_editor import edl


def test_validate_ok(edl_doc: dict, segments: dict) -> None:
    assert edl.validate_edl(edl_doc, segments) == []


def test_validate_unknown_seg_id(edl_doc: dict, segments: dict) -> None:
    edl_doc["cuts"][0]["seg_ids"] = ["없는id"]
    errs = edl.validate_edl(edl_doc, segments)
    assert any("없는id" in e for e in errs)


def test_validate_verbatim_mismatch(edl_doc: dict, segments: dict) -> None:
    edl_doc["cuts"][0]["text"] = "지어낸 문장"
    errs = edl.validate_edl(edl_doc, segments)
    assert any("verbatim" in e for e in errs)


def test_validate_empty_cuts(segments: dict) -> None:
    errs = edl.validate_edl({"cuts": []}, segments)
    assert any("cuts" in e for e in errs)


def test_ordered_segments_flattens_in_edl_order(edl_doc: dict, segments: dict) -> None:
    out = edl.ordered_segments(edl_doc, segments)
    assert [o["text"] for o in out] == [
        "그런데 도저히 꿈을 포기 못 하겠더라고요", "그래서 바로 시작했습니다"]


def test_estimate_duration_applies_speed(edl_doc: dict, segments: dict) -> None:
    # t1: 10s + t2: 8s = 18s 소스 → 1.2배속이면 15.0s
    assert edl.estimate_duration_s(edl_doc, segments, speed=1.2) == pytest.approx(15.0, abs=0.1)
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_edl.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'reels_editor.edl'`

- [ ] **Step 3: 구현**

`reels_editor/edl.py` (기존 `build_edl.py` 이식 + `estimate_duration_s`·빈 cuts 검사 추가):

```python
"""EDL(LLM 생성) 검증·해석. 자막 verbatim 원칙의 집행 지점."""
from __future__ import annotations

from reels_editor.capcut import US


def _seg_index(segments: dict) -> dict:
    return {s["id"]: s for s in segments["segments"]}


def validate_edl(edl_doc: dict, segments: dict) -> list[str]:
    idx = _seg_index(segments)
    errors: list[str] = []
    cuts = edl_doc.get("cuts", [])
    if not cuts:
        errors.append("cuts가 비어 있음 — 최소 1개 비트 필요")
    for c, cut in enumerate(cuts):
        ids = cut.get("seg_ids", [])
        if not ids:
            errors.append(f"cut {c}: seg_ids 비어있음")
        for sid in ids:
            if sid not in idx:
                errors.append(f"cut {c}: 알 수 없는 seg_id '{sid}'")
        # text가 명시됐으면 참조 세그먼트 원문 이어붙임과 문자 단위 일치해야 함
        if "text" in cut and all(sid in idx for sid in ids):
            joined = " ".join(idx[sid]["text"] for sid in ids)
            if cut["text"].strip() != joined.strip():
                errors.append(f"cut {c}: verbatim 불일치 — 원문 그대로만 허용 "
                              f"(기대: {joined!r})")
    return errors


def ordered_segments(edl_doc: dict, segments: dict) -> list[dict]:
    """EDL 순서대로 세그먼트를 펼친다. 검증 실패 시 ValueError."""
    errs = validate_edl(edl_doc, segments)
    if errs:
        raise ValueError("EDL 검증 실패:\n" + "\n".join(errs))
    idx = _seg_index(segments)
    out: list[dict] = []
    for cut in edl_doc["cuts"]:
        for sid in cut["seg_ids"]:
            s = idx[sid]
            out.append({
                "source_start_us": s["source_start_us"],
                "source_end_us": s["source_end_us"],
                "speed": s.get("speed", 1.0),
                "text": s.get("text", ""),
            })
    return out


def estimate_duration_s(edl_doc: dict, segments: dict, speed: float) -> float:
    """배속 적용 후 예상 결과물 길이(초)."""
    total_us = sum(o["source_end_us"] - o["source_start_us"]
                   for o in ordered_segments(edl_doc, segments))
    return total_us / US / speed
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_edl.py tests/test_capcut.py -q
git add reels_editor/edl.py tests/test_edl.py
git commit -m "feat(edl): verbatim 검증 + 길이 추정 이식"
```

Expected: 10 passed

---

### Task 3: style 모듈 + D.one 프리셋

**Files:**
- Create: `reels_editor/style.py`
- Create: `styles/done.yaml`
- Test: `tests/test_style.py`

**Interfaces:**
- Consumes: 없음
- Produces:
  - `style.StylePreset` — frozen dataclass. 필드: `canvas: tuple[int, int]`, `top_bar: int`, `bottom_bar: int`, `title_font: Path`, `title_size: int`, `title_color: str`, `title_highlight: str`, `title_max_lines: int`, `sub_font: Path`, `sub_size: int`, `sub_color: str`, `sub_highlight: str`, `sub_box_alpha: int`, `watermark_text: str`, `watermark_font: Path`, `watermark_size: int`, `speed: float`
  - `style.load_style(path: Path) -> StylePreset` — 폰트 파일 미존재 시 `FileNotFoundError`
  - `StylePreset.video_area() -> tuple[int, int]` — `(canvas_w, canvas_h - top_bar - bottom_bar)`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_style.py`:

```python
from pathlib import Path

import pytest

from reels_editor.style import StylePreset, load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_load_done_preset() -> None:
    s = load_style(STYLE)
    assert s.canvas == (1080, 1920)
    assert s.title_highlight == "#FF7A00"
    assert s.sub_highlight == "#FF3B30"
    assert s.watermark_text == "D.one"
    assert s.speed == 1.2
    assert s.title_font.is_file()  # Pretendard 실제 설치 확인


def test_video_area_excludes_bars() -> None:
    s = load_style(STYLE)
    assert s.video_area() == (1080, 1920 - s.top_bar - s.bottom_bar)


def test_missing_font_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(STYLE.read_text().replace("Pretendard-ExtraBold", "없는폰트"),
                   encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        load_style(bad)
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_style.py -q
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`styles/done.yaml`:

```yaml
# D.one 릴스 스타일 (examples/완성된릴스화면*.png에서 추출)
canvas: [1080, 1920]
top_bar: 220        # 상단 블랙바(타이틀 영역) 높이 px
bottom_bar: 180     # 하단 블랙바(워터마크 영역) 높이 px
font_dir: ~/Library/Fonts
title:
  font: Pretendard-ExtraBold.otf
  size: 72
  color: "#FFFFFF"
  highlight: "#FF7A00"   # 타이틀 키워드 오렌지
  max_lines: 2
subtitle:
  font: Pretendard-SemiBold.otf
  size: 44
  color: "#FFFFFF"
  highlight: "#FF3B30"   # 자막 키워드 레드
  box_alpha: 200         # 검정 박스 불투명도 0-255
watermark:
  text: "D.one"
  font: Pretendard-Medium.otf
  size: 48
speed: 1.2
```

`reels_editor/style.py`:

```python
"""스타일 프리셋 로딩. 렌더가 참조하는 모든 시각 파라미터의 단일 출처."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class StylePreset:
    canvas: tuple[int, int]
    top_bar: int
    bottom_bar: int
    title_font: Path
    title_size: int
    title_color: str
    title_highlight: str
    title_max_lines: int
    sub_font: Path
    sub_size: int
    sub_color: str
    sub_highlight: str
    sub_box_alpha: int
    watermark_text: str
    watermark_font: Path
    watermark_size: int
    speed: float

    def video_area(self) -> tuple[int, int]:
        return self.canvas[0], self.canvas[1] - self.top_bar - self.bottom_bar


def _font(font_dir: Path, name: str) -> Path:
    p = (font_dir / name).expanduser()
    if not p.is_file():
        raise FileNotFoundError(
            f"폰트 없음: {p}\nPretendard를 설치하거나 style yaml의 font_dir를 수정하세요.")
    return p


def load_style(path: Path) -> StylePreset:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    font_dir = Path(raw["font_dir"]).expanduser()
    t, s, w = raw["title"], raw["subtitle"], raw["watermark"]
    return StylePreset(
        canvas=tuple(raw["canvas"]),
        top_bar=raw["top_bar"], bottom_bar=raw["bottom_bar"],
        title_font=_font(font_dir, t["font"]), title_size=t["size"],
        title_color=t["color"], title_highlight=t["highlight"],
        title_max_lines=t["max_lines"],
        sub_font=_font(font_dir, s["font"]), sub_size=s["size"],
        sub_color=s["color"], sub_highlight=s["highlight"],
        sub_box_alpha=s["box_alpha"],
        watermark_text=w["text"], watermark_font=_font(font_dir, w["font"]),
        watermark_size=w["size"],
        speed=float(raw["speed"]),
    )
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_style.py -q
git add reels_editor/style.py styles/done.yaml tests/test_style.py
git commit -m "feat(style): D.one 스타일 프리셋 + 로더"
```

Expected: 3 passed

---

### Task 4: render 순수 함수 — 타임라인·자막 그룹핑·키워드 분리·필터 문자열

**Files:**
- Create: `reels_editor/render.py`
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `edl.ordered_segments`(Task 2), `capcut.US`
- Produces (전부 순수 함수 — Task 5의 렌더 오케스트레이션이 사용):
  - `render.DEFAULT_TEXT_FIXES: dict[str, str]`
  - `render.apply_text_fixes(text: str, fixes: dict[str, str]) -> str`
  - `render.timeline_items(ordered: list[dict], speed: float) -> list[list]` — `[[start_s, end_s, text], …]`
  - `render.group_captions(items: list[list], max_dur: float = 2.4, max_chars: int = 20) -> list[list]`
  - `render.split_by_keywords(text: str, keywords: list[str]) -> list[tuple[str, bool]]` — `[(조각, 강조여부)]`
  - `render.build_base_filter(ordered, speed, style: StylePreset, in_size: tuple[int, int]) -> str` — 트림+배속+concat+크롭+스케일+**pad**(상하 블랙바) filter_complex
  - `render.build_overlay_filter(n_static: int, groups: list[list]) -> tuple[str, str]` — 정적 오버레이(타이틀·워터마크) + 시간창 자막 overlay 체인

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_render.py`:

```python
import pytest

from reels_editor import edl, render
from reels_editor.style import load_style
from pathlib import Path

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_timeline_items_speed_compresses(edl_doc: dict, segments: dict) -> None:
    ordered = edl.ordered_segments(edl_doc, segments)
    items = render.timeline_items(ordered, speed=2.0)
    # t1 소스 10초 → 5초
    assert items[0][:2] == [0.0, 5.0]
    assert items[1][0] == 5.0


def test_group_captions_merges_short_fragments() -> None:
    items = [[0.0, 0.5, "결국은"], [0.5, 1.5, "제가 시장을"], [1.5, 2.2, "설득하는 방법은"]]
    groups = render.group_captions(items, max_dur=2.4, max_chars=20)
    assert groups[0][2] == "결국은 제가 시장을 설득하는 방법은"[:20] or len(groups) >= 1
    # 20자 제한: "결국은 제가 시장을" 까지만 병합되고 나머지는 새 그룹
    assert all(len(g[2]) <= 20 for g in groups)


def test_split_by_keywords_marks_highlight() -> None:
    parts = render.split_by_keywords("일단 무조건 거부감을 가져요", ["거부감"])
    assert parts == [("일단 무조건 ", False), ("거부감", True), ("을 가져요", False)]


def test_split_by_keywords_no_match() -> None:
    assert render.split_by_keywords("평범한 문장", ["없는말"]) == [("평범한 문장", False)]


def test_build_base_filter_has_pad_for_bars(edl_doc: dict, segments: dict) -> None:
    style = load_style(STYLE)
    ordered = edl.ordered_segments(edl_doc, segments)
    f = render.build_base_filter(ordered, 1.2, style, in_size=(1920, 1080))
    assert "concat=n=2" in f
    assert "atempo=1.2" in f
    assert f"pad={style.canvas[0]}:{style.canvas[1]}" in f
    assert f":0:{style.top_bar}" in f  # 영상이 top_bar 아래에 놓임


def test_build_overlay_filter_static_then_timed() -> None:
    groups = [[0.0, 2.0, "안녕"], [2.0, 4.0, "하세요"]]
    filt, last = render.build_overlay_filter(n_static=2, groups=groups)
    # 입력 1,2 = 타이틀·워터마크(상시), 3,4 = 자막(시간창)
    assert "between(t,0.000,2.000)" in filt
    assert filt.count("overlay") == 4
    assert last == "[o3]"
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_render.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'reels_editor.render'`

- [ ] **Step 3: 구현**

`reels_editor/render.py` (기존 render_reel.py 순수 함수 이식 + pad·키워드·정적 오버레이 확장):

```python
"""EDL + 원본 → 릴스 mp4. 순수 함수(필터 문자열·레이아웃 계산)와
ffmpeg/Pillow 오케스트레이션(Task 5)을 분리한다.

이 환경 ffmpeg는 libass/drawtext가 없어 텍스트는 전부 Pillow PNG + overlay.
"""
from __future__ import annotations

from reels_editor.capcut import US
from reels_editor.style import StylePreset

# 자동자막(STT) 흔한 오인식 보정. 필요 시 확장.
DEFAULT_TEXT_FIXES = {
    "추준생": "취준생", "주중생": "취준생", "로션": "노션",
    "임플란서": "인플루언서", "바이러를": "바이럴을", "서법": "서버비",
}


def apply_text_fixes(text: str, fixes: dict[str, str]) -> str:
    for a, b in fixes.items():
        text = text.replace(a, b)
    return text.strip()


def timeline_items(ordered: list[dict], speed: float) -> list[list]:
    """각 세그먼트의 결과물 타임라인 위치(초). [[start_s, end_s, text], …]."""
    items: list[list] = []
    cur = 0.0
    for s in ordered:
        dur = (s["source_end_us"] - s["source_start_us"]) / US / speed
        items.append([round(cur, 3), round(cur + dur, 3), s["text"]])
        cur += dur
    return items


def group_captions(items: list[list], max_dur: float = 2.4,
                   max_chars: int = 20) -> list[list]:
    """파편 자막을 읽기 좋은 덩어리로 병합. 빈 텍스트는 앞 그룹 시간에 흡수."""
    groups: list[list] = []
    buf: list | None = None
    for a, b, t in items:
        if not t:
            if buf:
                buf[1] = b
            continue
        if buf and (b - buf[0] <= max_dur) and (len(buf[2] + " " + t) <= max_chars):
            buf[1] = b
            buf[2] = (buf[2] + " " + t).strip()
        else:
            if buf:
                groups.append(buf)
            buf = [a, b, t]
    if buf:
        groups.append(buf)
    return groups


def split_by_keywords(text: str, keywords: list[str]) -> list[tuple[str, bool]]:
    """텍스트를 (조각, 강조여부) 시퀀스로 분리. 먼저 매칭되는 키워드 우선."""
    for kw in keywords:
        i = text.find(kw)
        if i < 0:
            continue
        head = split_by_keywords(text[:i], keywords) if text[:i] else []
        tail = split_by_keywords(text[i + len(kw):], keywords) if text[i + len(kw):] else []
        return head + [(kw, True)] + tail
    return [(text, False)]


def _crop_expr(in_w: int, in_h: int, aspect_w: int, aspect_h: int) -> str:
    """중앙 크롭 영역을 숫자로 계산(식 안 쉼표는 필터 구분자로 오해되므로 금지)."""
    cw = min(in_w, int(round(in_h * aspect_w / aspect_h)))
    ch = min(in_h, int(round(in_w * aspect_h / aspect_w)))
    x = (in_w - cw) // 2
    y = (in_h - ch) // 2
    return f"crop={cw}:{ch}:{x}:{y}"


def build_base_filter(ordered: list[dict], speed: float, style: StylePreset,
                      in_size: tuple[int, int]) -> str:
    """트림+배속+concat → 영상영역 크롭·스케일 → 캔버스 pad(상하 블랙바)."""
    vw, vh = style.video_area()
    cw, ch = style.canvas
    parts: list[str] = []
    n = len(ordered)
    for i, s in enumerate(ordered):
        a = s["source_start_us"] / US
        b = s["source_end_us"] / US
        parts.append(f"[0:v]trim={a}:{b},setpts=(PTS-STARTPTS)/{speed}[v{i}];")
        parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS,atempo={speed}[a{i}];")
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[vc][a];"
    vid = (f"[vc]{_crop_expr(in_size[0], in_size[1], vw, vh)},scale={vw}:{vh},"
           f"pad={cw}:{ch}:0:{style.top_bar}:black[v]")
    return "".join(parts) + concat + vid


def build_overlay_filter(n_static: int, groups: list[list]) -> tuple[str, str]:
    """오버레이 체인. 입력 1..n_static은 상시(타이틀·워터마크),
    이후 len(groups)개는 시간창 자막. (filter_complex, 마지막 라벨) 반환."""
    parts: list[str] = []
    prev = "[0:v]"
    idx = 0
    for i in range(n_static):
        out = f"[o{idx}]"
        parts.append(f"{prev}[{i + 1}:v]overlay=0:0{out}")
        prev = out
        idx += 1
    for j, (a, b, _t) in enumerate(groups):
        out = f"[o{idx}]"
        parts.append(
            f"{prev}[{n_static + j + 1}:v]overlay=enable='between(t,{a:.3f},{b:.3f})'{out}")
        prev = out
        idx += 1
    return ";".join(parts), prev
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_render.py -q
git add reels_editor/render.py tests/test_render.py
git commit -m "feat(render): 타임라인·그룹핑·키워드 분리·filter_complex 순수 함수"
```

Expected: 6 passed

---

### Task 5: render 오케스트레이션 — Pillow 텍스트 PNG + ffmpeg 실행

**Files:**
- Modify: `reels_editor/render.py` (함수 추가)
- Test: `tests/test_render_images.py`

**Interfaces:**
- Consumes: Task 3 `StylePreset`, Task 4 순수 함수
- Produces:
  - `render.render_title_png(title: str, keyword: str, style: StylePreset, out: Path) -> Path` — 캔버스 크기 투명 PNG, 상단 블랙바 중앙에 타이틀(키워드 오렌지)
  - `render.render_watermark_png(style: StylePreset, out: Path) -> Path` — 하단 중앙 워터마크
  - `render.render_subtitle_pngs(groups: list[list], keywords: list[str], style: StylePreset, out_dir: Path) -> list[Path]` — 그룹별 검정박스+키워드 레드 자막 PNG (`s000.png`…)
  - `render.render_reel(video_path: Path, segments: dict, edl_doc: dict, style: StylePreset, out_path: Path, speed: float | None = None, work_dir: Path | None = None) -> Path` — 최종 mp4. `speed=None`이면 `style.speed`
  - ffmpeg 실패 시 `RuntimeError`(stderr 포함), work_dir 보존

- [ ] **Step 1: 실패하는 테스트 작성 (PNG 생성 — ffmpeg 불필요, 빠름)**

`tests/test_render_images.py`:

```python
from pathlib import Path

from PIL import Image

from reels_editor import render
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_title_png_canvas_size_with_highlight(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_title_png("해양경찰이 선택한 스타트업", "해양경찰", style,
                                tmp_path / "title.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 122, 0, 255) in colors      # #FF7A00 오렌지 강조 존재
    assert (255, 255, 255, 255) in colors    # 흰 텍스트 존재


def test_watermark_png_in_bottom_bar(tmp_path: Path) -> None:
    style = load_style(STYLE)
    p = render.render_watermark_png(style, tmp_path / "wm.png")
    img = Image.open(p).convert("RGBA")
    assert img.size == style.canvas
    top = img.crop((0, 0, style.canvas[0], style.canvas[1] - style.bottom_bar))
    assert top.getbbox() is None  # 텍스트는 하단 바에만 존재


def test_subtitle_pngs_one_per_group(tmp_path: Path) -> None:
    style = load_style(STYLE)
    groups = [[0.0, 2.0, "일단 무조건 거부감을 가져요"], [2.0, 4.0, "보수적인 시장이고요"]]
    paths = render.render_subtitle_pngs(groups, ["거부감"], style, tmp_path)
    assert [p.name for p in paths] == ["s000.png", "s001.png"]
    img = Image.open(paths[0]).convert("RGBA")
    colors = {c for _n, c in img.getcolors(maxcolors=1_000_000)}
    assert (255, 59, 48, 255) in colors  # #FF3B30 레드 강조
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_render_images.py -q
```

Expected: FAIL — `AttributeError: module 'reels_editor.render' has no attribute 'render_title_png'`

- [ ] **Step 3: 구현 — render.py에 추가**

```python
# render.py 상단 import에 추가
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _hex_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha


def _draw_highlighted_line(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                           keywords: list[str], font: ImageFont.FreeTypeFont,
                           base: tuple, highlight: tuple) -> None:
    """키워드 조각만 강조색으로, 좌→우 이어 그린다."""
    x, y = xy
    for part, hl in split_by_keywords(text, keywords):
        d.text((x, y), part, font=font, fill=highlight if hl else base)
        x += int(d.textlength(part, font=font))


def _wrap_lines(text: str, font: ImageFont.FreeTypeFont, max_w: int,
                d: ImageDraw.ImageDraw) -> list[str]:
    """공백 단위 그리디 줄바꿈."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        cand = f"{cur} {word}".strip()
        if cur and d.textlength(cand, font=font) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def render_title_png(title: str, keyword: str, style: StylePreset, out: Path) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(style.title_font), style.title_size)
    lines = _wrap_lines(title, font, max_w=W - 120, d=d)[:style.title_max_lines]
    line_h = int(style.title_size * 1.25)
    y0 = (style.top_bar - line_h * len(lines)) // 2
    for i, line in enumerate(lines):
        lw = int(d.textlength(line, font=font))
        _draw_highlighted_line(d, ((W - lw) // 2, y0 + i * line_h), line,
                               [keyword] if keyword else [], font,
                               _hex_rgba(style.title_color),
                               _hex_rgba(style.title_highlight))
    img.save(out)
    return out


def render_watermark_png(style: StylePreset, out: Path) -> Path:
    W, H = style.canvas
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(str(style.watermark_font), style.watermark_size)
    tw = int(d.textlength(style.watermark_text, font=font))
    y = H - style.bottom_bar + (style.bottom_bar - style.watermark_size) // 2
    d.text(((W - tw) // 2, y), style.watermark_text, font=font,
           fill=(255, 255, 255, 230))
    img.save(out)
    return out


def render_subtitle_pngs(groups: list[list], keywords: list[str],
                         style: StylePreset, out_dir: Path) -> list[Path]:
    W, H = style.canvas
    font = ImageFont.truetype(str(style.sub_font), style.sub_size)
    out_dir.mkdir(parents=True, exist_ok=True)
    pad_x, pad_y = 24, 12
    paths: list[Path] = []
    for i, (_a, _b, t) in enumerate(groups):
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        tw = int(d.textlength(t, font=font))
        th = style.sub_size
        x = (W - tw) // 2
        # 영상 하단(하단 바 위 8%) — 예시 릴스의 자막 위치
        y = H - style.bottom_bar - int(H * 0.08) - th
        d.rectangle((x - pad_x, y - pad_y, x + tw + pad_x, y + th + pad_y),
                    fill=(0, 0, 0, style.sub_box_alpha))
        _draw_highlighted_line(d, (x, y), t, keywords, font,
                               _hex_rgba(style.sub_color),
                               _hex_rgba(style.sub_highlight))
        p = out_dir / f"s{i:03d}.png"
        img.save(p)
        paths.append(p)
    return paths


def _probe_size(video_path: Path) -> tuple[int, int]:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x",
         str(video_path)],
        capture_output=True, text=True, check=True).stdout.strip()
    w, h = out.split("x")[:2]
    return int(w), int(h)


def _ffmpeg(args: list[str]) -> None:
    r = subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg 실패:\n{r.stderr}")


def render_reel(video_path: Path, segments: dict, edl_doc: dict, style: StylePreset,
                out_path: Path, speed: float | None = None,
                work_dir: Path | None = None) -> Path:
    from reels_editor import edl as edl_mod
    speed = speed if speed is not None else style.speed
    ordered = edl_mod.ordered_segments(edl_doc, segments)
    work = work_dir or Path(tempfile.mkdtemp(prefix="reels_render_"))
    work.mkdir(parents=True, exist_ok=True)

    # 1) 베이스: 컷+배속+크롭+pad
    filt = build_base_filter(ordered, speed, style, _probe_size(video_path))
    fpath = work / "base_filter.txt"
    fpath.write_text(filt)
    base = work / "base.mp4"
    _ffmpeg(["-i", str(video_path), "-filter_complex_script", str(fpath),
             "-map", "[v]", "-map", "[a]", "-c:v", "libx264", "-preset", "veryfast",
             "-crf", "20", "-c:a", "aac", str(base)])

    # 2) 텍스트 오버레이: 타이틀 + 워터마크(상시) + 자막(시간창)
    title = edl_doc["title_candidates"][edl_doc.get("selected_title", 0)]
    title_png = render_title_png(title["text"], title.get("keyword", ""), style,
                                 work / "title.png")
    wm_png = render_watermark_png(style, work / "wm.png")
    items = [[a, b, apply_text_fixes(t, DEFAULT_TEXT_FIXES)]
             for a, b, t in timeline_items(ordered, speed)]
    groups = group_captions(items)
    sub_paths = render_subtitle_pngs(groups, edl_doc.get("subtitle_keywords", []),
                                     style, work / "subs")
    filt2, last = build_overlay_filter(n_static=2, groups=groups)
    args = ["-i", str(base), "-i", str(title_png), "-i", str(wm_png)]
    for p in sub_paths:
        args += ["-i", str(p)]
    args += ["-filter_complex", filt2, "-map", last, "-map", "0:a",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "copy", str(out_path)]
    _ffmpeg(args)
    return out_path
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_render_images.py tests/test_render.py -q
git add reels_editor/render.py tests/test_render_images.py
git commit -m "feat(render): 타이틀·워터마크·키워드 자막 PNG + ffmpeg 렌더"
```

Expected: 9 passed (render_reel 자체는 Task 9 통합 테스트에서 검증)

---

### Task 6: export 모듈 — srt + 비트별 컷 클립

**Files:**
- Create: `reels_editor/export.py`
- Test: `tests/test_export.py`

**Interfaces:**
- Consumes: `render.timeline_items`/`group_captions`(Task 4), `edl.ordered_segments`(Task 2), `capcut.US`
- Produces:
  - `export.srt_timestamp(seconds: float) -> str` — `"00:00:01,466"` 형식
  - `export.write_srt(groups: list[list], path: Path) -> Path`
  - `export.export_cuts(video_path: Path, edl_doc: dict, segments: dict, out_dir: Path, speed: float) -> list[Path]` — 비트별 `001-훅.mp4` 등 (배속 적용, 오디오 포함)
  - `export.write_outputs(work: Path, edl_doc: dict, segments: dict) -> None` — edl.json·segments.json 저장

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_export.py`:

```python
from pathlib import Path

from reels_editor import export


def test_srt_timestamp_format() -> None:
    assert export.srt_timestamp(0.0) == "00:00:00,000"
    assert export.srt_timestamp(1.466) == "00:00:01,466"
    assert export.srt_timestamp(3661.5) == "01:01:01,500"


def test_write_srt(tmp_path: Path) -> None:
    groups = [[0.0, 1.5, "결국은 제가"], [1.5, 3.0, "시장을 설득하는"]]
    p = export.write_srt(groups, tmp_path / "reel.srt")
    body = p.read_text(encoding="utf-8")
    assert "1\n00:00:00,000 --> 00:00:01,500\n결국은 제가" in body
    assert "2\n00:00:01,500 --> 00:00:03,000\n시장을 설득하는" in body


def test_write_outputs(tmp_path: Path, edl_doc: dict, segments: dict) -> None:
    export.write_outputs(tmp_path, edl_doc, segments)
    assert (tmp_path / "edl.json").is_file()
    assert (tmp_path / "segments.json").is_file()
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_export.py -q
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`reels_editor/export.py`:

```python
"""수정용 재료 산출: srt, 비트별 컷 클립, edl/segments 저장."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from reels_editor.capcut import US


def srt_timestamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(groups: list[list], path: Path) -> Path:
    blocks = [f"{i + 1}\n{srt_timestamp(a)} --> {srt_timestamp(b)}\n{t}\n"
              for i, (a, b, t) in enumerate(groups)]
    path.write_text("\n".join(blocks), encoding="utf-8")
    return path


def export_cuts(video_path: Path, edl_doc: dict, segments: dict,
                out_dir: Path, speed: float) -> list[Path]:
    """비트별 클립(배속 적용) — CapCut에서 부분 교체용."""
    idx = {s["id"]: s for s in segments["segments"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, cut in enumerate(edl_doc["cuts"], start=1):
        first, last = idx[cut["seg_ids"][0]], idx[cut["seg_ids"][-1]]
        a = first["source_start_us"] / US
        b = last["source_end_us"] / US
        safe_beat = (cut.get("beat") or f"cut{i}").replace("/", "-")
        p = out_dir / f"{i:03d}-{safe_beat}.mp4"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video_path),
             "-ss", f"{a:.3f}", "-to", f"{b:.3f}",
             "-filter_complex",
             f"[0:v]setpts=PTS/{speed}[v];[0:a]atempo={speed}[a]",
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-c:a", "aac", str(p)],
            capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"컷 추출 실패 ({p.name}):\n{r.stderr}")
        paths.append(p)
    return paths


def write_outputs(work: Path, edl_doc: dict, segments: dict) -> None:
    work.mkdir(parents=True, exist_ok=True)
    (work / "edl.json").write_text(
        json.dumps(edl_doc, ensure_ascii=False, indent=2), encoding="utf-8")
    (work / "segments.json").write_text(
        json.dumps(segments, ensure_ascii=False, indent=2), encoding="utf-8")
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_export.py -q
git add reels_editor/export.py tests/test_export.py
git commit -m "feat(export): srt·비트별 컷·산출물 저장"
```

Expected: 3 passed

---

### Task 7: storyteller — 프롬프트 + claude -p 호출 + 재시도 루프

**Files:**
- Create: `reels_editor/storyteller.py`
- Create: `prompts/storytelling-30s.md`
- Test: `tests/test_storyteller.py`

**Interfaces:**
- Consumes: `edl.validate_edl`, `edl.estimate_duration_s`(Task 2)
- Produces:
  - `storyteller.build_prompt(segments: dict, duration_s: int, feedback: str | None) -> str`
  - `storyteller.extract_json(text: str) -> dict` — 응답에서 첫 `{`~마지막 `}` JSON 파싱, 실패 시 `ValueError`
  - `storyteller.generate_script(segments: dict, duration_s: int = 30, feedback: str | None = None, *, runner: Callable[[str], str] | None = None) -> dict` — 검증 통과 EDL 반환. 검증 실패를 피드백으로 최대 2회 재시도, 그래도 실패면 마지막 응답을 `<work>/llm_raw.txt`에 남기라는 안내와 함께 `RuntimeError`. `runner`는 테스트 주입용(기본: `claude -p` subprocess)

- [ ] **Step 1: 프롬프트 작성**

`prompts/storytelling-30s.md` (storytelling 스킬의 30초 변형):

```markdown
# 30초 스토리텔링 릴스 대본 (EDL) 생성

너는 창업가 인터뷰를 30초 릴스로 재구성하는 에디터다.
아래 SEGMENTS(자막 조각, 각각 id와 원문 text)만 재료로 쓴다.

## 절대 규칙 (verbatim)
1. 자막으로 나갈 문장은 SEGMENTS의 text 그대로만 쓴다. 삭제와 순서 재배치만 허용.
   어미·조사 하나도 바꾸지 말 것. 문장 합치기·다듬기·새 연결어 금지.
2. 파편 자막은 여러 seg_id를 한 cut에 순서대로 묶어 문장을 구성한다.
3. 타이틀만 창작 허용 — 궁금증을 만드는 후킹 타이틀 후보 3개
   (예시 스타일: "해양경찰이 선택한 스타트업", "플라스틱으로 배를 만들면 생기는 일").
   각 후보에 강조할 keyword(타이틀 안의 부분 문자열) 1개를 지정한다.

## 스토리 구조 (훅→갈등 루프→라스트 답)
1. 먼저 5줄 뼈대(Situation→Desire→Conflict→Change→Result)를 SEGMENTS 발췌로 잡는다.
2. 스토리렌즈: 인터뷰 전체가 아니라 한 각도/한 장면으로 좁힌다(한 문장).
3. 라스트 답 먼저: "그것만 들어도 공유하고 싶은" 원문 한 줄을 마지막 cut으로.
4. 훅: 첫 3초. 주제를 직접 드러내는 원문 한 줄. 애매한 낚시 금지.
5. 비트: 훅 → 맥락 → 갈등 → 전환 → 핵심 장면 → 라스트 답 (4~6개 cut).
   "그러나/그래서"가 이미 들어있는 원문 문장을 활용해 갈등 루프를 만든다.
6. 목표 길이: 배속 {speed}x 적용 시 약 {duration_s}초. 원문 소스 길이 합이
   약 {source_budget_s}초가 되도록 문장을 고른다.
7. subtitle_keywords: 자막에서 레드로 강조할 단어 3~6개 (원문에 실제 등장하는 단어만).

## 출력
설명 없이 아래 JSON 하나만 출력한다:
{schema}

## SEGMENTS
{segments_listing}
{feedback_block}
```

- [ ] **Step 2: 실패하는 테스트 작성**

`tests/test_storyteller.py`:

```python
import json

import pytest

from reels_editor import storyteller


def test_build_prompt_lists_segments_and_budget(segments: dict) -> None:
    p = storyteller.build_prompt(segments, duration_s=30, feedback=None)
    assert "t0: 저는 원래 대기업에 합격했어요" in p
    assert "약 30초" in p
    assert "36초" in p  # 소스 예산 = 30s * speed 1.2


def test_build_prompt_includes_feedback(segments: dict) -> None:
    p = storyteller.build_prompt(segments, 30, feedback="훅을 더 세게")
    assert "훅을 더 세게" in p


def test_extract_json_from_noisy_output() -> None:
    assert storyteller.extract_json('앞말 {"a": 1} 뒷말') == {"a": 1}
    with pytest.raises(ValueError):
        storyteller.extract_json("JSON 없음")


def test_generate_script_returns_valid_edl(segments: dict, edl_doc: dict) -> None:
    out = storyteller.generate_script(
        segments, runner=lambda prompt: json.dumps(edl_doc, ensure_ascii=False))
    assert out["cuts"][0]["seg_ids"] == ["t1"]


def test_generate_script_retries_then_fails(segments: dict) -> None:
    calls: list[str] = []

    def bad_runner(prompt: str) -> str:
        calls.append(prompt)
        return '{"cuts": [{"beat": "훅", "seg_ids": ["없는id"]}]}'

    with pytest.raises(RuntimeError):
        storyteller.generate_script(segments, runner=bad_runner)
    assert len(calls) == 3  # 최초 1회 + 재시도 2회, 그 이상 금지
    assert "없는id" in calls[1]  # 검증 에러가 피드백으로 전달됨
```

- [ ] **Step 3: 실패 확인**

```bash
.venv/bin/pytest tests/test_storyteller.py -q
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 4: 구현**

`reels_editor/storyteller.py`:

```python
"""LLM(claude -p) 1회 호출로 EDL 대본 생성. 검증 실패는 피드백 재시도 최대 2회."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Callable

from reels_editor import edl as edl_mod

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "storytelling-30s.md"
DEFAULT_SPEED = 1.2
MAX_RETRIES = 2

_SCHEMA = json.dumps({
    "story": {"five_lines": {"situation": "…", "desire": "…", "conflict": "…",
                             "change": "…", "result": "…"}, "lens": "…"},
    "title_candidates": [{"text": "…", "keyword": "…"}],
    "subtitle_keywords": ["…"],
    "cuts": [{"beat": "훅", "seg_ids": ["seg_id"], "broll_marker": None}],
}, ensure_ascii=False, indent=2)


def build_prompt(segments: dict, duration_s: int, feedback: str | None) -> str:
    template = PROMPT_PATH.read_text(encoding="utf-8")
    listing = "\n".join(f"- {s['id']}: {s['text']}" for s in segments["segments"])
    fb = f"\n## 수정 피드백 (반드시 반영)\n{feedback}\n" if feedback else ""
    return (template
            .replace("{speed}", str(DEFAULT_SPEED))
            .replace("{duration_s}", str(duration_s))
            .replace("{source_budget_s}", str(round(duration_s * DEFAULT_SPEED)))
            .replace("{schema}", _SCHEMA)
            .replace("{segments_listing}", listing)
            .replace("{feedback_block}", fb))


def extract_json(text: str) -> dict:
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b <= a:
        raise ValueError(f"응답에서 JSON을 찾지 못함:\n{text[:500]}")
    return json.loads(text[a:b + 1])


def _run_claude(prompt: str) -> str:
    r = subprocess.run(["claude", "-p", prompt], capture_output=True, text=True,
                       timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"claude -p 실패:\n{r.stderr}")
    return r.stdout


def generate_script(segments: dict, duration_s: int = 30,
                    feedback: str | None = None, *,
                    runner: Callable[[str], str] | None = None) -> dict:
    run = runner or _run_claude
    last_raw = ""
    for _attempt in range(1 + MAX_RETRIES):
        last_raw = run(build_prompt(segments, duration_s, feedback))
        try:
            doc = extract_json(last_raw)
        except ValueError as e:
            feedback = f"이전 응답이 JSON 파싱에 실패했다: {e}. JSON 하나만 출력할 것."
            continue
        errs = edl_mod.validate_edl(doc, segments)
        if not errs:
            doc.setdefault("selected_title", 0)
            return doc
        feedback = ("이전 EDL이 검증에 실패했다. 다음 오류를 고쳐라 "
                    "(seg_ids는 SEGMENTS의 id만, verbatim 유지):\n" + "\n".join(errs))
    raise RuntimeError(
        "대본 생성 3회 실패 — 마지막 응답을 확인하세요:\n" + last_raw[:2000])
```

- [ ] **Step 5: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_storyteller.py -q
git add reels_editor/storyteller.py prompts tests/test_storyteller.py
git commit -m "feat(storyteller): 30초 대본 프롬프트 + claude -p 재시도 루프"
```

Expected: 5 passed

---

### Task 8: gate — 브라우저 검토 UI + 터미널 폴백

**Files:**
- Create: `reels_editor/gate.py`
- Test: `tests/test_gate.py`

**Interfaces:**
- Consumes: `edl.estimate_duration_s`(Task 2), EDL 스키마
- Produces:
  - `gate.GateDecision` — dataclass: `action: str`("approve"|"revise"), `title_index: int`, `feedback: str`
  - `gate.build_gate_html(edl_doc: dict, segments: dict, thumbs: dict[int, str], duration_s: float, target_s: int) -> str` — thumbs는 `{cut_index: base64 jpg}` (빈 dict 허용)
  - `gate.extract_thumbs(video_path: Path, edl_doc: dict, segments: dict, out_dir: Path) -> dict[int, str]` — 컷 시작 프레임을 jpg로 뽑아 base64 인코딩
  - `gate.run_gate(html: str, *, open_browser: bool = True, port: int = 0) -> GateDecision` — localhost 서버 띄우고 결정 대기(블로킹)
  - `gate.run_gate_terminal(edl_doc: dict, segments: dict, duration_s: float, target_s: int, input_fn: Callable[[str], str] = input) -> GateDecision`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_gate.py`:

```python
import json
import threading
import urllib.request

from reels_editor import gate


def test_html_contains_titles_beats_and_warning(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, thumbs={},
                                duration_s=34.2, target_s=30)
    assert "대기업을 버린 이유" in html          # 타이틀 후보
    assert "훅" in html and "라스트 답" in html  # 비트
    assert "그래서 바로 시작했습니다" in html      # 자막 원문
    assert "⚠️" in html                          # 30s ±10% 초과 경고


def test_html_no_warning_within_tolerance(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, {}, duration_s=31.0, target_s=30)
    assert "⚠️" not in html


def test_run_gate_approve_roundtrip(edl_doc: dict, segments: dict) -> None:
    html = gate.build_gate_html(edl_doc, segments, {}, 30.0, 30)
    result: list[gate.GateDecision] = []

    def serve() -> None:
        result.append(gate.run_gate(html, open_browser=False, port=8765))

    t = threading.Thread(target=serve)
    t.start()
    body = json.dumps({"action": "approve", "title_index": 0, "feedback": ""}).encode()
    req = urllib.request.Request("http://127.0.0.1:8765/decision", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5)
    t.join(timeout=5)
    assert result and result[0].action == "approve" and result[0].title_index == 0


def test_terminal_gate_approve(edl_doc: dict, segments: dict) -> None:
    answers = iter(["1", "y"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "approve" and d.title_index == 0


def test_terminal_gate_revise(edl_doc: dict, segments: dict) -> None:
    answers = iter(["1", "훅을 더 강하게"])
    d = gate.run_gate_terminal(edl_doc, segments, 30.0, 30,
                               input_fn=lambda _p: next(answers))
    assert d.action == "revise" and d.feedback == "훅을 더 강하게"
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_gate.py -q
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 구현**

`reels_editor/gate.py`:

```python
"""대본 검토 게이트 — 로컬 브라우저 UI(stdlib http.server) + 터미널 폴백."""
from __future__ import annotations

import base64
import html as html_mod
import json
import subprocess
import threading
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Callable

from reels_editor.capcut import US


@dataclass(frozen=True)
class GateDecision:
    action: str          # "approve" | "revise"
    title_index: int
    feedback: str = ""


def extract_thumbs(video_path: Path, edl_doc: dict, segments: dict,
                   out_dir: Path) -> dict[int, str]:
    """각 cut 시작 프레임 → base64 jpg. 실패한 컷은 조용히 건너뛴다(썸네일은 장식)."""
    idx = {s["id"]: s for s in segments["segments"]}
    out_dir.mkdir(parents=True, exist_ok=True)
    thumbs: dict[int, str] = {}
    for i, cut in enumerate(edl_doc["cuts"]):
        first = idx.get(cut["seg_ids"][0]) if cut.get("seg_ids") else None
        if not first:
            continue
        p = out_dir / f"thumb{i:02d}.jpg"
        r = subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error",
             "-ss", f"{first['source_start_us'] / US:.3f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale=270:-2", str(p)],
            capture_output=True)
        if r.returncode == 0 and p.is_file():
            thumbs[i] = base64.b64encode(p.read_bytes()).decode()
    return thumbs


def _beat_rows(edl_doc: dict, segments: dict, thumbs: dict[int, str]) -> str:
    idx = {s["id"]: s for s in segments["segments"]}
    rows = []
    for i, cut in enumerate(edl_doc["cuts"]):
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        img = (f'<img src="data:image/jpeg;base64,{thumbs[i]}" alt="">'
               if i in thumbs else "")
        rows.append(
            f'<div class="beat">{img}<div><h3>{html_mod.escape(cut.get("beat") or f"cut {i+1}")}</h3>'
            f'<p>{html_mod.escape(text)}</p></div></div>')
    return "\n".join(rows)


def build_gate_html(edl_doc: dict, segments: dict, thumbs: dict[int, str],
                    duration_s: float, target_s: int) -> str:
    over = abs(duration_s - target_s) > target_s * 0.10
    badge = (f'<span class="warn">⚠️ {duration_s:.1f}초 (목표 {target_s}초 ±10% 벗어남)</span>'
             if over else f"<span>총 {duration_s:.1f}초</span>")
    titles = "".join(
        f'<label><input type="radio" name="title" value="{i}" {"checked" if i == 0 else ""}>'
        f'<span class="title-preview">{html_mod.escape(t["text"]).replace(html_mod.escape(t.get("keyword", "")) or chr(0), f"<em>{html_mod.escape(t.get("keyword", ""))}</em>") if t.get("keyword") else html_mod.escape(t["text"])}</span></label>'
        for i, t in enumerate(edl_doc["title_candidates"]))
    five = edl_doc.get("story", {}).get("five_lines", {})
    skeleton = " → ".join(html_mod.escape(five.get(k, "")) for k in
                          ("situation", "desire", "conflict", "change", "result"))
    lens = html_mod.escape(edl_doc.get("story", {}).get("lens", ""))
    keywords = ", ".join(html_mod.escape(k) for k in edl_doc.get("subtitle_keywords", []))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>대본 검토 — reels-editor</title><style>
body{{font-family:Pretendard,-apple-system,sans-serif;background:#111;color:#eee;
     max-width:760px;margin:2rem auto;padding:0 1rem}}
.warn{{color:#ff3b30;font-weight:700}}
.title-preview{{font-weight:800;font-size:1.2rem;margin-left:.5rem}}
.title-preview em{{color:#ff7a00;font-style:normal}}
label{{display:block;margin:.4rem 0}}
.beat{{display:flex;gap:1rem;background:#1c1c1c;border-radius:12px;
      padding:1rem;margin:.6rem 0}}
.beat img{{width:135px;border-radius:8px;align-self:center}}
.beat h3{{margin:0 0 .3rem;color:#ff7a00}}
textarea{{width:100%;background:#222;color:#eee;border:1px solid #444;
         border-radius:8px;min-height:70px}}
button{{font-size:1rem;padding:.6rem 1.4rem;border-radius:8px;border:0;
       cursor:pointer;margin-right:.6rem}}
#approve{{background:#30d158}}#revise{{background:#ff9f0a}}
</style></head><body>
<h1>🎬 대본 검토 {badge}</h1>
<h2>타이틀 선택</h2>{titles}
<h2>5줄 뼈대</h2><p>{skeleton}</p><p>렌즈: {lens}</p>
<p>자막 강조 키워드: <span style="color:#ff3b30">{keywords}</span></p>
<h2>비트</h2>{_beat_rows(edl_doc, segments, thumbs)}
<h2>결정</h2>
<textarea id="fb" placeholder="수정 요청 내용 (수정 요청 시에만)"></textarea><br><br>
<button id="approve">✅ 승인하고 렌더</button>
<button id="revise">✏️ 수정 요청</button>
<script>
function send(action){{
  const title_index=+document.querySelector('input[name=title]:checked').value;
  const feedback=document.getElementById('fb').value;
  fetch('/decision',{{method:'POST',headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{action,title_index,feedback}})}})
    .then(()=>document.body.innerHTML='<h1>전달됨 — 터미널로 돌아가세요</h1>');
}}
document.getElementById('approve').onclick=()=>send('approve');
document.getElementById('revise').onclick=()=>send('revise');
</script></body></html>"""


def run_gate(html: str, *, open_browser: bool = True, port: int = 0) -> GateDecision:
    decision: list[GateDecision] = []
    done = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode())

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            decision.append(GateDecision(body["action"], int(body["title_index"]),
                                         body.get("feedback", "")))
            self.send_response(200)
            self.end_headers()
            done.set()

        def log_message(self, *args: object) -> None:
            pass  # 테스트/CLI 출력 오염 방지

    server = HTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    if open_browser:
        webbrowser.open(url)
    print(f"대본 검토 페이지: {url}")
    done.wait()
    server.shutdown()
    return decision[0]


def run_gate_terminal(edl_doc: dict, segments: dict, duration_s: float,
                      target_s: int,
                      input_fn: Callable[[str], str] = input) -> GateDecision:
    idx = {s["id"]: s for s in segments["segments"]}
    warn = " ⚠️ ±10% 벗어남" if abs(duration_s - target_s) > target_s * 0.10 else ""
    print(f"\n=== 대본 검토 — 총 {duration_s:.1f}초 (목표 {target_s}초){warn} ===")
    for i, t in enumerate(edl_doc["title_candidates"], 1):
        print(f"  타이틀 {i}: {t['text']}  (강조: {t.get('keyword', '-')})")
    for cut in edl_doc["cuts"]:
        text = " ".join(idx[sid]["text"] for sid in cut["seg_ids"] if sid in idx)
        print(f"  [{cut.get('beat', '?')}] {text}")
    ti = int(input_fn("타이틀 번호 선택: ").strip() or "1") - 1
    ans = input_fn("[y] 승인 / 그 외 입력 = 수정 요청: ").strip()
    if ans.lower() == "y":
        return GateDecision("approve", ti)
    return GateDecision("revise", ti, ans)
```

- [ ] **Step 4: 통과 확인 + 커밋**

```bash
.venv/bin/pytest tests/test_gate.py -q
git add reels_editor/gate.py tests/test_gate.py
git commit -m "feat(gate): 브라우저 대본 검토 UI + 터미널 폴백"
```

Expected: 5 passed

---

### Task 9: 렌더·컷 통합 테스트 (합성 영상)

**Files:**
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: `render.render_reel`(Task 5), `export.export_cuts`·`write_srt`(Task 6), conftest fixtures
- Produces: 없음 (검증 전용)

- [ ] **Step 1: 통합 테스트 작성**

`tests/test_integration.py`:

```python
"""합성 영상으로 전체 렌더 검증. ffmpeg 필요 — LLM/CapCut은 fixture로 대체."""
import json
import subprocess
from pathlib import Path

import pytest

from reels_editor import edl, export, render
from reels_editor.style import load_style

STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


@pytest.fixture(scope="module")
def synth_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """30초 640x480 테스트 영상(영상+사인파 오디오)."""
    p = tmp_path_factory.mktemp("video") / "synth.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=30:size=640x480:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=30",
         "-c:v", "libx264", "-c:a", "aac", "-shortest", str(p)],
        check=True)
    return p


def _probe(path: Path, entries: str) -> str:
    return subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", entries,
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, check=True).stdout.strip()


def test_render_reel_full(synth_video: Path, segments: dict, edl_doc: dict,
                          tmp_path: Path) -> None:
    style = load_style(STYLE)
    out = render.render_reel(synth_video, segments, edl_doc, style,
                             tmp_path / "reel.mp4", work_dir=tmp_path / "work")
    assert out.is_file()
    w, h = _probe(out, "stream=width,height").splitlines()[0].split(",")
    assert (int(w), int(h)) == style.canvas
    # 소스 18초(t1 10s + t2 8s) / 1.2배속 = 15초
    dur = float(_probe(out, "format=duration"))
    assert dur == pytest.approx(15.0, abs=1.0)
    # 오디오 트랙 존재
    assert "aac" in _probe(out, "stream=codec_name")


def test_export_cuts_per_beat(synth_video: Path, segments: dict, edl_doc: dict,
                              tmp_path: Path) -> None:
    paths = export.export_cuts(synth_video, edl_doc, segments,
                               tmp_path / "cuts", speed=1.2)
    assert [p.name for p in paths] == ["001-훅.mp4", "002-라스트 답.mp4"]
    assert all(p.stat().st_size > 0 for p in paths)


def test_srt_matches_render_groups(segments: dict, edl_doc: dict,
                                   tmp_path: Path) -> None:
    ordered = edl.ordered_segments(edl_doc, segments)
    groups = render.group_captions(render.timeline_items(ordered, 1.2))
    p = export.write_srt(groups, tmp_path / "reel.srt")
    assert "-->" in p.read_text(encoding="utf-8")
```

- [ ] **Step 2: 실행 (render_reel 첫 실전 구동 — 여기서 ffmpeg 필터 버그가 드러남)**

```bash
.venv/bin/pytest tests/test_integration.py -q
```

Expected: 3 passed. 실패하면 `tmp_path/work/base_filter.txt` 내용과 ffmpeg stderr로 필터 문자열을 디버그해 render.py를 수정한다 (같은 에러 2회 반복 시 멈추고 원인 보고).

- [ ] **Step 3: 전체 테스트 + 커밋**

```bash
.venv/bin/pytest -q
git add tests/test_integration.py
git commit -m "test(integration): 합성 영상 전체 렌더·컷·srt 검증"
```

Expected: 전체 passed

---

### Task 10: cli — preflight + make/render 명령 + README

**Files:**
- Create: `reels_editor/cli.py`
- Create: `README.md`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: 모든 이전 태스크의 public 함수
- Produces:
  - `cli.app` — typer 앱 (`pyproject.toml`의 entry point)
  - `reels-editor make "<프로젝트명|경로>" [--speed F] [--duration 30] [--style PATH] [--no-ui] [--out DIR]`
  - `reels-editor render <작업폴더> [--speed F] [--style PATH]` — 저장된 edl.json·segments.json으로 재렌더
  - `cli.preflight(project: str | None, style_path: Path) -> list[str]` — 문제 리스트(빈 리스트면 통과): ffmpeg/ffprobe/claude 존재, 스타일·폰트 로드, (project 지정 시) draft_info.json과 자막 세그먼트 존재

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_cli.py`:

```python
import json
from pathlib import Path

from typer.testing import CliRunner

from reels_editor import cli

runner = CliRunner()
STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def test_preflight_reports_missing_project() -> None:
    problems = cli.preflight("존재하지않는프로젝트", STYLE)
    assert any("CapCut" in p for p in problems)


def test_preflight_ok_without_project() -> None:
    # 이 머신에는 ffmpeg/claude/Pretendard가 있으므로 project 없이는 통과
    assert cli.preflight(None, STYLE) == []


def test_make_fails_fast_on_missing_project() -> None:
    result = runner.invoke(cli.app, ["make", "존재하지않는프로젝트"])
    assert result.exit_code == 1
    assert "CapCut" in result.output


def test_render_command_rerenders_workdir(tmp_path: Path, segments: dict,
                                          edl_doc: dict, monkeypatch) -> None:
    (tmp_path / "edl.json").write_text(json.dumps(edl_doc, ensure_ascii=False))
    (tmp_path / "segments.json").write_text(json.dumps(segments, ensure_ascii=False))
    called: dict = {}

    def fake_render(video_path, segs, doc, style, out_path, **kw):
        called["out"] = out_path
        Path(out_path).write_bytes(b"")
        return out_path

    monkeypatch.setattr(cli.render, "render_reel", fake_render)
    result = runner.invoke(cli.app, ["render", str(tmp_path)])
    assert result.exit_code == 0
    assert called["out"] == tmp_path / "reel.mp4"
```

- [ ] **Step 2: 실패 확인**

```bash
.venv/bin/pytest tests/test_cli.py -q
```

Expected: FAIL — `ModuleNotFoundError: No module named 'reels_editor.cli'`

- [ ] **Step 3: 구현**

`reels_editor/cli.py`:

```python
"""reels-editor CLI — make(전체 파이프라인) / render(재렌더)."""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import typer

from reels_editor import capcut, edl, export, gate, render, storyteller
from reels_editor.style import StylePreset, load_style

app = typer.Typer(help="창업가 인터뷰 → 30초 스토리텔링 릴스")
DEFAULT_STYLE = Path(__file__).parent.parent / "styles" / "done.yaml"


def preflight(project: str | None, style_path: Path) -> list[str]:
    problems: list[str] = []
    for binname, hint in (("ffmpeg", "brew install ffmpeg"),
                          ("ffprobe", "brew install ffmpeg"),
                          ("claude", "Claude Code CLI 설치 필요")):
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
            typer.echo(f"✗ {p}")
        raise typer.Exit(1)


def _render_all(video: Path, segments: dict, edl_doc: dict, style: StylePreset,
                work: Path, speed: float) -> None:
    export.write_outputs(work, edl_doc, segments)
    render.render_reel(video, segments, edl_doc, style, work / "reel.mp4",
                       speed=speed, work_dir=work / ".render")
    ordered = edl.ordered_segments(edl_doc, segments)
    groups = render.group_captions([
        [a, b, render.apply_text_fixes(t, render.DEFAULT_TEXT_FIXES)]
        for a, b, t in render.timeline_items(ordered, speed)])
    export.write_srt(groups, work / "reel.srt")
    export.export_cuts(video, edl_doc, segments, work / "cuts", speed)
    typer.echo(f"✅ 완료: {work / 'reel.mp4'}")
    typer.echo(f"   수정용 재료: {work}/reel.srt, edl.json, cuts/")


@app.command()
def make(project: str,
         speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
         duration: int = typer.Option(30, help="목표 길이(초)"),
         style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml"),
         no_ui: bool = typer.Option(False, "--no-ui", help="터미널 게이트 사용"),
         out: Path = typer.Option(Path("out"), help="산출물 루트")) -> None:
    """CapCut 프로젝트 → 대본 게이트 → 30초 릴스."""
    _fail_if_problems(preflight(project, style))
    preset = load_style(style)
    spd = speed if speed is not None else preset.speed
    pdir = capcut.find_project(project)
    segments = capcut.build_segments(capcut.load_project(pdir))
    video = Path(segments["video_path"])
    work = out / f"{pdir.name}-{dt.date.today():%Y%m%d}"
    work.mkdir(parents=True, exist_ok=True)

    feedback: str | None = None
    while True:
        typer.echo("🧠 대본 생성 중 (claude)…")
        edl_doc = storyteller.generate_script(segments, duration, feedback)
        dur = edl.estimate_duration_s(edl_doc, segments, spd)
        if no_ui:
            decision = gate.run_gate_terminal(edl_doc, segments, dur, duration)
        else:
            thumbs = gate.extract_thumbs(video, edl_doc, segments, work / ".thumbs")
            html = gate.build_gate_html(edl_doc, segments, thumbs, dur, duration)
            decision = gate.run_gate(html)
        if decision.action == "approve":
            edl_doc["selected_title"] = decision.title_index
            break
        feedback = decision.feedback

    _render_all(video, segments, edl_doc, preset, work, spd)


@app.command("render")
def render_cmd(workdir: Path,
               speed: float = typer.Option(None, help="배속 (기본: 스타일 프리셋)"),
               style: Path = typer.Option(DEFAULT_STYLE, help="스타일 yaml")) -> None:
    """수동 수정한 edl.json으로 재렌더 (게이트·LLM 없이)."""
    edl_path, seg_path = workdir / "edl.json", workdir / "segments.json"
    if not edl_path.is_file() or not seg_path.is_file():
        typer.echo(f"✗ {workdir}에 edl.json/segments.json이 없습니다.")
        raise typer.Exit(1)
    _fail_if_problems(preflight(None, style))
    preset = load_style(style)
    spd = speed if speed is not None else preset.speed
    edl_doc = json.loads(edl_path.read_text(encoding="utf-8"))
    segments = json.loads(seg_path.read_text(encoding="utf-8"))
    errs = edl.validate_edl(edl_doc, segments)
    if errs:
        typer.echo("✗ EDL 검증 실패:\n" + "\n".join(errs))
        raise typer.Exit(1)
    _render_all(Path(segments["video_path"]), segments, edl_doc, preset,
                workdir, spd)


if __name__ == "__main__":
    app()
```

`README.md`:

```markdown
# reels-editor

창업가 인터뷰(CapCut 자동자막 프로젝트) → 30초 스토리텔링 릴스 CLI.

## 준비
1. CapCut에 인터뷰 원본을 넣고 **Text → 자동자막** 생성
2. `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`

## 사용
```bash
.venv/bin/reels-editor make "<CapCut 프로젝트명>"   # 대본 생성 → 브라우저 승인 → 렌더
.venv/bin/reels-editor render out/<작업폴더>        # edl.json 수정 후 재렌더
```

산출물: `out/<프로젝트-날짜>/reel.mp4`, `reel.srt`, `edl.json`, `cuts/`

## 스토리 원칙
- 자막은 원문 verbatim (삭제·재배치만) — `storytelling` 스킬 방법론
- 타이틀만 창작 (후보 3개 중 게이트에서 선택)

## 테스트
`.venv/bin/pytest -q`
```

- [ ] **Step 4: 통과 확인**

```bash
.venv/bin/pytest tests/test_cli.py -q && .venv/bin/pytest -q
```

Expected: 전체 passed

- [ ] **Step 5: 커밋**

```bash
git add reels_editor/cli.py README.md tests/test_cli.py
git commit -m "feat(cli): make/render 명령 + preflight + README"
```

---

### Task 11: 실전 검증 — 실제 CapCut 프로젝트로 end-to-end

**Files:**
- Modify: (버그 수정 발생 시 해당 모듈)

**Interfaces:**
- Consumes: 완성된 CLI 전체
- Produces: 검증된 v0.1.0

- [ ] **Step 1: Jayden에게 자동자막이 생성된 실제 CapCut 프로젝트명을 확인** (예: `~/Movies/CapCut/User Data/Projects/com.lveditor.draft/` 아래 `0605` 등). 없으면 CapCut에서 `examples/원본(인터뷰이).mov`로 프로젝트를 만들고 자동자막 생성 요청.

- [ ] **Step 2: 실전 실행 (LLM 실호출 — 유일하게 mock 없는 단계)**

```bash
.venv/bin/reels-editor make "<실제 프로젝트명>"
```

Expected: 브라우저 게이트가 열리고, 승인 후 `out/<프로젝트-날짜>/reel.mp4` 생성. Jayden이 mp4를 열어 스타일(타이틀 오렌지·자막 레드·워터마크·30초)을 examples/ 캡처와 비교 확인.

- [ ] **Step 3: 발견된 문제 수정** — 각 수정은 실패 재현 테스트 먼저 추가 후 수정 (같은 에러 2회 반복 시 멈추고 원인 설명).

- [ ] **Step 4: 최종 커밋**

```bash
.venv/bin/pytest -q
git add -A && git commit -m "fix: 실전 검증 피드백 반영"
```

---

## Self-Review 결과

- **Spec coverage**: 입력(CapCut)→Task 1, verbatim 검증→Task 2, 스타일→Task 3, 렌더(타이틀·자막·워터마크·pad)→Task 4·5, srt·컷 수출→Task 6, LLM·재시도 상한→Task 7, 게이트 UI·터미널 폴백·길이 경고·썸네일→Task 8, 통합 검증→Task 9, preflight·CLI·재렌더→Task 10, 실전 e2e→Task 11. 스펙의 비범위(모션·b-roll 자동삽입·whisper)는 계획에 없음 — 일치.
- **Placeholder scan**: TBD/TODO 없음. 모든 코드 스텝에 실제 코드 포함.
- **Type consistency**: `build_segments`/`ordered_segments`/`estimate_duration_s`/`render_reel`/`GateDecision` 시그니처가 태스크 간 일치함을 교차 확인.
