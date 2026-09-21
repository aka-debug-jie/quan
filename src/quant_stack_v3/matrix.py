"""Run and compare only the preregistered V3 strategy and stress matrix."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable
from quant_stack_v3.protocol import Protocol, StrategySpec
from quant_stack_v3.runner import RunOptions, run_strategy


@dataclass(frozen=True)
class MatrixPaths:
    """Frozen inputs shared by every matrix member."""

    bundle_root: Path
    bundle_sha256: str
    bars_path: Path
    scores_path: Path
    artifact_root: Path


def run_matrix(
    protocol: Protocol,
    protocol_path: Path,
    paths: MatrixPaths,
) -> tuple[Path, dict[str, object]]:
    """Run every main and stress configuration, retaining every result."""
    results: dict[str, dict[str, object]] = {}
    main = {item.id: item for item in protocol.strategies}
    for strategy in protocol.strategies:
        _, result = _run(protocol, protocol_path, strategy, RunOptions(), paths)
        results[strategy.id] = result
    for stress in protocol.stress_tests:
        base = main[stress.base]
        strategy = base.model_copy(update={"id": stress.id})
        options = RunOptions()
        if stress.kind == "friction_x2":
            options = RunOptions(friction_multiplier=Decimal("2"))
        elif stress.kind == "execution_t2":
            options = RunOptions(delay_sessions=2)
        elif stress.kind == "exit_rank":
            strategy = base.model_copy(update={"id": stress.id, "exit_rank": stress.value})
        _, result = _run(protocol, protocol_path, strategy, options, paths)
        results[stress.id] = result
    aggregate = compile_matrix(results)
    encoded = canonical_json(aggregate) + b"\n"
    output = paths.artifact_root / "matrix" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(output, encoded)
    return output, aggregate


def compile_matrix(results: dict[str, dict[str, object]]) -> dict[str, object]:
    """Compare all retained results to B00 without selecting a winner post hoc."""
    required = {
        "B00_LIQ20_D20",
        "A01_AF7_D1",
        "A02_AF7_D1_B40",
        "A03_AF7_D5",
        "A04_AF7_D20",
        "A05_AF7_D20_B40",
        "P01_A01_FRICTION_X2",
        "P02_A01_T2",
        "P03_A02_B30",
        "P04_A02_B50",
    }
    if set(results) != required:
        raise ValueError("historical result matrix is incomplete")
    benchmark = results["B00_LIQ20_D20"]
    rows = {
        strategy_id: _comparison(result, benchmark)
        for strategy_id, result in sorted(results.items())
    }
    valid = all(
        result.get("RESEARCH_VALIDITY") == "VALID_RETROSPECTIVE_DEVELOPMENT_COMPARISON"
        for result in results.values()
    )
    main_rows = [rows[key] for key in sorted(required) if key.startswith("A")]
    positive = [
        row
        for row in main_rows
        if _number(row["excess_cagr"]) > 0 and _number(row["sharpe_difference"]) > 0
    ]
    a01_robust = (
        _number(rows["A01_AF7_D1"]["excess_cagr"]) > 0
        and _number(rows["A01_AF7_D1"]["sharpe_difference"]) > 0
        and _number(rows["A01_AF7_D1"]["maximum_drawdown_difference"]) >= -0.05
        and _number(rows["A01_AF7_D1"]["positive_excess_year_fraction"]) > 0.5
        and _number(rows["P01_A01_FRICTION_X2"]["excess_cagr"]) >= 0
        and _number(rows["P02_A01_T2"]["excess_cagr"]) >= 0
    )
    a02_robust = (
        _number(rows["A02_AF7_D1_B40"]["excess_cagr"]) > 0
        and _number(rows["A02_AF7_D1_B40"]["sharpe_difference"]) > 0
        and _number(rows["A02_AF7_D1_B40"]["maximum_drawdown_difference"]) >= -0.05
        and _number(rows["A02_AF7_D1_B40"]["positive_excess_year_fraction"]) > 0.5
        and _number(rows["P03_A02_B30"]["excess_cagr"]) > 0
        and _number(rows["P04_A02_B50"]["excess_cagr"]) > 0
    )
    outcome = (
        "NOT_EVALUABLE_DATA"
        if not valid
        else "HISTORICAL_NET_EDGE_OBSERVED"
        if a01_robust or a02_robust
        else "MIXED_HISTORICAL_EVIDENCE"
        if positive
        else "NO_HISTORICAL_COST_ADJUSTED_EDGE"
    )
    return {
        "schema_version": 1,
        "IMPLEMENTATION_STATUS": "IMPLEMENTED_REAL_DATA_PATH",
        "HISTORICAL_RUN_STATUS": "COMPLETE_REAL_DATA" if valid else "PARTIAL_REAL_DATA",
        "DATA_USE_LEVEL": "RQALPHA_SINGLE_SOURCE_NONCOMMERCIAL_PRIVATE_RESEARCH_ONLY",
        "RESEARCH_VALIDITY": "VALID_RETROSPECTIVE_DEVELOPMENT_COMPARISON"
        if valid
        else "NOT_EVALUABLE_DATA",
        "ECONOMIC_OUTCOME": outcome,
        "PROSPECTIVE_ISOLATION_STATUS": "SEPARATE_WORKTREE_ENV_DATA_AND_LEDGER",
        "benchmark_id": "B00_LIQ20_D20",
        "comparisons": rows,
        "result_identities": {
            key: str(value["run_identity"]) for key, value in sorted(results.items())
        },
    }


def _comparison(result: dict[str, object], benchmark: dict[str, object]) -> dict[str, object]:
    metrics = _mapping(result["metrics"])
    base = _mapping(benchmark["metrics"])
    years = _mapping(_mapping(result["periods"])["calendar_year_returns"])
    base_years = _mapping(_mapping(benchmark["periods"])["calendar_year_returns"])
    common = sorted(set(years) & set(base_years))
    positive_years = sum(_number(years[key]) > _number(base_years[key]) for key in common)
    return {
        "strategy_id": result["strategy_id"],
        "total_return": metrics["total_return"],
        "cagr": metrics["cagr"],
        "annualized_volatility": metrics["annualized_volatility"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "maximum_drawdown": metrics["maximum_drawdown"],
        "turnover": metrics["turnover"],
        "total_transaction_costs": metrics["total_transaction_costs"],
        "excess_cagr": _number(metrics["cagr"]) - _number(base["cagr"]),
        "sharpe_difference": _number(metrics["sharpe_ratio"]) - _number(base["sharpe_ratio"]),
        "maximum_drawdown_difference": _number(metrics["maximum_drawdown"])
        - _number(base["maximum_drawdown"]),
        "positive_excess_year_fraction": positive_years / len(common) if common else 0.0,
        "RESEARCH_VALIDITY": result["RESEARCH_VALIDITY"],
    }


def _run(
    protocol: Protocol,
    protocol_path: Path,
    strategy: StrategySpec,
    options: RunOptions,
    paths: MatrixPaths,
) -> tuple[Path, dict[str, object]]:
    return run_strategy(
        protocol,
        protocol_path,
        strategy,
        options,
        bundle_root=paths.bundle_root,
        bundle_sha256=paths.bundle_sha256,
        bars_path=paths.bars_path,
        scores_path=paths.scores_path,
        artifact_root=paths.artifact_root,
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("historical matrix field must be a mapping")
    return value


def _number(value: object) -> float:
    if value is None:
        return float("-inf")
    if not isinstance(value, (int, float, str)):
        raise ValueError("historical matrix metric must be numeric")
    return float(value)
