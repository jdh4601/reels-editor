# Candidate generation validation and recovery

A YouTube title or channel does not guarantee that the transcript contains a
speaker's company or job title. Missing roles must permit a name-only label;
unsupported role claims are removed rather than invented or retried indefinitely.

Selected candidate titles have already passed candidate analysis validation and
are used for the final overlay. Unused generated title alternatives must not block
the corresponding EDL. CLI generation still validates its generated titles.

Recovery validates the cached response first. If it is invalid, subsequent
attempts request a fresh response with validation feedback and the selected
candidate brief. Selected candidate recovery applies the same 20–40 second
bounds as initial generation.

Verified on 2026-10-06 with the failed Chamath video job: all five selected clips
were recovered to 1080×1920 H.264/AAC MP4 files. Regression tests cover name-only
speaker labels, fixed candidate titles, and fresh responses after invalid cache.

Missing roles now trigger a dedicated Codex CLI live web search before desktop
rendering. The returned source URL is fetched independently; the exact quote,
source person name, company and role must be supported by the page. Public HTTPS
sources are required, including on redirects. Search errors retain the name-only
label and are recorded in `speaker_lookup.json` without failing video generation.
Verified results are cached per video context for 30 days, failed lookups for five
minutes. Persisted speaker data includes the source URL, source name, and check
time; rerendering updates the saved EDL and uses the enriched speaker in the
render cache key.
