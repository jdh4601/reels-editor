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

On 2026-10-07 the `ill76IbVuM8` job completed three of five selected clips.
One section download exited with FFmpeg code 8; the old quiet downloader did
not retain stderr, so the underlying FFmpeg error is unknown. A separate retry
of the same candidate's source range succeeded. Another candidate failed when
Codex reported `Selected model is at capacity` during validation feedback.

Section preparation now resolves fresh stream URLs for each of up to three
attempts, runs FFmpeg through the cancellable process registry, limits encoding
threads, and saves URL-redacted stderr in `download-error.txt`. Exact trimming
still re-encodes the source, and completed cache sections remain reusable.
Codex capacity errors retry the same model and prompt with bounded cancellable
backoff; unrelated failures are not retried. Every received script response is
persisted immediately, including successful responses and invalid responses
before a later transport failure. Recovery can request a fresh response when
older jobs have no response file, using their original transcript and candidate.
Regression coverage includes capacity retries, missing response recovery,
response retention, stream refresh, cancellation, and a real HTTP/FFmpeg cut.

Frame cropping now checks every decoded frame, retaining the actual FFmpeg
presentation timestamp instead of uniformly sampling five frames per second.
The `ill76IbVuM8` s3 regression had short two-shots and missed second-face
observations, which failed the old 80% two-person-window threshold. The new
planner moves to a side on the first detected wide shot or edge face, holds the
selected side through intermittent detections, and returns immediately on a
centered close-up. Identical consecutive positions merge before rendering;
face observations, rather than stateful crop decisions, are shared in version 7
analysis caches. All five clips were rerendered and their outputs verified.
The reported s3 regression inspected 947 frames; the same subtitle scene now
shows an intact face. Speaker identity is still inferred from visual signals,
so this change does not guarantee that the selected person is always speaking.
