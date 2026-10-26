<div align="center">
<img src="docs/images/icon.png" alt="Reels Editor" width="112">

# Reels Editor

**YouTube 롱폼 영상을 내 컴퓨터에서 세로 숏폼 릴스로 만듭니다.**

**한국어** · [English](README.md) · [简体中文](README.zh-CN.md)
</div>

자막이 있는 YouTube 링크를 넣으면 원문 근거가 있는 후보 10개를 제안합니다. 선택한 후보만 1080×1920 영상으로 만들고, 제목·번역 자막을 실제 발화에 맞춘 뒤 최종 MP4를 검수합니다. 개인 작업 공간이나 회사 전용 자산 없이 실행할 수 있는 로컬 릴스 생성기입니다.

## 0.2에서 달라진 점

- 최신 음성 기준 자막 정렬·독립 검수·자동 수정 흐름을 독립 앱에 연결했습니다.
- 도입 훅의 인용이 연속된 원문 자막과 일치하는지 검사합니다. 발언의 수치·부정·인과관계와 문맥을 보존합니다.
- 측정한 강조 단어에 도입 줌과 로컬 바람 효과음을 맞추고 실제 출력에서 적용 여부를 확인합니다.
- **한국어 / English / 简体中文** 생성 언어를 선택합니다. 제목·자막·캡션에 반영하고 작업 저장·재시도·분석 캐시에 언어를 보존합니다. 중국어 제목에는 불필요한 띄어쓰기를 요구하지 않습니다.
- 제목·자막 오버레이를 수정하면 다시 검수합니다. 내보내기 직전 원본과 복사본의 해시를 통과한 MP4와 대조합니다.
- 영상과 썸네일에 하단 로고·에피소드 번호를 표시하지 않습니다.
- 회사 로고와 특정 분야의 홍보 문구를 제거하고, 공개 라이선스 CJK 글꼴·기본 템플릿·효과음·프롬프트를 패키지에 포함했습니다.
- Google Drive 없이 로컬 폴더로 내보냅니다. 표지 실패와 영상 완료 상태를 구분합니다.

## 실행 환경

전체 생성 파이프라인은 현재 **Apple silicon macOS**를 대상으로 합니다. 단어 시간 측정에 MLX Whisper를 쓰고, 데스크톱 창과 얼굴 검출에도 macOS API를 사용합니다. Linux에서 Python 테스트와 UI 빌드가 실행된다고 해서 전체 앱의 Linux·Windows 실행을 지원한다는 뜻은 아닙니다.

| 필요 항목 | 용도 |
| --- | --- |
| Python 3.11 이상 | 백엔드·영상 처리 |
| Node.js 22.13 이상과 npm | React UI 빌드 |
| FFmpeg·FFprobe | 미디어 처리·검사 |
| 로그인한 Codex CLI | 자막 정렬·자동 수정 |
| Opus를 사용할 수 있는 Claude Code CLI | 독립 최종 검수 |
| 인터넷 연결 | YouTube·모델 호출·최초 ASR 모델 다운로드 |

생성 모델은 Codex·Claude·Gemini·OpenAI·Kimi 중에서 고를 수 있습니다. **생성 프로바이더와 관계없이 검증 layer에는 Codex와 Claude/Opus가 모두 필요합니다.** 자신의 계정으로 인증하며 사용 가능량과 비용은 각 계정 조건에 따릅니다. 검수 실패 시 다른 모델로 조용히 대체하거나 검사를 생략하지 않습니다.

## 설치와 실행

```bash
brew install ffmpeg

git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

npm ci --prefix desktop/ui
npm run build --prefix desktop/ui
```

검증에 필요한 CLI가 없다면 설치하고 로그인합니다.

```bash
npm install -g @openai/codex @anthropic-ai/claude-code
codex login
claude
```

Claude의 대화형 로그인을 완료한 뒤 앱을 엽니다.

```bash
.venv/bin/reels-editor-desktop
```

앱은 임의 세션 토큰으로 보호한 로컬 루프백 서버를 사용합니다. 공개 서버나 다른 작업 공간은 필요하지 않습니다. Noto Sans CJK 글꼴과 직접 생성한 바람 효과음이 포함되어 있습니다. 최초 ASR 실행에서는 모델을 다운로드하고 이후 로컬 캐시를 재사용합니다.

## 사용 순서

1. 자막을 읽을 수 있는 단일 YouTube 영상 링크를 붙여넣습니다.
2. **Output language**에서 한국어·English·简体中文을 고릅니다.
3. 후보 10개를 분석한 뒤 만들 후보를 선택합니다. 각 후보에는 실제 원문 구간 ID와 도입 인용이 있습니다.
4. 선택한 후보만 생성합니다. 대본 확정 후 필요한 원본 구간을 다운로드합니다. 고정 길이를 맞추려고 발언을 억지로 늘리거나 자르지 않습니다.
5. 세로 미리보기에서 제목·자막·표지를 확인합니다. 제목·인물 정보를 수정하면 오버레이를 렌더링하고 독립 검수를 다시 수행합니다.
6. 완성된 영상을 선택해 내보냅니다. Drive 미설정 상태에서는 `~/Movies/Reels Editor Exports/` 아래의 로컬 폴더에 저장합니다. 설정한 로컬 Google Drive 폴더도 선택적으로 사용할 수 있습니다.

언어 선택은 생성되는 글을 바꿉니다. 원래 음성을 더빙하거나 교체하지 않습니다. 인터페이스·메뉴·알림·오류 안내는 영어입니다. 새 작업의 기본 생성 언어는 English이며 한국어·중국어도 선택할 수 있습니다. 직접 인용은 원문 언어를 유지합니다. 화자가 화면에 보이는 영상에 적합하며, 신원·음성·타이밍 근거가 부족하면 정보를 지어내는 대신 검수에 실패할 수 있습니다.

## 검증 layer

```text
원문 자막 → 근거가 있는 후보 → 선택 대본
  → 원문·문맥 확인 → 로컬 단어 시간 측정 → 자막 의미 정렬
  → 측정 기반 도입 줌·효과음 → 최종 MP4
  → 최종 음성 재분석 + 프로그램 검사 + 독립 Opus 검수
       ├─ 통과: 정확한 MP4 해시에 검수 연결 → 내보내기
       └─ 실패·불확실: 수정 → 재정렬 → 재렌더 → 재검수 (최대 2회 수정)
```

주제·번역·자막 타이밍·도입 음성·도입 자막·읽기 시간·인물 크롭·줌·효과음을 확인합니다. 필수 항목 누락, 근거 부족, 불확실 판정, 프로그램 오류, 영상 해시 불일치는 통과시키지 않습니다. 검수자는 최종 MP4에서 추출한 프레임과 음성의 단어 시간·신호 지표를 받습니다. 직접 음성을 듣는 검수가 아니며 ASR 시각도 추정값입니다.

시도마다 `jobs/<작업>/sN/quality/` 아래에 근거·모델 원문 응답·수정안·검수 보고서를 보존합니다. 실패한 클립은 재시도할 수 있고 다른 완료 영상은 유지합니다. 완전한 검수와 현재 MP4의 해시 일치가 없는 이전 작업은 재생성해야 내보낼 수 있습니다.

코드 경로와 회귀 검증 기준은 [검증 명세](docs/verification.md)를 참고하세요.

## 로컬 처리와 외부 호출

렌더링·미디어 저장·얼굴 검출·음성 인식은 내 컴퓨터에서 수행합니다. 원문 일부·선택 대본·시간 근거는 생성·정렬 모델에, 최종 프레임과 음성 분석 근거는 Claude/Opus에 전송합니다. 화자 확인과 선택적 표지 검색에서는 공개 출처를 조회할 수 있습니다. 완전한 오프라인 AI 파이프라인은 아닙니다. 자동 게시 기능은 포함하지 않습니다.

| 데이터 | 기본 위치 |
| --- | --- |
| 작업·원문 자막·원본 구간·검수 근거 | `~/Library/Application Support/reels-editor/jobs/` |
| 원본·분석 공유 캐시 | `jobs/.source-cache/` |
| 사용자 설정 | `~/.config/reels-editor/config.yaml` |
| 완료 영상 보관함 | `~/Movies/Reels Editor/` |
| 선택 영상 로컬 내보내기 | `~/Movies/Reels Editor Exports/` |

완료 영상은 보관함에서 7일 동안 다시 열 수 있습니다. 개인 미디어·인증 정보·작업 데이터·검수 근거를 저장소에 커밋하지 마세요.

설정 예시:

```yaml
provider: codex-cli
model: ""
output_language: ko  # ko | en | zh
style:
  speed: 1.2
```

새 작업의 언어는 화면 선택값을 사용합니다. 기존 작업은 저장된 언어를 유지하고, 언어 정보가 없는 이전 작업은 한국어로 읽습니다. 새 작업 화면은 마지막으로 선택한 언어를 기억합니다.

## 재렌더와 개발 검증

```bash
.venv/bin/reels-editor render path/to/workdir --title 1
```

작업 폴더에 `edl.json`, `segments.json`과 접근 가능한 원본 미디어가 필요합니다. 데스크톱과 같은 검증 파이프라인·모델 인증을 사용하고 `.verified-jobs/`에 검수 기록을 남깁니다. 최종 검수에 통과하지 못하면 실패를 반환합니다.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
npm run typecheck --prefix desktop/ui
npm run build --prefix desktop/ui
npm run test:dashboard --prefix desktop/ui
```

자동 테스트의 외부 모델 호출은 격리된 대역을 사용합니다. UI 테스트는 창 크기 3개, 언어 선택·저장, 영상 이동, 실제 생성 요청 구성을 확인합니다. 자동 테스트 통과가 모든 원본의 실제 모델 검수 통과를 보장하지는 않습니다.

macOS 앱 묶음 만들기:

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
open "dist/Reels Editor.app"
```

직접 만든 앱은 서명되지 않습니다. [기여 안내](CONTRIBUTING.md)와 [변경 내역](CHANGELOG.md)도 참고하세요.

## 문제 해결

- **원문 자막 없음:** 자막이 있는 영상을 사용하세요. ASR은 선택 음성 검증용이며 YouTube 자막의 자동 대체 수단이 아닙니다.
- **CLI·인증 오류:** `codex --version`, `claude --version`과 양쪽 로그인 상태를 확인하세요. 생성 프로바이더 설정만으로 검증 준비가 끝나지 않습니다.
- **검수 실패:** 클립의 오류와 보존한 근거를 확인한 뒤 재시도하세요. 불완전·불확실 판정을 완료로 표시하지 않습니다.
- **표지 실패:** 통과한 MP4는 재생·내보내기할 수 있습니다. 다른 장면이나 사진으로 표지를 다시 만드세요.
- **YouTube 추출 실패:** 환경의 `yt-dlp`를 갱신한 뒤 재시도하세요. 비공개·접근 제한 영상은 처리하지 못할 수 있습니다.

## 라이선스

[MIT](LICENSE) © DongHyun Jung. Noto Sans CJK는 [SIL OFL 1.1](reels_editor/resources/styles/assets/fonts/OFL.txt)을 따릅니다. [자산 출처](reels_editor/resources/styles/assets/README.md)를 참고하세요. 사용할 권한이 있는 영상만 처리·게시하세요.
