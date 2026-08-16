"""Incremental claim alignment with frozen TF-IDF vocab."""

import sqlite3
import json
import numpy as np
from typing import Dict, List
from collections import defaultdict

from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer


class UnionFind:
    """Union-find for clustering."""

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


def align_incremental(
    conn: sqlite3.Connection,
    claim_ids: List[int],
    similarity_threshold: float = 0.55,
) -> Dict[str, int]:
    """
    Align new claims into events, using frozen TF-IDF vocab if available.
    Batch 1: freeze vocab in tfidf_vocab table.
    New batches: vectorize only new claims, cosine join >= threshold.

    Returns:
        {events_created, claims_aligned, claims_unaligned}
    """
    # Load new claims
    cursor = conn.execute(
        """
        SELECT c.id, c.actor, c.action, c.object, a.title, a.outlet_id
        FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.id IN ({}) AND c.event_id IS NULL
        ORDER BY c.id
        """.format(",".join("?" * len(claim_ids))),
        claim_ids,
    )
    claim_rows = cursor.fetchall()

    if not claim_rows:
        return {"events_created": 0, "claims_aligned": 0, "claims_unaligned": 0}

    new_claim_ids = [row[0] for row in claim_rows]
    claim_texts = [_normalize_claim_text(row[1], row[2], row[3], row[4]) for row in claim_rows]

    # Explicit set of ids actually created by _create_event() below - the ids
    # assigned claims land on also include pre-existing events they matched,
    # so counting "events touched" is not the same as "events created" (#A8).
    new_event_ids = set()

    # Check if vocab is frozen
    vocab_cursor = conn.execute("SELECT COUNT(*) FROM tfidf_vocab")
    vocab_frozen = vocab_cursor.fetchone()[0] > 0

    if vocab_frozen:
        # Load frozen vocab and IDF values
        vocab_rows = conn.execute("SELECT term, idx, idf FROM tfidf_vocab ORDER BY idx").fetchall()
        # Handle both Row and tuple returns
        if vocab_rows and hasattr(vocab_rows[0], 'keys'):
            # Row factory enabled
            vocab_dict = {row['term']: row['idx'] for row in vocab_rows}
            idf_dict = {row['term']: row['idf'] for row in vocab_rows}
        else:
            # Regular tuples
            vocab_dict = {row[0]: row[1] for row in vocab_rows}
            idf_dict = {row[0]: row[2] for row in vocab_rows}
        n_features = max(v for v in vocab_dict.values()) + 1 if vocab_dict else 0

        # Vectorize new claims using frozen vocab
        new_vectors = _vectorize_frozen_claims(claim_texts, vocab_dict, idf_dict, n_features)

        # Load existing centroids
        centroid_rows = conn.execute(
            "SELECT event_id, vec_json FROM event_centroid"
        ).fetchall()
        existing_events = {row[0]: json.loads(row[1]) for row in centroid_rows}

        # Comparison pool starts from existing (pre-batch) centroids and grows
        # as new events are created below, so a second claim in THIS batch
        # that matches a claim earlier in the same batch joins its event
        # instead of spawning its own singleton (#A7) - candidate ids/vectors
        # stay in parallel lists so a newly created event is immediately
        # visible to later claims in the loop.
        event_ids_list = list(existing_events.keys())
        # Pool kept as one 2-D array (not rebuilt from a Python list on every
        # claim) - vstack only fires when a new event is created, not once
        # per claim (#C5).
        pool_matrix = (
            np.array([np.array(v) for v in existing_events.values()])
            if existing_events
            else np.empty((0, n_features))
        )
        assignments = {}

        for i, new_vec in enumerate(new_vectors):
            if pool_matrix.shape[0] > 0:
                sims = _cosine_similarity(new_vec, pool_matrix)
                best_idx = int(np.argmax(sims))
                best_sim = sims[best_idx]
                best_event_id = event_ids_list[best_idx]
            else:
                best_sim = -1.0
                best_event_id = None

            if best_sim >= similarity_threshold:
                assignments[new_claim_ids[i]] = best_event_id
            else:
                # Create new event
                event_id = _create_event(conn)
                new_event_ids.add(event_id)
                assignments[new_claim_ids[i]] = event_id
                # Store centroid
                conn.execute(
                    "INSERT INTO event_centroid (event_id, vec_json, n) VALUES (?, ?, 1)",
                    (event_id, json.dumps(new_vec.tolist())),
                )
                event_ids_list.append(event_id)
                pool_matrix = np.vstack([pool_matrix, new_vec.reshape(1, -1)])
    else:
        # First batch: fit vocab and create events
        tfidf = TfidfVectorizer(
            max_features=5000, stop_words="english", ngram_range=(1, 2)
        )
        tfidf_matrix = tfidf.fit_transform(claim_texts)

        # Store vocab (convert numpy int64 to Python int)
        for term, idx in tfidf.vocabulary_.items():
            idf = float(tfidf.idf_[idx])
            conn.execute(
                "INSERT INTO tfidf_vocab (term, idx, idf) VALUES (?, ?, ?)",
                (term, int(idx), idf),
            )

        # Cluster within this first batch before creating events, so two
        # outlets covering the same story in the same batch land in one
        # event instead of each getting a singleton (#A7) - this is the
        # UnionFind merge the frozen-vocab branch does incrementally above.
        #
        # Never materialize the full N x N Gram matrix (#C1) - a first batch
        # of tens of thousands of claims makes tfidf_matrix @ tfidf_matrix.T
        # gigabytes as a dense float64 array. Score row-blocks instead and
        # keep the result sparse, thresholding via the sparse .data array so
        # the union-find loop only visits pairs that actually clear
        # similarity_threshold instead of every pair.
        n_claims = len(new_claim_ids)
        uf = UnionFind(n_claims)
        block_size = 1000
        for start in range(0, n_claims, block_size):
            end = min(start + block_size, n_claims)
            block_sims = (tfidf_matrix[start:end] @ tfidf_matrix.T).tocoo()
            keep = block_sims.data >= similarity_threshold
            for local_i, j in zip(block_sims.row[keep], block_sims.col[keep]):
                i = start + int(local_i)
                j = int(j)
                if j > i:
                    uf.union(i, j)

        clusters = defaultdict(list)
        for i in range(n_claims):
            clusters[uf.find(i)].append(i)

        assignments = {}
        for members in clusters.values():
            event_id = _create_event(conn)
            new_event_ids.add(event_id)
            member_vecs = tfidf_matrix[members].toarray()
            centroid = member_vecs.mean(axis=0)
            norm = np.linalg.norm(centroid)
            if norm > 0:
                centroid = centroid / norm
            for idx in members:
                assignments[new_claim_ids[idx]] = event_id
            conn.execute(
                "INSERT INTO event_centroid (event_id, vec_json, n) VALUES (?, ?, ?)",
                (event_id, json.dumps(centroid.tolist()), len(members)),
            )

    # Assign claims to events
    for claim_id, event_id in assignments.items():
        conn.execute("UPDATE claim SET event_id = ? WHERE id = ?", (event_id, claim_id))

    events_created = len(new_event_ids)

    conn.commit()

    # Count aligned vs unaligned
    claims_aligned = len(assignments)
    claims_unaligned = len(claim_ids) - claims_aligned

    return {
        "events_created": events_created,
        "claims_aligned": claims_aligned,
        "claims_unaligned": claims_unaligned,
    }


def _normalize_claim_text(actor: str, action: str, obj: str, title: str) -> str:
    """Normalize claim to text for vectorization."""
    parts = []
    if actor:
        parts.append(actor.lower())
    if action:
        parts.append(action.lower())
    if obj:
        parts.append(obj.lower())
    if title:
        parts.append(title.lower())
    return " ".join(parts)


def _vectorize_frozen_claims(
    texts: List[str], vocab: Dict[str, int], idf_dict: Dict[str, float], n_features: int
) -> np.ndarray:
    """
    Vectorize texts using frozen vocab (unigrams + bigrams).

    Tokenizes with the same analyzer the batch-1 TfidfVectorizer used to
    build the frozen vocab (stop_words='english', ngram_range=(1, 2)) -
    a plain text.split() strips punctuation differently and builds bigrams
    from raw adjacent tokens (including stopwords) instead of from the
    stopword-filtered token list, so the same wording produced a disjoint
    feature set here vs. at fit time.
    """
    analyzer = CountVectorizer(stop_words="english", ngram_range=(1, 2)).build_analyzer()
    vectors = []

    for text in texts:
        vec = np.zeros(n_features)
        for token in analyzer(text):
            if token in vocab:
                idx = vocab[token]
                idf = idf_dict[token]
                vec[idx] += idf

        # L2 normalize
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm

        vectors.append(vec)

    return np.array(vectors)


def _cosine_similarity(vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of vec against rows of matrix."""
    # Ensure both are normalized
    vec_norm = np.linalg.norm(vec)
    if vec_norm > 0:
        vec = vec / vec_norm

    sims = np.dot(matrix, vec)
    return sims


def _create_event(conn: sqlite3.Connection) -> int:
    """Create new event, return event_id."""
    cursor = conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, NULL, NULL)"
    )
    return cursor.lastrowid
