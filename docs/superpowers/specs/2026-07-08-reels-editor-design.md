# reels-editor 설계 스펙

날짜: 2026-07-08
상태: 승인됨 (Jayden)

## 목적

창업가 인터뷰 원본(긴 mp4)을 **30초 속도감 있는 스토리텔링 릴스**로 자동 편집하는
독립 CLI 도구. 스토리 구조는 `storytelling` 스킬 방법론(훅→갈등 루프→라스트 답,
자막 verbatim 원칙)을 따르고, 비주얼 스타일은 기존 D.one 릴스 스타일을 재현한다.

## 요구사항 (인터뷰로 확정)

| 항목 | 결정 |
|---|---|
| 결과물 길이 | 30초 (±10% 벗어나면 게이트에 경고 표시) |
| 전사 소스 | CapCut 자동자막 프로젝트 (사용자가 CapCut에서 자동자막 생성 후 실행) |
| 출력 | 완성 mp4 + 수정용 재료 (srt, edl.json, 비트별 컷 클립) |
| 사람 개입 | 대본 승인 게이트 1회 (브라우저 UI, `--no-ui` 시 터미널) |
| 도구 형태 | 독립 CLI, `/Users/jayden/Developer/reels-editor` |
| LLM 연동 | `claude -p` (Claude Code headless / Agent SDK) — 파이프라인당 1회 호출 |
| 창작 범위 | 자막 본문 = 원문 verbatim (삭제·재배치만). 타이틀 = 창작 허용, 후보 3개 제시 |
| 폰트 | Pretendard (전 패밀리 `~/Library/Fonts`에 설치 확인됨) |

## 아키텍처

핵심 원칙: **LLM은 "무엇을 말할지" 1회만 판단, 자르고 그리는 것은 전부 결정적 코드.**
같은 EDL이면 항상 같은 mp4가 나온다.

기존 `reels-edit` 스킬(~/.claude/skills/reels-edit)의 검증된 스크립트를 이식한다:
`read_draft.py` → `capcut.py`, `build_edl.py` → `edl.py`, `render_reel.py` → `render.py`.

### 프로젝트 구조

```
/Users/jayden/Developer/reels-editor/
├── pyproject.toml              # pip install -e . → `reels-editor` 명령 등록
├── reels_editor/
│   ├── cli.py                  # 명령 정의 (typer)
│   ├── capcut.py               # CapCut draft_info.json → segments.json
│   ├── storyteller.py          # claude -p 호출 + 대본 프롬프트 조립
│   ├── edl.py                  # EDL 스키마 + verbatim 검증
│   ├── gate.py                 # 대본 검토 게이트 (로컬 웹 UI + 터미널 폴백)
│   ├── style.py                # 스타일 프리셋 로딩 (색·폰트·레이아웃)
│   ├── render.py               # ffmpeg + Pillow 렌더
│   └── export.py               # srt·컷 클립·산출물 정리
├── prompts/storytelling-30s.md # storytelling 스킬의 30초 변형 프롬프트
├── styles/done.yaml            # D.one 스타일 프리셋
├── tests/
└── examples/                   # 기존 예시 파일 이동 (완성된릴스*.png/srt, 원본.mov 등)
```

### CLI 명령

```bash
reels-editor make "<CapCut 프로젝트명>"     # 전체 파이프라인
reels-editor render <작업폴더>              # EDL 수동 수정 후 재렌더만
# 옵션: --speed 1.2  --duration 30  --style done  --no-ui
```

### 데이터 흐름

```
CapCut 프로젝트 (자동자막 생성됨)
  │ capcut.py
  ▼
segments.json (문장조각 + 원본 마이크로초 좌표 + speed 매핑)
  │ storyteller.py ── claude -p (LLM 호출 1회)
  ▼
대본 제안: 5줄 뼈대 + 스토리렌즈 + 훅→비트→라스트 답 EDL
          + 타이틀 후보 3개 + 강조 키워드(타이틀 오렌지/자막 레드)
  │ gate.py ── ★브라우저 게이트: 승인 / 수정 피드백(재생성) / 타이틀 선택
  ▼
edl.json (승인본) ── edl.py verbatim 검증 (실패 시 렌더 불가)
  │ render.py + export.py
  ▼
out/<프로젝트명-YYYYMMDD>/
  ├── reel.mp4        # 완성본
  ├── reel.srt        # 자막 (CapCut 수정용)
  ├── edl.json        # 대본 (수정 후 `render`로 재렌더)
  ├── segments.json
  └── cuts/*.mp4      # 비트별 클립 (부분 교체용)
```

## 대본 게이트 UI

대본 생성 완료 시 CLI가 로컬 서버(Python stdlib `http.server`, 외부 의존성 없음)를
localhost 임의 포트에 띄우고 브라우저를 자동으로 연다.

화면 구성:
- **타이틀 후보 3개** 라디오 선택 — 실제 Pretendard + 오렌지 강조 적용된 미리보기
- **5줄 뼈대** (Situation→Desire→Conflict→Change→Result) + 스토리렌즈 한 줄
- **비트 카드** (훅~라스트 답): 장면 캡처 썸네일(ffmpeg로 비트 시작 프레임 추출),
  타임코드, 자막 텍스트(레드 키워드 미리보기), 비트 길이
- **총 길이 배지**: 30초 ±10% 벗어나면 ⚠️
- **액션**: `승인하고 렌더` → 서버 종료, 렌더 진행 /
  `수정 요청` (텍스트 입력) → claude -p 재호출(피드백 포함) → 페이지 갱신

`--no-ui` 플래그: 동일 내용을 터미널 텍스트로 출력하고 y/수정텍스트 입력을 받는다.

## 스타일 프리셋 (`styles/done.yaml`)

기존 D.one 릴스 캡처에서 추출. 전부 yaml로 조정 가능.

| 요소 | 스펙 |
|---|---|
| 캔버스 | 1080×1920, 블랙 배경, 영상 중앙 배치 (상하 블랙바) |
| 타이틀 | 상단 블랙바, Pretendard ExtraBold, 흰색 + 오렌지 `#FF7A00` 키워드, 최대 2줄 |
| 자막 | 검정 박스 + 흰 텍스트, 레드 `#FF3B30` 키워드, Pretendard SemiBold, 영상 하단 |
| 워터마크 | `D.one`, 하단 블랙바 중앙, Pretendard Medium |
| 배속 | 1.2x 기본 (`--speed`로 조정) |

자막 렌더는 기존 방식 유지: 이 환경 ffmpeg에 libass/drawtext가 없으므로
Pillow로 자막 이미지를 렌더한 뒤 overlay 합성한다. STT 오타 보정 테이블
(`DEFAULT_TEXT_FIXES`)도 이식한다.

## 에러 처리

- **프리플라이트** (실행 즉시): ffmpeg·claude CLI·Pretendard 폰트·CapCut 프로젝트·
  자동자막 존재 확인 → 없으면 해결 방법 안내와 함께 즉시 중단
- **LLM 출력 불량** (JSON 파싱 실패 / verbatim 위반 / 미존재 seg_id):
  위반 내용을 피드백으로 자동 재시도 최대 2회 → 실패 시 원문 응답 저장 후 중단
  (동일 방법 3회 재시도 금지 규칙 준수)
- **렌더 실패**: ffmpeg stderr 그대로 표시, 생성된 컷 클립 보존 (디버깅용)
- **길이 초과/미달**: 게이트 UI에 경고 표시 (차단하지 않음 — 사용자 판단)

## 테스트 (TDD)

- **unit**: CapCut 파서(fixture draft_info.json), verbatim 검증기, 스타일 로더,
  srt 생성기, 키워드 하이라이트 분리 로직
- **integration**: ffmpeg로 합성한 10초 테스트 영상 + 가짜 segments → 전체 렌더 →
  길이·오디오 존재·해상도(1080×1920) 검증
- **게이트**: HTML 생성 스냅샷 + 승인/수정 POST 흐름 (테스트 클라이언트)
- **LLM은 전부 mock** (고정 JSON fixture) — 테스트는 결정적, API 비용 0
- 실행: `python3 -m pytest -q` (기존 reels-edit 테스트도 이식)

## 비범위 (YAGNI)

- 타이틀/자막 모션 애니메이션 (필요해지면 render 단계만 Remotion으로 교체 가능)
- B-roll 자동 삽입 (EDL에 `broll_marker`만 남기고 CapCut 수동 마감)
- 색보정, BGM — CapCut에서 마감
- whisper 직접 전사 (CapCut 자동자막으로 충분, 추후 입력 어댑터 추가 가능)
