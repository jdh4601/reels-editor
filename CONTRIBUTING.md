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
| `prompts/` | Prompt templates sent to the model |
| `tests/` | Pytest suite, mirroring the module layout |

`prompts/` is worth knowing about: prompt text is data, not code. If you are
changing what the model writes, the edit usually belongs in a `.md` file there
rather than in Python. `prompts/text-hook-principles.md` is shared by both the
candidate-analysis and script-generation prompts, so a change there affects
every generated title.

## Conventions

Match the surrounding code rather than importing a new style.

- Commits follow [Conventional Commits](https://www.conventionalcommits.org/):
  `feat(scope): description`, `fix(scope): ...`, `docs: ...`.
- Python is typed and formatted in the style already in the tree: type hints on
  signatures, `pathlib.Path` over `os.path`, guard clauses over deep nesting.
- TypeScript runs under `strict`. No `any`.
- User-facing strings in the app are Korean. Code, comments, commit messages,
  and this documentation are English.
- New behavior needs a test. Write the failing test first when you can.

## Reporting bugs

Include the version (`git rev-parse --short HEAD`), your macOS and Python
version, and the exact error. Strip API keys out of anything you paste.
