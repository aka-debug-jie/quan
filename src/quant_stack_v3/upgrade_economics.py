"""Compile real-run economics, failures, holding periods and intent attribution."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import numpy as np
import pandas as pd

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable


def build_economic_summary(
    matrix_path: Path,
    artifact_root: Path,
    output_root: Path,
    *,
    old_matrix_path: Path | None = None,
    old_artifact_root: Path | None = None,
) -> tuple[Path, dict[str, object]]:
    """Aggregate every real-cost run without dropping failures or invalid results."""
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    identities = _mapping(matrix["result_identities"])
    rows: dict[str, object] = {}
    failures: list[dict[str, object]] = []
    for experiment_id, identity_value in sorted(identities.items()):
        if not experiment_id.endswith("__REAL_T1_1M"):
            continue
        run_root = artifact_root / "runs" / str(identity_value)
        result = json.loads((run_root / "result.json").read_text(encoding="utf-8"))
        if not str(result.get("RESEARCH_VALIDITY", "")).startswith("VALID_"):
            failure = str(result.get("failure", "unknown"))
            rows[experiment_id] = {
                "status": "NOT_EVALUABLE",
                "failure": failure,
            }
            failures.append({"experiment_id": experiment_id, "failure": failure})
            continue
        metrics = _mapping(result["metrics"])
        turnover = _mapping(_mapping(result["turnover_costs"])["total"])
        execution = _mapping(result["execution"])
        ledger = pd.read_parquet(run_root / "ledger.parquet")
        intents = pd.read_parquet(run_root / "order_intents.parquet")
        costs = _fill_costs(ledger)
        rows[experiment_id] = {
            "status": "VALID",
            "total_return": metrics["total_return"],
            "cagr": metrics["cagr"],
            "annualized_volatility": metrics["annualized_volatility"],
            "sharpe_ratio": metrics["sharpe_ratio"],
            "maximum_drawdown": metrics["maximum_drawdown"],
            "two_sided_turnover": turnover["two_sided_turnover"],
            "half_turnover": turnover["half_turnover"],
            "annualized_two_sided_turnover": turnover["annualized_two_sided_turnover"],
            "buy_notional": turnover["buy_notional"],
            "sell_notional": turnover["sell_notional"],
            "gross_notional": turnover["gross_notional"],
            "costs": costs,
            "cost_to_gross_notional": turnover["cost_to_gross_notional"],
            "cost_to_initial_cash": Decimal(str(turnover["total_cost"])) / Decimal("1000000"),
            "fills": execution["fills"],
            "rejections": execution["rejections"],
            "holding_periods": _holding_periods(ledger),
            "turnover_by_order_intent": _intent_attribution(ledger, intents),
        }
    revisions = _revision_comparison(
        rows,
        old_matrix_path=old_matrix_path,
        old_artifact_root=old_artifact_root,
    )
    failure_counts = Counter(item["failure"] for item in failures)
    report: dict[str, object] = {
        "schema_version": 1,
        "status": "REAL_ECONOMIC_SUMMARY_COMPLETE",
        "matrix_sha256": _file_sha256(matrix_path),
        "real_runs": rows,
        "failure_count": len(failures),
        "failure_reasons": dict(sorted(failure_counts.items())),
        "revision_comparison": revisions,
        "interpretation": [
            "spread and slippage are embedded in fill prices and are not deducted twice",
            "minimum commission uplift is separated from proportional commission",
            "invalid runs remain failures rather than negative-return observations",
        ],
    }
    encoded = canonical_json(report) + b"\n"
    path = output_root / "economics" / f"{sha256(encoded).hexdigest()}.json"
    write_immutable(path, encoded)
    return path, report


def _fill_costs(ledger: pd.DataFrame) -> dict[str, Decimal]:
    totals: defaultdict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for payload_text in ledger.loc[ledger.event_type == "fill", "payload"]:
        payload = json.loads(str(payload_text))
        notional = Decimal(str(payload["notional"]))
        commission = Decimal(str(payload["commission"]))
        proportional = min(commission, notional * Decimal("0.0003"))
        totals["proportional_commission"] += proportional
        totals["minimum_commission_uplift"] += commission - proportional
        for name in ("spread_cost", "slippage_cost", "tax_cost", "transfer_fee"):
            totals[name] += Decimal(str(payload[name]))
    totals["total_cost"] = sum(totals.values(), Decimal("0"))
    return dict(sorted(totals.items()))


def _intent_attribution(
    ledger: pd.DataFrame, intents: pd.DataFrame
) -> dict[str, dict[str, object]]:
    fill_notional = {
        str(payload["order_id"]): Decimal(str(payload["notional"]))
        for payload in (
            json.loads(str(value)) for value in ledger.loc[ledger.event_type == "fill", "payload"]
        )
    }
    rejected = {
        str(payload["order_id"])
        for payload in (
            json.loads(str(value))
            for value in ledger.loc[ledger.event_type == "rejection", "payload"]
        )
    }
    output: dict[str, dict[str, object]] = {}
    for intent, group in intents.groupby("intent", sort=True):
        order_ids = [str(value) for value in group.order_id]
        output[str(intent)] = {
            "orders": len(order_ids),
            "fills": sum(order_id in fill_notional for order_id in order_ids),
            "rejections": sum(order_id in rejected for order_id in order_ids),
            "executed_notional": sum(
                (fill_notional.get(order_id, Decimal("0")) for order_id in order_ids),
                Decimal("0"),
            ),
        }
    return output


def _holding_periods(ledger: pd.DataFrame) -> dict[str, object]:
    starts: dict[str, int] = {}
    durations: list[int] = []
    censored = 0
    snapshots = ledger.loc[ledger.event_type == "snapshot"].sort_values("sequence")
    for ordinal, payload_text in enumerate(snapshots.payload):
        payload = json.loads(str(payload_text))
        current = {
            str(symbol)
            for symbol, quantity in _mapping(payload["positions"]).items()
            if Decimal(str(quantity)) > 0
        }
        for symbol in current - set(starts):
            starts[symbol] = ordinal
        for symbol in set(starts) - current:
            durations.append(ordinal - starts.pop(symbol))
    for start in starts.values():
        durations.append(len(snapshots) - start)
        censored += 1
    values = np.asarray(durations, dtype=float)
    return {
        "completed_and_censored_periods": len(durations),
        "right_censored_periods": censored,
        "mean_sessions": float(values.mean()) if len(values) else None,
        "median_sessions": float(np.median(values)) if len(values) else None,
        "p25_sessions": float(np.quantile(values, 0.25)) if len(values) else None,
        "p75_sessions": float(np.quantile(values, 0.75)) if len(values) else None,
        "maximum_sessions": int(values.max()) if len(values) else None,
    }


def _revision_comparison(
    new_rows: dict[str, object],
    *,
    old_matrix_path: Path | None,
    old_artifact_root: Path | None,
) -> dict[str, object]:
    if old_matrix_path is None or old_artifact_root is None:
        return {"status": "NOT_REQUESTED"}
    old = json.loads(old_matrix_path.read_text(encoding="utf-8"))
    old_identities = _mapping(old["result_identities"])
    mapping = {
        "B00_LIQ20_D20": "B00_LIQ20_D20__REAL_T1_1M",
        "A01_AF7_D1": "A01_AF7_D1__REAL_T1_1M",
        "A04_AF7_D20": "A04_AF7_TOP20_D20__REAL_T1_1M",
        "A05_AF7_D20_B40": "A05R_AF7_D20_ACTUAL_B40__REAL_T1_1M",
    }
    output: dict[str, object] = {}
    for old_id, new_id in mapping.items():
        old_result = json.loads(
            (old_artifact_root / "runs" / str(old_identities[old_id]) / "result.json").read_text(
                encoding="utf-8"
            )
        )
        new_result = _mapping(new_rows[new_id])
        old_metrics = _mapping(old_result["metrics"])
        output[old_id] = {
            "new_id": new_id,
            "old_total_return": old_metrics["total_return"],
            "new_total_return": new_result["total_return"],
            "total_return_difference": _number(new_result["total_return"])
            - _number(old_metrics["total_return"]),
            "old_cagr": old_metrics["cagr"],
            "new_cagr": new_result["cagr"],
            "cagr_difference": _number(new_result["cagr"]) - _number(old_metrics["cagr"]),
            "old_sharpe": old_metrics["sharpe_ratio"],
            "new_sharpe": new_result["sharpe_ratio"],
        }
    return output


def _number(value: object) -> float:
    if not isinstance(value, (int, float, str)):
        raise ValueError("economic summary metric must be numeric")
    return float(value)


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("economic summary field must be a mapping")
    return value


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
