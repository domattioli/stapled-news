"""Consensus distance analysis for event headline variance across outlets."""

import re
import sqlite3
import numpy as np
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from scipy.sparse import hstack, csr_matrix


def build_event_vectors(titles: List[str]) -> Tuple[Dict, csr_matrix]:
    """
    Build dual word+char TF-IDF vectors for titles.

    Args:
        titles: List of headline strings

    Returns:
        (vectorizer_dict, sparse matrix): vectorizer_dict contains both fitted
        vectorizers; matrix is L2-normalized combined sparse matrix.
    """
    # Word n-grams
    word_tfidf = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 2),
        sublinear_tf=True,
        min_df=1,
        lowercase=True,
        max_features=5000,
    )
    word_matrix = word_tfidf.fit_transform(titles)

    # Character n-grams
    char_min_df = min(2, max(1, len(titles) // 2))
    char_tfidf = TfidfVectorizer(
        analyzer="char_wb",
        ngram_range=(3, 5),
        sublinear_tf=True,
        min_df=char_min_df,
        lowercase=True,
        max_features=3000,
    )
    char_matrix = char_tfidf.fit_transform(titles)

    # Combine and normalize
    combined = hstack([word_matrix, char_matrix])
    combined = normalize(combined, norm="l2", axis=1)

    vectorizer_dict = {
        "word": word_tfidf,
        "char": char_tfidf,
        "combined": None,  # Marker only
    }

    return (vectorizer_dict, combined)


def compute_distances(
    conn: sqlite3.Connection,
    min_outlets: int = 5,
    weights: Optional[Dict[int, float]] = None,
) -> Dict:
    """
    Compute consensus distance for all events with >= min_outlets.

    For each qualifying event:
    1. Load member articles and titles
    2. Build combined TF-IDF vectors
    3. Compute weighted centroid
    4. Measure distance from each article to centroid
    5. Identify consensus headline (closest to centroid)

    Args:
        conn: SQLite connection
        min_outlets: Minimum distinct outlets per event
        weights: Dict {article_id -> weight} for centroid (default 1.0 for all)

    Returns:
        {
            "articles": [{article_id, outlet, event_id, title, distance}, ...],
            "events": [{event_id, n_outlets, consensus_headline, nearest_outlet, farthest_outlet, farthest_distance}, ...]
        }
    """
    # Get events with >= min_outlets distinct outlets
    cursor = conn.execute(
        """
        SELECT c.event_id FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.event_id IS NOT NULL
        GROUP BY c.event_id
        HAVING COUNT(DISTINCT a.outlet_id) >= ?
        ORDER BY c.event_id
        """,
        (min_outlets,),
    )
    event_ids = [row[0] for row in cursor.fetchall()]

    article_rows = []
    event_rows = []

    for event_id in event_ids:
        # Load articles for this event
        cursor = conn.execute(
            """
            SELECT DISTINCT a.id, o.name, a.title
            FROM claim c
            JOIN article a ON c.article_id = a.id
            JOIN outlet o ON a.outlet_id = o.id
            WHERE c.event_id = ?
            ORDER BY a.id
            """,
            (event_id,),
        )
        members = cursor.fetchall()

        if not members:
            continue

        article_ids = [m[0] for m in members]
        outlet_names = [m[1] for m in members]
        titles = [m[2] if m[2] else "" for m in members]

        # Vectorize all titles for this event
        vectorizer_dict, vectors = build_event_vectors(titles)

        # Compute weighted centroid
        if weights:
            w = np.array([weights.get(aid, 1.0) for aid in article_ids])
            w = w / w.sum()  # Normalize weights
            centroid = vectors.T.dot(w)  # (n_features,)
        else:
            centroid = np.asarray(vectors.mean(axis=0)).flatten()

        # L2 normalize centroid
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm > 0:
            centroid = centroid / centroid_norm

        # Compute distances
        distances = []
        for i, (aid, outlet, title) in enumerate(zip(article_ids, outlet_names, titles)):
            vec = vectors[i].toarray().flatten()
            # cosine_sim = dot(vec, centroid) / (||vec|| * ||centroid||)
            # But vec and centroid are both L2-normalized, so:
            sim = float(np.dot(vec, centroid))
            dist = 1.0 - sim
            distances.append(dist)

            article_rows.append({
                "article_id": aid,
                "outlet": outlet,
                "event_id": event_id,
                "title": title,
                "distance": dist,
            })

        # Find consensus headline (closest to centroid)
        best_idx = np.argmin(distances)
        consensus_headline = titles[best_idx]
        nearest_outlet = outlet_names[best_idx]

        # Find farthest
        farthest_idx = np.argmax(distances)
        farthest_outlet = outlet_names[farthest_idx]
        farthest_distance = distances[farthest_idx]

        n_outlets = len(set(outlet_names))

        event_rows.append({
            "event_id": event_id,
            "n_outlets": n_outlets,
            "consensus_headline": consensus_headline,
            "nearest_outlet": nearest_outlet,
            "farthest_outlet": farthest_outlet,
            "farthest_distance": farthest_distance,
        })

    return {
        "articles": article_rows,
        "events": event_rows,
    }


def aggregate_outlets(
    article_rows: List[Dict],
    seed: int = 42,
    n_boot: int = 1000,
) -> List[Dict]:
    """
    Aggregate distance metrics by outlet with bootstrap CIs.

    Args:
        article_rows: Output "articles" from compute_distances
        seed: Random seed for reproducible bootstrap
        n_boot: Number of bootstrap resamples

    Returns:
        List of dicts sorted by mean_distance (ascending):
        {outlet, n_articles, mean_distance, ci_low, ci_high, deciles: [11 floats]}
    """
    # Group by outlet
    outlet_data = defaultdict(list)
    for row in article_rows:
        outlet_data[row["outlet"]].append(row["distance"])

    rng = np.random.default_rng(seed)

    results = []
    for outlet, distances in outlet_data.items():
        distances_arr = np.array(distances)
        mean_dist = float(distances_arr.mean())
        n_articles = len(distances)

        # Bootstrap CI
        bootstrap_means = []
        for _ in range(n_boot):
            sample = rng.choice(distances_arr, size=len(distances_arr), replace=True)
            bootstrap_means.append(sample.mean())

        bootstrap_means = np.array(bootstrap_means)
        ci_low = float(np.quantile(bootstrap_means, 0.025))
        ci_high = float(np.quantile(bootstrap_means, 0.975))

        # Deciles (quantiles 0.0, 0.1, 0.2, ..., 1.0)
        deciles = [float(np.quantile(distances_arr, q)) for q in np.linspace(0, 1, 11)]

        results.append({
            "outlet": outlet,
            "n_articles": n_articles,
            "mean_distance": mean_dist,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "deciles": deciles,
        })

    # Sort by mean_distance
    results.sort(key=lambda r: r["mean_distance"])
    return results


def weekly_series(
    conn: sqlite3.Connection,
    article_rows: List[Dict],
) -> Dict[str, List[Dict]]:
    """
    Compute weekly time series of mean distance per outlet.

    Args:
        conn: SQLite connection (for joining first_seen timestamps)
        article_rows: Output "articles" from compute_distances

    Returns:
        {outlet: [{week (ISO), mean_distance, n_articles}, ...], ...}
        Only outlets with >= 30 total articles are included.
    """
    # Get first_seen for each article
    # Try fp_article_meta first (for frontpage data), fall back to article.published_at
    article_first_seen = {}

    article_ids = tuple(row["article_id"] for row in article_rows)
    if not article_ids:
        return {}

    # Get URLs from article table
    cursor = conn.execute(
        "SELECT id, url, published_at FROM article WHERE id IN ({})".format(
            ",".join("?" * len(article_ids))
        ),
        article_ids,
    )
    article_data = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

    # Try to get first_seen from fp_article_meta
    urls = tuple(v[0] for v in article_data.values())
    if urls:
        cursor = conn.execute(
            "SELECT url, first_seen FROM fp_article_meta WHERE url IN ({})".format(
                ",".join("?" * len(urls))
            ),
            urls,
        )
        fp_meta = {row[0]: row[1] for row in cursor.fetchall()}
    else:
        fp_meta = {}

    # Build article_first_seen using fp_meta if available, else published_at
    for article_id, (url, published_at) in article_data.items():
        ts = fp_meta.get(url) or published_at
        if ts:
            article_first_seen[article_id] = ts

    # Group by outlet and ISO week
    outlet_weekly = defaultdict(lambda: defaultdict(list))
    for row in article_rows:
        outlet = row["outlet"]
        article_id = row["article_id"]
        distance = row["distance"]

        ts = article_first_seen.get(article_id)
        if not ts:
            continue

        # Parse ISO week (YYYY-Www format)
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            iso_week = dt.strftime("%G-W%V")
        except (ValueError, AttributeError):
            continue

        outlet_weekly[outlet][iso_week].append(distance)

    # Aggregate by week
    result = {}
    for outlet, weeks_data in outlet_weekly.items():
        if sum(len(v) for v in weeks_data.values()) < 30:
            continue  # Skip outlets with <30 articles total

        weekly_list = []
        for week in sorted(weeks_data.keys()):
            distances = np.array(weeks_data[week])
            weekly_list.append({
                "week": week,
                "mean_distance": float(distances.mean()),
                "n_articles": len(distances),
            })

        result[outlet] = weekly_list

    return result


def validate_planted(data_dict: Dict) -> Dict:
    """
    V1 sanity gate via synthetic planted outlets, measured against REAL event centroids.

    For each event, the real centroid is rebuilt from the actual member titles
    (uniform weights, same vectorizer family as compute_distances). Two synthetic
    articles are then scored against that real centroid:
    - "copier": the event's own consensus headline (expected distance near 0)
    - "noise": the consensus headline of a DIFFERENT event (derangement shift;
      expected distance well above the copier)

    Gate: copier_mean < 0.1 AND noise_mean > copier_mean + 0.3.

    Args:
        data_dict: Output dict from compute_distances (articles carry title+event_id)

    Returns:
        {copier_mean, noise_mean, gate_pass}
    """
    articles = data_dict["articles"]
    events = data_dict["events"]

    consensus_map = {e["event_id"]: e["consensus_headline"] for e in events}
    event_ids = [e["event_id"] for e in events]
    if len(event_ids) < 2:
        return {"copier_mean": 0.0, "noise_mean": 0.0, "gate_pass": False}

    event_articles = defaultdict(list)
    for row in articles:
        event_articles[row["event_id"]].append(row)

    # One global vectorizer over all member titles plus all consensus headlines,
    # so synthetic titles can be transformed into the same space.
    member_titles = [r["title"] for r in articles]
    all_titles = member_titles + [consensus_map[e] for e in event_ids]
    _, vectors = build_event_vectors(all_titles)
    title_vec = {t: vectors[i] for i, t in enumerate(all_titles)}

    # Derangement: noise headline for event i = consensus of event i+1 (cyclic).
    noise_map = {
        event_ids[i]: consensus_map[event_ids[(i + 1) % len(event_ids)]]
        for i in range(len(event_ids))
    }

    copier_distances = []
    noise_distances = []
    for event_id in event_ids[:200]:
        members = event_articles.get(event_id, [])
        if not members:
            continue
        # Real centroid from actual member titles (uniform weights).
        mat = np.vstack([
            np.asarray(title_vec[m["title"]].todense()).flatten() for m in members
        ])
        centroid = mat.mean(axis=0)
        norm = np.linalg.norm(centroid)
        if norm == 0:
            continue
        centroid = centroid / norm

        copier_vec = np.asarray(title_vec[consensus_map[event_id]].todense()).flatten()
        noise_vec = np.asarray(title_vec[noise_map[event_id]].todense()).flatten()
        copier_distances.append(1.0 - float(np.dot(copier_vec, centroid)))
        noise_distances.append(1.0 - float(np.dot(noise_vec, centroid)))

    if not copier_distances:
        return {"copier_mean": 0.0, "noise_mean": 0.0, "gate_pass": False}

    copier_mean = float(np.mean(copier_distances))
    noise_mean = float(np.mean(noise_distances))

    # Gate criteria are distribution-relative: char-n-gram cosine distances on
    # short headlines are scale-dependent (sparse titles put even the nearest
    # member well away from a centroid, and tight wire stories compress the whole
    # scale). The metric is sane when the copier sits INSIDE the real articles'
    # distance distribution and noise sits OUTSIDE it, with wide separation.
    corpus_mean = float(np.mean([r["distance"] for r in articles])) if articles else 0.0
    gate_pass = (
        noise_mean > copier_mean + 0.3
        and corpus_mean > 0
        and copier_mean < corpus_mean
        and noise_mean > corpus_mean
    )

    return {
        "copier_mean": copier_mean,
        "noise_mean": noise_mean,
        "corpus_mean": corpus_mean,
        "gate_pass": bool(gate_pass),
    }


def validate_split_half(
    conn: sqlite3.Connection,
    article_rows: List[Dict],
    seed: int = 42,
) -> Dict:
    """
    Validate stability via split-half Spearman correlation.

    Splits qualifying events randomly into two halves. For each outlet,
    computes mean_distance in each half (only if >=10 articles in both halves).
    Reports Spearman ρ and passes if ρ >= 0.6.

    Args:
        conn: SQLite connection
        article_rows: Output "articles" from compute_distances
        seed: Random seed for reproducible split

    Returns:
        {
            rho: float (Spearman correlation),
            n_outlets: int (outlets with >=10 articles in BOTH halves),
            gate_pass: bool (rho >= 0.6)
        }
    """
    from scipy.stats import spearmanr

    # Get event_id -> ISO week for each article
    article_week = {}

    article_ids = tuple(row["article_id"] for row in article_rows)
    if not article_ids:
        return {"rho": 0.0, "n_outlets": 0, "gate_pass": False}

    # Get URLs and published_at from article table
    cursor = conn.execute(
        "SELECT id, url, published_at FROM article WHERE id IN ({})".format(
            ",".join("?" * len(article_ids))
        ),
        article_ids,
    )
    article_data = {row[0]: (row[1], row[2]) for row in cursor.fetchall()}

    # Try to get first_seen from fp_article_meta
    urls = tuple(v[0] for v in article_data.values())
    if urls:
        cursor = conn.execute(
            "SELECT url, first_seen FROM fp_article_meta WHERE url IN ({})".format(
                ",".join("?" * len(urls))
            ),
            urls,
        )
        fp_meta = {row[0]: row[1] for row in cursor.fetchall()}
    else:
        fp_meta = {}

    # Build article_week using fp_meta if available, else published_at
    for article_id, (url, published_at) in article_data.items():
        ts = fp_meta.get(url) or published_at
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                iso_week = dt.strftime("%G-W%V")
                article_week[article_id] = iso_week
            except (ValueError, AttributeError):
                pass

    # Extract unique events and randomly split them
    unique_events = set(row["event_id"] for row in article_rows)
    rng = np.random.default_rng(seed)
    events_list = sorted(unique_events)
    rng.shuffle(events_list)
    split_point = len(events_list) // 2
    half1_events = set(events_list[:split_point])
    half2_events = set(events_list[split_point:])

    # Assign each article to a half based on its event
    half1_articles = [r for r in article_rows if r["event_id"] in half1_events]
    half2_articles = [r for r in article_rows if r["event_id"] in half2_events]

    # Compute outlet means per half
    outlet_half1_distances = defaultdict(list)
    outlet_half2_distances = defaultdict(list)

    for row in half1_articles:
        outlet_half1_distances[row["outlet"]].append(row["distance"])

    for row in half2_articles:
        outlet_half2_distances[row["outlet"]].append(row["distance"])

    # Find outlets with >=10 articles in BOTH halves
    half1_means = {}
    half2_means = {}
    valid_outlets = []

    for outlet in set(outlet_half1_distances.keys()) | set(outlet_half2_distances.keys()):
        h1_dists = outlet_half1_distances.get(outlet, [])
        h2_dists = outlet_half2_distances.get(outlet, [])

        if len(h1_dists) >= 10 and len(h2_dists) >= 10:
            half1_means[outlet] = np.mean(h1_dists)
            half2_means[outlet] = np.mean(h2_dists)
            valid_outlets.append(outlet)

    # Compute Spearman correlation
    if len(valid_outlets) < 2:
        rho = 0.0
        n_outlets = len(valid_outlets)
    else:
        means1 = np.array([half1_means[o] for o in valid_outlets])
        means2 = np.array([half2_means[o] for o in valid_outlets])
        rho, _ = spearmanr(means1, means2)
        n_outlets = len(valid_outlets)

    gate_pass = rho >= 0.6

    return {
        "rho": float(rho) if not np.isnan(rho) else 0.0,
        "n_outlets": int(n_outlets),
        "gate_pass": bool(gate_pass),
    }


def token_impacts(member_titles: List[str], max_events_tokens: int = 40) -> List[List[Dict]]:
    """
    Per-headline word-level attribution of distance from the event centroid.

    For each member headline, every word gets:
      weight    — the word's share of the headline's vector mass (Σ a_f², features
                  attributed to the word; bigram features split between both words,
                  char_wb n-grams assigned to the word containing them)
      alignment — the fraction of that mass that overlaps the (uniform) member
                  centroid (Σ a_f·c_f / Σ a_f²), in [0, ~1]. Low alignment with
                  high weight marks the words pushing the headline away from
                  consensus; high alignment marks shared-with-consensus wording.

    Returns one list per member title: [{token, weight, alignment}], tokens in
    original order, weights normalized per headline to sum to 1.
    """
    vec_dict, vectors = build_event_vectors(member_titles)
    dense = np.asarray(vectors.todense())
    centroid = dense.mean(axis=0)
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    word_vec = vec_dict["word"]
    char_vec = vec_dict["char"]
    word_features = word_vec.get_feature_names_out()
    char_features = char_vec.get_feature_names_out()
    n_word = len(word_features)

    out = []
    for i, title in enumerate(member_titles):
        a = dense[i]
        tokens = re.findall(r"\w[\w'’-]*", title)
        lowered = [t.lower() for t in tokens]
        toward = np.zeros(len(tokens))
        weight = np.zeros(len(tokens))

        def _attribute(feat_idx, contribution_w, contribution_t):
            for tok_i in feat_idx:
                weight[tok_i] += contribution_w
                toward[tok_i] += contribution_t

        # Word features: unigrams map to matching tokens; bigrams split halfway.
        for f_idx in np.nonzero(a[:n_word])[0]:
            feat = word_features[f_idx]
            a_f = a[f_idx]
            c_f = centroid[f_idx]
            parts = feat.split()
            hits = [j for j, lt in enumerate(lowered) if lt in parts]
            if not hits:
                continue
            share_w = (a_f * a_f) / len(hits)
            share_t = (a_f * c_f) / len(hits)
            _attribute(hits, share_w, share_t)

        # Char features: assign to every token containing the n-gram (stripped).
        for f_idx in np.nonzero(a[n_word:])[0]:
            feat = char_features[f_idx].strip()
            if not feat:
                continue
            a_f = a[n_word + f_idx]
            c_f = centroid[n_word + f_idx]
            hits = [j for j, lt in enumerate(lowered) if feat in lt]
            if not hits:
                continue
            share_w = (a_f * a_f) / len(hits)
            share_t = (a_f * c_f) / len(hits)
            _attribute(hits, share_w, share_t)

        total_w = weight.sum()
        rows = []
        for j, tok in enumerate(tokens[:max_events_tokens]):
            w = float(weight[j] / total_w) if total_w > 0 else 0.0
            align = float(toward[j] / weight[j]) if weight[j] > 0 else 0.0
            rows.append({
                "token": tok,
                "weight": round(w, 4),
                "alignment": round(min(align, 1.0), 4),
            })
        out.append(rows)
    return out


# Panel lean assignments from AllSides public media-bias ratings (allsides.com,
# retrieved 2026-06). Three buckets: lean-left+left -> "left", lean-right+right
# -> "right". Static because the Baly/MBFC corpus lacks most mainstream majors.
PANEL_LEAN = {
    "cnn.com": "left", "huffpost.com": "left", "salon.com": "left",
    "motherjones.com": "left", "dailykos.com": "left", "rawstory.com": "left",
    "thedailybeast.com": "left", "msnbc.com": "left", "theguardian.com": "left",
    "nytimes.com": "left", "washingtonpost.com": "left", "npr.org": "left",
    "abcnews.go.com": "left", "cbsnews.com": "left", "nbcnews.com": "left",
    "politico.com": "left", "axios.com": "left", "yahoo.com": "left",
    "thehill.com": "center", "reuters.com": "center", "apnews.com": "center",
    "usatoday.com": "center", "wsj.com": "center",
    "foxnews.com": "right", "washingtontimes.com": "right",
    "washingtonexaminer.com": "right", "nationalreview.com": "right",
    "dailycaller.com": "right", "breitbart.com": "right", "newsmax.com": "right",
    # Alias for rows ingested before the domain lstrip fix mangled the name.
    "ashingtonexaminer.com": "right",
}


def lean_breakdown(article_rows: List[Dict], seed: int = 42, n_boot: int = 1000) -> Dict:
    """
    Mean distance from consensus by panel lean bucket, with bootstrap CIs.

    Answers "is the consensus itself leaning?": if the centroid sat nearer one
    bloc's wording, that bloc's mean distance would be systematically lower.
    Composition context included — the centroid is the consensus of THIS panel,
    so bucket sizes matter as much as bucket means.
    """
    rng = np.random.default_rng(seed)
    groups: Dict[str, List[float]] = {"left": [], "center": [], "right": []}
    unmapped = set()
    for r in article_rows:
        lean = PANEL_LEAN.get(r["outlet"])
        if lean:
            groups[lean].append(r["distance"])
        else:
            unmapped.add(r["outlet"])

    out = {"groups": {}, "unmapped_outlets": sorted(unmapped)}
    for g, vals in groups.items():
        if not vals:
            out["groups"][g] = {"n_articles": 0}
            continue
        arr = np.array(vals)
        boots = [rng.choice(arr, size=len(arr), replace=True).mean() for _ in range(n_boot)]
        out["groups"][g] = {
            "n_articles": len(vals),
            "mean_distance": round(float(arr.mean()), 6),
            "ci_low": round(float(np.quantile(boots, 0.025)), 6),
            "ci_high": round(float(np.quantile(boots, 0.975)), 6),
        }
    return out
