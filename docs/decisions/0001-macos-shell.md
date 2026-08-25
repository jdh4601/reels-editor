# 0001. Personal macOS Shell

Status: Accepted for the personal MVP
Date: 2026-07-20

## Decision

Use a pywebview macOS `.app` shell around a loopback-only FastAPI/Uvicorn
process and a bundled React/Vite dashboard. Keep the existing Python editing
engine in-process and package the app as a PyInstaller `onedir` bundle.

The GUI uses the configured AI provider. Generated video remains local, and
only JobStore-registered artifacts are exposed to the webview through
token-protected byte-range URLs.

## Rationale

- Python continues to own YouTube source preparation, AI execution, ffmpeg
  rendering, persistence, cancellation, and export without a second IPC runtime.
- React provides the three-storyline comparison surface while pywebview keeps
  native folder and save dialogs.
- An ephemeral loopback port plus a per-launch token limits the local HTTP
  surface without requiring accounts or a remote service.
- PyInstaller gives the sole user a Finder-launchable app without introducing
  App Store distribution work.

## Verification

- The full Python test suite passes, including JobStore, JobService, API auth,
  WebSocket sequencing, registered media ranges, and overlay-only variants.
- TypeScript checking, the Vite production build, and Playwright dashboard
  checks pass at 1440x900, 1280x800, and 1024x800.
- `김현지대표인터뷰` completed through the real Codex CLI with three ready
  storylines and three 1080x1920 H.264 representative videos.
- Changing the selected title and disabling subtitles left the persisted base
  video and LLM outputs unchanged, then exported exactly one selected MP4.
- The packaged `dist/Reels Editor.app` launches directly and through macOS
  LaunchServices; authenticated snapshot, tools, WebSocket, and style-loading
  smoke checks pass.

## Constraints

- The app is ad-hoc signed but intentionally not Developer ID signed or
  notarized because it is a personal MVP.
- Codex CLI, ffmpeg, and ffprobe remain external prerequisites detected from
  common Homebrew and user-local executable paths.
