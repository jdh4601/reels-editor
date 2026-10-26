# Contributing

Thanks for taking the time. This is a small project, so the process is short.

## Before you start

For anything larger than a bug fix, open an issue first and describe what you
want to change. That is cheaper than finding out after the code is written that
the change does not fit.

## Setting up

You need macOS to run the desktop app, but the tests and the dashboard build run
anywhere. See the [Requirements](README.md#requirements) section for the tools
the app needs at runtime.

```bash
git clone https://github.com/jdh4601/reels-editor.git
cd reels-editor

python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"

cd desktop/ui && npm install && npm run build && cd ../..
```

Run the app straight from the source tree:

```bash
.venv/bin/reels-editor-desktop
```

## Verifying a change

Run what the CI runs, plus the visual check when you touch the dashboard:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest

cd desktop/ui
npm run typecheck
npm run build
npm run test:dashboard   # only needed for dashboard layout changes
npm run test:parallel    # desktop tabs and three concurrent jobs
```

`npm run test:dashboard` drives the real dashboard with Playwright at three
window sizes. It asserts that panels do not overlap and writes screenshots to
`desktop/ui/test-results/dashboard/`. Look at them when a layout assertion
fails; they usually show the problem immediately.

## How the code is laid out

| Path | What lives there |
| --- | --- |
| `reels_editor/` | Library and CLI: transcript handling, EDL, rendering, export |
| `reels_editor/jobs/` | Job state machine and on-disk store |
| `reels_editor/desktop/` | FastAPI server and the packaged dashboard assets |
| `desktop/ui/` | Dashboard source (React + Vite); builds into `reels_editor/desktop/ui/` |
| `desktop/pyinstaller/` | macOS `.app` bundling |
| `reels_editor/resources/prompts/` | Prompt templates sent to the model |
| `tests/` | Pytest suite, mirroring the module layout |

`reels_editor/resources/prompts/` is worth knowing about: prompt text is data, not code. If you are
changing what the model writes, the edit usually belongs in a `.md` file there
rather than in Python. `reels_editor/resources/prompts/text-hook-principles.md` is shared by both the
candidate-analysis and script-generation prompts, so a change there affects
every generated title.

Most prompt templates, and some instructions built in Python, are currently
written in Korean. English translations are welcome; keep the rules and their
order unchanged so generated output stays comparable, and mention it in the
pull request.

## Rerendering a saved clip

Rerender a saved EDL through the same verification pipeline as the app:

```bash
.venv/bin/reels-editor render path/to/workdir --title 1
```

The directory must contain `edl.json`, `segments.json` and accessible source
media. The command needs the same signed-in CLIs as the app, writes attempt
evidence under `.verified-jobs/`, and fails if the final review does not
approve the clip.

## Building the macOS app

```bash
.venv/bin/pyinstaller desktop/pyinstaller/reels_editor_desktop.spec --noconfirm
open "dist/Reels Editor.app"
```

The build is unsigned, so macOS asks for confirmation on first launch.

## Conventions

Match the surrounding code rather than importing a new style.

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(scope): description`, `fix(scope): ...`, `docs: ...`.
- Python is typed and formatted in the style already in the tree: type hints on
  signatures, `pathlib.Path` over `os.path`, guard clauses over deep nesting.
- TypeScript runs under `strict`. No `any`.
- User-facing interface strings in the app are English. Generated content follows the selected output language. Code, comments, commit messages,
  and this documentation are English.
- New behavior needs a test. Write the failing test first when you can.

## Reporting bugs

Include the version (`git rev-parse --short HEAD`), your macOS and Python
version, and the exact error. Strip API keys out of anything you paste.

`npm run test:parallel` builds the packaged UI and connects Chrome/Chromium to a
real local FastAPI job service. External YouTube, AI, and render calls use test
substitutes. It checks independent URLs and candidate selections, simultaneous
rendering, the three-job limit, scoped WebSocket updates, tab reset/close, and
compact desktop layout. Screenshots go to `desktop/ui/test-results/parallel-*.png`.
If Playwright Chromium is unavailable, use an installed Chrome with
`REELS_TEST_BROWSER_CHANNEL=chrome npm run test:parallel`.

## Verification changes

Keep the fail-closed contract in [docs/verification.md](docs/verification.md). Test language propagation and cached-source reuse independently. Never add a fallback that labels unreviewed bytes ready. Package all runtime resources; tests must not depend on a sibling repository or a private font installation.
