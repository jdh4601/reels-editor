# reels-editor

창업가 인터뷰(CapCut 자동자막 프로젝트) → 30초 스토리텔링 릴스 CLI.

## 준비
1. CapCut에 인터뷰 원본을 넣고 **Text → 자동자막** 생성
2. `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"`

## 사용
```bash
.venv/bin/reels-editor make "<CapCut 프로젝트명>"       # 스토리라인 3개 생성 → 조합 선택·설정 → 병렬 렌더
.venv/bin/reels-editor render out/<작업폴더>/s1 --title 2  # edl.json 수정 후 타이틀 2로 재렌더
```

산출물: `out/<프로젝트-날짜>/s{n}/reel-t{m}.mp4`, `reel.srt`, `edl.json`,
`cuts/`, `manifest.json`

## 설정
브라우저 게이트의 설정 패널에서 AI 프로바이더(`claude-cli`, `openai`, `kimi`,
`custom`)와 모델, 스토리라인 개수, 자막 크기·위치, 포인트 컬러, 배속을 조절할
수 있다. 승인하거나 재생성하면 설정은 `~/.config/reels-editor/config.yaml`에 저장된다.

API 키는 `OPENAI_API_KEY`, `MOONSHOT_API_KEY`, `REELS_LLM_API_KEY` 환경변수를
우선 사용한다. 게이트에서 입력한 키는 프로젝트 밖의
`~/.config/reels-editor/credentials.yaml`에 권한 `0600`으로 저장된다.

## 스토리 원칙
- 자막은 원문 verbatim (삭제·재배치만) — `storytelling` 스킬 방법론
- 타이틀만 창작 (후보 3개 중 게이트에서 선택)

## 테스트
`.venv/bin/pytest -q`
