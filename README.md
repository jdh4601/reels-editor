<div align="center">

<img src="docs/images/icon.png" alt="Reels Editor" width="128">

# Reels Editor

**Turn a one-hour founder interview into short-form reels — on your own machine.**

[![CI](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)](#requirements)

[한국어 README](README.ko.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

</div>

---

Paste a YouTube interview. The app reads the transcript, proposes ten reel ideas
that do not overlap, and renders only the ones you pick as 9:16 videos with
Korean subtitles and a hook title across the top.

Everything runs locally. The video, the transcript, and the render all stay on
your machine; the only thing that leaves is the transcript text you send to
whichever model provider you configure.

## Why this exists

Cutting short-form clips out of a long interview is mostly judgment, not
editing. You watch an hour looking for the ninety seconds that are worth
sharing, and by the time you find them you still have to cut, subtitle, and
title them.

This tool splits that in two. It does the reading and proposes candidates with
evidence — each one points at the exact transcript segments that back it — and
you make the call about which ones are worth making. Then it does the cutting.

## What makes it different

**Nothing is paraphrased.** Subtitles are the source transcript, verbatim. The
model may delete and reorder segments; it may not rewrite a single ending or
particle. If a quote opens, the cut runs through the segment that closes it. The
only text the model writes is the title.

**Candidates carry their evidence.** Each of the ten proposals names the
transcript segments it is built from, so a claim can be checked before you spend
a render on it.

**Titles are text hooks, not summaries.** The ten generated candidates must use
12–24 visible characters and at least three naturally spaced Korean words, so
they stay specific and readable instead of collapsing into short, unspaced
phrases. The rules live in
[`prompts/text-hook-principles.md`](prompts/text-hook-principles.md) and are
enforced in validation — a title that misses the contract is sent back for a rewrite.

**Two-line titles have a clear hierarchy.** The first line is a smaller white
setup; the second line stays large and orange as the actual hook.

**Wide shots follow the speaker.** On macOS, Apple Vision detects faces and
mouth movement locally. The crop moves toward the active speaker and adds a
restrained zoom when a two-person shot would otherwise cut that person off.

**Your model, your choice.** Codex CLI, Claude Code CLI, the OpenAI API, Kimi,
or any OpenAI-compatible server.

## Requirements

macOS, plus:

| Tool | Why | Install |
| --- | --- | --- |
| Python 3.11+ | Runs the app | [python.org](https://www.python.org/downloads/) |
| ffmpeg, ffprobe | Cuts and renders the video | `brew install ffmpeg` |
| Pretendard | The font used in titles and subtitles | `brew install --cask font-pretendard` |
| A model provider | Reads the transcript, writes the plan | see [Model providers](#model-providers) |

Verify before continuing:

```bash
python3 --version && ffmpeg -version | head -1 && ffprobe -version | head -1
```

## Install

```bash
git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cd desktop/ui && npm install && npm run build && cd ../..
```

Set up a model provider — Codex CLI is the default:

```bash
npm install -g @openai/codex
codex login
```

Then start the app:

```bash
.venv/bin/reels-editor-desktop
```

## Using it

1. Paste the YouTube link to a long-form founder interview.
2. Pick one or more reel types: story, strategy, failure analysis, principle.
3. Click **후보 10개 분석** (Analyze 10 candidates). The app downloads the video
   and transcript, then proposes ten non-overlapping ideas.
4. Select the ones worth making and click **선택한 후보로 릴스 생성**
   (Generate selected reels). Only your picks get rendered, at 20–40 seconds each.
5. Optionally click **캡션 생성하기** (Generate caption) for an Instagram caption
   written from that reel's actual script.
6. Select what you want and click **선택 영상 내보내기** (Export selected).
7. With Buffer configured, click **Buffer 큐에 업로드** to add only the selected
   videos as Instagram Reels in the next available Buffer slots.

Each export gets its own directory containing only the videos selected for that
run. App-managed render archives and user-requested export directories are kept
separate.

### Buffer upload setup

Buffer requires a stable public media URL rather than accepting local video
files directly. Reels Editor uploads each selected MP4 through a Cloudinary
unsigned upload preset, then creates an Instagram Reel with Buffer's GraphQL API.

Open generation settings and save your Buffer API key, Instagram channel ID,
Cloudinary cloud name, and unsigned upload preset. The Buffer key stays in
`~/.config/reels-editor/credentials.yaml` with `0600` permissions; the
`BUFFER_API_KEY` environment variable takes precedence when present. Keep the
Cloudinary URL public until Buffer has published the queued post.

The Buffer channel ID and Cloudinary values persist in
`~/.config/reels-editor/config.yaml`. Both configuration files live outside the
`.app` bundle, so rebuilding or replacing the application preserves them. API
keys are intentionally never stored in the Git repository.

The first render crops, composites the title, subtitles, and logo, and encodes
the final MP4 in one FFmpeg pass. Title and subtitle edits reuse the downloaded
source, crop plan, face analysis, and generated PNG assets; no intermediate
H.264 video is encoded and decoded again.

On the reference M4 Pro, the app keeps `libx264 -preset veryfast` as the default
because the complete 1080×1920 CPU-filtered graph benchmarked faster than
VideoToolbox. You can compare the hardware encoder on another Mac with:

```bash
REELS_EDITOR_VIDEO_ENCODER=h264_videotoolbox .venv/bin/reels-editor-desktop
```

If VideoToolbox is unavailable at runtime, rendering retries with `libx264`.
Final hardware encodes are serialized so multiple reel analyses can still run
in parallel without oversubscribing Apple's video encoder.

### Transcripts

The app uses YouTube's own captions and will not quietly substitute speech
recognition. English manual captions are preferred, then English auto-generated
ones, then whatever else the video provides. A video with no captions at all is
rejected with an explicit error rather than a silent fallback.

For English-language sources, subtitles are translated into Korean while numbers,
proper nouns, and factual claims are preserved.

## Model providers

Choose a provider in settings, or edit `~/.config/reels-editor/config.yaml`:

```yaml
provider: codex-cli
model: gpt-5.6-sol
style: {}
```

| Provider | `provider` value | Authentication |
| --- | --- | --- |
| OpenAI Codex CLI | `codex-cli` | `codex login` |
| Claude Code CLI | `claude-cli` | `claude` login |
| Google Gemini CLI | `gemini-cli` | `gemini` login |
| OpenAI API | `openai` | `OPENAI_API_KEY` |
| Kimi | `kimi` | `MOONSHOT_API_KEY` |
| OpenAI-compatible server | `custom` | `REELS_LLM_API_KEY` |

## Build a standalone app

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
open "dist/Reels Editor.app"
```

Install it like any other Mac app:

```bash
ditto "dist/Reels Editor.app" "/Applications/Reels Editor.app"
```

The build is unsigned and un-notarized. The first time you open it, macOS will
refuse; Control-click the app in Finder and choose **Open**.

## Where files go

| What | Where |
| --- | --- |
| Jobs, downloaded video, transcripts, render assets and local face-analysis cache | `~/Library/Application Support/reels-editor/jobs/` |
| Configuration | `~/.config/reels-editor/config.yaml` |
| Exported MP4 | A per-run folder under `~/Movies/Reels Editor Exports/` |

Re-running the same video reuses the existing download. The video ID is what
matters, so `youtu.be/…` and `watch?v=…` links to the same video will not
download twice.

## CLI

Re-render an existing EDL work directory after editing `edl.json` by hand:

```bash
.venv/bin/reels-editor render out/<project-date>/s1
```

## Troubleshooting

<details>
<summary><b>The app cannot find Codex or ffmpeg</b></summary>

Check that they work in a terminal:

```bash
codex --version && ffmpeg -version | head -1
```

When launched from Finder, the app adds `~/.npm-global/bin`, `~/.local/bin`,
`/opt/homebrew/bin`, and `/usr/local/bin` to its `PATH` automatically. A tool
installed somewhere else will not be found.
</details>

<details>
<summary><b>Download or transcript extraction fails</b></summary>

- Use a link to a single video. Playlist links are not supported.
- Private, age-restricted, and login-required videos may be undownloadable.
- Confirm the video actually has captions.
- If YouTube changed formats, update the downloader: `pip install -U yt-dlp`.
</details>

<details>
<summary><b>The build fails</b></summary>

Reinstall both halves of the project:

```bash
.venv/bin/pip install -e ".[dev]"
cd desktop/ui && npm install && npm run build && cd ../..
```
</details>

## Development

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest

cd desktop/ui
npm run typecheck
npm run build
npm run test:dashboard
```

`npm run test:dashboard` drives the dashboard with Playwright at three window
sizes, asserts that nothing overlaps, and writes screenshots to
`desktop/ui/test-results/dashboard/`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for the layout of the codebase.

## A note on the videos you process

Download and publish only what you have the right to use. This tool does not
check that for you.

## License

[MIT](LICENSE) © DongHyun Jung
