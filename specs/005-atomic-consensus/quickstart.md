# Atomic Consensus Quickstart

This is a design contract for the planned implementation. It does not change
the existing legacy consensus commands.

## Frozen analysis

1. Freeze corpus revision and analysis cutoff.
2. Assign `aspect-taxonomy-v1`; multi-aspect/ambiguous headlines abstain as
   `unknown_aspect`.
3. Build event-specific reporting groups and allocate cross-stratum families to
   one home stratum; retain alternate allocation sensitivity.
4. Establish event/aspect eligibility before any SCU mention scoring.
5. Run deterministic `atomic-grammar-v1` extraction; inspect abstentions and
   exact spans.
6. Match compatible occurrences within event/aspect; emit rule evidence.
7. Build separate coverage and SCU observations; mask structural absence.
8. Compute raw outlet/group support, balanced support, missing-mass bounds,
   effective sample size, and
   leave-group/stratum sensitivity.
9. Apply labels using the frozen threshold and independent-strata rule.
10. Optionally run held-out-anchored categorical estimator with persistent
    outlet/source parameters and unseen-source prior fallback.
11. Validate canonical hash/digests and export atomic JSON beside legacy outputs.

Suggested future CLI shape:

```text
stapled atomic extract --db us.db --run-config CONFIG
stapled atomic match --run RUN_ID
stapled atomic summarize --run RUN_ID
stapled atomic evaluate --run RUN_ID --annotations ANNOTATIONS
stapled atomic export --run RUN_ID --out docs/
```

## Required pilot/evaluation order

Planned annotation budget: 20 pilot events + 80 held-out events. Record actual
annotated/adjudicated counts and ownership. Freeze parser, aliases, taxonomy,
matching rules, thresholds, panel, estimator prior, and paired metrics after
the pilot. Evaluate once on 80 disjoint held-out events. Do not tune on held-out
results; underpowered or below-minimum-conflict results are `inconclusive`.

## Verification checklist

- Repeat two clean pinned CPU runs; canonical JSON bytes and hash match.
- Duplicate known syndicated headlines; balanced support and effective sample
  size stay unchanged.
- Remove a target stratum; missing mass widens bounds or yields `insufficient
  panel`, never zero-support votes.
- With zero eligible groups, balanced support is `null`, bounds are `[0,1]`, and
  effective N is `0`.
- Confirm exact source spans resolve to original headlines.
- Confirm attribution remains qualified (`reported`/`alleged`), not unqualified.
- Confirm non-coverage, collector failure, unknown relevance, and omission stay
  distinct.
- Keep descriptive `unknown` visible but mask it, structural absence, and all
  non-eligible states from categorical estimation.
- Run `pytest`, `ruff`, existing `test_consensus.js`, `npm run check`, and site
  build after implementation lands.

## Website integration

The source export remains in `stapled-news/docs/`. Website work runs from the
absolute sibling workdir `/Users/domattioli/Projects/domattioli.github.io`.
Extend the fetched static bundle and add an atomic-consensus view under
`/vault/stapled-news/app/`. Keep legacy centroid pages and fields visible; label
atomic results as reported-proposition analysis. Pin immutable upstream ref +
40/64-char commit SHA, show cutoff/source SHA, validate schema and SHA-256
artifact digests, and define browser loading/error/empty/oversized-payload
states. Update vault copy only after verified export. Fetch must fail loudly.
