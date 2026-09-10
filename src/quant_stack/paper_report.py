"""Offline, single-file HTML reporting for paper-trading account snapshots.

The renderer deliberately consumes a small mapping protocol instead of importing the
ledger implementation.  This keeps report generation usable during recovery and
prevents a presentation concern from becoming a ledger dependency.
"""

from __future__ import annotations

import html
import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TypeAlias

from quant_stack.snapshot import write_immutable

ReportValue: TypeAlias = str | int | float | bool | None
ReportRow: TypeAlias = Mapping[str, object]
ReportInput: TypeAlias = Mapping[str, object]


def render_paper_report(report: ReportInput) -> str:
    """Render an offline HTML report from a paper-account snapshot mapping.

    Expected top-level keys are ``run_id``, ``account_id``, ``trading_date``,
    ``strategy``, ``benchmark``, ``nav_history``, ``positions``, ``orders``,
    ``fills``, ``rejected_orders``, ``corporate_actions``, ``data_anomalies`` and
    ``evidence``.  All keys except ``run_id`` are optional.  Row values are escaped
    before insertion, so provider text and rejection messages cannot add markup.
    ``nav_history`` rows use ``date``, ``strategy_nav`` and optional
    ``benchmark_nav`` fields.
    """
    title = f"Paper account {_text(report.get('account_id', 'unknown'))}"
    strategy = _mapping(report.get("strategy"))
    benchmark = _mapping(report.get("benchmark"))
    history = _rows(report.get("nav_history"))
    nav_chart = _nav_chart(history)
    drawdown_chart = _drawdown_chart(history)
    sections = (
        _summary(report, strategy, benchmark),
        _chart_section("NAV", nav_chart),
        _chart_section("Drawdown", drawdown_chart),
        _table_section("Positions", _rows(report.get("positions"))),
        _table_section("Orders", _rows(report.get("orders"))),
        _table_section("Fills", _rows(report.get("fills"))),
        _table_section("Rejected orders", _rows(report.get("rejected_orders"))),
        _table_section("Corporate actions", _rows(report.get("corporate_actions"))),
        _table_section("Data anomalies", _rows(report.get("data_anomalies"))),
        _evidence_section(_mapping(report.get("evidence"))),
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#172033;background:#f7f9fc}}
main{{max-width:1200px;margin:auto}}
section{{background:#fff;padding:1rem 1.25rem;margin:1rem 0;border-radius:8px;
box-shadow:0 1px 3px #0002}}
h1,h2{{margin-top:0}} .status{{color:#9b1c1c;font-weight:700}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:.75rem}}
.metric{{padding:.75rem;background:#f1f5f9;border-radius:5px}}
.metric b{{display:block;font-size:.8rem;color:#52606d}}
table{{border-collapse:collapse;width:100%;font-size:.9rem}}
th,td{{text-align:left;padding:.45rem;border-bottom:1px solid #d9e2ec;vertical-align:top}}
th{{background:#eef2f7}} .empty{{color:#64748b}}
svg{{width:100%;height:220px;background:#fbfdff}}
</style>
</head>
<body><main>
<h1>{title}</h1>
<p>Run: <code>{_text(report.get("run_id", "unknown"))}</code>
· Trading date: {_text(report.get("trading_date", "unknown"))}</p>
<p class="status">Issue 009 research status: NO_EVIDENCE_OF_EDGE.
This is paper-account monitoring, not investment advice or a live-order system.</p>
{"".join(sections)}
</main></body></html>"""


def write_paper_report(report: ReportInput, output_path: Path) -> Path:
    """Publish an immutable UTF-8 report for one completed run identity."""
    write_immutable(output_path, render_paper_report(report).encode("utf-8"))
    return output_path


def _summary(report: ReportInput, strategy: ReportRow, benchmark: ReportRow) -> str:
    """Return the account and benchmark summary grid."""
    values: tuple[tuple[str, object], ...] = (
        ("Strategy NAV", strategy.get("nav", report.get("nav"))),
        ("Benchmark NAV", benchmark.get("nav")),
        ("Cash", report.get("cash")),
        ("Cumulative fees", report.get("cumulative_fees")),
        ("Turnover", strategy.get("turnover", report.get("turnover"))),
        ("Strategy return", strategy.get("total_return", report.get("total_return"))),
        ("Benchmark return", benchmark.get("total_return")),
        ("Maximum drawdown", strategy.get("maximum_drawdown", report.get("maximum_drawdown"))),
    )
    cards = "".join(
        f'<div class="metric"><b>{_text(label)}</b>{_text(value)}</div>' for label, value in values
    )
    return f'<section><h2>Account summary</h2><div class="grid">{cards}</div></section>'


def _chart_section(title: str, chart: str) -> str:
    """Wrap an inline SVG chart in a report section."""
    return f"<section><h2>{_text(title)}</h2>{chart}</section>"


def _table_section(title: str, rows: tuple[ReportRow, ...]) -> str:
    """Render an escaped table whose columns are the ordered union of row keys."""
    if not rows:
        return f'<section><h2>{_text(title)}</h2><p class="empty">None recorded.</p></section>'
    columns = tuple(dict.fromkeys(key for row in rows for key in row))
    header = "".join(f"<th>{_text(key)}</th>" for key in columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{_text(row.get(column))}</td>" for column in columns) + "</tr>"
        for row in rows
    )
    return (
        f"<section><h2>{_text(title)}</h2><table><thead><tr>{header}</tr></thead>"
        f"<tbody>{body}</tbody></table></section>"
    )


def _evidence_section(evidence: ReportRow) -> str:
    """Render identifiers binding this report to its inputs and ledger state."""
    required = (
        "input_manifest",
        "raw_data_sha256",
        "corporate_action_evidence_sha256",
        "ledger_head_sha256",
        "code_version",
        "config_sha256",
    )
    rows = tuple({"evidence": key, "value": evidence.get(key, "not supplied")} for key in required)
    return _table_section("Evidence and reproducibility", rows)


def _nav_chart(rows: tuple[ReportRow, ...]) -> str:
    """Produce an inline SVG NAV chart for strategy and optional benchmark."""
    strategy = _series(rows, "strategy_nav")
    benchmark = _series(rows, "benchmark_nav")
    return _line_chart(("Strategy", strategy, "#1769aa"), ("Benchmark", benchmark, "#6b7280"))


def _drawdown_chart(rows: tuple[ReportRow, ...]) -> str:
    """Produce an inline SVG drawdown chart computed from the strategy NAV series."""
    nav = _series(rows, "strategy_nav")
    peak = 0.0
    drawdowns: list[float] = []
    for value in nav:
        peak = max(peak, value)
        drawdowns.append((value / peak - 1.0) if peak else 0.0)
    return _line_chart(("Strategy drawdown", tuple(drawdowns), "#b91c1c"))


def _line_chart(*series: tuple[str, tuple[float, ...], str]) -> str:
    """Return a bounded SVG line chart without JavaScript or remote dependencies."""
    nonempty = tuple(item for item in series if item[1])
    if not nonempty:
        return '<p class="empty">No NAV history supplied.</p>'
    all_values = tuple(value for _, values, _ in nonempty for value in values)
    minimum, maximum = min(all_values), max(all_values)
    span = maximum - minimum or 1.0
    paths = "".join(
        f'<path d="{_path(values, minimum, span)}" fill="none" stroke="{color}" '
        f'stroke-width="2"><title>{_text(label)}</title></path>'
        for label, values, color in nonempty
    )
    legend = " ".join(
        f'<span style="color:{color}">■ {_text(label)}</span>' for label, _, color in nonempty
    )
    return f'<p>{legend}</p><svg viewBox="0 0 1000 220" role="img" aria-label="chart">{paths}</svg>'


def _path(values: tuple[float, ...], minimum: float, span: float) -> str:
    """Convert a numeric series to a scaled SVG path command string."""
    if len(values) == 1:
        return f"M 0 {_y(values[0], minimum, span):.2f}"
    return " ".join(
        f"{'M' if index == 0 else 'L'} {index * 1000 / (len(values) - 1):.2f} "
        f"{_y(value, minimum, span):.2f}"
        for index, value in enumerate(values)
    )


def _y(value: float, minimum: float, span: float) -> float:
    """Scale a chart value into the SVG's padded vertical coordinate range."""
    return 205.0 - (value - minimum) / span * 190.0


def _series(rows: tuple[ReportRow, ...], field: str) -> tuple[float, ...]:
    """Extract finite numeric observations from history rows in their supplied order."""
    values: list[float] = []
    for row in rows:
        value = row.get(field)
        if isinstance(value, bool):
            continue
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            values.append(number)
    return tuple(values)


def _mapping(value: object) -> ReportRow:
    """Return a mapping value or an empty mapping for optional report fields."""
    return value if isinstance(value, Mapping) else {}


def _rows(value: object) -> tuple[ReportRow, ...]:
    """Return only mapping rows from an optional sequence value."""
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _text(value: object) -> str:
    """Format and escape a scalar value for HTML text or attribute context."""
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)
