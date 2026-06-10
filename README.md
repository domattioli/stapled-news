# stapled-news

Infer latent truth from multi-outlet news coverage via statistical inference. The system generates ground-truth-labeled synthetic news corpora, validates them statistically, runs STAPLE-like EM inference to estimate event states and outlet reliability/bias, and exports results as a static site.

## Pipeline Overview

```
RSS Feeds → Articles → Claims → Event Alignment
                                      ↓
                          Synthetic Corpus Generation
                                      ↓
                    Corpus Validation (chi-squared, vocab, bias)
                                      ↓
                    EM Inference (Dawid-Skene)
                                      ↓
                    Recovery Scoring (accuracy, rank correlation)
                                      ↓
                    Stage Gate: Real Data Blocked Until PASS
                                      ↓
                        Static Site Export → GitHub Pages
```

## Quick Start (Synthetic Recovery)

Validate the inference method on synthetic data without any real articles:

```bash
# Setup
git clone https://github.com/domattioli/stapled-news
cd stapled-news
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Pipeline
stapled synth generate --config configs/synth-baseline.yml --seed 42
stapled synth validate --corpus 1
stapled infer --synthetic --corpus 1
stapled score --run 1
stapled export --run 1 --out docs/
```

**Expected results** (with configs/synth-baseline.yml, seed 42):
- State accuracy: ≥ 85%
- Reliability rank correlation: ≥ 0.8
- Liar outlet (tabloid-mirror, seeded at 0.1 reliability) ranks last
- Recovery verdict: **PASS**

Wall-clock time: ~2–5 minutes on typical hardware.

## Database

Single-file SQLite database (`stapled.db`, git-ignored):

- **outlet**: News sources with reliability, bias, calibration estimates
- **article**: Raw texts from outlets (or synthetic)
- **claim**: Extracted actor-action-object assertions with framing metadata
- **event**: Disputed assertions with inferred true states
- **corpus**: Synthetic datasets with seeded ground-truth parameters
- **inference_run**: Immutable EM execution records
- **run_event_result**: Inferred states, confidence, corroboration labels per run
- **run_outlet_result**: Estimated reliability, bias, calibration per outlet per run
- **recovery_report**: Score of inference vs ground truth (synthetic only)

## Commands

```bash
stapled synth generate --config FILE --seed N     # Generate synthetic corpus
stapled synth validate --corpus ID                # Validate corpus (chi-squared, vocab, bias)
stapled infer --synthetic --corpus ID             # Run EM (gated on corpus PASSED)
stapled infer --real --event-ids 1,2,3            # Real-data inference (gated on recovery PASS)
stapled score --run ID                             # Score synthetic run vs ground truth
stapled export --run ID --out docs/               # Export to static HTML + JSON
stapled status                                     # Show database state and gate status
stapled --version                                 # Show version
stapled --help                                    # Show all commands
```

## Output

`stapled export` produces:

- **run.html**: Clean HTML report with event inferred states, confidence, corroboration, outlet parameters
- **index.html**: Directory of all runs
- **run.json**: Machine-readable schema (events, outlets, gates)

All output committed to `docs/` and deployed to GitHub Pages on push to `main`.

## Testing

```bash
pytest                                  # All tests
pytest tests/unit -q                   # Unit tests only
pytest tests/integration -q             # Integration tests
pytest tests/integration -k recovery    # Recovery pipeline test (SC-001..003, SC-006)
```

## Configuration

### Synthetic corpus (synth-baseline.yml)

```yaml
outlets:
  - name: "reliable-press"
    reliability: 0.9
    bias: -0.1
    calibration: 1.0
  # ... more outlets ...

n_events: 20
articles_per_event_per_outlet: 1
```

- **reliability**: P(outlet reports correctly) ∈ [0, 1]
- **bias**: Direction/magnitude of systematic error ∈ [-1, 1]
- **calibration**: How well outlet's certainty matches accuracy ∈ (0, ∞)

### RSS feeds (feeds.yml)

Placeholder for real-data ingestion (not MVP scope):

```yaml
outlets:
  - name: "example-news"
    feed_url: "https://example.com/rss.xml"
```

## Outlet Bias Estimates

**Important**: Bias and reliability estimates are statistical artifacts of the EM model, not editorial judgments. They reflect systematic correlation patterns in the corpus and do NOT imply malice, intentional distortion, or editorial bias in a normative sense. They are outputs of a noisy-annotator model and should be interpreted with domain expertise.

## Stage Gates

1. **Corpus Validation Gate**: Real-data inference blocked until synthetic recovery test passes (verdict=PASS)
2. **Export Gate**: Cannot export runs with status ≠ 'converged' or without recovery PASS (synthetic)

Gates enforced in code, never bypassed by documentation.

## Implementation Notes

- **Language**: Python 3.11+
- **Core deps**: typer, numpy, scipy, jinja2, pyyaml
- **Dev deps**: pytest, ruff
- **Scale target**: Research scale (hundreds of articles, tens of outlets, dozens of events)
- **EM algorithm**: Dawid-Skene binary with per-outlet sensitivity/specificity, certainty tempering, label-switching detection, degeneracy checks

## Project Structure

```
src/stapled/
├── cli.py                  # typer CLI
├── db.py                   # SQLite schema + migrations
├── gates.py                # Stage gates
├── infer/                  # EM engine
├── synth/                  # Synthetic generation + validation
├── recover/                # Recovery scoring
└── export/                 # Static site rendering (Jinja2 templates)

tests/
├── unit/                   # Schema, gates, EM unit tests
└── integration/            # End-to-end recovery pipeline tests

.github/workflows/
├── ci.yml                  # Ruff + pytest on push
└── pages.yml               # Deploy docs/ to GitHub Pages
```

## Troubleshooting

**Recovery score below threshold**: Check seed variability, outlet reliability spread in config. Baseline uses seed 42 and reliabilities ranging 0.1–0.9; adjust if needed.

**Corpus validation fails**: Check that articles have diverse vocabularies and outlets report with varied outcomes. Degenerate corpus (all outlets identical) will be rejected.

**EM doesn't converge**: Large uncertainty or conflicting claims. Try increasing max_iter in RunConfig or examining outlet parameter seeds.

## Citation

If you use stapled-news in research, cite:

> Inference engine based on STAPLE (Warfield et al., 2004) and Dawid-Skene (1979) models for latent truth discovery from unreliable sources.