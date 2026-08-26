# Deep Interview: Reels Editor product upgrade

- Profile: Standard
- Context: brownfield
- Rounds: 12
- Final ambiguity: 12%
- Threshold: 20%
- Context snapshot: [`.context/reels-editor-product-upgrade-20260826T021734Z.md`](../.context/reels-editor-product-upgrade-20260826T021734Z.md)

## Summary

The next version upgrades the existing local macOS desktop workflow rather than
creating a new product. It adds branded navigation, a YouTube thumbnail, one
job-level episode selector, a completed-reels archive backed by a fixed local
export directory, revised text-hook generation and wrapping, editable finished
reel titles, and evidence-grounded speaker labels. The reported caption error was
retested by the user and is no longer part of the work. Buffer publishing was
examined and deliberately deferred because its API requires stable public media
hosting; no external upload integration or Buffer token setting belongs in this
version.

Implementation is authorized to use isolated worktrees and parallel agents. The
agents may decide internal structure, detailed UI composition, backward-compatible
migration mechanics, and tests, but must request confirmation before deleting
files, adding an external service, or changing the fixed export root.

## Clarity breakdown

| Dimension | Clarity | Remaining gap |
| --- | ---: | --- |
| Intent | 0.95 | None material |
| Outcome | 0.92 | Pixel-level presentation is delegated |
| Scope | 0.91 | Collision-safe filename details are delegated |
| Constraints | 0.84 | Existing historical files require a non-destructive migration choice |
| Success | 0.86 | Exact visual snapshots may change during implementation |
| Project context | 0.92 | No relevant repository instruction file was found |

Weighted brownfield ambiguity: approximately 12%.

Readiness gates:

- Non-goals: passed
- Decision boundaries: passed
- Pressure pass: passed

## Pressure findings

- The initial request required actual scheduled Buffer publication. The follow-up
  exposed that Buffer cannot upload a local MP4 and requires a stable public URL,
  introducing hosting cost, retention, and deletion policy. The user therefore
  deferred the entire Buffer feature instead of accepting an incomplete draft-only
  integration.
- “Past reel storage” is not a request for another temporary job view. Finished
  files need a durable, predictable home under `~/Movies/Reels Editor/`, and the
  archive should surface only jobs with completed reels.
- Speaker metadata may be incomplete. The product must prefer transcript evidence
  and visibly degrade to a smaller label rather than inventing a company or title.

## Condensed transcript

1. Buffer outcome: user wanted the rendered MP4 actually scheduled, not merely a
   draft.
2. Buffer hosting pressure: after learning stable public hosting is required, user
   deferred the feature.
3. Episode scope: one number applies to every reel created in the same job.
4. Episode outputs: the same number appears in the video and the `Ep N.` caption.
5. Archive contents: show only jobs containing completed reels.
6. Archive actions: play, generate/copy caption, and export again; no re-analysis,
   re-render controls, or deletion in this version.
7. Durable storage: use `~/Movies/Reels Editor/Ep-번호_영상제목/` as the fixed
   hierarchy.
8. Caption issue: user confirmed caption generation works; debugging removed.
9. Editable titles: finished titles use the same 6–24 non-whitespace-character
   rule, one line below 12 and two lines from 12 upward.
10. Speaker labels: prefer `이름 (기업명 창업자)` or `이름 (기업명 CEO)`.
11. Speaker fallback: use another role only when directly supported by the script;
    otherwise show only the name.
12. Decision boundary: agents own implementation details; destructive changes,
    external services, and export-root changes require confirmation.

