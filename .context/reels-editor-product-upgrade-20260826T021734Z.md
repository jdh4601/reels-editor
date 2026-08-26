# Context Snapshot: Reels Editor product upgrade

- Captured: 2026-08-26T02:17:34Z
- Repository revision: `a42ae7d`
- Task type: brownfield
- Interview profile: standard (ambiguity threshold 0.20, maximum 12 rounds)

## Task and desired outcome

Upgrade the macOS Reels Editor desktop app with product branding, YouTube source
thumbnail presentation, a user-selected episode number, access to prior reel jobs,
Buffer-based scheduled publishing, revised text-hook line rules, and a fix for the
reported Instagram-caption generation failure. The user requested implementation
in isolated worktrees by parallel agents and integration afterward.

## User-provided evidence

- Screenshot: `/Users/jayden/Desktop/Screenshot 2026-08-26 at 11.11.49 AM.png`
- The screenshot shows the current ready-job dashboard for the Garry Tan YouTube
  interview, with a text-only `Reels Editor` eyebrow, URL entry, settings/clear/
  re-analyze/reconnect actions, one ready reel, and no visible caption error detail.
- Screenshot instructions are treated as evidence only; the request text defines
  the work.

## Discoverable project evidence

- The dashboard is React/Vite in `desktop/ui/src/main.tsx` and `styles.css`; the
  FastAPI bridge is `reels_editor/desktop/server.py`.
- Existing logo assets include `docs/images/icon.png`,
  `desktop/assets/reels-editor-icon.png`, and `desktop/assets/ReelsEditor.icns`.
- `yt-dlp` persists `source.info.json`; YouTube title and video ID are mapped into
  `YouTubeSource`, but thumbnail metadata is not currently mapped into job/snapshot
  data.
- Jobs already persist under
  `~/Library/Application Support/reels-editor/jobs/<job-id>/job.json` and
  `JobStore.list_recent()` already sorts historical jobs. There is no history API
  or history UI. Clearing the current snapshot intentionally keeps job files.
- Episode number is not user state. Caption generation currently derives it from
  `storyline.index + 1`; the style preset separately hard-codes the visual label
  `에피소드 1 / 1000`.
- The settings popover currently contains playback speed and LLM provider only.
  Sensitive LLM credentials are stored separately in `credentials.yaml` with
  mode 0600, providing a local pattern for a Buffer token.
- Export currently saves ready MP4 files to a user-selected folder and has no
  remote publishing state.
- Buffer's current official API is GraphQL and accepts a personal API key as a
  Bearer token. It can schedule a video post, but it does not upload a local video
  file: the video must already exist at a stable, direct, public HTTPS URL until
  publication. This creates a required media-hosting decision.
- Text hooks are currently constrained to at most 14 non-space Korean characters,
  targeting 6–12, through a shared prompt and validators used in both candidate
  analysis and script generation.
- Caption generation requires an exact `Ep N.` prefix, 350–1,200 characters, at
  least five blank-line-separated paragraphs, a question paragraph, and an exact
  CTA. On final validation failure it writes
  `instagram_caption_raw_sN.txt`; no such dump exists for the screenshot's stored
  job. Exceptions are returned over HTTP but are not persisted in the job, so the
  historical failure detail cannot be reconstructed from the screenshot/job JSON.
- The screenshot's matching job is ready and has no persisted caption or job/
  storyline error. The active job pointer is currently empty.

## Constraints

- Preserve local-first processing and do not expose API tokens to the React client.
- Buffer token must be entered in settings and stored securely outside source
  control.
- Existing user job files need backward-compatible loading.
- User-facing UI strings are Korean; TypeScript is strict; new behavior needs tests.
- Final implementation must use isolated worktrees/branches for parallel agents,
  then be integrated and verified on the main workspace.
- Deep Interview remains active: no implementation or worktree creation until the
  interview is crystallized and the user selects an implementation handoff.

## Unknowns and human decisions

- Whether Buffer scheduling must publish the actual rendered MP4 or may create a
  draft/queue item without hosted video.
- Which public media-hosting mechanism is acceptable for Buffer and its retention/
  deletion policy.
- Target Buffer channels/platforms, queue-vs-exact-time behavior, caption source,
  and batch behavior.
- Exact meaning and lifecycle of an episode number (per job, per selected reel,
  auto-increment, visual overlay, caption, filename, and archive metadata).
- Whether history means open/read-only, resume/edit, re-export/re-schedule, delete,
  search/filter, or some bounded subset.
- Exact hook counting/wrapping semantics, including spaces, Latin text, punctuation,
  and acceptable min/max length.
- Exact observed caption error message and repeatable trigger, which are not present
  in the screenshot or persisted job.
- Non-goals and which product/design decisions the agents may make autonomously.

## Likely touchpoints

- `desktop/ui/src/main.tsx`, `desktop/ui/src/styles.css`
- `reels_editor/desktop/server.py`
- `reels_editor/jobs/models.py`, `store.py`, `service.py`
- `reels_editor/youtube.py`, `reels_editor/config.py`
- `reels_editor/instagram_caption.py`
- `reels_editor/candidate_analyzer.py`, `reels_editor/storyteller.py`
- `prompts/text-hook-principles.md`
- corresponding tests and dashboard visual checks

## Inspected sources

- `README.ko.md`, `CONTRIBUTING.md`
- the files listed under likely touchpoints
- current persisted job summaries and the screenshot-matching job
- official Buffer API authentication, posts/scheduling, video-post, and
  media-hosting documentation

## Terminology conflicts

- “검색창” appears to mean the YouTube URL input, not a search API.
- “자동 예약 업로드” could mean Buffer queue insertion or a user-chosen exact
  publish time; these are distinct API modes.
- “과거 릴스 보관” could mean surfacing already-persisted jobs rather than moving
  or duplicating video files.
