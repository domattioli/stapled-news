"""Near-duplicate detection via SimHash clustering."""

import sqlite3
import re
import hashlib


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

    if not articles:
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
    buckets: dict[tuple[int, str], list[int]] = {}
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
    clusters: dict[int, list[int]] = {}
    for i in range(n):
        root = uf.find(i)
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(i)

    # Join each new cluster against ALREADY-clustered articles (this function
    # only loaded WHERE dedup_cluster_id IS NULL above, so a re-ingested
    # verbatim copy of a story clustered on a prior run is otherwise invisible
    # here and would mint a second cluster id for the same wire story - mirrors
    # the banded-bucket join stream.py's dedup_new_articles does incrementally).
    existing_rows = conn.execute(
        "SELECT body, dedup_cluster_id FROM article WHERE dedup_cluster_id IS NOT NULL"
    ).fetchall()
    existing_buckets: dict[tuple[int, str], list[tuple[int, int]]] = {}
    for existing_body, existing_cluster in existing_rows:
        eh = _simhash(existing_body)
        for band in range(4):
            bucket_key = (band, _get_band_bits(eh, band))
            existing_buckets.setdefault(bucket_key, []).append((eh, existing_cluster))

    root_to_existing_cluster: dict[int, int] = {}
    root_to_existing_matches: dict[int, set[int]] = {}
    for root, members in clusters.items():
        matches = set()
        for member_idx in members:
            h = hashes[member_idx]
            for band in range(4):
                bucket_key = (band, _get_band_bits(h, band))
                for eh, existing_cluster in existing_buckets.get(bucket_key, []):
                    if _hamming_distance(h, eh) <= 6:
                        matches.add(existing_cluster)
        if matches:
            root_to_existing_cluster[root] = min(matches)
            root_to_existing_matches[root] = matches

    # Seed the cluster ID counter from existing clusters so a re-run (this
    # function only loads articles WHERE dedup_cluster_id IS NULL) doesn't
    # reissue IDs already held by clusters assigned on a prior run.
    max_existing = conn.execute(
        "SELECT COALESCE(MAX(dedup_cluster_id), 0) FROM article"
    ).fetchone()[0]

    # Assign dedup_cluster_id: clusters matching an existing dedup cluster join
    # it (even a lone new article); otherwise a fresh id is minted for
    # clusters with size >= 2. cluster_count reports only newly minted ids.
    cluster_count = 0
    next_cluster_id = max_existing + 1
    for root, members in clusters.items():
        target_cluster = root_to_existing_cluster.get(root)
        if target_cluster is None:
            if len(members) < 2:
                continue
            target_cluster = next_cluster_id
            next_cluster_id += 1
            cluster_count += 1
        else:
            # This new cluster is a near-duplicate of >1 pre-existing cluster
            # (a transitive bridge, e.g. a wire story whose two prior variants
            # were just under the threshold of each other but both match the
            # new copy) - collapse the other existing clusters into the
            # target so the story doesn't keep casting multiple dedup_voting
            # votes. Mirrors the incremental join in ingest/stream.py.
            other_matches = root_to_existing_matches[root] - {target_cluster}
            for other in other_matches:
                conn.execute(
                    "UPDATE article SET dedup_cluster_id = ? WHERE dedup_cluster_id = ?",
                    (target_cluster, other),
                )
        for member_idx in members:
            article_id = article_ids[member_idx]
            conn.execute(
                "UPDATE article SET dedup_cluster_id = ? WHERE id = ?",
                (target_cluster, article_id),
            )

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
