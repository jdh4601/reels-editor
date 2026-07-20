# Reels Editor

CapCut 자동자막이 들어 있는 인터뷰 프로젝트를 읽고, AI가 추천한 3개 스토리라인을 한 화면에서 비교한 뒤 선택한 릴스 하나만 내보내는 개인용 macOS 앱입니다.

## 가장 쉬운 실행 방법

### 1. 필요한 프로그램 설치

macOS에서 아래 프로그램이 필요합니다.

- Python 3.11 이상
- CapCut 데스크톱
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

1. `프로젝트` 버튼을 누릅니다.
2. CapCut 프로젝트 폴더를 선택합니다. `draft_info.json`이 들어 있는 폴더면 됩니다.
3. 폴더를 선택하면 AI가 스토리라인 3개를 만들고 대표 영상 3개를 자동으로 렌더합니다.
4. 각 스토리라인에서 `AI 추천 제목 3개 중 선택` 중 하나를 고릅니다.
5. 자막 스위치를 ON/OFF로 바꿉니다.
6. 내보낼 영상 하나만 `이 영상 선택`으로 고릅니다.
7. `선택 영상 내보내기`를 누르고 저장 위치를 선택합니다.

완료된 프로젝트를 새 스토리라인으로 다시 만들 때만 `다시 생성`을 누릅니다.

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

## CapCut 프로젝트 준비

1. CapCut에서 인터뷰 원본 영상을 추가합니다.
2. `Text`에서 자동자막을 생성합니다.
3. 프로젝트를 저장합니다.
4. 앱에서 해당 프로젝트 폴더를 선택합니다.

기본 CapCut 프로젝트 위치는 보통 아래입니다.

```text
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/
```

## 데이터 저장 위치

앱 작업 상태와 렌더 중간 파일은 아래에 저장됩니다.

```text
~/Library/Application Support/reels-editor/jobs/
```

내보낸 최종 MP4는 사용자가 저장 대화상자에서 고른 위치에 저장됩니다.

## CLI로 실행하기

GUI 대신 기존 CLI를 쓸 수도 있습니다.

```bash
.venv/bin/reels-editor make "<CapCut 프로젝트 폴더명>"
```

전체 경로를 직접 전달해도 됩니다.

```bash
.venv/bin/reels-editor make \
  "$HOME/Movies/CapCut/User Data/Projects/com.lveditor.draft/<프로젝트 폴더명>"
```

브라우저 검토 화면 없이 바로 렌더하려면 다음 옵션을 씁니다.

```bash
.venv/bin/reels-editor make "<CapCut 프로젝트 폴더명>" --no-ui
```

이미 만들어진 EDL을 다시 렌더할 수도 있습니다.

```bash
.venv/bin/reels-editor render out/<프로젝트명-날짜>/s1 --title 2
```

## AI 설정

GUI 앱은 Codex CLI를 사용합니다. 다른 AI provider는 CLI 모드에서만 사용하세요.

```yaml
provider: codex-cli
model: gpt-5.6-sol
n_storylines: 3
style: {}
```

설정 파일 위치:

```text
~/.config/reels-editor/config.yaml
```

CLI 모드에서 지원하는 프로바이더:

| 프로바이더 | `provider` 값 | 인증 |
| --- | --- | --- |
| OpenAI Codex CLI | `codex-cli` | `codex login` |
| Claude Code CLI | `claude-cli` | `claude` 로그인 |
| OpenAI API | `openai` | `OPENAI_API_KEY` |
| Kimi | `kimi` | `MOONSHOT_API_KEY` |
| OpenAI 호환 서버 | `custom` | `REELS_LLM_API_KEY` |

## ElevenLabs 음성 개선

설정 화면의 `ElevenLabs Voice Isolator`에서 API 키를 입력하고 `음성 개선 ON`으로
저장하면, 선택한 최종 영상을 내보낼 때 사람 목소리의 배경 소음과 잔향을 줄입니다.
미리보기 렌더에는 API를 호출하지 않으며 최종 선택 영상마다 한 번만 호출합니다.
같은 오디오는 작업 폴더의 SHA-256 캐시를 재사용하므로 다시 내보낼 때 중복 과금하지
않습니다.

API 키는 아래 로컬 파일에 권한 `0600`으로 저장됩니다.

```text
~/.config/reels-editor/credentials.yaml
```

환경변수로 설정할 수도 있습니다.

```bash
export ELEVENLABS_API_KEY="..."
```

Voice Isolator가 켜져 있는데 API 키가 없거나 호출이 실패하면 원본 음성으로 조용히
대체하지 않고 내보내기 오류를 표시합니다. ElevenLabs 사용량은 처리한 오디오 길이에
따라 계정에 차감됩니다.

## 문제 해결

### 앱에서 Codex 또는 ffmpeg를 찾지 못함

터미널에서 아래 명령이 되는지 확인합니다.

```bash
codex --version
ffmpeg -version
ffprobe -version
```

앱은 Finder에서 실행해도 `~/.npm-global/bin`, `~/.local/bin`, `/opt/homebrew/bin`, `/usr/local/bin`을 자동으로 PATH에 넣습니다.

### CapCut 프로젝트를 찾을 수 없음

- 프로젝트를 저장했는지 확인합니다.
- 자동자막이 만들어졌는지 확인합니다.
- 프로젝트 이름 대신 `draft_info.json`이 있는 폴더 전체 경로를 선택합니다.

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
