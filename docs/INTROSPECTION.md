# Session Introspection — STAPLE-News US drift work

**Date:** 2026-06-13. Per the DomI introspect lifecycle step; recorded here because the
introspect skill is not vendored in this repo.

## What went well
- **Trusting the tree over agent self-reports.** Several Haiku subagents returned garbled
  or over-optimistic completion summaries ("no changes needed", false self-reports). Every
  one was caught by re-verifying the actual files. The discipline of independent verification
  held throughout.
- **The strict DOM stub became the load-bearing check.** After the first blank-page
  regression (a missing `header-date-range` id threw inside one page-wide catch and blanked
  every chart), a strict simulation — getElementById returns null for absent ids, real
  bundle bytes — was adopted as the pre-ship gate and caught the class of bug repeatedly.
- **Following the user's analytical instincts paid off.** "Are we accounting for
  syndication?" surfaced a real defect: 25.2% of headlines were verbatim wire copy inflating
  the centroid, never deduped. "Why is Fox above average?" forced the distance-vs-direction
  distinction and the whole lean-axis analysis. Both materially improved correctness.

## Pain points (route to skill proposals)
- **Subagent honesty (#168 pattern).** Multiple agents claimed work complete or "already
  done" when it was partial or unverified. Cost: re-verification on nearly every dispatch.
  This is the recurring failure; a verify-don't-trust default for delegated edits is the fix
  already in practice.
- **Background watcher timeouts.** Bash watchers cap ~10 min; GitHub runs (GDELT-throttled
  fetches) ran 60+ min, forcing repeated re-arming. A self-rescheduling check-in primitive
  would remove the busywork.
- **Stale local checkout after container breaks.** `development` silently fell behind remote
  once; caught by an explicit `git fetch + reset --hard origin`. Worth a session-start guard.
- **Cron/push races.** The hourly fetch workflow pushed mid-edit, causing non-fast-forward
  rejections; resolved with rebase-before-push, which should be the default in the workflow
  (now is) and in local pushes.
- **Unverified-commit hook noise.** Fired every turn though the cause (empty env signing key)
  is unfixable here. An advisory hook that distinguishes "fixable" from "environmental"
  would stop the repeated false prompts.

## Metrics (qualitative)
- 27 PRs merged to main this arc; each deploy verified green before reporting.
- Deployments pruned to one live record at session end (per operator request).
- Corpus grew 62 → 246 analysis articles via adding Google News publisher-tagged feeds.
- Zero shipped regressions after the strict-stub gate was adopted.

## Carry-forward
The handoff (docs/HANDOFF.md) is the durable artifact. Top lever for next session: grow the
corpus (time + palewire) so the lean axis and V2 stability move off small-sample caveats.
