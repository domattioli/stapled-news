"""Synthetic news corpus generation with seeded ground truth."""

import sqlite3
import numpy as np
import json
from datetime import datetime, timedelta


# Word templates for article generation
COMMON_WORDS = [
    "announced",
    "reported",
    "confirmed",
    "denied",
    "claimed",
    "alleged",
    "revealed",
    "stated",
    "indicated",
    "suggested",
]

ACTOR_WORDS = [
    "officials",
    "representatives",
    "spokespersons",
    "sources",
    "analysts",
    "experts",
]

OBJECT_WORDS = [
    "development",
    "incident",
    "situation",
    "matter",
    "issue",
    "event",
    "occurrence",
]


def generate(
    conn: sqlite3.Connection, config: dict, seed: int
) -> int:
    """Generate synthetic corpus with seeded RNG and ground truth. Returns corpus_id."""
    rng = np.random.default_rng(seed)

    # Extract config
    outlets_cfg = config.get("outlets", [])
    n_events = config.get("n_events", 20)
    articles_per_event_per_outlet = config.get("articles_per_event_per_outlet", 1)

    # Create outlets and seed truth parameters
    outlet_ids = {}
    outlet_params = {}
    for outlet_cfg in outlets_cfg:
        name = outlet_cfg["name"]
        reliability = outlet_cfg["reliability"]
        bias = outlet_cfg["bias"]
        calibration = outlet_cfg["calibration"]

        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (name,)
        )
        outlet_id = cursor.lastrowid
        outlet_ids[name] = outlet_id
        outlet_params[outlet_id] = {
            "reliability": reliability,
            "bias": bias,
            "calibration": calibration,
        }

    # Create corpus record
    params_json = json.dumps(
        {
            "outlets": [
                {
                    "name": name,
                    "reliability": outlet_params[outlet_ids[name]]["reliability"],
                    "bias": outlet_params[outlet_ids[name]]["bias"],
                    "calibration": outlet_params[outlet_ids[name]]["calibration"],
                }
                for name in outlet_ids
            ],
            "n_events": n_events,
            "articles_per_event_per_outlet": articles_per_event_per_outlet,
        }
    )
    cursor = conn.execute(
        "INSERT INTO corpus (seed, params_json, validation_status) VALUES (?, ?, 'pending')",
        (seed, params_json),
    )
    corpus_id = cursor.lastrowid

    # Store seeded outlet parameters
    for outlet_id, params in outlet_params.items():
        conn.execute(
            "INSERT INTO outlet_truth (corpus_id, outlet_id, reliability, bias, calibration) VALUES (?, ?, ?, ?, ?)",
            (
                corpus_id,
                outlet_id,
                params["reliability"],
                params["bias"],
                params["calibration"],
            ),
        )

    # Generate events and articles
    base_date = datetime(2024, 1, 1)
    for event_idx in range(n_events):
        # Sample ground truth
        true_state = int(rng.binomial(1, 0.5))
        true_magnitude = int(rng.choice([0, 1, 2]))

        cursor = conn.execute(
            "INSERT INTO event (corpus_id, label, true_state, true_magnitude_bucket) VALUES (?, ?, ?, ?)",
            (corpus_id, f"Event {event_idx + 1}", true_state, true_magnitude),
        )
        event_id = cursor.lastrowid

        # Generate articles from each outlet
        for outlet_name, outlet_id in outlet_ids.items():
            params = outlet_params[outlet_id]
            for article_idx in range(articles_per_event_per_outlet):
                # Outlet reports correct state with prob = reliability (adjusted by bias)
                adj_reliability = _adjust_reliability_by_bias(
                    params["reliability"], params["bias"], true_state
                )
                reported_state = (
                    true_state if rng.random() < adj_reliability else 1 - true_state
                )

                # Generate article text
                title, body = _generate_article_text(
                    rng,
                    outlet_name,
                    event_idx + 1,
                    reported_state,
                    params["bias"],
                )

                # Create article
                url = f"synth://corpus/{corpus_id}/outlet/{outlet_id}/event/{event_id}/article/{article_idx}"
                pub_date = base_date + timedelta(days=event_idx)
                cursor = conn.execute(
                    "INSERT INTO article (outlet_id, corpus_id, url, published_at, title, body, ingest_status) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'ok')",
                    (
                        outlet_id,
                        corpus_id,
                        url,
                        pub_date.isoformat(),
                        title,
                        body,
                    ),
                )
                article_id = cursor.lastrowid

                # Generate claim pre-aligned to event
                claimed_magnitude = (
                    true_magnitude
                    if rng.random() < params["reliability"]
                    else int(rng.choice([b for b in [0, 1, 2] if b != true_magnitude]))
                )

                certainty = np.clip(
                    rng.normal(params["reliability"], 0.1), 0.01, 0.99
                )
                certainty *= params["calibration"]
                certainty = np.clip(certainty, 0.01, 0.99)

                valence = rng.uniform(-1, 1)
                # Bias influences valence slightly
                valence = np.clip(valence + params["bias"] * 0.3, -1, 1)

                extraction_score = 1.0  # Synthetic has perfect extraction

                conn.execute(
                    "INSERT INTO claim "
                    "(article_id, event_id, actor, action, object, "
                    "certainty, valence, hedging, attribution, extraction_score, magnitude_value) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        article_id,
                        event_id,
                        "officials",
                        "occurred" if reported_state else "did-not-occur",
                        "event",
                        certainty,
                        valence,
                        "none",
                        "official",
                        extraction_score,
                        float(claimed_magnitude),
                    ),
                )

    conn.commit()
    return corpus_id


def _adjust_reliability_by_bias(reliability: float, bias: float, true_state: int) -> float:
    """Adjust outlet reliability by bias direction. Positive bias helps state=1 reporting."""
    if true_state == 1:
        # When true state is 1, positive bias helps correct reporting
        adjustment = bias * 0.2
    else:
        # When true state is 0, positive bias hurts correct reporting
        adjustment = -bias * 0.2

    return np.clip(reliability + adjustment, 0.02, 0.98)


def _generate_article_text(
    rng: np.random.Generator,
    outlet_name: str,
    event_num: int,
    reported_state: int,
    bias: float,
) -> tuple:
    """Generate synthetic article title and body."""
    action = "occurred" if reported_state else "did not occur"

    # Outlet-specific vocabulary
    words_pool = {
        "reliable-press": COMMON_WORDS + ["confirmed", "verified"],
        "balanced-news": COMMON_WORDS + ["reported"],
        "center-weekly": COMMON_WORDS + ["suggested"],
        "moderate-journal": COMMON_WORDS + ["alleged"],
        "tabloid-mirror": COMMON_WORDS + ["claimed", "allegedly"],
    }

    vocab = words_pool.get(outlet_name, COMMON_WORDS)
    verb = vocab[rng.integers(0, len(vocab))]
    actor = ACTOR_WORDS[rng.integers(0, len(ACTOR_WORDS))]
    obj = OBJECT_WORDS[rng.integers(0, len(OBJECT_WORDS))]

    title = f"Event {event_num}: {verb.capitalize()} {action.lower()}"
    body = f"{actor.capitalize()} {verb} that the {obj} {action}. " \
           f"This is a report from {outlet_name}. " \
           f"Sources indicate the development was significant."

    return title, body
