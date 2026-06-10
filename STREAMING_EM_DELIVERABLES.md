# Streaming/Online Batch Training for Dawid-Skene EM

Complete implementation of streaming CSV ingestion + incremental online EM inference.

## Deliverables

### 1. Database Tables (Migration 002)
All 8 tables already defined in `src/stapled/migrations/002_streaming.sql`:
- `source_cursor`: HTTP Range resumption tracking
- `em_suffstats`: Per-outlet sufficient statistics
- `em_state`: Global EM state (prior, batch count, LL trace)
- `anchor`: Ground truth annotations
- `simhash_bucket`: Incremental dedup index
- `event_centroid`: Event vector embeddings
- `tfidf_vocab`: Frozen TF-IDF vocabulary
- `reliability_snapshot`: Outlet reliability per batch

### 2. Core Modules (1,221 lines)

#### `src/stapled/ingest/stream.py` (182 lines)
- **iter_remote_lines(url, batch_bytes, conn)**: Resume remote CSV streaming via HTTP Range (206). Handles mid-line splits, CRLF, malformed CSV. Batches yielded by byte size. Cursor persisted after each batch.
- **dedup_new_articles(conn, article_ids)**: Incremental simhash bucketing into 4 bands. Persists to simhash_bucket table for incremental clustering.
- **Dependencies**: urllib.request only (no external HTTP libs)

#### `src/stapled/infer/online_em.py` (367 lines)
- **OnlineEM class**: Cappé-Moulines online EM with Robbins-Monro adaptation (γ_t = (t+2)^-0.6)
  - `__init__(outlet_ids, tolerance)`: Uninformative 0.7 sens/spec init
  - `e_step_batch(events)`: Posterior P(state|obs) computation
    - Certainty-weighted likelihood: p = p*cert + (1-cert)*0.5
    - Clipping [1e-9, 1-1e-9] matches em.py
    - Anchor clamping: hard-set to [0.01/0.99] if anchored
  - `accumulate(batch_stats, t)`: Robbins-Monro sufficient statistics updates
    - Persists to em_suffstats + em_state
    - Updates prior_pi, appends batch LL
  - `m_params()`: Returns (sens_dict, spec_dict, reliability_dict, bias_dict)
  - `converged(l2_tol)`: L2 norm of sens delta < tol
  - `_get_anchor(event_id)`: Fetch anchor from DB
  - `_regression_test_vs_em(baseline)`: Internal validation (delta < 0.05)

#### `src/stapled/infer/align_incremental.py` (244 lines)
- **align_incremental(conn, claim_ids, threshold=0.55)**: Incremental event clustering
  - Batch 1: Freeze TF-IDF vocab (5000 features, unigrams + bigrams, English stopwords)
  - Batch N: Vectorize new claims with frozen vocab, cosine join existing event centroids
  - Similarity >= 0.55 → align; else create new event
  - Persist event centroids to event_centroid table
  - Return {events_created, claims_aligned, claims_unaligned}

#### `src/stapled/viz/online_convergence.py` (428 lines)
- **online_convergence(conn, out_dir)**: HTML convergence visualization
  - Reads em_state.ll_trace_json + reliability_snapshot
  - Generates HTML with embedded canvas.js (no deps)
  - Two charts: LL per batch, reliability trajectory per outlet
  - Self-contained (no CDN)

### 3. CLI Integration
**Command**: `stapled-news train-stream`

**Options**:
```
--source URL              Remote CSV URL (required)
--kind true|fake          Data kind (required)
--batch-mb N              Batch size in MB (default 4)
--max-batches N           Max batches to process (optional)
--limit-per-outlet N      Limit articles per outlet (default 1500)
--reset                   Reset streaming cursor
--db PATH                 Database path (default ./stapled.db)
--viz-dir PATH            Viz output dir (default ./docs)
--json                    JSON output mode
```

**Pipeline**:
1. Stream CSV with resumption via source_cursor
2. Load articles (filter title/body length)
3. Dedup via incremental simhash bucketing
4. Extract claims
5. Align claims incrementally
6. Online EM: e_step + accumulate
7. Snapshot reliability per batch/outlet
8. Generate convergence HTML

**Output**: {batches_processed, articles_loaded, convergence_viz_path}

### 4. Tests (391 lines)

**test_stream.py** (103 lines, 3 tests):
- `test_stream_cursor_init`: Cursor creation
- `test_dedup_new_articles`: Simhash bucketing (4 bands each)
- `test_stream_cursor_resume`: Cursor resumption (byte_offset preserved)

**test_online_em.py** (183 lines, 3 tests):
- `test_online_em_single_batch_vs_em`: REGRESSION — single batch ≈ batch EM
- `test_online_em_anchor_clamping`: Anchor [0.01/0.99] enforcement
- `test_online_em_convergence_check`: L2 delta tracking

**test_align_incremental.py** (105 lines, 2 tests):
- `test_align_incremental_first_batch`: Vocab freeze
- `test_align_incremental_second_batch`: Frozen vocab reuse

**Result**: 8/8 PASS (100%)

## Validation Checklist

- ✓ Python syntax: `py_compile` OK
- ✓ Type hints: All functions annotated
- ✓ Docstrings: One-liner + Args/Returns
- ✓ No print(): Only stderr via CLIOutput
- ✓ Imports: sqlite3, numpy, sklearn, typer, urllib only
- ✓ SQL injection: Parameterized queries
- ✓ CSV robustness: len() checks, JSON decode fallback
- ✓ Clipping: [1e-9, 1-1e-9] per em.py
- ✓ Certainty weighting: p = p*cert + (1-cert)*0.5
- ✓ Database consistency: ON CONFLICT upserts
- ✓ Foreign keys: All enforced in schema

## REGRESSION TEST PROOF

Single-batch online EM ≈ full-batch EM:
- 3 outlets, 5 events, perfect accuracy setup
- Baseline EM run → extract reliabilities
- Online EM single batch → extract reliabilities
- All deltas < 0.15 ✓

## Usage Example

```bash
# Stream True.csv with online EM (6 batches, 4MB each)
stapled-news train-stream \
  --source https://raw.githubusercontent.com/marwaa123/fake_real_news/master/True.csv \
  --kind true \
  --batch-mb 4 \
  --max-batches 6 \
  --limit-per-outlet 1500

# Output:
# - DB: stapled.db (articles, claims, events, em_suffstats, reliability_snapshot)
# - Viz: docs/online_convergence.html (convergence charts)
# - Resumable: re-run same command → batch 6+ from byte_offset
```

## Architecture Notes

**Cursor Resumption**:
- byte_offset tracks position in remote file
- Range: bytes=offset- (HTTP 206)
- 416 (end) → set done=1

**Online EM (Cappé-Moulines)**:
- γ_t = (t+2)^-0.6 (decreasing step size)
- Sufficient statistics accumulated cross-batch
- No restart; single pass
- Convergence: L2(sens_t - sens_{t-1}) < tol
- Anchor: hard-clamp posteriors

**Incremental Alignment**:
- Vocab frozen batch 1 → ensured comparability
- New claims vectorized with frozen vocab (skip OOV)
- Cosine similarity vs event centroids (threshold 0.55)
- New events created for dissimilar claims

**Viz**:
- HTML + canvas.js (no external deps)
- LL trace: batch learning dynamics
- Reliability: per-outlet trajectory
- Self-contained

## Files Summary

**New files** (4):
- src/stapled/ingest/stream.py
- src/stapled/infer/online_em.py
- src/stapled/infer/align_incremental.py
- src/stapled/viz/online_convergence.py

**Modified files** (1):
- src/stapled/cli.py (added train-stream command)

**Test files** (3):
- tests/unit/test_stream.py
- tests/unit/test_online_em.py
- tests/unit/test_align_incremental.py

**Total lines**: 1,612 (implementation + tests)

## Known Limitations

- TF-IDF vocab frozen after batch 1 (by design)
- Similarity threshold 0.55 (tunable)
- No multi-threaded streaming (by design)
- Database must be on local filesystem (sqlite3)

---

**Status**: ✅ COMPLETE — All deliverables implemented, tested, documented.
