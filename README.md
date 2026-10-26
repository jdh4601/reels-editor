<div align="center">
<img src="docs/images/icon.png" alt="Reels Editor" width="112">

# Reels Editor

**Turn long-form YouTube videos into vertical short-form reels, on your own machine.**

[한국어](README.ko.md) · **English** · [简体中文](README.zh-CN.md)

[![CI](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml/badge.svg)](https://github.com/jdh4601/reels-editor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-black.svg)](LICENSE)
</div>

Paste a captioned YouTube video, review ten transcript-backed clip ideas, and generate the ones you choose. Reels Editor cuts the original footage into 1080×1920 videos, adds titles and translated subtitles, aligns them to measured speech, and checks the finished MP4 before making it available for export.

It is a focused local reel generator. You do not need a private workspace, company assets, or a Google Drive account.

## What changed in 0.2

- The latest speech-alignment and independent review pipeline now runs in the standalone app.
- Opening quotations must match consecutive source captions. Original statements, numbers, negation and context must survive editing.
- Opening zoom and a bundled wind sound follow a measured emphasis word; their application is checked in the actual output.
- **한국어 / English / 简体中文** output options control generated titles, subtitles and captions. Language is saved per job and retained through retries; analysis caches distinguish languages. Chinese titles do not require artificial spaces.
- Title and subtitle overlay edits require another final review. Exports check the approved MP4 hash again, including the copied file.
- Videos and thumbnails contain no bottom logo or episode-number overlay.
- A neutral template, an openly licensed CJK font, and self-contained package resources replace private branding and machine-specific assets.
- Local export works without cloud storage. A failed cover does not discard a verified MP4.

## Requirements

The complete generation pipeline currently targets **Apple silicon macOS**. Local word timing uses MLX Whisper; the native desktop shell and face detection also use macOS APIs. Python tests and the UI build can run on Linux, but that does not establish Linux or Windows runtime support.

| Requirement | Purpose |
| --- | --- |
| Python 3.11+ | Backend and local video pipeline |
| Node.js 22.13+ and npm | Build the React desktop UI |
| FFmpeg and FFprobe | Decode, render and inspect media |
| Authenticated Codex CLI | Subtitle alignment and bounded repairs |
| Authenticated Claude Code CLI with Opus access | Independent final review |
| Internet connection | YouTube captions/media, model requests, first ASR model download |

A configured generator can use Codex, Claude, Gemini, OpenAI or Kimi. **The verification layer still requires Codex and Claude/Opus**, regardless of the generation provider. Authentication, capacity and provider usage charges depend on your own accounts. Review errors are not silently bypassed or replaced with a different model.

## Install and run

```bash
brew install ffmpeg

git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

npm ci --prefix desktop/ui
npm run build --prefix desktop/ui
```

Install and authenticate the two verification CLIs if they are not already available:

```bash
npm install -g @openai/codex @anthropic-ai/claude-code
codex login
claude
```

Complete Claude's interactive sign-in, then launch:

```bash
.venv/bin/reels-editor-desktop
```

The app uses a loopback server protected by a random session token. No public server or separate workspace is required. Noto Sans CJK and the procedural opening sound are bundled with the package. The ASR model downloads on first use and is cached locally.

## Make a reel

1. Paste a single YouTube video URL. The video must have accessible captions.
2. Choose **Output language**: 한국어, English or 简体中文.
3. Analyze ten candidates and select the clips you want to make. Each candidate carries its source segment IDs and opening quote.
4. Generate the selected clips. Only the required source sections are downloaded after the scripts are ready. Clips complete a topic rather than being forcibly trimmed to a fixed duration.
5. Inspect the portrait preview, title, subtitles and cover. Title or metadata edits rerender the overlay and trigger a fresh independent review.
6. Select finished reels and export. With no Drive folder configured, output goes to a local folder under `~/Movies/Reels Editor Exports/`. A configured local Google Drive folder remains an optional destination.

Language selection changes generated text; it does **not** dub or replace the original speech. The interface, menus, notifications and diagnostics are in English. New jobs default to English output; you can still choose Korean or Simplified Chinese. Source quotations retain their original language. Portrait framing works best when the speaker is visible. A source with insufficient identity, speech or timing evidence may fail verification instead of receiving invented details.

## The verification layer

```text
Source captions → evidence-backed candidates → selected script
  → source/context checks → local word timing → subtitle alignment
  → measured opening zoom + sound → final MP4
  → final-audio analysis + programmatic checks + independent Opus review
       ├─ pass: bind approval to the exact MP4 hash → export
       └─ fail/uncertain: repair → retime → rerender → review (at most 2 repairs)
```

The final review covers topic, translation, caption timing, opening audio, opening captions, readability, framing, zoom and opening sound. Missing checks, insufficient evidence, uncertainty, machine-detected problems, and changed video bytes prevent approval. The reviewer receives actual final-video frames and audio-derived timing/signal evidence. It does not directly listen to the audio, and ASR timestamps remain estimates.

Each attempt preserves its evidence, raw model response, repair and review report under `jobs/<job>/sN/quality/`. Successful approval is attached to the actual file hash. Failed clips remain retryable; other completed clips are preserved. Old jobs without a complete matching approval must be regenerated before export.

See [the verification contract](docs/verification.md) for the code paths, invariants and regression checks.

## Local processing and model calls

FFmpeg rendering, media storage, face detection and ASR run on your machine. Transcript excerpts, selected scripts and timing evidence go to the configured generation/alignment providers; final frame images and derived audio evidence go to Claude/Opus. Speaker verification or optional cover search can query public sources. This is **not a fully offline model pipeline**. There is no built-in automatic publishing step.

| Data | Default location |
| --- | --- |
| Jobs, source captions, downloaded sections and review evidence | `~/Library/Application Support/reels-editor/jobs/` |
| Source/analysis cache | `jobs/.source-cache/` |
| User settings | `~/.config/reels-editor/config.yaml` |
| Completed local archive | `~/Movies/Reels Editor/` |
| Selected local exports | `~/Movies/Reels Editor Exports/` |

Completed archive items remain reopenable for seven days. Do not put private media, credentials, generated jobs or review evidence into source control.

Example configuration:

```yaml
provider: codex-cli
model: ""
output_language: en  # ko | en | zh
style:
  speed: 1.2
```

The desktop selector is authoritative for each new job. Existing jobs retain their saved output language; older jobs default to Korean. The UI remembers the last selected language for a new workspace.

## Verified rerender and development

Rerender a saved EDL using the same verification pipeline:

```bash
.venv/bin/reels-editor render path/to/workdir --title 1
```

The directory must contain `edl.json`, `segments.json` and accessible source media. This command requires the same model authentication and writes attempt evidence under `.verified-jobs/`; it reports failure if the final review cannot approve the clip.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
npm run typecheck --prefix desktop/ui
npm run build --prefix desktop/ui
npm run test:dashboard --prefix desktop/ui
```

Unit/integration tests use isolated model substitutes. The dashboard test checks three window sizes, language selection/persistence, navigation and the actual creation request. Tests do not establish that every source will pass live model review.

Build a macOS app with:

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
open "dist/Reels Editor.app"
```

The build is unsigned. See [CONTRIBUTING.md](CONTRIBUTING.md) and [CHANGELOG.md](CHANGELOG.md).

## Troubleshooting

- **No source captions:** provide a captioned video. ASR verifies the selected audio; it is not a silent replacement for missing YouTube captions.
- **CLI missing or signed out:** verify `codex --version`, `claude --version`, and both accounts' sign-in state. A selected generation provider alone does not satisfy verification requirements.
- **Review fails:** inspect the per-clip error and preserved evidence, then retry. Incomplete or uncertain review is not a successful render.
- **Cover fails:** the verified MP4 remains playable and exportable; retry or choose another source image.
- **YouTube extraction changes:** update `yt-dlp` in your environment and retry. Availability of private or restricted videos is not guaranteed.

## License

[MIT](LICENSE) © DongHyun Jung. Noto Sans CJK uses [SIL OFL 1.1](reels_editor/resources/styles/assets/fonts/OFL.txt); see [asset provenance](reels_editor/resources/styles/assets/README.md). Process and publish only media you have permission to use.
