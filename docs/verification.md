# Standalone verification contract

The desktop app and `reels-editor render` use `JobService` without loading another application's Python modules, SQLite profiles or media assets.

## Generation and source evidence

`candidate_analyzer.py` validates ten distinct proposals against source segment IDs. `opening_hook.py` verifies opening quotations against consecutive selected source captions, restoring nearby omitted IDs only when the complete quote is verbatim and overlaps the selected evidence. Instructions embedded in transcripts are data, not model commands.

`storyteller.py`, `edl.py`, `topic_edges.py` and `speaker_identity.py` preserve source order, complete utterances, factual translation and evidence-backed speaker identity. A fixed clip length must not override meaning. Generated titles must not introduce unsupported quantities. Failed identity lookup does not establish an identity.

## Measured subtitles and effects

`caption_timing.py` extracts the selected speech with the same audio recipe used by rendering. A local MLX Whisper worker measures words. The alignment model maps semantic caption units to measured word indices. Code rejects missing or duplicate text, stale signatures, unsupported timings, excessive reading speed and overlapping cues. Character-count proportional timing is not accepted.

Alignment receives frozen translation tokens and returns token/word end indices and bounded holds. Display text and consecutive start indices are reconstructed locally, so the timing response cannot rewrite the translation. Legacy text-based plans remain validated for complete, unchanged content. Korean, English and Chinese use the same preservation contract.

Completed scripts stream into up to two rendering workers without waiting for the slowest script. Selected order and completed rows remain stable. Generation and final review have separate single-request AI queues and Codex slots, sharing the same cancellation and usage-limit circuit. A quota failure stops new requests in both queues; requests already in flight may finish. Optional render endings are concatenated in the final filter graph before a single encode, including for legacy cached render assets.

`hook_effects.py` selects an eligible emphasis word in the opening three seconds. It preserves ASR timing and any bounded waveform-onset refinement. The effect zooms to 130% over 0.1 seconds, holds for 0.65 seconds and returns over 0.18 seconds. The packaged 320 ms procedural wind sound is aligned by its peak. Video overlays remain fixed.

## Independent final review

`quality_review.py` analyzes the actual rendered MP4: full audio, tail or flagged audio windows, word timing, waveform/signal measurements, source boundary evidence, final frames and corresponding source frames. Programmatic checks and independent Claude/Opus review must both pass.

Required checks are:

- `topic`, `translation`, `caption_timing`
- `hook_audio`, `hook_caption`, `readability`, `framing`
- `hook_zoom`, `hook_whoosh`

Every required check needs concrete evidence. Substantiated major defects block output; explicit minor findings remain warnings, with original advisory verdicts retained. Missing checks, unexplained failures and malformed evidence cannot approve output. A sampled-frame observation may use a single timestamp: the parser preserves it and expands it by up to 40 ms on either side within the video. Reversed or out-of-range timestamps still fail. The reviewer does not directly hear audio, and ASR time estimates are not a guarantee of perceptual accuracy.

Failed review can trigger at most one repair cycle per run. Changes are source-grounded, retimed, rerendered and reviewed again. Old repair feedback is reusable only when both the review policy version and actual render recipe match. Retry retains the latest valid script and prior attempt evidence; it does not fabricate an approval.

Review version 8 treats isolated ASR boundary-word disagreement as uncertainty, preserving it for independent semantic review rather than treating text mismatch as proof of missing speech. Broad word loss (matching coverage below 85%), large measured timing errors, silent/clipped audio and independently identified material defects continue to block. Tail/window ASR runs only for blocking audio diagnostics. Identical final WAV hashes and languages share an ASR cache across repair attempts; changed audio is transcribed again. Final MP4 checks and independent visual review still run for every changed video. Previously approved version 6/7 videos remain exportable only under the same complete checks and exact-byte hash contract.

## Completion, edits and exports

`require_approved_video` rejects incomplete approval contracts or video bytes that differ from the reviewed SHA-256. `JobService._render_with_quality_gate` calls it before registering a ready video.

Title/metadata and subtitle-overlay changes produce a new MP4. `_review_changed_variant` validates and reviews it before replacing the active variant. If a title edit fails, the prior active video and script approval are restored.

`_copy_export_variant` checks approval before export and checks the staged copy before committing the destination. Both single and batch exports use this path. Legacy jobs with no complete matching approval are rejected; regenerate them with current verification.

## Output languages and isolation

`output_language` is `ko`, `en` or `zh`. It is validated in configuration and the API, persisted on the job, and propagated to candidates, scripts, subtitles, captions, repairs and review. Source caches remain reusable across languages; analysis prompts include language so generated candidate caches differ. Each job retains its own language during concurrent work and retries. Chinese text is not forced into Korean word-spacing rules.

Resources live inside `reels_editor/resources/` and are included in wheels and the desktop bundle. The public video and thumbnail templates show neither a company logo nor an episode number. Fonts carry SIL OFL 1.1; the opening sound is procedural audio under the project license.

## Tests and limits

`tests/test_standalone.py` checks all three languages, API/config/job round trips, translation directions, retry propagation, missing/uncertain/stale approval, changed-file export refusal and failed-edit rollback. Existing timing, effects, review and service tests cover bounded repairs and exact-file completion. Real FFmpeg integration tests check media encoding and audio recipes. The dashboard test checks three viewport widths and the actual language-bearing creation request.

Automated model tests use substitutes and do not prove that every source will pass online model review. Runtime generation currently requires Apple silicon macOS, authenticated Codex and Claude/Opus, and an accessible captioned source. A failed live verification remains failed.
