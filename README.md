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
