"""Event alignment via TF-IDF + agglomerative clustering."""

import re
import sqlite3
from typing import Dict, Tuple, List, Set
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
import numpy as np

from stapled.db import insert_and_get_id


# Alias normalization
ALIAS_MAP = {
    "doj": "department of justice",
    "justice department": "department of justice",
    "gop": "republican party",
    "potus": "president",
    "u.s.": "united states",
    "us": "united states",
    "hhs": "health and human services",
    "dhs": "homeland security",
    "fbi": "federal bureau of investigation",
}


def align(
    conn: sqlite3.Connection,
    min_outlets: int = 1,
    max_claims: int = 50000,
    similarity_threshold: float = 0.55,
) -> Dict[str, int]:
    """
    Cluster unaligned real claims into events via TF-IDF + agglomerative clustering.
    Returns {events_created, claims_aligned, claims_unaligned}.
    """
    # Load unaligned real claims
    cursor = conn.execute(
        """
        SELECT c.id, c.actor, c.action, c.object, a.title, a.outlet_id
        FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.event_id IS NULL
        AND a.corpus_id IS NULL
        LIMIT ?
        """,
        (max_claims,),
    )

    claim_rows = cursor.fetchall()
    if not claim_rows:
        return {"events_created": 0, "claims_aligned": 0, "claims_unaligned": 0}

    claim_ids = [row[0] for row in claim_rows]
    outlet_ids = [row[5] for row in claim_rows]

    # Build claim texts (vectorization input)
    claim_texts = [
        _normalize_claim_text(row[1], row[2], row[3], row[4])
        for row in claim_rows
    ]

    # TF-IDF vectorization
    tfidf = TfidfVectorizer(
        max_features=20000,
        stop_words="english",
        ngram_range=(1, 2),
    )
    tfidf_matrix = tfidf.fit_transform(claim_texts)

    # Agglomerative clustering via kNN + connected components
    k_neighbors = max(1, min(10, len(claim_ids) - 1))
    if k_neighbors < 1:
        # Not enough claims to cluster
        return {"events_created": 0, "claims_aligned": 0, "claims_unaligned": len(claim_ids)}

    nn = NearestNeighbors(
        n_neighbors=k_neighbors,
        metric="cosine",
    )
    nn.fit(tfidf_matrix)

    # Find edges where similarity >= threshold
    distances, indices = nn.kneighbors(tfidf_matrix)
    edges: Set[Tuple[int, int]] = set()

    for i in range(len(claim_ids)):
        for j, dist in zip(indices[i], distances[i]):
            # Distance = 1 - similarity; we want similarity >= threshold
            similarity = 1.0 - dist
            if similarity >= similarity_threshold:
                edges.add((min(i, j), max(i, j)))

    # Connected components via union-find
    uf = UnionFind(len(claim_ids))
    for i, j in edges:
        uf.union(i, j)

    # Build clusters
    clusters: Dict[int, List[int]] = defaultdict(list)
    for idx, claim_id in enumerate(claim_ids):
        root = uf.find(idx)
        clusters[root].append(idx)

    # Create events for clusters with >= min_outlets distinct outlets
    events_created = 0
    claims_aligned = 0

    for cluster_members in clusters.values():
        if len(cluster_members) < 2:
            continue

        # Check distinct outlets
        distinct_outlets = len(set(outlet_ids[i] for i in cluster_members))
        if distinct_outlets < min_outlets:
            continue

        # Create event with TF-IDF label
        top_terms = _get_top_tfidf_terms(
            tfidf, tfidf_matrix[cluster_members], tfidf.get_feature_names_out()
        )
        label = " + ".join(top_terms[:3])

        event_id = insert_and_get_id(
            conn,
            "INSERT INTO event (corpus_id, label, true_state, true_magnitude_bucket) VALUES (NULL, ?, NULL, NULL)",
            (label,),
        )

        # Assign claims to event
        for member_idx in cluster_members:
            claim_id = claim_ids[member_idx]
            conn.execute(
                "UPDATE claim SET event_id = ? WHERE id = ?",
                (event_id, claim_id),
            )
            claims_aligned += 1

        events_created += 1

    conn.commit()

    # Count remaining unaligned
    cursor = conn.execute(
        "SELECT COUNT(*) FROM claim WHERE event_id IS NULL AND article_id IN (SELECT id FROM article WHERE corpus_id IS NULL)"
    )
    claims_unaligned = cursor.fetchone()[0]

    return {
        "events_created": events_created,
        "claims_aligned": claims_aligned,
        "claims_unaligned": claims_unaligned,
    }


def _normalize_claim_text(
    actor: str, action: str, obj: str, title: str
) -> str:
    """Normalize claim text for vectorization: apply aliases."""
    parts = [actor or "", action or "", obj or "", title or ""]
    text = " ".join(parts).lower()

    # Apply alias normalization. Word-boundary match (not plain substring
    # replace) so e.g. the "us" -> "united states" alias doesn't rewrite the
    # interior of "House"/"Russia"/"discuss"/"bus"/etc. `(?<!\w)...(?!\w)`
    # rather than `\b...\b` because \b fails at a trailing non-word char
    # (e.g. the "." in "u.s."). Longest alias first so "justice department"
    # is consumed before the standalone "doj"/shorter aliases could interfere.
    for alias, canonical in sorted(ALIAS_MAP.items(), key=lambda kv: -len(kv[0])):
        text = re.sub(r"(?<!\w)" + re.escape(alias) + r"(?!\w)", canonical, text)

    return text


def _get_top_tfidf_terms(tfidf, matrix, feature_names, n=3):
    """Get top n TF-IDF terms from a matrix."""
    if matrix.shape[0] == 0:
        return []

    # Sum TF-IDF scores across cluster
    scores = np.asarray(matrix.sum(axis=0)).flatten()
    top_indices = np.argsort(-scores)[:n]
    return [feature_names[i] for i in top_indices if i < len(feature_names)]


class UnionFind:
    """Union-find for connected components."""

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
