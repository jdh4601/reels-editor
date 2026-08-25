<div align="center">

# Reels Editor

**Turn a one-hour founder interview into short-form reels — on your own machine.**

[![CI](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Platform: macOS](https://img.shields.io/badge/Platform-macOS-lightgrey.svg)](#requirements)

[한국어 README](README.ko.md) · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md)

<img src="docs/images/dashboard.png" alt="The Reels Editor dashboard: a YouTube link field, reel type chips, and a generated reel with its beat-by-beat structure" width="820">

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

**Titles are text hooks, not summaries.** Titles are capped at 14 characters
excluding spaces and pushed toward noun phrases, because a full sentence with
every particle intact reads slower than the viewer scrolls. The rules live in
[`prompts/text-hook-principles.md`](prompts/text-hook-principles.md) and are
enforced in validation — a title that runs long is sent back for a rewrite.

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
   (Generate selected reels). Only your picks get rendered, at 30–40 seconds each.
5. Optionally click **캡션 생성하기** (Generate caption) for an Instagram caption
   written from that reel's actual script.
6. Select what you want and click **선택 영상 내보내기** (Export selected).

Toggling subtitles re-renders only the overlay, not the whole video.

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
| OpenAI API | `openai` | `OPENAI_API_KEY` |
| Kimi | `kimi` | `MOONSHOT_API_KEY` |
| OpenAI-compatible server | `custom` | `REELS_LLM_API_KEY` |

<img src="docs/images/settings.png" alt="The settings popover, showing playback speed and model provider" width="420">

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
| Jobs, downloaded video, transcripts, render intermediates | `~/Library/Application Support/reels-editor/jobs/` |
| Configuration | `~/.config/reels-editor/config.yaml` |
| Exported MP4 | Wherever you choose in the save dialog |

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
