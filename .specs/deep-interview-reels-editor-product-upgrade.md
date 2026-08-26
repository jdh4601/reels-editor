# Specification: Reels Editor product upgrade

## Intent

Make the existing Reels Editor desktop app feel like a coherent, reusable local
production tool: the source should be visually identifiable, episode identity
should be set once and carried through every output, completed work should be easy
to find later, and generated reel titles should remain editable without returning
to the full cutting workflow.

## Desired outcome

A user can paste a YouTube URL, recognize its thumbnail, select an episode number,
generate one or more reels that consistently carry that episode, correct a finished
reel's title through the dashboard, and find the durable MP4 later from both a
top-level archive and a predictable `~/Movies/Reels Editor/` folder.

## In scope

### Branding and source input

- Place the existing Reels Editor logo at the far upper-left, immediately beside
  the `Reels Editor` text. Reuse an existing repository asset unless a technical
  packaging constraint requires a derived copy.
- When a valid supported YouTube URL is entered, show that video's thumbnail
  immediately to the left of the URL input. Handle common `youtube.com` and
  `youtu.be` forms. An invalid, incomplete, or unavailable URL must not leave a
  stale thumbnail from a previous URL.

### Episode selector and propagation

- Put an accessible numeric episode selector adjacent to the YouTube URL controls.
- The selector is job-level: one selected positive integer applies to every
  candidate/reel created by that analysis job.
- Persist the episode number in the job model and API payloads with backward-
  compatible defaults for existing jobs.
- Render the selected number in the video as `에피소드 N` and use the same value in
  the Instagram caption prefix `Ep N.`.
- The episode value also participates in archive folder naming.

### Completed-reels archive and fixed export

- Add a top-level `과거 릴스` button and archive view.
- Show only jobs with at least one completed, playable reel. Do not show analysis-
  only, failed-only, or cancelled-only jobs.
- Each archive entry should expose enough identity to choose the correct work:
  thumbnail or playable preview, episode, source/project title, reel title, and a
  useful completion date.
- Opening an archived reel supports playback, caption generation/copy, and exporting
  it again.
- Create and use the fixed root `~/Movies/Reels Editor/`.
- Store each completed reel under an `Ep-번호_영상제목/` directory. Sanitize unsafe
  path characters and resolve collisions without overwriting a different reel.
- Treat the durable MP4 under this root as the archive copy. Keep internal job data
  needed for playback, caption generation, and re-export.
- Preserve existing saved jobs. If existing completed jobs are imported into the
  new archive, migration must be non-destructive and idempotent; implementation may
  choose eager or lazy migration.
- The normal export action no longer asks for an arbitrary destination. It writes
  to the fixed archive hierarchy and clearly reveals the completed path in the UI.

### Text-hook generation, layout, and manual correction

- Apply one shared rule to generated and manually edited on-video titles:
  - count Unicode display characters after excluding whitespace;
  - allow 6–24 counted characters;
  - use one line for 6–11 characters;
  - use two lines for 12–24 characters.
- Generated titles should prefer the two-line range while remaining factual and
  compact; the one-line range remains valid when it is the stronger title.
- Two-line wrapping must split at a natural word/phrase boundary when one exists and
  must never emit an empty line.
- Render the reel title in orange.
- In every completed-reel card, replace the read-only `화면 제목` presentation with
  an editable text field/window and an explicit `수정하기` action.
- Validate before saving and show a useful inline error for a title outside 6–24
  counted characters.
- On `수정하기`, persist the new title and re-render the title-bearing video overlay
  so the playable/archive MP4 visibly changes. Do not re-download the source or
  regenerate the cut/story script.
- The UI must expose progress and a recoverable error if this overlay render fails;
  the previously playable output must not be destroyed by a failed update.
- Future caption generation uses the edited title. The implementation may invalidate
  a previously generated caption when needed to avoid stale title text.

### Speaker label normalization

- Render the speaker line below the orange title.
- Preferred forms are `이름 (기업이름 창업자)` and `이름 (기업이름 CEO)`.
- Normalize equivalent script-provided role text into those Korean forms when the
  evidence is explicit.
- When company/title data is unavailable, use another identity only if directly
  stated in the script, such as `이름 (투자자)` or `이름 (연쇄 창업가)`.
- If no grounded descriptor exists, show only the name.
- Never invent the company, role, or descriptor and do not perform an external web
  search to fill it.

### Verification and integration

- Add Python tests for model migration, episode propagation, archive filtering and
  paths, safe export, title validation/re-render behavior, and speaker fallbacks.
- Add TypeScript/build and dashboard visual coverage for logo, thumbnail, selector,
  archive view, and title editing at supported window sizes.
- Perform implementation in isolated worktrees/branches through parallel agents,
  integrate the changes, resolve conflicts against this specification, and run the
  repository's relevant Python, TypeScript, build, and visual checks.

## Non-goals

- Buffer API integration, Buffer token settings, public media hosting, and any other
  automatic social upload or scheduling.
- Debugging or changing Instagram caption generation solely for the previously
  reported error; the user confirmed it works.
- Showing failed, cancelled, or analysis-only work in the archive.
- Re-analyzing, regenerating story scripts, retrying failed jobs, or deleting work
  from inside the archive in this version.
- External person/company lookup.
- Changing the fixed `~/Movies/Reels Editor/` root without confirmation.

## Decision boundaries

### Agent may decide

- Detailed component layout, responsive behavior, icon choices, accessible labels,
  and empty/loading/error presentation consistent with the current visual language.
- Internal API shapes, module boundaries, migrations, idempotency markers, filename
  sanitization, and collision suffixes.
- How to derive/fetch a YouTube thumbnail safely from a validated video ID.
- Exact natural wrapping algorithm within the fixed 6–24 and 12-character rules.
- Test fixtures, test organization, worktree split, branch/commit structure, and
  integration order.

### User confirmation required

- Deleting or irreversibly moving existing job/export files.
- Adding any external hosting, upload, scheduling, analytics, or lookup service.
- Changing the fixed export root or the agreed user-visible behavior.
- Weakening evidence requirements for speaker metadata or expanding archive actions.

## Constraints

- Continue supporting the local macOS desktop app, Python 3.11+, strict TypeScript,
  and existing persisted job JSON.
- User-facing UI text is Korean; code/comments/commits follow repository conventions.
- Preserve local-first behavior. Normal thumbnail retrieval from YouTube is allowed
  as part of handling the user-entered source URL; no unrelated lookup is allowed.
- Never expose credentials in the browser or repository. This version adds no new
  credential because Buffer is deferred.
- Work around and preserve unrelated user changes in every worktree.
- New behavior requires tests, and dashboard changes require visual inspection.

## Acceptance criteria

1. Given a clean launch, the logo renders at the far upper-left beside `Reels
   Editor` without shifting the top actions out of the viewport at every dashboard
   test size.
2. Pasting supported long and short YouTube URLs shows the matching thumbnail to the
   left of the URL input; replacing the value with an invalid URL removes it.
3. Selecting episode 37 and generating two reels stores episode 37 on the job; both
   videos display `에피소드 37`, and both generated captions start with `Ep 37.`.
4. Existing job JSON without an episode field still loads and receives the documented
   backward-compatible default without data loss.
5. Completing a reel creates a playable MP4 below
   `~/Movies/Reels Editor/Ep-37_<sanitized-title>/` and exporting it again never
   silently overwrites an unrelated file.
6. `과거 릴스` lists that completed reel and omits fixtures that are failed,
   cancelled, or have no ready/playable reel.
7. From the archive, the user can play the reel, generate/copy its caption, and
   export it again; no delete, re-analysis, or full regeneration action is present.
8. Generated and edited titles reject fewer than 6 or more than 24 non-whitespace
   display characters. A valid 11-character title renders on one line; a valid
   12-character title renders on two non-empty lines.
9. Editing a ready reel title and pressing `수정하기` updates stored title state and
   the visible title in the resulting playable/archive MP4 without downloading the
   source or regenerating the story cuts.
10. A failed title-overlay render leaves the previous playable MP4 intact and shows
    a retryable error.
11. The title is orange. Grounded speaker data renders as `이름 (기업명 창업자)` or
    `이름 (기업명 CEO)`; transcript-grounded alternate roles and name-only fallbacks
    pass dedicated tests, and no ungrounded company/role is introduced.
12. Relevant pytest suites, UI typecheck/build, and dashboard visual checks pass
    after all worktree branches are integrated.

## Assumptions and resolutions

- “검색창” means the YouTube URL input.
- Whitespace is excluded from title length. Other displayed Unicode graphemes,
  including Latin characters and punctuation, count once; implementation may use a
  grapheme-aware library or equivalent deterministic logic.
- “모두 같은 번호” means job-level episode identity, not sequential numbering per
  selected candidate.
- The old `/ 1000` visual suffix is not part of the confirmed `에피소드 N` format.
- Completed-reel storage is durable export storage, not merely the existing internal
  render cache.
- The attached screenshots are evidence of current UI and desired placement context,
  not instruction-bearing documents.

## Pressure-test findings

- Actual Buffer scheduling is infeasible from a local-only MP4 without a public
  hosting decision. The whole feature is deferred, avoiding a misleading partial
  integration.
- Archive scope is intentionally narrow and read/reuse-oriented; destructive and
  regeneration workflows are excluded.
- Missing speaker metadata must degrade visibly instead of being inferred from
  general knowledge.

## Project evidence and terminology

- UI: `desktop/ui/src/main.tsx`, `desktop/ui/src/styles.css`
- API: `reels_editor/desktop/server.py`
- Persistence: `reels_editor/jobs/models.py`, `store.py`, `service.py`
- YouTube metadata: `reels_editor/youtube.py`
- Caption episode prefix: `reels_editor/instagram_caption.py`
- Hook generation/validation: `prompts/text-hook-principles.md`,
  `reels_editor/candidate_analyzer.py`, `reels_editor/storyteller.py`
- Rendering/style: `reels_editor/render.py`, `reels_editor/style.py`,
  `styles/done.yaml`
- Existing logo assets are under `docs/images/` and `desktop/assets/`.
- Existing jobs already persist in Application Support and `JobStore.list_recent()`
  provides the base historical ordering.

## Residual risks

- Old ready jobs may lack all metadata needed for the preferred archive identity or
  speaker format; migration must use fallbacks without blocking playback.
- Grapheme-aware counting and balanced Korean phrase wrapping need focused edge-case
  tests for punctuation, Latin names, and no-space strings.
- Overlay replacement and archive copying must be atomic to preserve the previous
  playable MP4 on interruption.
- Folder names based on editable titles require stable identity/collision handling so
  a rename does not orphan or overwrite archive files.

## Recommended handoff

Proceed with coordinated parallel execution in isolated worktrees, split along
low-overlap boundaries (UI shell/source controls; persistence/archive/export;
rendering/title/speaker rules), followed by a dedicated integration and verification
pass against this specification.
