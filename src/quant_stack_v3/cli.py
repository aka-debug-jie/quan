"""Command line entrypoint for isolated CN Historical Research V3."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated

import typer

from quant_stack_v3.bundle import (
    BundleError,
    BundleInspection,
    capture_bundle,
    extract_and_inspect,
    inspect_bundle,
)
from quant_stack_v3.closure_cli import app as closure_app
from quant_stack_v3.crosscheck import run_crosscheck
from quant_stack_v3.diagnostics import build_signal_diagnostics
from quant_stack_v3.market import MarketDataError, normalize_bundle
from quant_stack_v3.matrix import MatrixPaths, run_matrix
from quant_stack_v3.protocol import load_protocol
from quant_stack_v3.runner import RunOptions, run_strategy
from quant_stack_v3.signals import build_signal_cache
from quant_stack_v3.upgrade_cli import app as upgrade_app

app = typer.Typer(help="CN historical research only; no live brokerage capability.")
data_app = typer.Typer(help="Capture and inspect an isolated historical data snapshot.")
signal_app = typer.Typer(help="Build the preregistered seven-factor signal cache.")
run_app = typer.Typer(help="Run only preregistered local historical simulations.")
app.add_typer(data_app, name="data")
app.add_typer(signal_app, name="signal")
app.add_typer(run_app, name="run")
app.add_typer(upgrade_app, name="upgrade")
app.add_typer(closure_app, name="closure")


@data_app.command("capture")
def capture_data(
    data_root: Annotated[Path, typer.Option()] = Path("external/cn-historical-v3/data"),
    allow_network: Annotated[bool, typer.Option()] = False,
) -> None:
    """Capture, safely extract, and inspect the frozen RQAlpha bundle."""
    try:
        archive, receipt_path, receipt = capture_bundle(data_root, allow_network=allow_network)
        tree, report, inspection = extract_and_inspect(
            archive, data_root, expected_sha256=receipt.sha256
        )
    except BundleError as error:
        typer.echo(f"historical data capture failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "archive": archive.as_posix(),
                "receipt": receipt_path.as_posix(),
                "tree": tree.as_posix(),
                "inspection": report.as_posix(),
                "status": inspection.status,
            },
            indent=2,
        )
    )


@data_app.command("inspect")
def inspect_data(
    bundle_root: Annotated[Path, typer.Option()],
    bundle_sha256: Annotated[str, typer.Option()],
) -> None:
    """Print bounded metadata from a local extracted bundle."""
    try:
        result = inspect_bundle(bundle_root, bundle_sha256)
    except BundleError as error:
        typer.echo(f"historical data inspection failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(json.dumps(asdict(result), indent=2))


@data_app.command("normalize")
def normalize_data(
    bundle_root: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()] = Path("external/cn-historical-v3/data"),
    protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/cn_historical_research_v3.yaml"
    ),
    bundle_tree_sha256: Annotated[str, typer.Option()] = "",
) -> None:
    """Create one immutable causal bar table from an inspected local bundle."""
    try:
        protocol = load_protocol(protocol_path)
        path, report_path, report = normalize_bundle(
            bundle_root,
            output_root,
            protocol,
            bundle_tree_sha256=bundle_tree_sha256,
        )
    except (MarketDataError, ValueError) as error:
        typer.echo(f"historical normalization failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "bars": path.as_posix(),
                "report": report_path.as_posix(),
                "rows": report.rows,
                "symbols": report.symbols,
                "status": report.status,
            },
            indent=2,
        )
    )


@data_app.command("crosscheck")
def crosscheck_data(
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    data_root: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    allow_network: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the frozen 36-row independent BaoStock cross-check."""
    try:
        path, report = run_crosscheck(
            bars_path,
            scores_path,
            data_root,
            artifact_root,
            allow_network=allow_network,
        )
    except ValueError as error:
        typer.echo(f"historical cross-check failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "report": path.as_posix(),
                "matched": report.matched_count,
                "mismatched": report.mismatched_count,
                "status": report.status,
            },
            indent=2,
        )
    )


@signal_app.command("build")
def build_signals(
    bars_path: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()] = Path("external/cn-historical-v3/artifacts"),
    protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/cn_historical_research_v3.yaml"
    ),
) -> None:
    """Build factors and daily ranks once without reading portfolio returns."""
    try:
        path, report_path, report = build_signal_cache(
            bars_path,
            protocol_path,
            load_protocol(protocol_path),
            output_root,
        )
    except ValueError as error:
        typer.echo(f"historical signal build failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "scores": path.as_posix(),
                "report": report_path.as_posix(),
                "rows": report.rows,
                "sessions": report.sessions,
                "status": report.status,
            },
            indent=2,
        )
    )


@signal_app.command("diagnostics")
def signal_diagnostics(
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    output_root: Annotated[Path, typer.Option()],
) -> None:
    """Build IC, Rank-IC, and explicit holding-horizon diagnostics."""
    try:
        path, report = build_signal_diagnostics(bars_path, scores_path, output_root)
    except ValueError as error:
        typer.echo(f"historical signal diagnostics failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "report": path.as_posix(),
                "status": report["SHADOW_SIGNAL_STATUS"],
            },
            indent=2,
        )
    )


@run_app.command("one")
def run_one(
    strategy_id: Annotated[str, typer.Option()],
    bundle_root: Annotated[Path, typer.Option()],
    bundle_sha256: Annotated[str, typer.Option()],
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()] = Path("external/cn-historical-v3/artifacts"),
    protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/cn_historical_research_v3.yaml"
    ),
    delay_sessions: Annotated[int, typer.Option()] = 1,
    friction_multiplier: Annotated[str, typer.Option()] = "1",
) -> None:
    """Run one exact main or prespecified stress configuration locally."""
    try:
        protocol = load_protocol(protocol_path)
        strategy = next(item for item in protocol.strategies if item.id == strategy_id)
        result_path, result = run_strategy(
            protocol,
            protocol_path,
            strategy,
            RunOptions(delay_sessions, Decimal(friction_multiplier)),
            bundle_root=bundle_root,
            bundle_sha256=bundle_sha256,
            bars_path=bars_path,
            scores_path=scores_path,
            artifact_root=artifact_root,
        )
    except (StopIteration, ValueError) as error:
        typer.echo(f"historical run failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "result": result_path.as_posix(),
                "strategy_id": result["strategy_id"],
                "HISTORICAL_RUN_STATUS": result["HISTORICAL_RUN_STATUS"],
                "RESEARCH_VALIDITY": result["RESEARCH_VALIDITY"],
            },
            indent=2,
        )
    )


@run_app.command("matrix")
def run_frozen_matrix(
    bundle_root: Annotated[Path, typer.Option()],
    bundle_sha256: Annotated[str, typer.Option()],
    bars_path: Annotated[Path, typer.Option()],
    scores_path: Annotated[Path, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()],
    protocol_path: Annotated[Path, typer.Option()] = Path(
        "configs/v3/cn_historical_research_v3.yaml"
    ),
) -> None:
    """Run the exact six-main plus four-stress matrix and retain all results."""
    try:
        path, report = run_matrix(
            load_protocol(protocol_path),
            protocol_path,
            MatrixPaths(bundle_root, bundle_sha256, bars_path, scores_path, artifact_root),
        )
    except ValueError as error:
        typer.echo(f"historical matrix failed: {error}", err=True)
        raise typer.Exit(1) from error
    typer.echo(
        json.dumps(
            {
                "report": path.as_posix(),
                "HISTORICAL_RUN_STATUS": report["HISTORICAL_RUN_STATUS"],
                "ECONOMIC_OUTCOME": report["ECONOMIC_OUTCOME"],
            },
            indent=2,
        )
    )


def asdict(value: BundleInspection) -> dict[str, object]:
    """Return dataclass fields without accepting arbitrary objects."""
    from dataclasses import asdict as dataclass_asdict

    result = dataclass_asdict(value)
    if not isinstance(result, dict):
        raise TypeError("inspection must serialize to a mapping")
    return result


if __name__ == "__main__":
    app()
