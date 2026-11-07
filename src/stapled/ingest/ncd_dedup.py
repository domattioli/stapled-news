"""Near-duplicate detection via Normalized Compression Distance (NCD).

NCD(x, y) = (C(xy) - min(C(x), C(y))) / max(C(x), C(y)), with C the compressed
length. Candidate pairs come from MinHash LSH over 5-word shingles, so only
blocked pairs pay for one compression. Texts shorter than ``min_bytes`` (after
normalisation) are too short for NCD to be stable and use the SimHash path of
``dedup.py`` among themselves.

Writes ``article.dedup_cluster_id`` like ``dedup.dedup_articles`` does.
"""

import hashlib
import sqlite3
import zlib
from typing import Dict, List, Optional, Sequence, Set, Tuple

import numpy as np

from stapled.ingest.dedup import (
    UnionFind,
    _get_band_bits,
    _hamming_distance,
    _normalize_text,
    _simhash,
)

try:  # Python >= 3.14
    from compression import zstd as _zstd
except ImportError:  # pragma: no cover - depends on interpreter
    _zstd = None

# True when zstd was requested by default but the interpreter lacks it, so
# zlib is used instead. Reported by compressor_used().
ZSTD_AVAILABLE = _zstd is not None

# Calibrated on E2 perturbed copies; see results/ncd_calibration.json
# (produced by scripts/calibrate_ncd_tau.py).
TAU_DEFAULT = 0.29

_MINHASH_SEED = 0x5EED
_SHINGLE_WORDS = 5
_SIMHASH_MAX_DIST = 6

# Statistics of the most recent ncd_dedup call (for benchmarking only).
LAST_STATS: Dict[str, object] = {}


def compressor_used(compressor: str = "zstd") -> str:
    """Name of the compressor that will actually run for the request."""
    if compressor == "zstd":
        return "zstd" if ZSTD_AVAILABLE else "zlib (zstd unavailable, fallback)"
    if compressor == "zlib":
        return "zlib"
    raise ValueError(f"unknown compressor: {compressor!r}")


def _clen(data: bytes, compressor: str = "zstd", level: int = 3) -> int:
    """Compressed length of ``data``."""
    if compressor == "zstd" and ZSTD_AVAILABLE:
        return len(_zstd.compress(data, level=level))
    if compressor in ("zstd", "zlib"):
        return len(zlib.compress(data, max(1, min(9, level))))
    raise ValueError(f"unknown compressor: {compressor!r}")


def ncd(
    a: bytes,
    b: bytes,
    *,
    compressor: str = "zstd",
    level: int = 3,
    ca: Optional[int] = None,
    cb: Optional[int] = None,
) -> float:
    """Normalized compression distance. Pass cached ``ca``/``cb`` to skip C(x)."""
    if ca is None:
        ca = _clen(a, compressor, level)
    if cb is None:
        cb = _clen(b, compressor, level)
    cab = _clen(a + b, compressor, level)
    return (cab - min(ca, cb)) / max(ca, cb)


def _shingles(text: str) -> List[str]:
    words = _normalize_text(text).split()
    if len(words) < _SHINGLE_WORDS:
        return [" ".join(words)]
    return [
        " ".join(words[i : i + _SHINGLE_WORDS])
        for i in range(len(words) - _SHINGLE_WORDS + 1)
    ]


def _hash_family(num_perm: int) -> Tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(_MINHASH_SEED)
    a = rng.integers(1, 2**63 - 1, size=num_perm, dtype=np.uint64) * np.uint64(2) + np.uint64(1)
    b = rng.integers(0, 2**63 - 1, size=num_perm, dtype=np.uint64)
    return a, b


def _minhash_signature(text: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    base = np.array(
        [
            int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big")
            for s in _shingles(text)
        ],
        dtype=np.uint64,
    )
    with np.errstate(over="ignore"):
        mixed = base[:, None] * a[None, :] + b[None, :]  # uint64 wraps mod 2**64
    return mixed.min(axis=0)


def _check_bands(num_perm: int, bands: int, rows: int) -> None:
    if bands * rows != num_perm:
        raise ValueError(
            f"bands*rows must equal num_perm ({bands}*{rows} != {num_perm})"
        )


def candidate_pairs(
    texts: Sequence[str],
    *,
    num_perm: int = 128,
    bands: int = 32,
    rows: int = 4,
) -> List[Tuple[int, int]]:
    """MinHash-LSH candidate pairs (i < j), sorted. Deterministic (fixed seed)."""
    _check_bands(num_perm, bands, rows)
    a, b = _hash_family(num_perm)
    buckets: Dict[Tuple[int, bytes], List[int]] = {}
    for i, text in enumerate(texts):
        sig = _minhash_signature(text, a, b)
        for k in range(bands):
            key = (k, sig[k * rows : (k + 1) * rows].tobytes())
            buckets.setdefault(key, []).append(i)
    pairs: Set[Tuple[int, int]] = set()
    for members in buckets.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                pairs.add((members[x], members[y]))
    return sorted(pairs)


def _simhash_union(uf: UnionFind, indices: List[int], bodies: List[str]) -> None:
    """SimHash (Hamming <= 6) clustering among ``indices`` only."""
    hashes = {i: _simhash(bodies[i]) for i in indices}
    buckets: Dict[Tuple[int, str], List[int]] = {}
    for i in indices:
        for band in range(4):
            buckets.setdefault((band, _get_band_bits(hashes[i], band)), []).append(i)
    for members in buckets.values():
        for x in range(len(members)):
            for y in range(x + 1, len(members)):
                i, j = members[x], members[y]
                if _hamming_distance(hashes[i], hashes[j]) <= _SIMHASH_MAX_DIST:
                    uf.union(i, j)


def ncd_dedup(
    conn: sqlite3.Connection,
    *,
    compressor: str = "zstd",
    level: int = 3,
    tau: float = TAU_DEFAULT,
    blocker: str = "minhash",
    num_perm: int = 128,
    bands: int = 32,
    rows: int = 4,
    min_bytes: int = 200,
) -> int:
    """NCD near-duplicate clustering. Returns clusters created (size >= 2).

    Only articles with ``dedup_cluster_id IS NULL`` are considered. New ids are
    offset by the current MAX(dedup_cluster_id) so they never collide.
    """
    if blocker == "entity":
        raise NotImplementedError("entity blocker is not implemented")
    if blocker != "minhash":
        raise ValueError(f"unknown blocker: {blocker!r}")
    _check_bands(num_perm, bands, rows)
    compressor_used(compressor)  # validates the name

    articles = conn.execute(
        "SELECT id, body FROM article WHERE dedup_cluster_id IS NULL ORDER BY id"
    ).fetchall()
    LAST_STATS.clear()
    LAST_STATS.update(
        n_docs=len(articles),
        n_candidate_pairs=0,
        compressor=compressor_used(compressor),
    )
    if len(articles) < 2:
        return 0

    article_ids = [r[0] for r in articles]
    bodies = [r[1] or "" for r in articles]
    norm = [_normalize_text(t).encode() for t in bodies]
    n = len(articles)
    uf = UnionFind(n)

    long_idx = [i for i in range(n) if len(norm[i]) >= min_bytes]
    short_idx = [i for i in range(n) if len(norm[i]) < min_bytes]

    # NCD path: MinHash-blocked pairs among long documents.
    cache: Dict[int, int] = {}
    pairs = candidate_pairs(
        [bodies[i] for i in long_idx], num_perm=num_perm, bands=bands, rows=rows
    )
    LAST_STATS["n_candidate_pairs"] = len(pairs)
    for p, q in pairs:
        i, j = long_idx[p], long_idx[q]
        if i not in cache:
            cache[i] = _clen(norm[i], compressor, level)
        if j not in cache:
            cache[j] = _clen(norm[j], compressor, level)
        if ncd(norm[i], norm[j], compressor=compressor, level=level,
               ca=cache[i], cb=cache[j]) <= tau:
            uf.union(i, j)

    # Short documents: SimHash path among themselves.
    _simhash_union(uf, short_idx, bodies)

    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        clusters.setdefault(uf.find(i), []).append(i)

    base = conn.execute(
        "SELECT COALESCE(MAX(dedup_cluster_id), 0) FROM article"
    ).fetchone()[0]
    cluster_count = 0
    for cluster_idx, members in enumerate(clusters.values()):
        if len(members) >= 2:
            cluster_id = base + cluster_idx + 1
            for m in members:
                conn.execute(
                    "UPDATE article SET dedup_cluster_id = ? WHERE id = ?",
                    (cluster_id, article_ids[m]),
                )
            cluster_count += 1
    conn.commit()
    return cluster_count
