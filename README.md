# Reels Editor

창업가의 롱폼 YouTube 인터뷰를 분석해 1인 창업가에게 실질적으로 도움이 되는 릴스를 만드는 개인용 macOS 앱입니다. 스토리형·전략형·실패 분석형·원칙형을 복수 선택하면 서로 겹치지 않는 후보 10개를 먼저 보여주고, 사용자가 고른 후보만 30~40초의 9:16 영상으로 렌더링합니다. 원음은 유지되며 자연스러운 한국어 자막과 상단의 주황색 한국어 후킹 제목이 적용됩니다.

## 가장 쉬운 실행 방법

### 1. 필요한 프로그램 설치

macOS에서 아래 프로그램이 필요합니다.

- Python 3.11 이상
- ffmpeg와 ffprobe
- OpenAI Codex CLI
- Pretendard 폰트

Homebrew가 있다면 ffmpeg를 설치합니다.

```bash
brew install ffmpeg
brew install --cask font-pretendard
```

Codex CLI를 설치하고 로그인합니다.

```bash
npm install -g @openai/codex
codex login
```

설치가 됐는지 확인합니다.

```bash
python3 --version
ffmpeg -version
ffprobe -version
codex --version
```

### 2. 프로젝트 내려받기

```bash
git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
```

### 3. Python 앱 설치

최초 한 번만 실행합니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

### 4. 대시보드 UI 빌드

```bash
cd desktop/ui
npm install
npm run build
cd ../..
```

### 5. macOS 앱 실행

개발 중에는 아래 명령으로 바로 앱을 열 수 있습니다.

```bash
.venv/bin/reels-editor-desktop
```

앱이 열리면 다음 순서로 사용합니다.

1. 창업가 롱폼 인터뷰의 YouTube 영상 링크를 붙여넣습니다.
2. 스토리형·전략형·실패 분석형·원칙형 중 원하는 유형을 하나 이상 선택합니다.
3. `후보 10개 분석`을 누릅니다.
4. 앱이 영상과 원문 자막을 저장하고, 내용이 겹치지 않는 릴스 후보 10개를 보여줍니다.
5. 만들고 싶은 후보를 하나 이상 선택해 `선택한 후보로 릴스 생성`을 누릅니다.
6. 선택한 후보만 30~40초 영상으로 생성됩니다. 각 릴스에서 AI 추천 제목을 고르고 자막을 켜거나 끌 수 있습니다.
7. `캡션 생성하기`를 누르면 해당 릴스의 실제 대본을 바탕으로 Instagram 게시용 한국어 캡션이 생성됩니다. 결과는 바로 복사하거나 다시 생성할 수 있습니다.
8. 내보낼 영상을 선택한 뒤 `선택 영상 내보내기`를 누릅니다.

YouTube에 영어 수동 자막이나 영어 자동 생성 자막이 있으면 이를 우선 사용합니다. 영어 자막이 없으면 다른 제공 자막을 보조적으로 사용하며, 어떤 자막도 없는 영상은 사용할 수 없습니다. 앱은 별도 음성 인식으로 몰래 대체하지 않고 자막이 필요하다는 오류를 표시합니다.

같은 인터뷰에서 후보 10개를 다시 분석하려면 `다시 분석`을 누릅니다.

제목이나 자막 ON/OFF를 바꿀 때는 전체 영상을 다시 만들지 않고 오버레이만 빠르게 다시 렌더합니다.

## 앱 파일로 빌드하기

`dist/Reels Editor.app`을 만들려면 아래 명령을 실행합니다.

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
```

빌드 후 Finder에서 열거나 터미널에서 실행할 수 있습니다.

```bash
open "dist/Reels Editor.app"
```

일반 macOS 앱처럼 `응용 프로그램` 폴더에 설치하려면 다음 명령을 한 번 실행합니다.

```bash
ditto "dist/Reels Editor.app" "/Applications/Reels Editor.app"
open "/Applications/Reels Editor.app"
```

이후에는 Finder의 `응용 프로그램`에서 `Reels Editor` 아이콘을 클릭하거나 Spotlight에서 `Reels Editor`를 검색해 실행할 수 있습니다. 자주 쓴다면 실행 중인 Dock 아이콘을 우클릭하고 `옵션 > Dock에 유지`를 선택합니다.

이 앱은 개인용 unsigned/unnotarized 빌드입니다. macOS가 처음 실행을 막으면 Finder에서 앱을 Control-클릭한 뒤 `열기`를 선택합니다.

## 로컬에 저장되는 YouTube 소스

다운로드한 영상, 원본 JSON3 자막, 읽기 쉬운 `transcript.txt`, 타임코드가 정리된 `segments.json`은 해당 작업 폴더의 `source/`에 저장됩니다.

같은 영상을 다시 생성할 때는 YouTube 영상 ID를 기준으로 기존 영상과 자막을 찾아 재사용합니다. 공유 링크의 쿼리 문자열이나 `youtu.be`/`watch?v=` 형식이 달라도 같은 영상이면 다시 다운로드하지 않습니다. 데스크톱 생성 과정은 쓰이지 않는 개별 중간 컷 파일을 인코딩하지 않고 최종 릴스를 원본 타임라인에서 바로 렌더링합니다.

```text
~/Library/Application Support/reels-editor/jobs/<작업ID>/source/
```

다운로드한 콘텐츠는 사용 권한이 있는 영상에만 사용하세요.

## 데이터 저장 위치

앱 작업 상태와 렌더 중간 파일은 아래에 저장됩니다.

```text
~/Library/Application Support/reels-editor/jobs/
```

내보낸 최종 MP4는 사용자가 저장 대화상자에서 고른 위치에 저장됩니다.

## CLI로 다시 렌더하기

이미 만들어진 EDL 작업 폴더는 CLI로 다시 렌더할 수 있습니다.

```bash
.venv/bin/reels-editor render out/<프로젝트명-날짜>/s1 --title 2
```

## AI 설정

설정 화면에서 사용할 AI provider를 선택할 수 있습니다.

```yaml
provider: codex-cli
model: gpt-5.6-sol
style: {}
```

설정 파일 위치:

```text
~/.config/reels-editor/config.yaml
```

지원하는 프로바이더:

| 프로바이더 | `provider` 값 | 인증 |
| --- | --- | --- |
| OpenAI Codex CLI | `codex-cli` | `codex login` |
| Claude Code CLI | `claude-cli` | `claude` 로그인 |
| OpenAI API | `openai` | `OPENAI_API_KEY` |
| Kimi | `kimi` | `MOONSHOT_API_KEY` |
| OpenAI 호환 서버 | `custom` | `REELS_LLM_API_KEY` |

## 문제 해결

### 앱에서 Codex 또는 ffmpeg를 찾지 못함

터미널에서 아래 명령이 되는지 확인합니다.

```bash
codex --version
ffmpeg -version
ffprobe -version
```

앱은 Finder에서 실행해도 `~/.npm-global/bin`, `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`을 자동으로 PATH에 넣습니다.

### YouTube 다운로드 또는 자막 추출이 실패함

- 일반 YouTube 영상 링크인지 확인합니다. 재생목록 전체 링크는 지원하지 않습니다.
- 비공개·연령 제한·로그인이 필요한 영상은 다운로드할 수 없을 수 있습니다.
- 영상에 수동 자막 또는 YouTube 자동 생성 자막이 있는지 확인합니다.
- YouTube 쪽 형식이 바뀐 경우 `pip install -U yt-dlp`로 다운로드 모듈을 업데이트합니다.

### 빌드가 실패함

의존성을 다시 설치합니다.

```bash
.venv/bin/pip install -e ".[dev]"
cd desktop/ui
npm install
npm run build
cd ../..
```

## 개발 검증

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest
cd desktop/ui
npm run typecheck
npm run build
npm run test:dashboard
```
