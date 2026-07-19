# reels-editor

CapCut 자동자막이 들어 있는 인터뷰 프로젝트를 읽어 여러 개의 30초
스토리텔링 릴스를 만드는 macOS용 CLI입니다.

실행하면 다음 순서로 작업합니다.

1. CapCut 프로젝트에서 자동자막을 읽습니다.
2. 서로 다른 관점의 스토리라인을 최대 3개까지 동시에 만듭니다.
3. 브라우저에서 스토리라인과 타이틀 조합을 선택합니다.
4. 선택한 조합을 세로형 MP4로 렌더합니다.

## 빠른 시작

### 1. 필요한 프로그램 설치

다음 프로그램이 필요합니다.

- macOS
- Python 3.11 이상
- CapCut 데스크톱
- ffmpeg와 ffprobe
- Claude Code CLI 또는 OpenAI 호환 API 키

Homebrew가 있다면 ffmpeg를 다음 명령으로 설치합니다.

```bash
brew install ffmpeg
```

설치 여부를 확인합니다.

```bash
python3 --version
ffmpeg -version
ffprobe -version
```

### 2. 프로젝트 내려받기

```bash
git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
```

### 3. Python 환경 만들기

아래 명령은 최초 한 번만 실행하면 됩니다.

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

설치가 끝나면 CLI가 정상적으로 보이는지 확인합니다.

```bash
.venv/bin/reels-editor --help
```

### 4. 사용할 AI 선택하기

기본값은 로컬 Claude Code CLI입니다. `claude` 명령이 설치되어 있고 로그인이
완료되어 있다면 추가 설정 없이 사용할 수 있습니다.

```bash
claude --version
```

Claude Code CLI 대신 OpenAI를 사용하려면 API 키와 설정 파일을 먼저 만듭니다.

```bash
export OPENAI_API_KEY="sk-여기에-키를-입력"
mkdir -p ~/.config/reels-editor
```

`~/.config/reels-editor/config.yaml` 파일을 만들고 다음 내용을 넣습니다.

```yaml
provider: openai
model: gpt-4o
n_storylines: 3
style: {}
```

지원하는 프로바이더는 다음과 같습니다.

| 프로바이더 | `provider` 값 | API 키 환경변수 |
| --- | --- | --- |
| Claude Code CLI | `claude-cli` | 필요 없음 |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Kimi | `kimi` | `MOONSHOT_API_KEY` |
| OpenAI 호환 서버 | `custom` | `REELS_LLM_API_KEY` |

`custom`을 사용할 때는 `config.yaml`에 `base_url`과 `model`도 지정해야 합니다.

### 5. CapCut 프로젝트 준비하기

1. CapCut에서 새 프로젝트를 만들고 인터뷰 원본 영상을 추가합니다.
2. **Text → 자동자막**을 실행합니다.
3. 자동자막이 타임라인에 생성됐는지 확인하고 프로젝트를 저장합니다.
4. CapCut 프로젝트 폴더 이름 또는 폴더 경로를 확인합니다.

기본적으로 다음 폴더 아래에서 프로젝트를 찾습니다.

```text
~/Movies/CapCut/User Data/Projects/com.lveditor.draft/
```

프로젝트 이름으로 찾지 못하면 `draft_info.json`이 들어 있는 프로젝트 폴더의
전체 경로를 실행 명령에 전달하면 됩니다.

### 6. 첫 릴스 만들기

`<CapCut 프로젝트 폴더명>`을 실제 프로젝트 폴더 이름으로 바꿉니다.

```bash
.venv/bin/reels-editor make "<CapCut 프로젝트 폴더명>"
```

전체 경로를 직접 전달해도 됩니다.

```bash
.venv/bin/reels-editor make \
  "$HOME/Movies/CapCut/User Data/Projects/com.lveditor.draft/<프로젝트 폴더명>"
```

실행 후 브라우저 검토 화면이 열립니다.

1. 원하는 스토리라인과 타이틀 조합을 체크합니다.
2. 필요한 경우 자막 크기, 색상, 위치와 배속을 조절합니다.
3. **선택한 조합 렌더** 버튼을 누릅니다.
4. 터미널에 완료 메시지가 나올 때까지 기다립니다.

브라우저를 사용하지 않으려면 `--no-ui` 옵션을 추가합니다.

```bash
.venv/bin/reels-editor make "<CapCut 프로젝트 폴더명>" --no-ui
```

스토리라인 개수와 목표 길이도 지정할 수 있습니다.

```bash
.venv/bin/reels-editor make "<CapCut 프로젝트 폴더명>" \
  --storylines 3 \
  --duration 30
```

## 결과 파일 찾기

결과는 저장소의 `out/` 폴더에 생성됩니다.

```text
out/<프로젝트명-날짜>/
├── manifest.json
├── s1/
│   ├── reel-t1.mp4
│   ├── reel-t2.mp4
│   ├── reel.srt
│   ├── edl.json
│   ├── segments.json
│   └── cuts/
└── s2/
    └── ...
```

- `reel-t1.mp4`: 최종 릴스 영상
- `reel.srt`: 최종 자막
- `edl.json`: 사용한 장면과 타이틀 정보
- `cuts/`: 비트별로 나눈 수정용 영상
- `manifest.json`: 선택한 조합과 렌더 결과 요약

## 수정 후 다시 렌더하기

`s1/edl.json`을 수정한 뒤 LLM과 게이트를 다시 실행하지 않고 렌더할 수 있습니다.

```bash
.venv/bin/reels-editor render out/<프로젝트명-날짜>/s1 --title 2
```

`--title 2`는 두 번째 타이틀 후보를 사용한다는 뜻입니다.

## 설정 저장 위치

브라우저 게이트에서 바꾼 설정은 다음 파일에 저장됩니다.

```text
~/.config/reels-editor/config.yaml
```

게이트에서 입력한 API 키는 프로젝트 폴더가 아닌 다음 파일에 권한 `0600`으로
저장됩니다.

```text
~/.config/reels-editor/credentials.yaml
```

환경변수에 API 키가 있으면 저장된 키보다 환경변수를 우선 사용합니다.

## 자주 발생하는 문제

### `ffmpeg 없음` 또는 `ffprobe 없음`

```bash
brew install ffmpeg
```

설치 후 새 터미널을 열고 다시 실행합니다.

### `claude 없음`

Claude Code CLI를 설치하고 로그인하거나, 위의 OpenAI 설정 방법에 따라
`provider: openai`로 변경합니다.

### `CapCut 프로젝트를 찾을 수 없습니다`

- CapCut 프로젝트를 저장했는지 확인합니다.
- 자동자막이 생성됐는지 확인합니다.
- 프로젝트 이름 대신 `draft_info.json`이 있는 폴더의 전체 경로를 전달합니다.
- 프로젝트 루트가 다른 경우 `CAPCUT_ROOT`를 지정합니다.

```bash
export CAPCUT_ROOT="/다른/CapCut/프로젝트/루트"
.venv/bin/reels-editor make "<프로젝트 폴더명>"
```

### `API 키가 없습니다`

사용하는 프로바이더에 맞는 환경변수를 확인합니다.

```bash
echo "$OPENAI_API_KEY"
echo "$MOONSHOT_API_KEY"
echo "$REELS_LLM_API_KEY"
```

API 키 자체를 터미널 화면이나 로그에 공유하지 마세요.

## 스토리 원칙

- 자막은 원문을 새로 쓰지 않고 삭제하거나 재배치합니다.
- 타이틀 후보만 새로 만듭니다.

## 테스트

개발 의존성을 설치하고 전체 테스트를 실행합니다.

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q
```
