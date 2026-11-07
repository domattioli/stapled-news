"""Command-line interface for experiments."""

import argparse
import sys
from pathlib import Path

from stapled.experiments.runner import run_experiment
from stapled.experiments import e1_recovery
from stapled.experiments import e2_syndication
from stapled.experiments import e3_isot
from stapled.experiments import e3b_fnn
from stapled.experiments import e4_external
from stapled.experiments import e5_omission
from stapled.experiments import e6_anchoring
from stapled.experiments import e7_consensus


def main(argv=None):
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run stapled-news experiments")
    parser.add_argument(
        "experiment",
        choices=["e1", "e2", "e3", "e3b", "e4", "e4_uci", "e5", "e6", "e7"],
        help="Experiment name",
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--n-seeds", type=int, default=1, help="Run seeds seed..seed+N-1 (default 1)")
    parser.add_argument("--quick", action="store_true", help="Quick mode (2 seeds instead of 30)")
    parser.add_argument("--out-dir", default="results", help="Output directory (default: results)")
    parser.add_argument(
        "--db-path",
        default=None,
        help="Input DB for e3, e3b, e4, e4_uci (e4_uci default: uci.db)",
    )

    args = parser.parse_args(argv)
    if args.n_seeds < 1:
        parser.error("--n-seeds must be >= 1")

    # Map experiment names to modules and functions
    experiment_map = {
        "e1": (e1_recovery, "run"),
        "e2": (e2_syndication, "run"),
        "e3": (e3_isot, "run"),
        "e3b": (e3b_fnn, "run"),
        "e4": (e4_external, "run"),
        "e4_uci": (e4_external, "run"),
        "e5": (e5_omission, "run"),
        "e6": (e6_anchoring, "run"),
        "e7": (e7_consensus, "run"),
    }

    if args.experiment not in experiment_map:
        print(f"Unknown experiment: {args.experiment}", file=sys.stderr)
        sys.exit(1)

    module, fn_name = experiment_map[args.experiment]
    fn = getattr(module, fn_name)

    # Build config
    if args.experiment == "e4_uci":
        config = {
            "db_path": args.db_path or "uci.db",
            "min_outlets": 2,
            "batch_size": 32,
            "min_articles_per_outlet": 5,
            "min_obs": 3,
        }
    else:
        config = {
            "quick": args.quick,
        }
        if args.db_path and args.experiment in ("e3", "e3b", "e4"):
            config["db_path"] = args.db_path

    for seed in range(args.seed, args.seed + args.n_seeds):
        out_dir = args.out_dir if args.n_seeds == 1 else str(Path(args.out_dir) / f"seed_{seed}")

        # Run experiment
        entry = run_experiment(args.experiment, fn, config, seed, out_dir=out_dir)

        # Print summary
        print(f"Experiment {args.experiment} completed")
        print(f"  Seed: {entry['seed']}")
        print(f"  Outputs: {len(entry['outputs'])} files")
        print(f"  Git SHA: {entry['git_sha'][:8]}")
        print(f"  Config hash: {entry['config_hash'][:8]}")
        if entry.get("metrics"):
            print(f"  Metrics: {entry['metrics']}")


if __name__ == "__main__":
    main()
