"""Language audit tests — verify consensus-agreement framing in user-facing text."""

import inspect
from pathlib import Path

from stapled.viz import charts, online_convergence


def test_chart_labels_consensus():
    """Verify viz charts use consensus-agreement (not truth-reporter / outlet reliability)."""
    banned_phrases = [
        "truth-reporter",
        "Outlet Reliability",
        "outlet reliability:",
        "reliable truth",
    ]

    # Inspect charts.py source
    charts_source = inspect.getsource(charts)
    for phrase in banned_phrases:
        assert phrase not in charts_source, (
            f"Found banned phrase '{phrase}' in charts.py user-facing labels"
        )

    # Inspect online_convergence.py source
    convergence_source = inspect.getsource(online_convergence)
    for phrase in banned_phrases:
        assert phrase not in convergence_source, (
            f"Found banned phrase '{phrase}' in online_convergence.py user-facing labels"
        )


def test_report_template_consensus():
    """Verify run.html.j2 and index.html.j2 use consensus-agreement framing."""
    template_dir = Path(__file__).parent.parent.parent / "src" / "stapled" / "export" / "templates"

    # Check run.html.j2
    run_template = (template_dir / "run.html.j2").read_text()
    assert "Est. Consensus-Agreement" in run_template, (
        "run.html.j2 header should say 'Est. Consensus-Agreement' not 'Est. Reliability'"
    )
    assert "consensus-agreement" in run_template.lower(), (
        "run.html.j2 should mention consensus-agreement in caveat text"
    )
    assert "truth-reporter" not in run_template.lower(), (
        "run.html.j2 should not contain 'truth-reporter'"
    )

    # Check index.html.j2
    index_template = (template_dir / "index.html.j2").read_text()
    # index.html doesn't need consensus-agreement in headings, but shouldn't reference reliability as truth
    assert "outlet reliability:" not in index_template.lower(), (
        "index.html.j2 should not label reliability as a truth metric"
    )
