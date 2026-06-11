"""Near-duplicate detection via SimHash clustering."""

import sqlite3
import re
import hashlib
from typing import Dict, List, Tuple


class UnionFind:
    """Union-find data structure for clustering."""

    def __init__(self, n: int):
        self.parent = list(range(n))
        self.rank = [0] * n

    def find(self, x: int) -> int:
        if self.parent[x] != x:
            self.parent[x] = self.find(self.parent[x])
        return self.parent[x]

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px == py:
            return
        if self.rank[px] < self.rank[py]:
            px, py = py, px
        self.parent[py] = px
        if self.rank[px] == self.rank[py]:
            self.rank[px] += 1


def dedup_articles(conn: sqlite3.Connection) -> int:
    """
    Near-duplicate detection via SimHash.
    Returns number of dedup clusters created (size >= 2).
    """
    # Load all articles without dedup_cluster_id set
    cursor = conn.execute(
        """
        SELECT id, body FROM article WHERE dedup_cluster_id IS NULL
        ORDER BY id
    """
    )
    articles = cursor.fetchall()

    if len(articles) < 2:
        return 0

    article_ids = [row[0] for row in articles]
    bodies = [row[1] for row in articles]

    # Compute SimHash for each article
    hashes = [_simhash(body) for body in bodies]

    # Cluster articles with Hamming distance <= 6
    n = len(articles)
    uf = UnionFind(n)

    # Banded bucketing: partition hash space into 4 bands of 16 bits
    # For each band, articles with same bucket are candidates
    buckets: Dict[Tuple[int, str], List[int]] = {}
    for i, h in enumerate(hashes):
        for band in range(4):
            bucket_bits = _get_band_bits(h, band)
            bucket_key = (band, bucket_bits)
            if bucket_key not in buckets:
                buckets[bucket_key] = []
            buckets[bucket_key].append(i)

    # Within each bucket, compare Hamming distances
    for idx_list in buckets.values():
        for i in range(len(idx_list)):
            for j in range(i + 1, len(idx_list)):
                idx_i = idx_list[i]
                idx_j = idx_list[j]
                if _hamming_distance(hashes[idx_i], hashes[idx_j]) <= 6:
                    uf.union(idx_i, idx_j)

    # Build clusters
    clusters: Dict[int, List[int]] = {}
    for i in range(n):
        root = uf.find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(i)

    # Assign dedup_cluster_id for clusters with size >= 2
    cluster_count = 0
    for cluster_idx, (root, members) in enumerate(clusters.items()):
        if len(members) >= 2:
            cluster_id = cluster_idx + 1  # 1-indexed cluster ID
            for member_idx in members:
                article_id = article_ids[member_idx]
                conn.execute(
                    "UPDATE article SET dedup_cluster_id = ? WHERE id = ?",
                    (cluster_id, article_id),
                )
            cluster_count += 1

    conn.commit()
    return cluster_count


def _simhash(text: str) -> int:
    """Compute 64-bit SimHash from text via 5-word shingles."""
    text = _normalize_text(text)
    words = text.split()

    if len(words) < 5:
        # Too short; fall back to hash of full text
        return int(hashlib.sha256(text.encode()).hexdigest(), 16) & ((1 << 64) - 1)

    # Extract 5-word shingles
    shingles = []
    for i in range(len(words) - 4):
        shingle = " ".join(words[i : i + 5])
        shingles.append(shingle)

    # Hash each shingle and accumulate bit vector
    bit_vector = [0] * 64
    for shingle in shingles:
        h = int(hashlib.md5(shingle.encode()).hexdigest(), 16)
        for bit_idx in range(64):
            if (h >> bit_idx) & 1:
                bit_vector[bit_idx] += 1

    # Threshold: if bit appears in > half the shingles, set it
    threshold = len(shingles) / 2
    result = 0
    for i in range(64):
        if bit_vector[i] > threshold:
            result |= 1 << i

    return result


def _normalize_text(text: str) -> str:
    """Lowercase, remove punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[^\w\s]", "", text)  # Remove non-word chars
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _get_band_bits(h: int, band: int) -> str:
    """Extract 16-bit band from 64-bit hash as hex string."""
    # Band 0: bits 0-15, Band 1: bits 16-31, etc.
    start = band * 16
    mask = (1 << 16) - 1
    bits = (h >> start) & mask
    return format(bits, "04x")


def _hamming_distance(h1: int, h2: int) -> int:
    """Hamming distance between two 64-bit integers."""
    xor = h1 ^ h2
    return bin(xor).count("1")
