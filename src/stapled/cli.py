"""CLI interface for stapled-news."""

import json
import sys
from pathlib import Path
from typing import List, Optional

import typer
import yaml

from stapled import __version__
from stapled.db import connect
from stapled.gates import GateError, assert_corpus_passed, assert_recovery_passed
from stapled.synth.generator import generate as synth_generate
from stapled.synth.validate import validate as synth_validate
from stapled.infer.model import RunConfig
from stapled.infer.em import run_em
from stapled.recover.score import score as score_run
from stapled.export.site import export_run
from stapled.ingest.csv_loader import load_isot as load_isot_data
from stapled.ingest.dedup import dedup_articles
from stapled.extract.claims import extract_all_unextracted
from stapled.extract.framing import update_all_framing
from stapled.align.cluster import align

app = typer.Typer()
synth_app = typer.Typer()
app.add_typer(synth_app, name="synth")


class CLIOutput:
    """Helper for JSON/human output."""

    def __init__(self, json_mode: bool = False):
        self.json_mode = json_mode
        self.data = {}
        self.errors = []

    def set_data(self, **kwargs):
        self.data.update(kwargs)

    def add_error(self, msg: str):
        self.errors.append(msg)

    def print_table(self, rows: List[dict], columns: List[str], title: str = ""):
        """Print a human-readable table."""
        if self.json_mode:
            return
        if title:
            print(f"\n{title}", file=sys.stderr)
        if not rows:
            print("  (no results)", file=sys.stderr)
            return
        # Simple table format
        col_widths = {col: max(len(col), max(len(str(r.get(col, ""))) for r in rows)) for col in columns}
        header = "  " + " | ".join(col.ljust(col_widths[col]) for col in columns)
        print(header, file=sys.stderr)
        print("  " + "-" * (len(header) - 2), file=sys.stderr)
        for row in rows:
            print("  " + " | ".join(str(row.get(col, "")).ljust(col_widths[col]) for col in columns), file=sys.stderr)

    def output(self, command: str, exit_code: int = 0):
        """Print final output."""
        if self.json_mode:
            output = {
                "command": command,
                "ok": exit_code == 0,
                "exit_code": exit_code,
                "data": self.data,
                "errors": self.errors,
            }
            print(json.dumps(output))
        if exit_code != 0:
            for error in self.errors:
                print(f"Error: {error}", file=sys.stderr)


def _handle_gate_error(err: GateError, out: CLIOutput, command: str) -> int:
    """Handle GateError and return exit code."""
    out.add_error(str(err))
    out.output(command, exit_code=2)
    raise typer.Exit(code=2)


@app.command()
def status(db: str = typer.Option("./stapled.db", help="Path to database")):
    """Show database and gate status."""
    out = CLIOutput()
    try:
        conn = connect(db)

        # Corpus summary
        cursor = conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN validation_status='PASSED' THEN 1 ELSE 0 END) "
            "FROM corpus"
        )
        total_corpora, passed_corpora = cursor.fetchone()

        # Run summary
        cursor = conn.execute(
            "SELECT status, COUNT(*) FROM inference_run GROUP BY status"
        )
        run_summary = {row[0]: row[1] for row in cursor.fetchall()}

        # Recovery gate
        cursor = conn.execute(
            "SELECT COUNT(*) FROM recovery_report WHERE verdict='PASS'"
        )
        passing_recovery = cursor.fetchone()[0]

        out.set_data(
            corpora_total=total_corpora,
            corpora_passed=passed_corpora,
            runs_summary=run_summary,
            recovery_gate_passed=passing_recovery > 0,
        )

        rows = [
            {"key": "Total corpora", "value": str(total_corpora)},
            {"key": "Passed corpora", "value": str(passed_corpora)},
            {"key": "Inference runs", "value": json.dumps(run_summary)},
            {"key": "Recovery gate", "value": "PASS" if passing_recovery > 0 else "BLOCKED"},
        ]
        out.print_table(rows, ["key", "value"], "Database Status")
        out.output("status", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("status", exit_code=1)
        raise typer.Exit(code=1)


@synth_app.command("generate")
def synth_generate_cmd(
    config: str = typer.Option(..., help="Path to config YAML"),
    seed: int = typer.Option(42, help="RNG seed"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Generate synthetic corpus."""
    out = CLIOutput(json_mode=json_output)
    try:
        config_path = Path(config)
        if not config_path.exists():
            raise FileNotFoundError(f"Config not found: {config}")

        config_data = yaml.safe_load(config_path.read_text())
        conn = connect(db)
        corpus_id = synth_generate(conn, config_data, seed)

        out.set_data(corpus_id=corpus_id)
        out.print_table([{"corpus_id": corpus_id}], ["corpus_id"], "Synthetic Corpus Generated")
        out.output("synth generate", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("synth generate", exit_code=1)
        raise typer.Exit(code=1)


@synth_app.command("validate")
def synth_validate_cmd(
    corpus: int = typer.Option(..., help="Corpus ID"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Validate synthetic corpus."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        report = synth_validate(conn, corpus)

        out.set_data(report=report)
        rows = [
            {"check": c["name"], "passed": "YES" if c["passed"] else "NO", "detail": c["detail"]}
            for c in report["checks"]
        ]
        out.print_table(rows, ["check", "passed", "detail"], "Validation Report")

        exit_code = 0 if report["status"] == "PASSED" else 3
        out.output("synth validate", exit_code=exit_code)
        raise typer.Exit(code=exit_code)

    except typer.Exit:
        raise
    except Exception as e:
        out.add_error(str(e))
        out.output("synth validate", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def load_isot(
    true_csv: str = typer.Option(..., "--true-csv", help="Path to True.csv"),
    fake_csv: str = typer.Option(..., "--fake-csv", help="Path to Fake.csv"),
    limit: Optional[int] = typer.Option(None, "--limit", help="Limit per outlet"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Load ISOT dataset (Reuters + fake outlets)."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        counts = load_isot_data(conn, true_csv, fake_csv, limit_per_outlet=limit)

        out.set_data(**counts)
        rows = [
            {"metric": "Articles loaded", "value": str(counts["articles_loaded"])},
            {"metric": "Articles skipped", "value": str(counts["articles_skipped"])},
            {"metric": "Outlets created", "value": str(counts["outlets_created"])},
        ]
        out.print_table(rows, ["metric", "value"], "ISOT Load Complete")
        out.output("load_isot", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("load_isot", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def dedup(
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Run near-duplicate detection."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        n_clusters = dedup_articles(conn)

        out.set_data(dedup_clusters=n_clusters)
        rows = [{"dedup_clusters": n_clusters}]
        out.print_table(rows, ["dedup_clusters"], "Dedup Complete")
        out.output("dedup", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("dedup", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def extract(
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Extract claims from articles."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        counts = extract_all_unextracted(conn)

        # Update framing
        framing_counts = update_all_framing(conn)

        out.set_data(**counts, **framing_counts)
        rows = [
            {"metric": "Articles processed", "value": str(counts["articles_processed"])},
            {"metric": "Claims created", "value": str(counts["claims_created"])},
            {"metric": "Claims framed", "value": str(framing_counts["claims_updated"])},
        ]
        out.print_table(rows, ["metric", "value"], "Extraction Complete")
        out.output("extract", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("extract", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def align_cmd(
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Align claims into events."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        stats = align(conn)

        out.set_data(**stats)
        rows = [
            {"metric": "Events created", "value": str(stats["events_created"])},
            {"metric": "Claims aligned", "value": str(stats["claims_aligned"])},
            {"metric": "Claims unaligned", "value": str(stats["claims_unaligned"])},
        ]
        out.print_table(rows, ["metric", "value"], "Alignment Complete")
        out.output("align", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("align", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def infer(
    synthetic: bool = typer.Option(False, "--synthetic", help="Synthetic corpus mode"),
    real: bool = typer.Option(False, "--real", help="Real-data mode"),
    corpus: Optional[int] = typer.Option(None, help="Corpus ID (synthetic mode)"),
    event_ids: Optional[str] = typer.Option(None, help="Event IDs (real mode)"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Run EM inference."""
    out = CLIOutput(json_mode=json_output)
    try:
        if not (synthetic or real):
            raise ValueError("Must specify --synthetic or --real")
        if synthetic and real:
            raise ValueError("Cannot specify both --synthetic and --real")

        conn = connect(db)

        if synthetic:
            if corpus is None:
                raise ValueError("--corpus required for synthetic mode")
            assert_corpus_passed(conn, corpus)
            config = RunConfig()
            run_id = run_em(conn, corpus, config, is_real=False)
        else:
            # Real mode requires recovery gate
            try:
                assert_recovery_passed(conn)
            except GateError as e:
                _handle_gate_error(e, out, "infer --real")
            config = RunConfig()
            run_id = run_em(conn, None, config, is_real=True)

        out.set_data(run_id=run_id)
        out.print_table([{"run_id": run_id}], ["run_id"], "Inference Complete")
        out.output("infer", exit_code=0)

    except GateError as e:
        _handle_gate_error(e, out, "infer")
    except Exception as e:
        out.add_error(str(e))
        out.output("infer", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def score(
    run: int = typer.Option(..., help="Run ID"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Score a synthetic run."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        result = score_run(conn, run)

        out.set_data(**result)
        rows = [
            {"metric": "State Accuracy", "value": f"{result['state_accuracy']:.3f}"},
            {"metric": "Rank Correlation", "value": f"{result['reliability_rank_corr']:.3f}"},
            {"metric": "Verdict", "value": result["verdict"]},
        ]
        out.print_table(rows, ["metric", "value"], "Recovery Score")

        exit_code = 0 if result["verdict"] == "PASS" else 3
        out.output("score", exit_code=exit_code)
        raise typer.Exit(code=exit_code)

    except typer.Exit:
        raise
    except Exception as e:
        out.add_error(str(e))
        out.output("score", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def export(
    run: int = typer.Option(..., help="Run ID"),
    out_dir: str = typer.Option(..., "--out", help="Output directory"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Export run to static site."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)
        export_run(conn, run, out_dir)

        out.set_data(output_dir=out_dir)
        out.print_table([{"file": "index.html"}, {"file": "run.html"}, {"file": "run.json"}],
                        ["file"], "Exported Files")
        out.output("export", exit_code=0)

    except GateError as e:
        _handle_gate_error(e, out, "export")
    except Exception as e:
        out.add_error(str(e))
        out.output("export", exit_code=1)
        raise typer.Exit(code=1)


@app.callback()
def main(version: bool = typer.Option(None, "--version", help="Show version")):
    """Stapled-news: infer latent truth from multi-outlet coverage."""
    if version:
        print(f"stapled-news {__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()
