"""CLI interface for stapled-news."""

import json
import sqlite3
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
from stapled.ingest.csv_loader import (
    load_isot as load_isot_data,
    _get_or_create_outlet,
    _strip_reuters_dateline,
    _normalize_subject,
)
from stapled.ingest.dedup import dedup_articles
from stapled.ingest.stream import iter_remote_lines, dedup_new_articles
from stapled.extract.claims import extract_all_unextracted
from stapled.extract.framing import update_all_framing
from stapled.align.cluster import align
from stapled.infer.online_em import OnlineEM
from stapled.infer.align_incremental import align_incremental
from stapled.viz.online_convergence import online_convergence

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
        col_widths = {
            col: max(len(col), max((len(str(r.get(col, ""))) for r in rows), default=0))
            for col in columns
        }
        header = "  " + " | ".join(col.ljust(col_widths[col]) for col in columns)
        print(header, file=sys.stderr)
        print("  " + "-" * (len(header) - 2), file=sys.stderr)
        for row in rows:
            cells = [str(row.get(col, "")).ljust(col_widths[col]) for col in columns]
            print("  " + " | ".join(cells), file=sys.stderr)

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

        # Streaming status
        cursor = conn.execute(
            "SELECT COUNT(*) FROM source_cursor WHERE done = 0"
        )
        active_sources = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM source_cursor"
        )
        total_sources = cursor.fetchone()[0]

        # EM state and batches
        cursor = conn.execute(
            "SELECT batches_seen FROM em_state WHERE id = 1"
        )
        em_row = cursor.fetchone()
        batches_seen = em_row[0] if em_row else 0
        em_state_exists = em_row is not None

        # Outlet reliabilities from most recent batch
        cursor = conn.execute(
            """SELECT outlet_id, reliability FROM reliability_snapshot
               WHERE batch = (SELECT MAX(batch) FROM reliability_snapshot)
               ORDER BY reliability DESC LIMIT 5"""
        )
        top_outlets = [
            {"outlet_id": row[0], "reliability": f"{row[1]:.3f}"}
            for row in cursor.fetchall()
        ]

        out.set_data(
            corpora_total=total_corpora,
            corpora_passed=passed_corpora,
            runs_summary=run_summary,
            recovery_gate_passed=passing_recovery > 0,
            active_sources=active_sources,
            total_sources=total_sources,
            batches_seen=batches_seen,
            em_state_initialized=em_state_exists,
            top_outlets=top_outlets,
        )

        rows = [
            {"key": "Total corpora", "value": str(total_corpora)},
            {"key": "Passed corpora", "value": str(passed_corpora)},
            {"key": "Inference runs", "value": json.dumps(run_summary)},
            {"key": "Recovery gate", "value": "PASS" if passing_recovery > 0 else "BLOCKED"},
            {"key": "Active sources", "value": f"{active_sources}/{total_sources}"},
            {"key": "Batches processed", "value": str(batches_seen)},
            {"key": "EM state", "value": "INITIALIZED" if em_state_exists else "PENDING"},
            {"key": "Top outlets", "value": json.dumps(top_outlets)},
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


@app.command()
def train_stream(
    source: str = typer.Option(..., "--source", help="Remote CSV URL"),
    kind: str = typer.Option("true", "--kind", help="true|fake"),
    batch_mb: int = typer.Option(10, "--batch-mb", help="Batch size in MB"),
    max_batches: Optional[int] = typer.Option(
        None, "--max-batches", help="Max batches to process"
    ),
    limit_per_outlet: Optional[int] = typer.Option(
        None, "--limit-per-outlet", help="Limit per outlet"
    ),
    reset: bool = typer.Option(False, "--reset", help="Reset stream cursor"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Train online EM on streaming remote CSV."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)

        # Reset cursor if requested
        if reset:
            conn.execute("DELETE FROM source_cursor WHERE source_url = ?", (source,))
            conn.commit()

        # Initialize online EM lazily (after first batch insert)
        em = None
        outlet_ids = None

        # Stream and process batches
        batch_bytes = batch_mb * 1024 * 1024
        batch_count = 0
        total_rows = 0
        online_ll_trace = []
        new_events_count = 0
        new_claims_count = 0

        for batch_rows in iter_remote_lines(source, batch_bytes, conn):
            if max_batches and batch_count >= max_batches:
                break

            batch_count += 1
            total_rows += len(batch_rows)

            # Load articles from batch rows
            # Handle both custom (outlet field) and ISOT format (subject → outlet mapping for fake)
            article_ids = []
            for row in batch_rows:
                # Use 'text' field if body not present (ISOT format)
                body_text = row.get("body") or row.get("text", "")
                title = row.get("title", "")

                # Skip if missing critical fields or body too short
                if not title or not body_text or len(body_text) < 200:
                    continue

                # Get or create outlet based on kind
                outlet_name = row.get("outlet")
                if outlet_name:
                    # Custom outlet field: get-or-create with that name
                    outlet_id = _get_or_create_outlet(
                        conn, outlet_name, feed_url=None, is_synthetic=0
                    )
                elif kind == "true":
                    # Reuters: get-or-create 'reuters'
                    outlet_id = _get_or_create_outlet(
                        conn, "reuters", feed_url=None, is_synthetic=0
                    )
                    # Strip Reuters dateline from body
                    body_text = _strip_reuters_dateline(body_text)
                elif kind == "fake":
                    # Fake news: derive outlet name from subject
                    subject = row.get("subject", "news")
                    outlet_name = _normalize_subject(subject)
                    outlet_id = _get_or_create_outlet(
                        conn, outlet_name, feed_url=None, is_synthetic=0
                    )
                else:
                    continue

                # For ISOT, use title as URL if no explicit URL
                url = row.get("url", f"http://example.com/{outlet_id}/{title[:50].replace(' ', '_')}")

                # Check if article already exists
                try:
                    cursor = conn.execute(
                        "SELECT id FROM article WHERE outlet_id = ? AND url = ?",
                        (outlet_id, url),
                    )
                    existing = cursor.fetchone()
                    if existing:
                        article_ids.append(existing[0])
                        continue

                    cursor = conn.execute(
                        """INSERT INTO article (outlet_id, corpus_id, url, title, body, ingest_status)
                           VALUES (?, NULL, ?, ?, ?, 'ok')""",
                        (outlet_id, url, title, body_text),
                    )
                    article_ids.append(cursor.lastrowid)
                except sqlite3.IntegrityError:
                    # Skip on constraint violation
                    continue

            if not article_ids:
                continue

            conn.commit()

            # Dedup and extract
            dedup_new_articles(conn, article_ids)
            extract_all_unextracted(conn)
            update_all_framing(conn)

            # Get newly created claim IDs
            new_claim_ids = []
            cursor = conn.execute(
                "SELECT id FROM claim WHERE article_id IN ({})".format(
                    ",".join("?" * len(article_ids))
                ),
                article_ids,
            )
            new_claim_ids = [row[0] for row in cursor.fetchall()]

            # Align incremental
            if new_claim_ids:
                align_stats = align_incremental(conn, new_claim_ids)
                new_events_count += align_stats["events_created"]
                new_claims_count += align_stats["claims_aligned"]

            # Lazy-initialize OnlineEM after first batch with articles
            if em is None:
                cursor = conn.execute("SELECT DISTINCT id FROM outlet ORDER BY id")
                outlet_ids = [row[0] for row in cursor.fetchall()]
                if not outlet_ids:
                    raise ValueError("No outlets in database. Load data first (load_isot, load_real, etc.)")
                em = OnlineEM(outlet_ids, tolerance=1e-5, conn=conn)

            # Get events with claims (no corpus_id)
            cursor = conn.execute(
                """SELECT DISTINCT e.id FROM event e
                   JOIN claim c ON e.id = c.event_id
                   WHERE e.corpus_id IS NULL"""
            )
            event_ids = [row[0] for row in cursor.fetchall()]

            if event_ids:
                # E-step (loads from DB)
                result = em.e_step_batch(event_ids)
                batch_stats = result["batch_stats"]
                batch_ll = result["batch_ll"]

                batch_stats["ll"] = batch_ll
                online_ll_trace.append(batch_ll)

                # Accumulate with Robbins-Monro
                em.accumulate(batch_stats, batch_count - 1)

        # Get top 3 outlets by reliability
        top_3_outlets = []
        if em is not None:
            params = em.params()
            top_3_outlets = sorted(
                [(o, params[o]["reliability"]) for o in outlet_ids],
                key=lambda x: x[1],
                reverse=True,
            )[:3]

        out.set_data(
            source_bytes=total_rows,
            batches_processed=batch_count,
            new_events=new_events_count,
            new_claims=new_claims_count,
            final_ll=float(online_ll_trace[-1]) if online_ll_trace else 0.0,
            top_outlets=[{"outlet_id": o, "reliability": float(r)} for o, r in top_3_outlets],
        )

        rows = [
            {"metric": "Batches processed", "value": str(batch_count)},
            {"metric": "Total rows", "value": str(total_rows)},
            {"metric": "New events", "value": str(new_events_count)},
            {"metric": "New claims", "value": str(new_claims_count)},
            {
                "metric": "Final LL",
                "value": (
                    f"{online_ll_trace[-1]:.2f}" if online_ll_trace else "N/A"
                ),
            },
        ]
        out.print_table(rows, ["metric", "value"], "Online EM Streaming Complete")
        out.output("train_stream", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("train_stream", exit_code=1)
        raise typer.Exit(code=1)


@app.command()
def train_report(
    out_dir: str = typer.Option("./docs", help="Output directory for report"),
    db: str = typer.Option("./stapled.db", help="Path to database"),
    json_output: bool = typer.Option(False, "--json", help="JSON output"),
):
    """Generate streaming EM training report with convergence + reliability charts."""
    out = CLIOutput(json_mode=json_output)
    try:
        conn = connect(db)

        # Generate convergence viz (PNG)
        convergence_path = online_convergence(conn, out_dir)

        # Create output directory
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # Generate HTML report embedding both PNGs
        html_file = out_path / "stream.html"
        html_content = _generate_training_report(convergence_path)
        html_file.write_text(html_content)

        out.set_data(
            report_path=str(html_file),
            convergence_chart=convergence_path,
        )
        rows = [
            {"file": "stream.html"},
            {"file": "convergence chart"},
        ]
        out.print_table(rows, ["file"], "Training Report Generated")
        out.output("train_report", exit_code=0)

    except Exception as e:
        out.add_error(str(e))
        out.output("train_report", exit_code=1)
        raise typer.Exit(code=1)


def _generate_training_report(convergence_path: Optional[str]) -> str:
    """Generate HTML report for streaming EM training."""
    chart_section = ""
    if convergence_path:
        chart_section = f"""
        <div class="chart-section">
            <h2>Convergence Analysis</h2>
            <p>See <a href="{Path(convergence_path).name}">convergence chart</a>
            for detailed analysis.</p>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Streaming EM Training Report</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            margin: 20px;
            background: #f5f5f5;
            color: #333;
        }}
        .container {{
            max-width: 900px;
            margin: 0 auto;
            background: white;
            padding: 30px;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #222;
            border-bottom: 2px solid #ddd;
            padding-bottom: 10px;
        }}
        .chart-section {{
            margin: 30px 0;
            padding: 20px;
            background: #f9f9f9;
            border-radius: 4px;
        }}
        a {{
            color: #1f77b4;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Streaming EM Training Report</h1>
        <p>Generated using online Dawid-Skene EM with Robbins-Monro step sizes.</p>
        {chart_section}
    </div>
</body>
</html>"""
    return html


@app.callback()
def main(version: bool = typer.Option(None, "--version", help="Show version")):
    """Stapled-news: infer latent truth from multi-outlet coverage."""
    if version:
        print(f"stapled-news {__version__}")
        raise typer.Exit()


if __name__ == "__main__":
    app()
