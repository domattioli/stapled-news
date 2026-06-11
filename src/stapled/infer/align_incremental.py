"""Incremental claim alignment with frozen TF-IDF vocab."""

import sqlite3
import json
import numpy as np
from typing import Dict, List

from sklearn.feature_extraction.text import TfidfVectorizer


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

        if existing_events:
            # Find nearest existing event for each new claim
            existing_vectors = np.array(list(existing_events.values()))
            assignments = {}

            for i, new_vec in enumerate(new_vectors):
                # Cosine similarity
                sims = _cosine_similarity(new_vec, existing_vectors)
                best_sim = np.max(sims)
                best_event_id = list(existing_events.keys())[np.argmax(sims)]

                if best_sim >= similarity_threshold:
                    assignments[new_claim_ids[i]] = best_event_id
                else:
                    # Create new event
                    event_id = _create_event(conn)
                    assignments[new_claim_ids[i]] = event_id
                    # Store centroid
                    conn.execute(
                        "INSERT INTO event_centroid (event_id, vec_json, n) VALUES (?, ?, 1)",
                        (event_id, json.dumps(new_vec.tolist())),
                    )
        else:
            # No existing events; create new ones
            assignments = {}
            for i, new_vec in enumerate(new_vectors):
                event_id = _create_event(conn)
                assignments[new_claim_ids[i]] = event_id
                conn.execute(
                    "INSERT INTO event_centroid (event_id, vec_json, n) VALUES (?, ?, 1)",
                    (event_id, json.dumps(new_vec.tolist())),
                )
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

        # Create events for all new claims
        assignments = {}
        for i, claim_id in enumerate(new_claim_ids):
            event_id = _create_event(conn)
            assignments[claim_id] = event_id
            vec = tfidf_matrix[i].toarray().flatten().tolist()
            conn.execute(
                "INSERT INTO event_centroid (event_id, vec_json, n) VALUES (?, ?, 1)",
                (event_id, json.dumps(vec)),
            )

    # Assign claims to events
    events_created = 0
    assigned_event_ids = set()
    for claim_id, event_id in assignments.items():
        conn.execute("UPDATE claim SET event_id = ? WHERE id = ?", (event_id, claim_id))
        assigned_event_ids.add(event_id)

    # Count newly created events (those not previously in database)
    if assigned_event_ids:
        placeholders = ",".join("?" * len(assigned_event_ids))
        cursor = conn.execute(
            f"SELECT COUNT(*) FROM event WHERE id IN ({placeholders}) AND id > 0",
            list(assigned_event_ids),
        )
        events_created = cursor.fetchone()[0]

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
    """Vectorize texts using frozen vocab (unigrams + bigrams)."""
    vectors = []

    for text in texts:
        vec = np.zeros(n_features)
        # Simple bigram tokenization
        tokens = text.split()

        # Add unigrams
        for token in tokens:
            if token in vocab:
                idx = vocab[token]
                idf = idf_dict[token]
                vec[idx] += idf

        # Add bigrams
        for i in range(len(tokens) - 1):
            bigram = tokens[i] + " " + tokens[i + 1]
            if bigram in vocab:
                idx = vocab[bigram]
                idf = idf_dict[bigram]
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
