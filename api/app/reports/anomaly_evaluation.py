"""Stage 3C held-out evaluation report.

Renders an ``AnomalyEvaluation`` (see app.services.anomaly_ranking) as a
self-contained HTML page. This is a REVIEW-PRIORITIZATION report: it shows
review-worthy precision@k against a random-ranking baseline and the ranks of
known operational confounders. It is deliberately separate from the
attribution/service-outcome reports, and it states in the page itself that it
measures no criminal guilt, ownership, service identity, or fraud, and that a
high-ranked confounder is a false positive to inspect rather than a finding.
"""

from __future__ import annotations

import html as html_mod
from typing import Any

from app.services.anomaly_ranking import AnomalyEvaluation


def _esc(value: Any) -> str:
    return html_mod.escape(str(value))


def render_anomaly_evaluation_html(evaluation: AnomalyEvaluation) -> str:
    metrics = evaluation.metrics.to_dict()
    metric_rows = "".join(
        f"<tr><td>{_esc(key)}</td><td>{_esc(value)}</td></tr>"
        for key, value in sorted(metrics.items())
    )
    note_items = "".join(f"<li>{_esc(note)}</li>" for note in evaluation.notes)
    confounder_rows = "".join(
        f"<tr><td>{_esc(wallet_id)}</td><td>{_esc(rank)}</td></tr>"
        for wallet_id, rank in evaluation.confounder_ranks
    ) or "<tr><td colspan='2'>none in the evaluation split</td></tr>"

    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>Stage 3C held-out anomaly-rank evaluation</title></head><body>"
        f"<h1>Evaluation kind: {_esc(evaluation.evaluation_kind)}</h1>"
        f"<h2>Experiment: {_esc(evaluation.experiment_kind)}</h2>"
        "<p>A <code>future_window</code> experiment evaluates later windows of "
        "wallets already in training and is not an independent-wallet holdout.</p>"
        "<p>This report covers model REVIEW PRIORITIZATION only. It is not an "
        "accuracy or fraud measure and does not establish ownership, service "
        "identity, or guilt. A high-ranked confounder is a false positive to "
        "inspect, not a finding.</p>"
        f"<p>Rubric: {_esc(evaluation.rubric_id)} &mdash; "
        f"{_esc(evaluation.rubric_description)}</p>"
        f"<p>k = {_esc(evaluation.k)}; split: {_esc(evaluation.split_description)}</p>"
        "<h2>Review-prioritization metrics</h2>"
        f"<table border='1' cellpadding='4'>{metric_rows}</table>"
        "<h2>Known operational confounders (ranks)</h2>"
        f"<table border='1' cellpadding='4'>{confounder_rows}</table>"
        "<h2>Notes</h2>"
        f"<ul>{note_items}</ul>"
        "</body></html>"
    )
