"""Command-line interface for experiments."""

import argparse
import sys

from stapled.experiments.runner import run_experiment
from stapled.experiments import e1_recovery
from stapled.experiments import e2_syndication
from stapled.experiments import e3_isot


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Run stapled-news experiments")
    parser.add_argument("experiment", choices=["e1", "e2", "e3"], help="Experiment name")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    parser.add_argument("--quick", action="store_true", help="Quick mode (2 seeds instead of 30)")
    parser.add_argument("--out-dir", default="results", help="Output directory (default: results)")

    args = parser.parse_args()

    # Map experiment names to modules and functions
    experiment_map = {
        "e1": (e1_recovery, "run"),
        "e2": (e2_syndication, "run"),
        "e3": (e3_isot, "run"),
    }

    if args.experiment not in experiment_map:
        print(f"Unknown experiment: {args.experiment}", file=sys.stderr)
        sys.exit(1)

    module, fn_name = experiment_map[args.experiment]
    fn = getattr(module, fn_name)

    # Build config
    config = {
        "quick": args.quick,
    }

    # Run experiment
    entry = run_experiment(args.experiment, fn, config, args.seed, out_dir=args.out_dir)

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
