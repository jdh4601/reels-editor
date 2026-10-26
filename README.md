<div align="center">
<img src="docs/images/icon.png" alt="Reels Editor" width="112">

# Reels Editor

**Turn long-form YouTube videos into vertical short-form reels, on your own machine.**

[한국어](README.ko.md) · **English** · [简体中文](README.zh-CN.md)

[![CI](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
</div>

Paste a captioned YouTube video, pick from ten transcript-backed clip ideas, and get finished 1080×1920 reels with titles and subtitles timed to the actual speech. Every reel is reviewed by a separate model before you can export it.

> **Before you install:** Reels Editor runs on **Apple silicon Macs only**, and it needs two signed-in AI CLIs: **Codex CLI** and **Claude Code with Opus access**. Model usage is billed to your own accounts.

## Features

- **Clip ideas from the transcript.** Ten candidates, each tied to the source captions it came from.
- **Faithful editing.** Opening quotes must match the source word for word. Numbers, negations and context survive the cut.
- **Speech-timed subtitles.** Local word timing (MLX Whisper) aligns subtitles and the opening zoom to the measured audio.
- **Three output languages.** Titles, subtitles and captions in English, Korean or Simplified Chinese. The original audio is kept; nothing is dubbed.
- **Review before export.** An independent Opus review checks the final MP4. Approval is bound to the file hash, so an edited or changed file needs a new review.
- **Local first.** Rendering, media storage, face detection and speech recognition run on your Mac. Exports go to a local folder.

## Supported environments

| Environment | Status |
| --- | --- |
| macOS on Apple silicon | Supported |
| macOS on Intel | Not supported (MLX Whisper requires Apple silicon) |
| Linux | Tests and UI build only; the app does not run |
| Windows | Not supported |

## Requirements

| Tool | Used for |
| --- | --- |
| Python 3.11+ | Backend and video pipeline |
| Node.js 22.13+ and npm | Building the desktop UI |
| FFmpeg and FFprobe | Decoding, rendering and inspecting media |
| Codex CLI, signed in | Subtitle alignment and automatic repairs |
| Claude Code CLI with Opus access, signed in | Final review of every reel |

Clip ideas and scripts can come from Claude, Codex, Gemini, OpenAI or Kimi. Choose one in the app's settings. Subtitle alignment and repairs use Codex. If your Codex usage limit is reached, they continue with the provider you chose. The final review always uses Opus and is never skipped.

## Quick start

```bash
brew install ffmpeg
npm install -g @openai/codex @anthropic-ai/claude-code
codex login
claude          # complete the sign-in, then exit

git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
python3 -m venv .venv
.venv/bin/pip install -e .
npm ci --prefix desktop/ui
npm run build --prefix desktop/ui

.venv/bin/reels-editor-desktop
```

The speech recognition model downloads on first use and is cached afterwards.

## Making a reel

1. Paste the URL of a YouTube video that has captions.
2. Choose the output language.
3. Analyze the video and select the clip ideas you want.
4. Generate. Only the source sections each clip needs are downloaded.
5. Check the preview, title, subtitles and cover. Editing the title or subtitles triggers a new review.
6. Export the approved reels. They are saved to `~/Movies/Reels Editor Exports/`.

If a clip fails review, open its error, then retry it. Other finished clips are kept.

## How review works

Each reel is checked twice: by programmatic checks on the final audio and video, and by an independent Opus review of frames taken from the final MP4. A reel that fails is repaired, re-timed, re-rendered and reviewed again, at most twice. A reel that still fails cannot be exported. Every attempt keeps its evidence on disk so you can see why.

The full contract is in [docs/verification.md](docs/verification.md).

## Privacy and data

Rendering and speech recognition stay on your Mac. Some data goes to the model providers:

| Sent to | What |
| --- | --- |
| Your chosen generation provider | Transcript excerpts and selected scripts |
| Codex | Scripts and word timings for alignment and repairs |
| Claude (Opus) | Frames from the final video and timing evidence derived from its audio |
| Public web sources | Speaker lookups and the optional cover image search |

There is no automatic publishing step.

| Data | Location |
| --- | --- |
| Jobs and review evidence | `~/Library/Application Support/reels-editor/jobs/` |
| Settings | `~/.config/reels-editor/config.yaml` |
| Finished reels (kept for seven days) | `~/Movies/Reels Editor/` |
| Exports | `~/Movies/Reels Editor Exports/` |

## Configuration

Settings are saved from the app to `~/.config/reels-editor/config.yaml`:

```yaml
provider: claude-cli   # claude-cli | codex-cli | gemini-cli | openai | kimi | custom
model: ""              # empty uses the provider's default; custom requires a model
output_language: en    # en | ko | zh
style:
  speed: 1.2           # playback speed of the source footage
```

The language chosen in the app applies to each new job and is saved with it. You can also export to a local Google Drive folder by setting it in the app.

## Troubleshooting

- **The video has no captions.** Reels Editor needs YouTube captions to find clip ideas. Choose a video with captions.
- **A CLI is missing or signed out.** Run `codex --version` and `claude --version`, then sign in again.
- **Codex usage limit reached.** Subtitle alignment continues with your chosen provider. To keep using Codex, wait for your Codex limit to reset.
- **Review keeps failing.** Open the clip's error and evidence under `jobs/<job>/<clip>/quality/`, then retry. Sources where the speech or speaker is unclear may not pass.
- **The cover fails.** The reel is still exportable. Retry, or pick another image.
- **YouTube download errors.** Update `yt-dlp` in `.venv` and retry. Private and restricted videos may not work.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the development setup, tests and the macOS app build. Release history is in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) © DongHyun Jung. Noto Sans CJK is under the [SIL OFL 1.1](reels_editor/resources/styles/assets/fonts/OFL.txt); see [asset provenance](reels_editor/resources/styles/assets/README.md).

Only process and publish videos you have permission to use.
