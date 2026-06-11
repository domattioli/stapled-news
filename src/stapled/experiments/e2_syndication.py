"""E2: Syndication distortion experiment via deduplication."""

import os
import tempfile
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import spearmanr

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from stapled.db import connect
from stapled.synth.generator import generate
from stapled.infer.online_em import OnlineEM
from stapled.ingest.dedup import dedup_articles


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E2 syndication distortion experiment.

    Config keys:
        multiplicities: List of syndication multiplicities to test (default [1,2,5,10,20])
        quick: If True, override multiplicities=[1,5] and n_seeds=3
        synth_config_path: Path to synth config YAML (default "configs/synth-baseline.yml")
        n_seeds: Number of seeds per multiplicity (default 10)
        perturb: If True, run both "exact" and "perturbed" modes (default True)

    Returns:
        dict with outputs (CSV, PNG paths) and metrics
    """
    # Parse config
    multiplicities = config.get("multiplicities", [1, 2, 5, 10, 20])
    quick = config.get("quick", False)
    n_seeds = config.get("n_seeds", 10)
    perturb = config.get("perturb", True)
    synth_config_path = config.get("synth_config_path", "configs/synth-baseline.yml")

    if quick:
        multiplicities = [1, 5]
        n_seeds = 3

    # Load synth config
    synth_config = _load_synth_config(synth_config_path)

    # Run experiment for each (mode, multiplicity, seed)
    results = []
    modes = ["exact", "perturbed"] if perturb else ["exact"]

    for mode in modes:
        for m in multiplicities:
            for s in range(n_seeds):
                seed_results = _run_seed(
                    s, seed, synth_config, m, mode
                )
                results.extend(seed_results)

    # Write CSV
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    csv_path = out_path / "e2_syndication.csv"

    # Sort deterministically
    results.sort(key=lambda r: (r["mode"], r["multiplicity"], r["seed"], r["dedup"]))

    with open(csv_path, "w") as f:
        f.write("mode,multiplicity,seed,dedup,rho,wire_reliability_est\n")
        for r in results:
            f.write(
                f"{r['mode']},{r['multiplicity']},{r['seed']},"
                f"{r['dedup']},{r['rho']:.6f},{r['wire_reliability_est']:.6f}\n"
            )

    # Compute metrics
    metrics = _compute_metrics(results)

    # Create plots
    png_paths = _create_plots(results, out_path)

    return {
        "outputs": [str(csv_path)] + [str(p) for p in png_paths],
        "metrics": metrics,
    }


def _load_synth_config(path: str) -> dict:
    """Load synth config from YAML file."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _run_seed(
    seed_idx: int, base_seed: int, synth_config: dict, multiplicity: int, mode: str
) -> list:
    """
    Run experiment for one (seed, multiplicity, mode) triplet.
    Returns list of dicts with results.
    """
    actual_seed = base_seed + seed_idx

    # Create temp DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        conn = connect(db_path)

        # Generate synthetic corpus
        corpus_id = generate(conn, synth_config, seed=actual_seed)

        # Get outlet IDs
        cursor = conn.execute("SELECT id FROM outlet WHERE is_synthetic = 1 ORDER BY id")
        outlet_ids = [row[0] for row in cursor.fetchall()]

        # Load planted reliability parameters
        cursor = conn.execute(
            "SELECT outlet_id, reliability FROM outlet_truth WHERE corpus_id = ?",
            (corpus_id,),
        )
        planted = {}
        for outlet_id, reliability in cursor.fetchall():
            planted[outlet_id] = reliability

        # Find wire outlet (lowest reliability)
        wire_outlet_id = min(planted.keys(), key=lambda oid: planted[oid])
        other_outlet_ids = [oid for oid in outlet_ids if oid != wire_outlet_id]

        # Inject syndication duplicates if m > 1
        if multiplicity > 1:
            rng = np.random.default_rng(actual_seed + 1000)  # Separate seed for perturbations
            _inject_syndication(
                conn, wire_outlet_id, other_outlet_ids, multiplicity, mode, rng
            )

        # Run dedup to cluster duplicates
        dedup_articles(conn)

        # Get event IDs
        cursor = conn.execute(
            "SELECT id FROM event WHERE corpus_id = ? ORDER BY id",
            (corpus_id,),
        )
        event_ids = [row[0] for row in cursor.fetchall()]

        results = []

        # Run OnlineEM with dedup=True
        em_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)
        _run_em(em_dedup, event_ids, 8)
        est_params = em_dedup.params()
        rho = _compute_rho(planted, est_params, exclude_injected=False)
        wire_est = est_params.get(wire_outlet_id, {}).get("reliability", 0.0)
        results.append({
            "mode": mode,
            "multiplicity": multiplicity,
            "seed": seed_idx,
            "dedup": True,
            "rho": rho,
            "wire_reliability_est": wire_est,
        })

        # Run OnlineEM with dedup=False
        conn.execute("DELETE FROM em_suffstats")
        conn.execute("DELETE FROM em_state")
        conn.execute("DELETE FROM reliability_snapshot")
        conn.commit()

        em_nodedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
        _run_em(em_nodedup, event_ids, 8)
        est_params = em_nodedup.params()
        rho = _compute_rho(planted, est_params, exclude_injected=False)
        wire_est = est_params.get(wire_outlet_id, {}).get("reliability", 0.0)
        results.append({
            "mode": mode,
            "multiplicity": multiplicity,
            "seed": seed_idx,
            "dedup": False,
            "rho": rho,
            "wire_reliability_est": wire_est,
        })

        conn.close()
        return results

    finally:
        # Clean up temp DB
        try:
            os.remove(db_path)
        except OSError:
            pass


def _inject_syndication(
    conn,
    wire_outlet_id: int,
    other_outlet_ids: list,
    multiplicity: int,
    mode: str,
    rng: np.random.Generator,
) -> int:
    """
    Inject syndication duplicates for wire outlet articles.
    For each article from wire_outlet_id, create (m-1) duplicates
    attributed to other outlets, copying or perturbing the body.

    Returns: count of articles inserted.
    """
    # Get all articles from wire outlet
    cursor = conn.execute(
        "SELECT id, corpus_id, url, title, body, published_at, outlet_id "
        "FROM article WHERE outlet_id = ?",
        (wire_outlet_id,),
    )
    wire_articles = cursor.fetchall()

    count = 0
    for article_id, corpus_id, url, title, body, pub_date, _ in wire_articles:
        # Get claims for this article
        cursor = conn.execute(
            "SELECT event_id, actor, action, object, certainty, valence, hedging, "
            "attribution, extraction_score, magnitude_value "
            "FROM claim WHERE article_id = ?",
            (article_id,),
        )
        claims = cursor.fetchall()

        # Create (m-1) duplicates in other outlets
        for dup_idx in range(multiplicity - 1):
            outlet_idx = (dup_idx + wire_outlet_id) % len(other_outlet_ids)
            dup_outlet_id = other_outlet_ids[outlet_idx]

            # Perturb body if mode='perturbed'
            dup_body = body
            if mode == "perturbed":
                dup_body = _perturb_text(body, rng)

            # Insert duplicate article
            dup_url = f"{url}?dup={dup_idx}"
            cursor = conn.execute(
                "INSERT INTO article "
                "(outlet_id, corpus_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?, 'ok')",
                (dup_outlet_id, corpus_id, dup_url, title, dup_body, pub_date),
            )
            dup_article_id = cursor.lastrowid

            # Copy claims to duplicate article
            for (
                event_id,
                actor,
                action,
                obj,
                certainty,
                valence,
                hedging,
                attribution,
                extraction_score,
                magnitude_value,
            ) in claims:
                conn.execute(
                    "INSERT INTO claim "
                    "(article_id, event_id, actor, action, object, certainty, valence, "
                    "hedging, attribution, extraction_score, magnitude_value) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        dup_article_id,
                        event_id,
                        actor,
                        action,
                        obj,
                        certainty,
                        valence,
                        hedging,
                        attribution,
                        extraction_score,
                        magnitude_value,
                    ),
                )

            count += 1

    conn.commit()
    return count


def _perturb_text(text: str, rng: np.random.Generator) -> str:
    """
    Lightly perturb text by changing ~5% of words.
    Swap a couple of words or append a few tokens.
    """
    words = text.split()
    if len(words) == 0:
        return text

    # 5% of words
    n_change = max(1, int(0.05 * len(words)))

    # Randomly select positions to change
    change_positions = rng.choice(len(words), size=min(n_change, len(words)), replace=False)

    for pos in change_positions:
        # Randomly choose perturbation: swap or append
        if rng.random() < 0.5:
            # Swap with adjacent word
            if pos < len(words) - 1:
                words[pos], words[pos + 1] = words[pos + 1], words[pos]
        else:
            # Append a token (modifier)
            modifiers = ["additional", "further", "extra", "more", "noted"]
            modifier = modifiers[rng.integers(0, len(modifiers))]
            words[pos] = words[pos] + modifier

    return " ".join(words)


def _run_em(em, event_ids: list, batch_size: int):
    """Run EM over event IDs in batches."""
    for batch_idx in range(0, len(event_ids), batch_size):
        batch_ids = event_ids[batch_idx : batch_idx + batch_size]
        result = em.e_step_batch(batch_ids)
        em.accumulate(result["batch_stats"], batch_idx // batch_size)


def _compute_rho(
    planted: dict, est_params: dict, exclude_injected: bool = False
) -> float:
    """
    Compute Spearman rho between planted and estimated reliability.

    planted: {outlet_id: reliability}
    est_params: {outlet_id: {"reliability", "sens", "spec", ...}}
    exclude_injected: not used in E2 (kept for API compatibility)
    """
    planted_list = []
    est_list = []

    for outlet_id in planted:
        if outlet_id in est_params:
            planted_list.append(planted[outlet_id])
            params = est_params[outlet_id]
            if "reliability" in params:
                reliability = params["reliability"]
            elif "sens" in params and "spec" in params:
                reliability = (params["sens"] + params["spec"]) / 2
            else:
                reliability = 0.5  # default
            est_list.append(reliability)

    if len(planted_list) < 2:
        return 0.0

    rho, _ = spearmanr(planted_list, est_list)
    return float(rho) if not np.isnan(rho) else 0.0


def _compute_metrics(results: list) -> dict:
    """Compute summary metrics from all results."""
    # Group by mode, multiplicity, dedup
    by_config = {}
    for r in results:
        key = (r["mode"], r["multiplicity"], r["dedup"])
        if key not in by_config:
            by_config[key] = []
        by_config[key].append(r["rho"])

    # Compute mean rho by (mode, m, dedup)
    mean_rho_by_m = {"dedup_on": {}, "dedup_off": {}}

    for (mode, m, dedup), rhos in by_config.items():
        if mode == "exact":  # Focus on exact mode for primary metric
            rhos_arr = np.array(rhos)
            mean_rho = float(np.mean(rhos_arr))

            dedup_key = "dedup_on" if dedup else "dedup_off"
            if m not in mean_rho_by_m[dedup_key]:
                mean_rho_by_m[dedup_key][m] = mean_rho

    # Compute distortion metric: rho_off - rho_on at largest m
    max_m = max(m for (_, m, _) in by_config.keys())
    rho_off_max = mean_rho_by_m["dedup_off"].get(max_m, 0.0)
    rho_on_max = mean_rho_by_m["dedup_on"].get(max_m, 0.0)
    distortion = rho_off_max - rho_on_max

    metrics = {
        "mean_rho_by_m": mean_rho_by_m,
        "distortion_at_max_m": distortion,
    }

    return metrics


def _create_plots(results: list, out_path: Path) -> list:
    """Create plots: one for exact mode, one for perturbed mode."""
    import matplotlib as mpl

    # Group results by (mode, multiplicity, dedup)
    by_mode = {}
    for r in results:
        mode = r["mode"]
        if mode not in by_mode:
            by_mode[mode] = {}
        key = (r["multiplicity"], r["dedup"])
        if key not in by_mode[mode]:
            by_mode[mode][key] = []
        by_mode[mode][key].append(r["rho"])

    mpl.rcParams.update({
        'figure.facecolor': '#f0f0f0',
        'axes.facecolor': '#f0f0f0',
        'font.family': 'DejaVu Sans',
        'axes.titlesize': 14,
        'axes.titleweight': 'bold',
        'axes.grid': True,
        'grid.color': '#cccccc',
        'grid.linestyle': '-',
        'grid.linewidth': 0.5,
    })

    png_paths = []

    # Create one plot per mode
    for mode in sorted(by_mode.keys()):
        fig, ax = plt.subplots(figsize=(10, 6))

        # Extract multiplicities and compute means
        multiplicities = sorted(
            set(m for (m, _) in by_mode[mode].keys())
        )
        mean_rho_on = []
        mean_rho_off = []

        for m in multiplicities:
            rhos_on = by_mode[mode].get((m, True), [0.0])
            rhos_off = by_mode[mode].get((m, False), [0.0])
            mean_rho_on.append(np.mean(rhos_on))
            mean_rho_off.append(np.mean(rhos_off))

        # Plot lines
        ax.plot(
            multiplicities,
            mean_rho_on,
            marker='o',
            linewidth=2.5,
            label='dedup=on',
            color='#5b9bd5',
        )
        ax.plot(
            multiplicities,
            mean_rho_off,
            marker='s',
            linewidth=2.5,
            label='dedup=off',
            color='#ff7f0e',
        )

        ax.set_xlabel("Syndication Multiplicity (m)", fontsize=11)
        ax.set_ylabel("Mean Spearman ρ (Planted vs. Estimated Reliability)", fontsize=11)
        ax.set_title(f"E2: Syndication Distortion vs Deduplication ({mode} mode)", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10, loc='best')
        ax.grid(True, alpha=0.3)

        caption = (
            "As m grows, dedup=off degrades (echoed unreliable wire vote corrupts consensus) "
            "while dedup=on stays flat/high (clustering prevents vote inflation)."
        )
        ax.text(
            0.5,
            -0.15,
            caption,
            transform=ax.transAxes,
            ha="center",
            fontsize=9,
            style="italic",
            wrap=True,
        )

        plt.tight_layout()

        png_name = f"e2_syndication_{mode}.png" if mode != "exact" else "e2_syndication.png"
        png_path = out_path / png_name
        plt.savefig(png_path, dpi=100, bbox_inches="tight")
        plt.close()

        png_paths.append(png_path)

    return png_paths
