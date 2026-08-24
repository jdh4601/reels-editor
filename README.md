# Reels Editor

창업가의 1시간 안팎 영어 YouTube 인터뷰 링크를 넣으면 영상과 영어 원문 자막을 로컬에 저장하고, 창업가가 공감하거나 재미있어할 1분 이하 클립 후보를 만드는 개인용 macOS 앱입니다. 구간 선택은 영어 원문을 기준으로 하며, 각 후보는 영어 원음이 유지된 9:16 영상, 자연스러운 한국어 자막, 상단의 주황색 한국어 후킹 제목으로 렌더링됩니다.

## 가장 쉬운 실행 방법

### 1. 필요한 프로그램 설치

macOS에서 아래 프로그램이 필요합니다.

- Python 3.11 이상
- ffmpeg와 ffprobe
- OpenAI Codex CLI
- Pretendard 폰트

기존 CapCut 프로젝트를 직접 가져오는 기능을 함께 쓰려면 CapCut 데스크톱도 설치합니다.

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
2. 목표 길이(15초·30초·60초)와 만들 클립 개수를 설정합니다.
3. `클립 만들기`를 누릅니다.
4. 앱이 영상과 영어 원문 자막을 작업 폴더에 다운로드하고, AI가 서로 다른 관점의 클립을 골라 선택 구간만 한국어 자막으로 번역해 렌더합니다.
5. 각 스토리라인에서 `AI 추천 제목 3개 중 선택` 중 하나를 고릅니다.
6. 자막 스위치를 ON/OFF로 바꿉니다.
7. 내보낼 영상을 하나 이상 선택합니다.
8. `선택 영상 내보내기`를 누르고 저장 위치를 선택합니다.

YouTube에 영어 수동 자막이나 영어 자동 생성 자막이 있으면 이를 우선 사용합니다. 영어 자막이 없으면 다른 제공 자막을 보조적으로 사용하며, 어떤 자막도 없는 영상은 사용할 수 없습니다. 앱은 별도 음성 인식으로 몰래 대체하지 않고 자막이 필요하다는 오류를 표시합니다.

완료된 인터뷰를 새 스토리라인으로 다시 만들 때만 `다시 생성`을 누릅니다.

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

```text
~/Library/Application Support/reels-editor/jobs/<작업ID>/source/
```

다운로드한 콘텐츠는 사용 권한이 있는 영상에만 사용하세요.

## 기존 CapCut 프로젝트 가져오기

1. CapCut에서 인터뷰 원본 영상을 추가합니다.
2. `Text`에서 자동자막을 생성합니다.
3. 프로젝트를 저장합니다.
4. 앱에서 `CapCut 가져오기`를 눌러 해당 프로젝트 폴더를 선택합니다.

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
격리된 음성에는 하이패스/로우패스, 적응형 FFT 잡음 억제, 노이즈 게이트,
컴프레서와 라우드니스 정규화를 순서대로 적용해 남은 저역 진동과 고역 잡음도 함께
줄입니다.
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
