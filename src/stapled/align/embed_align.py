"""Enhanced claim alignment with TF-IDF + character n-grams + entity boosting."""

import sqlite3
import re
import numpy as np
from typing import Dict, List, Set
from collections import defaultdict

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from scipy.sparse import hstack


# Stopwords for entity filtering
_ENTITY_STOPWORDS = {
    "the", "a", "an", "this", "that", "these", "those", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "can", "it", "its", "he",
    "she", "they", "them", "their", "theirs", "him", "her", "us", "we", "me", "i",
    "you", "why", "how", "what", "when", "where", "which", "who", "whom", "whose"
}


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


def realign_all(
    conn: sqlite3.Connection,
    similarity_threshold: float = 0.5,
    entity_mode: str = "boost",
) -> Dict[str, int]:
    """
    Realign all claims into events using combined TF-IDF (word + char n-grams)
    + entity-based blocking + union-find clustering.

    Args:
        conn: SQLite connection
        similarity_threshold: Cosine similarity threshold for merging
        entity_mode: "boost" (default) to boost similarity when entities overlap

    Returns:
        Dict with keys: claims_total, clusters_multi, events_created, claims_in_multi, multi_outlet_events
    """

    # 1. Load ALL claims with article info
    cursor = conn.execute(
        """
        SELECT c.id, c.actor, c.action, c.object, a.title, a.outlet_id
        FROM claim c
        JOIN article a ON c.article_id = a.id
        ORDER BY c.id
        """
    )
    claim_rows = cursor.fetchall()

    if not claim_rows:
        return {
            "claims_total": 0,
            "clusters_multi": 0,
            "events_created": 0,
            "claims_in_multi": 0,
            "multi_outlet_events": 0,
        }

    claims_total = len(claim_rows)
    claim_ids = [row[0] for row in claim_rows]

    # 2. Build claim texts and extract entities from original (non-lowercased) text
    claim_texts = []
    claim_entities = []  # List[Set[str]] of lowercased entity tokens + phrases
    original_texts = []  # For entity extraction from capitalized version

    for row in claim_rows:
        actor, action, obj, title = row[1], row[2], row[3], row[4]
        # Lowercased version for vectorization
        normalized = _normalize_claim_text(actor, action, obj, title)
        claim_texts.append(normalized)

        # Original for entity extraction (capitalization preserved in actor+title)
        original = " ".join(
            [p for p in [actor or "", title or ""] if p]
        )
        original_texts.append(original)

        # Extract entities from original text
        entities = _extract_entities(original)
        claim_entities.append(entities)

    # 3. Build dual vectorizers: word + char n-gram TF-IDF
    word_tfidf = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
        stop_words="english",
        lowercase=True,
        max_features=5000,
    )
    word_matrix = word_tfidf.fit_transform(claim_texts)

    # For char n-grams with few documents, scale min_df down
    char_min_df = min(2, max(1, len(claim_texts) // 2))
    char_tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        sublinear_tf=True,
        min_df=char_min_df,
        lowercase=True,
        max_features=3000,
    )
    char_matrix = char_tfidf.fit_transform(claim_texts)

    # Concatenate and L2 normalize
    combined_matrix = hstack([word_matrix, char_matrix])
    combined_matrix = normalize(combined_matrix, norm="l2", axis=1)

    # 4. Build inverted index for entity-based blocking
    entity_to_claims = defaultdict(set)  # entity_token -> set of claim indices
    rare_word_to_claims = defaultdict(set)  # rare_word -> set of claim indices
    rare_threshold = 20  # df threshold

    # Get document frequencies for rare-word fallback
    vocab_df = np.asarray(word_matrix.astype(bool).sum(axis=0)).flatten()

    for idx, entities in enumerate(claim_entities):
        if entities:
            for entity_token in entities:
                entity_to_claims[entity_token].add(idx)
        else:
            # Fallback: rare words in this claim
            word_indices = word_matrix[idx].nonzero()[1]
            for word_idx in word_indices:
                if vocab_df[word_idx] <= rare_threshold:
                    # Map index back to term (approximate: just use the index)
                    rare_word_to_claims[word_idx].add(idx)

    # 5. Generate candidate pairs via blocking
    candidate_pairs = set()
    for idx in range(len(claim_ids)):
        candidates = set()

        if claim_entities[idx]:
            # Block on shared entity tokens
            for entity_token in claim_entities[idx]:
                candidates.update(entity_to_claims[entity_token])
        else:
            # Fallback: rare words
            word_indices = word_matrix[idx].nonzero()[1]
            for word_idx in word_indices:
                if vocab_df[word_idx] <= rare_threshold:
                    candidates.update(rare_word_to_claims[word_idx])

        candidates.discard(idx)
        for j in candidates:
            if idx < j:
                candidate_pairs.add((idx, j))
            else:
                candidate_pairs.add((j, idx))

    # 6. Score pairs and generate merge edges
    merge_edges = []
    for i, j in candidate_pairs:
        cosine_sim = float(combined_matrix[i].dot(combined_matrix[j].T).toarray()[0, 0])

        # Apply entity boost if enabled
        effective_sim = cosine_sim
        if entity_mode == "boost" and claim_entities[i] and claim_entities[j]:
            # Count phrase/token overlaps
            entity_overlap = len(claim_entities[i] & claim_entities[j])
            if entity_overlap > 0:
                effective_sim = cosine_sim + 0.1

        # Merge if effective_sim >= threshold AND cosine >= threshold - 0.15
        if effective_sim >= similarity_threshold and cosine_sim >= similarity_threshold - 0.15:
            # Hard guard: disjoint entity sets with both having entities -> higher bar
            if (
                claim_entities[i]
                and claim_entities[j]
                and len(claim_entities[i] & claim_entities[j]) == 0
            ):
                if cosine_sim < 0.75:
                    continue  # Too risky to merge

            merge_edges.append((i, j))

    # 7. Union-find to form clusters
    uf = UnionFind(len(claim_ids))
    for i, j in merge_edges:
        uf.union(i, j)

    clusters = defaultdict(list)
    for idx in range(len(claim_ids)):
        root = uf.find(idx)
        clusters[root].append(idx)

    # 8. Clear existing event assignments and orphan events/centroids
    conn.execute("UPDATE claim SET event_id = NULL")
    conn.execute("DELETE FROM event_centroid")
    # Delete orphan events (events with no claims assigned after clearing all assignments)
    conn.execute("DELETE FROM event WHERE id NOT IN (SELECT -1)")  # Will delete all after UPDATE claim SET event_id=NULL
    conn.commit()

    # 9. Create events from clusters
    events_created = 0
    claims_in_multi = 0
    multi_outlet_clusters = 0

    for cluster_members in clusters.values():
        cluster_size = len(cluster_members)

        # Determine event label: 3 most frequent non-stopword tokens in cluster
        label = _get_cluster_label(claim_texts, cluster_members)

        # Create event for cluster (both singletons and multi-claims)
        cursor = conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, ?, NULL)",
            (label,),
        )
        event_id = cursor.lastrowid

        # Assign all claims in cluster to this event
        for member_idx in cluster_members:
            claim_id = claim_ids[member_idx]
            conn.execute(
                "UPDATE claim SET event_id = ? WHERE id = ?",
                (event_id, claim_id),
            )

        events_created += 1

        if cluster_size >= 2:
            claims_in_multi += cluster_size
            multi_outlet_clusters += 1

    conn.commit()

    # Count multi-outlet events (distinct outlets >= 2)
    cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT e.id)
        FROM event e
        WHERE (
            SELECT COUNT(DISTINCT outlet_id)
            FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE c.event_id = e.id
        ) >= 2
        """
    )
    multi_outlet_events = cursor.fetchone()[0]

    return {
        "claims_total": claims_total,
        "clusters_multi": multi_outlet_clusters,
        "events_created": events_created,
        "claims_in_multi": claims_in_multi,
        "multi_outlet_events": multi_outlet_events,
    }


def _normalize_claim_text(actor: str, action: str, obj: str, title: str) -> str:
    """Normalize claim text: lowercase, strip whitespace."""
    parts = []
    for part in [actor, action, obj, title]:
        if part:
            parts.append(part.lower())
    return " ".join(parts)


def _extract_entities(text: str) -> Set[str]:
    """
    Extract capitalized entity spans from original text.
    Returns set of lowercased entity phrases and individual tokens.
    """
    entities = set()
    if not text:
        return entities

    # Regex: capitalized word sequences (allows apostrophes and hyphens)
    pattern = r"[A-Z][a-zA-Z''.-]+(?:\s+[A-Z][a-zA-Z''.-]+)*"
    matches = re.findall(pattern, text)

    for match in matches:
        # Skip if it's a single stopword-like starter
        tokens = match.split()
        if len(tokens) == 1 and tokens[0].lower() in _ENTITY_STOPWORDS:
            continue

        # Add the full phrase (lowercased)
        phrase = match.lower()
        entities.add(phrase)

        # Also add individual tokens
        for token in tokens:
            token_lower = token.lower()
            if token_lower not in _ENTITY_STOPWORDS:
                entities.add(token_lower)

    return entities


def _get_cluster_label(
    claim_texts: List[str], cluster_members: List[int], n_terms: int = 3
) -> str:
    """
    Get label for cluster: n_terms most frequent non-stopword tokens.
    """
    token_freq = defaultdict(int)
    stopwords = {
        "the", "a", "an", "and", "or", "is", "are", "was", "were",
        "be", "been", "have", "has", "had", "do", "does", "did",
        "in", "on", "at", "to", "for", "of", "with", "by", "from",
    }

    for idx in cluster_members:
        tokens = claim_texts[idx].split()
        for token in tokens:
            token = token.lower()
            if token not in stopwords and len(token) > 2:
                token_freq[token] += 1

    # Get top n_terms by frequency
    if not token_freq:
        return "unnamed"

    top_terms = sorted(token_freq.items(), key=lambda x: x[1], reverse=True)[:n_terms]
    return " + ".join([term for term, _ in top_terms])
