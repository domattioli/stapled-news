"""Consensus distance analysis for event headline variance across outlets."""

import re
import sqlite3
import numpy as np
from collections import defaultdict
from datetime import datetime

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import normalize
from scipy.sparse import hstack, csr_matrix


def build_event_vectors(titles: list[str]) -> tuple[dict, csr_matrix]:
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


def _lean_bucket_weights(
    outlet_names: list[str], synd_w: np.ndarray | None = None
) -> np.ndarray:
    """
    Per-article weights so each ideological bucket present among an event's
    outlets (left / center / right / unrated, via PANEL_LEAN) contributes
    equal total weight to that event's centroid — controlling for a panel
    that happens to include more outlets or articles from one camp than
    another (e.g. a corpus with more left-rated than right-rated outlets)
    mechanically defining "consensus" as that camp's wording.

    `synd_w` (optional, one entry per outlet_names, default all-1) is the
    caller's syndication-dedup weight (1/dup_count). Within a bucket,
    articles split that bucket's share in proportion to synd_w, normalized
    over the bucket's OWN synd_w total — not article count — so a bucket
    made mostly of wire copies of one headline still gets its full equal
    share instead of having that share divided down by dedup on top of the
    bucket split (a wire-heavy camp would otherwise be muted, not equalized).
    The returned weights already fold in synd_w; callers must not multiply
    synd_w in again.
    """
    buckets = [PANEL_LEAN.get(o, "unrated") for o in outlet_names]
    if synd_w is None:
        synd_w = np.ones(len(outlet_names))
    bucket_synd_total: dict[str, float] = {}
    for b, sw in zip(buckets, synd_w):
        bucket_synd_total[b] = bucket_synd_total.get(b, 0.0) + sw
    share = 1.0 / len(bucket_synd_total)
    return np.array([share * sw / bucket_synd_total[b] for b, sw in zip(buckets, synd_w)])


def compute_distances(
    conn: sqlite3.Connection,
    min_outlets: int = 5,
    weights: dict[int, float] | None = None,
    lean_balanced: bool = True,
) -> dict:
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
        lean_balanced: if True (default), weight each event's centroid so every
            present ideological bucket (left/center/right/unrated) contributes
            equally, instead of one-article-one-vote. Controls for corpus-level
            panel skew (see _lean_bucket_weights); set False to reproduce the
            raw per-article-weighted centroid.

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

        # Syndication weighting: collapse exact-duplicate headlines (case/space
        # normalized) so one AP wire story carried verbatim by N outlets counts
        # as a single vote in the consensus, not N. Per-article distances below
        # are still scored individually.
        norm_titles = [re.sub(r"\s+", " ", (t or "").strip().lower()) for t in titles]
        dup_counts = {}
        for nt in norm_titles:
            dup_counts[nt] = dup_counts.get(nt, 0) + 1
        synd_w = np.array([1.0 / dup_counts[nt] for nt in norm_titles])
        # lean_w already folds synd_w in when lean_balanced (bucket-normalized
        # over effective, syndication-collapsed votes — see _lean_bucket_weights);
        # do not multiply synd_w in again here.
        lean_w = _lean_bucket_weights(outlet_names, synd_w) if lean_balanced else synd_w

        if weights:
            w = np.array([weights.get(aid, 1.0) for aid in article_ids]) * lean_w
        else:
            w = lean_w
        w = w / w.sum()
        centroid = vectors.T.dot(w)

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
                "event_outlets": len(set(outlet_names)),
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
    article_rows: list[dict],
    seed: int = 42,
    n_boot: int = 1000,
) -> list[dict]:
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
    # Group by outlet. Each article weighted by its event's outlet count, so a
    # headline on a story the whole field covered moves an outlet's average more
    # than a headline on a barely-corroborated story.
    outlet_data = defaultdict(list)
    for row in article_rows:
        outlet_data[row["outlet"]].append(
            (row["distance"], float(row.get("event_outlets", 1)))
        )

    rng = np.random.default_rng(seed)

    results = []
    for outlet, pairs in outlet_data.items():
        distances_arr = np.array([p[0] for p in pairs])
        w = np.array([p[1] for p in pairs])
        w = w / w.sum()
        mean_dist = float(np.dot(distances_arr, w))
        n_articles = len(pairs)

        # Bootstrap CI (resample articles, recompute the weighted mean)
        bootstrap_means = []
        idx = np.arange(len(pairs))
        for _ in range(n_boot):
            s = rng.choice(idx, size=len(idx), replace=True)
            sw = w[s]
            bootstrap_means.append(float(np.dot(distances_arr[s], sw / sw.sum())))

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


def _fetch_in_chunks(
    conn: sqlite3.Connection, sql_template: str, values, chunk_size: int = 900
) -> list:
    """Run a 'SELECT ... WHERE col IN ({})' query in chunks and concatenate the
    rows. SQLite caps bound parameters per statement (SQLITE_MAX_VARIABLE_NUMBER,
    32766 by default) — a single IN(...) built from the full analyzed-article set
    can exceed that as the corpus grows, so chunk instead of binding it all at once.
    """
    rows = []
    values = list(values)
    for i in range(0, len(values), chunk_size):
        chunk = values[i : i + chunk_size]
        cursor = conn.execute(
            sql_template.format(",".join("?" * len(chunk))),
            chunk,
        )
        rows.extend(cursor.fetchall())
    return rows


def weekly_series(
    conn: sqlite3.Connection,
    article_rows: list[dict],
    min_week_articles: int = 3,
) -> dict[str, list[dict]]:
    """
    Compute weekly time series of mean distance per outlet.

    Args:
        conn: SQLite connection (for joining first_seen timestamps)
        article_rows: Output "articles" from compute_distances
        min_week_articles: drop individual weeks with fewer than this many
            articles for that outlet — a "mean" over 1-2 articles is noise,
            not a trend point, and reads as a misleading spike in a chart.

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
    rows = _fetch_in_chunks(
        conn, "SELECT id, url, published_at FROM article WHERE id IN ({})", article_ids
    )
    article_data = {row[0]: (row[1], row[2]) for row in rows}

    # Try to get first_seen from fp_article_meta
    urls = tuple(v[0] for v in article_data.values())
    if urls:
        rows = _fetch_in_chunks(
            conn, "SELECT url, first_seen FROM fp_article_meta WHERE url IN ({})", urls
        )
        fp_meta = {row[0]: row[1] for row in rows}
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
            if len(distances) < min_week_articles:
                continue
            weekly_list.append({
                "week": week,
                "mean_distance": float(distances.mean()),
                "n_articles": len(distances),
            })

        result[outlet] = weekly_list

    return result


def validate_planted(data_dict: dict) -> dict:
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
    article_rows: list[dict],
    seed: int = 42,
) -> dict:
    """
    Validate stability via split-half Spearman correlation.

    Splits qualifying events randomly into two halves. For each outlet,
    computes mean_distance in each half (only if >=10 articles in both halves).
    Reports Spearman ρ and passes if ρ >= 0.6.

    Args:
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

    if not article_rows:
        return {"rho": 0.0, "n_outlets": 0, "gate_pass": False}

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


def token_impacts(
    member_titles: list[str],
    max_events_tokens: int = 40,
    weights: np.ndarray | None = None,
    attribute_indices: list[int] | None = None,
) -> list[list[dict]]:
    """
    Per-headline word-level attribution of distance from the event centroid.

    For each member headline, every word gets:
      weight    — the word's share of the headline's vector mass (Σ a_f², features
                  attributed to the word; bigram features split between both words,
                  char_wb n-grams assigned to the word containing them)
      alignment — the fraction of that mass that overlaps the member centroid
                  (Σ a_f·c_f / Σ a_f²), in [0, ~1]. Low alignment with high
                  weight marks the words pushing the headline away from
                  consensus; high alignment marks shared-with-consensus wording.

    Args:
        member_titles: headlines used to fit the vectorizer and the centroid
            (so the vocabulary/IDF and centroid match a caller's full-event
            distance computation, even if only a subset is attributed below).
        max_events_tokens: cap on tokens attributed per headline.
        weights: optional per-title weight for the centroid (e.g. the same
            syndication/lean weighting compute_distances uses), so the centroid
            matches the one a caller's displayed distance was computed against.
            Defaults to a uniform mean over member_titles when omitted.
        attribute_indices: optional subset of member_titles indices to run the
            (expensive, per-title) attribution loop for. The centroid is still
            fit and weighted over the FULL member_titles list; only the dense
            row extraction + attribution below is limited to this subset, so a
            caller with a huge member list and a handful of curated rows to
            display doesn't have to densify/attribute the whole matrix.
            Defaults to all indices when omitted.

    Returns one list per attributed title (all of member_titles, in order, if
    attribute_indices is omitted; otherwise one per attribute_indices entry,
    in that order): [{token, weight, alignment}], tokens in original order,
    weights normalized per headline to sum to 1.
    """
    vec_dict, vectors = build_event_vectors(member_titles)
    if weights is not None:
        w = np.asarray(weights, dtype=float)
        w = w / w.sum() if w.sum() > 0 else np.full(len(member_titles), 1.0 / len(member_titles))
        centroid = np.asarray(vectors.T.dot(w)).ravel()
    else:
        centroid = np.asarray(vectors.mean(axis=0)).ravel()
    norm = np.linalg.norm(centroid)
    if norm > 0:
        centroid = centroid / norm

    word_vec = vec_dict["word"]
    char_vec = vec_dict["char"]
    word_features = word_vec.get_feature_names_out()
    char_features = char_vec.get_feature_names_out()
    n_word = len(word_features)

    indices = range(len(member_titles)) if attribute_indices is None else attribute_indices

    out = []
    for i in indices:
        title = member_titles[i]
        a = np.asarray(vectors[i].todense()).ravel()
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


# AllSides media-bias ratings (allsides.com, retrieved 2026-06), five-point scale.
# LEAN5 keeps the granular rating; PANEL_LEAN collapses to three buckets for the
# coverage / distance breakdowns; LEAN_ORDINAL maps to -2..+2 for the spectrum.
PANEL_LEAN5 = {
    "huffpost.com": "left", "msnbc.com": "left", "salon.com": "left",
    "motherjones.com": "left", "dailykos.com": "left", "rawstory.com": "left",
    "thedailybeast.com": "left", "alternet.org": "left", "vox.com": "left",
    "cnn.com": "lean-left", "nytimes.com": "lean-left", "washingtonpost.com": "lean-left",
    "npr.org": "lean-left", "abcnews.go.com": "lean-left", "cbsnews.com": "lean-left",
    "nbcnews.com": "lean-left", "politico.com": "lean-left", "theguardian.com": "lean-left",
    "axios.com": "lean-left", "yahoo.com": "lean-left", "time.com": "lean-left",
    "theatlantic.com": "lean-left", "bloomberg.com": "lean-left", "usatoday.com": "lean-left",
    "thehill.com": "center", "reuters.com": "center", "apnews.com": "center",
    "wsj.com": "center", "newsweek.com": "center", "forbes.com": "center",
    "csmonitor.com": "center", "marketwatch.com": "center", "realclearpolitics.com": "center",
    "washingtonexaminer.com": "lean-right", "nationalreview.com": "lean-right",
    "thedispatch.com": "lean-right", "washingtontimes.com": "lean-right",
    "nypost.com": "lean-right", "justthenews.com": "lean-right",
    "foxnews.com": "right", "breitbart.com": "right", "newsmax.com": "right",
    "dailycaller.com": "right", "thefederalist.com": "right", "dailywire.com": "right",
    "theblaze.com": "right", "oann.com": "right",
}
LEAN_ORDINAL = {"left": -2, "lean-left": -1, "center": 0, "lean-right": 1, "right": 2}
_THREE = {"left": "left", "lean-left": "left", "center": "center",
          "lean-right": "right", "right": "right"}
PANEL_LEAN = {dom: _THREE[v] for dom, v in PANEL_LEAN5.items()}


def lean_breakdown(article_rows: list[dict], seed: int = 42, n_boot: int = 1000) -> dict:
    """
    Mean distance from consensus by panel lean bucket, with bootstrap CIs.

    Answers "is the consensus itself leaning?": if the centroid sat nearer one
    bloc's wording, that bloc's mean distance would be systematically lower.
    Distances here come from compute_distances' bucket-balanced centroid, so a
    corpus with more left-rated than right-rated outlets does not by itself
    make one bucket look closer — remaining differences reflect wording, not
    panel size. Composition context (panel_composition) is reported alongside
    since it is worth knowing what the panel looks like even though it no
    longer drives the centroid.
    """
    rng = np.random.default_rng(seed)
    groups: dict[str, list[float]] = {"left": [], "center": [], "right": []}
    unmapped = set()
    for r in article_rows:
        lean = PANEL_LEAN.get(r["outlet"])
        if lean:
            groups[lean].append((r["distance"], float(r.get("event_outlets", 1))))
        else:
            unmapped.add(r["outlet"])

    out = {"groups": {}, "unmapped_outlets": sorted(unmapped)}
    for g, pairs in groups.items():
        if not pairs:
            out["groups"][g] = {"n_articles": 0}
            continue
        arr = np.array([p[0] for p in pairs])
        w = np.array([p[1] for p in pairs])
        w = w / w.sum()
        idx = np.arange(len(pairs))
        boots = []
        for _ in range(n_boot):
            s = rng.choice(idx, size=len(idx), replace=True)
            sw = w[s]
            boots.append(float(np.dot(arr[s], sw / sw.sum())))
        out["groups"][g] = {
            "n_articles": len(pairs),
            "mean_distance": round(float(np.dot(arr, w)), 6),
            "ci_low": round(float(np.quantile(boots, 0.025)), 6),
            "ci_high": round(float(np.quantile(boots, 0.975)), 6),
        }
    return out


def panel_composition(article_rows: list[dict]) -> dict:
    """Panel makeup by lean bucket: outlet counts, article counts, and
    coverage-weighted article share. This is the composition the consensus
    centroid is built from — the direct evidence for or against a leaning panel.
    """
    outlets_by = defaultdict(set)
    articles_by = defaultdict(int)
    weight_by = defaultdict(float)
    for r in article_rows:
        lean = PANEL_LEAN.get(r["outlet"])
        if not lean:
            continue
        outlets_by[lean].add(r["outlet"])
        articles_by[lean] += 1
        weight_by[lean] += float(r.get("event_outlets", 1))
    total_w = sum(weight_by.values()) or 1.0
    return {
        g: {
            "outlets": len(outlets_by[g]),
            "articles": articles_by[g],
            "weighted_share": round(weight_by[g] / total_w, 4),
        }
        for g in ("left", "center", "right")
    }


def consensus_lean_axis(conn, min_outlets: int = 5, seed: int = 42, n_boot: int = 1000) -> dict:
    """
    Signed left<->right position of each consensus headline, not just its distance.

    For every event that has at least one left-rated and one right-rated member
    (AllSides buckets), build a left-camp wording centroid L and a right-camp
    centroid R from those members, plus a bucket-balanced consensus centroid C
    (see _lean_bucket_weights: left/center/right/unrated each contribute equal
    weight, rather than whichever bucket has more outlets covering the story).
    Project C onto the L->R axis:  t = (C - L)·(R - L) / ||R - L||^2.
      t = 0   -> consensus phrased like the left camp
      t = 0.5 -> exactly between the camps
      t = 1   -> phrased like the right camp
    separation = ||R - L|| says how distinguishable the two camps' wording even is
    on that story (small -> there is barely a "left way" vs "right way" to write it).

    Because C is bucket-balanced, t reflects wording differences between camps,
    not how many outlets from each camp happened to cover the story — the panel's
    raw composition (see panel_composition/panel_spectrum) no longer mechanically
    determines the result.
    """
    cur = conn.execute(
        """
        SELECT c.event_id FROM claim c JOIN article a ON c.article_id = a.id
        WHERE c.event_id IS NOT NULL
        GROUP BY c.event_id HAVING COUNT(DISTINCT a.outlet_id) >= ?
        ORDER BY c.event_id
        """,
        (min_outlets,),
    )
    event_ids = [r[0] for r in cur.fetchall()]

    per_event = []
    for eid in event_ids:
        members = conn.execute(
            """
            SELECT DISTINCT o.name, a.title FROM claim c
            JOIN article a ON c.article_id = a.id
            JOIN outlet o ON a.outlet_id = o.id
            WHERE c.event_id = ? ORDER BY a.id
            """,
            (eid,),
        ).fetchall()
        leans = [PANEL_LEAN.get(o) for o, _ in members]
        if leans.count("left") < 1 or leans.count("right") < 1:
            continue
        titles = [t or "" for _, t in members]
        _, vecs = build_event_vectors(titles)
        dense = np.asarray(vecs.todense())

        # Syndication weighting: collapse exact-duplicate headlines (same
        # normalization as compute_distances) so a wire story carried
        # verbatim by N outlets in one camp counts as a single vote toward
        # that camp's centroid, not N - otherwise duplication manufactures
        # false consensus inside the direction axis itself.
        norm_titles = [re.sub(r"\s+", " ", (t or "").strip().lower()) for t in titles]
        dup_counts = {}
        for nt in norm_titles:
            dup_counts[nt] = dup_counts.get(nt, 0) + 1
        synd_w = np.array([1.0 / dup_counts[nt] for nt in norm_titles])

        # synd_w bound as a default so the closure cannot pick up a later
        # iteration's array if this is ever called after the loop advances.
        def _centroid(mask, synd_w=synd_w):
            sub = dense[mask]
            sw = synd_w[mask]
            sw = sw / sw.sum() if sw.sum() > 0 else np.full(sw.shape, 1.0 / len(sw))
            v = sub.T.dot(sw)
            n = np.linalg.norm(v)
            return v / n if n > 0 else v

        Lmask = np.array([le == "left" for le in leans])
        Rmask = np.array([le == "right" for le in leans])
        L = _centroid(Lmask)
        R = _centroid(Rmask)
        outlet_names = [o for o, _ in members]
        # _lean_bucket_weights folds synd_w in already (bucket-normalized over
        # effective votes) — do not multiply synd_w in again here.
        lean_w = _lean_bucket_weights(outlet_names, synd_w)
        lean_w = lean_w / lean_w.sum()
        C_vec = dense.T.dot(lean_w)
        C_norm = np.linalg.norm(C_vec)
        C = C_vec / C_norm if C_norm > 0 else C_vec
        axis = R - L
        sep = float(np.linalg.norm(axis))
        if sep < 1e-9:
            continue
        t = float(np.dot(C - L, axis) / np.dot(axis, axis))
        # consensus headline = full-centroid nearest member
        dists = [1.0 - float(np.dot(dense[i] / (np.linalg.norm(dense[i]) or 1), C))
                 for i in range(len(titles))]
        per_event.append({
            "event_id": eid,
            "position": round(t, 4),
            "separation": round(sep, 4),
            # Effective (syndication-collapsed) vote counts, matching the
            # weighting _centroid() actually uses to place L/R and the
            # plotted position — not raw member counts, which overstate a
            # camp dominated by copies of one wire headline (#C4).
            "n_left": round(float(synd_w[Lmask].sum()), 1),
            "n_right": round(float(synd_w[Rmask].sum()), 1),
            "consensus_headline": titles[int(np.argmin(dists))],
        })

    out = {"per_event": per_event, "n_events_scored": len(per_event)}
    if per_event:
        ts = np.array([e["position"] for e in per_event])
        rng = np.random.default_rng(seed)
        boots = [rng.choice(ts, size=len(ts), replace=True).mean() for _ in range(n_boot)]
        out["mean_position"] = round(float(ts.mean()), 4)
        out["ci_low"] = round(float(np.quantile(boots, 0.025)), 4)
        out["ci_high"] = round(float(np.quantile(boots, 0.975)), 4)
        out["mean_separation"] = round(float(np.mean([e["separation"] for e in per_event])), 4)
    return out


def panel_spectrum(article_rows: list[dict]) -> dict:
    """Five-point AllSides spectrum of the panel: per-category outlet count,
    article count, and coverage-weighted share. Finer than the 3-bucket
    composition so the site can render a true left->right spectrum."""
    cats = ["left", "lean-left", "center", "lean-right", "right"]
    outlets_by = {c: set() for c in cats}
    weight_by = {c: 0.0 for c in cats}
    for r in article_rows:
        c = PANEL_LEAN5.get(r["outlet"])
        if not c:
            continue
        outlets_by[c].add(r["outlet"])
        weight_by[c] += float(r.get("event_outlets", 1))
    total = sum(weight_by.values()) or 1.0
    return {
        "categories": cats,
        "by_category": {
            c: {"outlets": len(outlets_by[c]),
                "weighted_share": round(weight_by[c] / total, 4)}
            for c in cats
        },
        "mean_ordinal": round(
            sum(LEAN_ORDINAL[c] * weight_by[c] for c in cats) / total, 4
        ),
    }


def regional_impact(article_rows: list[dict]) -> dict:
    """Footprint of AllSides-unrated outlets (mostly regional chains) on the
    corpus: their share of analyzed articles, their mean drift vs rated national
    outlets, and how many events they form the majority of. Unrated outlets carry
    no political-lean placement, so the directional analysis cannot see them even
    though they shape the consensus."""
    rated = [r for r in article_rows if PANEL_LEAN5.get(r["outlet"])]
    unrated = [r for r in article_rows if not PANEL_LEAN5.get(r["outlet"])]
    n = len(article_rows) or 1
    by_event = defaultdict(set)
    for r in article_rows:
        by_event[r["event_id"]].add(r["outlet"])
    unrated_majority = sum(
        1 for outs in by_event.values()
        if sum(1 for o in outs if not PANEL_LEAN5.get(o)) > len(outs) / 2
    )
    def mean(xs):
        return round(float(np.mean([x["distance"] for x in xs])), 4) if xs else None
    return {
        "n_total": len(article_rows),
        "n_unrated": len(unrated),
        "pct_unrated": round(100.0 * len(unrated) / n, 1),
        "n_unrated_outlets": len(set(r["outlet"] for r in unrated)),
        "mean_drift_rated": mean(rated),
        "mean_drift_unrated": mean(unrated),
        "events_total": len(by_event),
        "events_unrated_majority": unrated_majority,
    }
