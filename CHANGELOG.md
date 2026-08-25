# Changelog

All notable changes to this project are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Text-hook principles shared by every prompt that writes a title, in
  `prompts/text-hook-principles.md`. Titles are now capped at 14 characters
  excluding spaces, and at least one candidate must end as a noun phrase rather
  than a full sentence.
- Open-source project files: MIT license, contributing guide, issue and pull
  request templates, and a CI workflow running the test suite on Python 3.11
  and 3.12 plus the dashboard type check and build.

### Changed

- The title chosen during candidate analysis is now the title burned into the
  reel. Previously the analysis titles and the on-screen titles were generated
  separately and had nothing to do with each other.
- The workspace header was simplified: the logo mark is gone, the YouTube link
  field sits directly under the project title, reel types collapsed from a
  2×2 card grid into a single row of chips, and the dashboard/settings tabs were
  replaced by a settings popover next to the clear button.

### Removed

- The per-reel picker that offered three AI-suggested titles. Reels now carry
  the single confirmed title, and the selection endpoint only toggles subtitles.
- Title highlighting. Titles render in a single color.

### Migration

Jobs saved by earlier versions load without any manual step. `Storyline.title`
is read from the old `title_candidates` and `selected_title_index` pair when the
new field is absent.

## [0.1.0]

### Added

- Desktop app for macOS that turns a long-form founder interview on YouTube into
  vertical 30–40 second reels.
- Candidate analysis: ten non-overlapping reel ideas across four content types
  (story, strategy, failure analysis, principle), of which you generate only the
  ones you pick.
- Verbatim editing. Subtitles use the source transcript exactly as spoken;
  only deletion and reordering are allowed.
- Korean subtitle translation for English-language sources.
- Instagram caption generation from the reel's actual script.
- Multiple model providers: OpenAI Codex CLI, Claude Code CLI, the OpenAI API,
  Kimi, and any OpenAI-compatible server.
- CLI for re-rendering an existing EDL work directory.

[Unreleased]: https://github.com/jdh4601/reels-editor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/jdh4601/reels-editor/releases/tag/v0.1.0
