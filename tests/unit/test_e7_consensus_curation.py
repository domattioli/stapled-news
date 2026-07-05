"""Unit tests for E7 display-curation helpers (ranking, weekly, explorer cards)."""

from stapled.experiments.e7_consensus import (
    _curate_members,
    _curate_ranking_for_display,
    _curate_weekly_for_display,
    FAMOUS_OUTLETS,
)


def _member(outlet, distance):
    return {"outlet": outlet, "distance": distance, "title": outlet}


def test_curate_members_caps_one_per_category():
    """A story dominated by one camp should still surface at most one member
    per AllSides lean category, not let that camp fill the card."""
    members = [
        _member("nytimes.com", 0.10),   # lean-left
        _member("cnn.com", 0.12),        # lean-left
        _member("msnbc.com", 0.05),      # left
        _member("foxnews.com", 0.40),    # right
        _member("reuters.com", 0.20),    # center
        _member("some-local-paper.example", 0.30),  # unrated
        _member("nationalreview.com", 0.35),  # lean-right
    ]
    curated = _curate_members(members)
    categories = set()
    from stapled.analyze.consensus_distance import PANEL_LEAN5
    for m in curated:
        cat = PANEL_LEAN5.get(m["outlet"], "unrated")
        assert cat not in categories, f"category {cat} appeared twice"
        categories.add(cat)
    # lean-left had 2 candidates (nytimes, cnn); only one should survive.
    assert len({m["outlet"] for m in curated} & {"nytimes.com", "cnn.com"}) == 1


def test_curate_members_prefers_famous_within_category():
    from stapled.analyze.consensus_distance import PANEL_LEAN5

    # Both lean-left; time.com is not in FAMOUS_OUTLETS but is closer.
    assert PANEL_LEAN5.get("nytimes.com") == "lean-left"
    assert PANEL_LEAN5.get("time.com") == "lean-left"
    assert "time.com" not in FAMOUS_OUTLETS
    members = [
        _member("nytimes.com", 0.20),
        _member("time.com", 0.05),
    ]
    curated = _curate_members(members)
    assert len(curated) == 1
    assert curated[0]["outlet"] == "nytimes.com"


def test_curate_ranking_keeps_small_lists_unchanged():
    ranking = [{"outlet": f"outlet{i}.example", "mean_distance": i / 10} for i in range(5)]
    assert _curate_ranking_for_display(ranking) == ranking


def test_curate_ranking_includes_tail_and_famous():
    ranking = sorted(
        (
            [{"outlet": f"obscure{i}.example", "mean_distance": 0.3 + i * 0.001} for i in range(40)]
            + [{"outlet": "nytimes.com", "mean_distance": 0.05}]
            + [{"outlet": "foxnews.com", "mean_distance": 0.95}]
        ),
        key=lambda r: r["mean_distance"],
    )
    curated = _curate_ranking_for_display(ranking, n_recognizable=20, n_tail=3)
    curated_outlets = {r["outlet"] for r in curated}
    # Recognizable names present.
    assert "nytimes.com" in curated_outlets
    assert "foxnews.com" in curated_outlets
    # Tail ends (nearest and farthest) present even though not "famous".
    assert ranking[0]["outlet"] in curated_outlets
    assert ranking[-1]["outlet"] in curated_outlets
    # Curated list is materially smaller than the full one.
    assert len(curated) < len(ranking)
    # Still sorted by mean_distance.
    assert curated == sorted(curated, key=lambda r: r["mean_distance"])


def test_curate_weekly_spreads_across_spectrum():
    # Two famous outlets per lean category, each with a distinct week count.
    weekly = {}
    per_category = {
        "left": ["msnbc.com", "huffpost.com"],
        "lean-left": ["nytimes.com", "cnn.com"],
        "center": ["reuters.com", "apnews.com"],
        "lean-right": ["nationalreview.com", "nypost.com"],
        "right": ["foxnews.com", "newsmax.com"],
    }
    for outlets in per_category.values():
        for j, outlet in enumerate(outlets):
            weekly[outlet] = [{"week": f"2026-W{20+w}", "mean_distance": 0.1} for w in range(5 - j)]

    curated = _curate_weekly_for_display(weekly, target=8)
    assert len(curated) <= 8
    from stapled.analyze.consensus_distance import PANEL_LEAN5
    categories_present = {PANEL_LEAN5.get(o) for o in curated}
    # Should draw from more than just one or two categories.
    assert len(categories_present) >= 4
    # Only FAMOUS_OUTLETS should ever be picked.
    assert all(o in FAMOUS_OUTLETS for o in curated)


def test_curate_weekly_ignores_non_famous_and_empty():
    weekly = {
        "nytimes.com": [{"week": "2026-W20", "mean_distance": 0.1}],
        "obscure-blog.example": [{"week": "2026-W20", "mean_distance": 0.1}],
        "cnn.com": [],
    }
    curated = _curate_weekly_for_display(weekly, target=8)
    assert "obscure-blog.example" not in curated
    assert "cnn.com" not in curated
    assert "nytimes.com" in curated
