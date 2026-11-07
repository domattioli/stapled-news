"""Export the golden parity fixture for the browser "Fool the crowd" demo.

Usage: .venv/bin/python scripts/export_ftc_golden.py [--out results/ftc_golden.json]
Copy the output to domattioli.github.io src/scripts/fool-the-crowd/__fixtures__/golden.json.
"""

import argparse

from stapled.export.ftc_golden import write_fixture


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="results/ftc_golden.json")
    ap.add_argument("--synth-config", default="configs/synth-baseline.yml")
    ap.add_argument("--e1-csv", default="results/e1_recovery.csv")
    a = ap.parse_args()
    fx = write_fixture(a.out, a.synth_config, a.e1_csv)
    print(f"wrote {a.out}: schema {fx['schema']}, {len(fx['cases'])} cases")


if __name__ == "__main__":
    main()
