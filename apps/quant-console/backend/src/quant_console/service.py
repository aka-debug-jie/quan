"""Thin domain services over one verified immutable Console snapshot."""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass

from pydantic import JsonValue

from quant_console.models import (
    BenchmarkComparability,
    CompareRequest,
    ComparisonMode,
    CompatibilityResult,
    DataEvaluability,
    EvidenceSummary,
    ExperimentDetail,
    ExperimentFilters,
    ExperimentPage,
    ExperimentSummary,
    ExportFormat,
    ExportRequest,
    ExportScope,
    HealthSummary,
    Overview,
    ProspectiveSummary,
    RuntimeStatus,
    SeriesResponse,
    SignalsSummary,
    SortDirection,
    StudyList,
    StudySummary,
)
from quant_console.repository import SnapshotRepository, load_series

JsonObject = dict[str, JsonValue]
ALLOWED_SORTS = {
    "experiment_id",
    "study_id",
    "family",
    "scenario_id",
    "data_evaluability",
    "economic_outcome",
    "cagr",
    "maximum_drawdown",
    "turnover",
    "total_transaction_costs",
}


@dataclass(frozen=True)
class ExportPayload:
    """Encoded safe aggregate export."""

    body: bytes
    media_type: str
    filename: str
    snapshot_id: str


class ConsoleService:
    """Application services that never read configured research sources directly."""

    def __init__(self, repository: SnapshotRepository) -> None:
        self.repository = repository

    def overview(self, snapshot_id: str) -> Overview:
        """Return the research overview for one immutable snapshot."""
        view = self.repository.view(snapshot_id)
        return Overview.model_validate({"snapshot_id": snapshot_id, **view.overview})

    def studies(self, snapshot_id: str) -> StudyList:
        """Return typed study revisions for one immutable snapshot."""
        view = self.repository.view(snapshot_id)
        return StudyList(
            snapshot_id=snapshot_id,
            items=[StudySummary.model_validate(item) for item in view.studies],
        )

    def experiments(
        self,
        snapshot_id: str,
        *,
        filters: ExperimentFilters,
        page: int,
        page_size: int,
        sort: str,
        direction: SortDirection,
    ) -> ExperimentPage:
        """Filter, sort, and page across the full experiment ledger."""
        view = self.repository.view(snapshot_id)
        rows = _filter(view.experiments, filters)
        rows = _sort(rows, sort, direction)
        start = (page - 1) * page_size
        return ExperimentPage(
            snapshot_id=snapshot_id,
            total=len(rows),
            page=page,
            page_size=page_size,
            items=[
                ExperimentSummary.model_validate(row) for row in rows[start : start + page_size]
            ],
        )

    def detail(self, snapshot_id: str, artifact_id: str) -> ExperimentDetail:
        """Return one typed experiment detail."""
        view = self.repository.view(snapshot_id)
        value = view.details.get(artifact_id)
        if value is None:
            raise KeyError(artifact_id)
        return ExperimentDetail.model_validate(value)

    def series(self, snapshot_id: str, series_id: str) -> SeriesResponse:
        """Return one full-precision display series."""
        view = self.repository.view(snapshot_id)
        value = load_series(view, series_id)
        return SeriesResponse.model_validate({"snapshot_id": snapshot_id, **value})

    def compare(self, snapshot_id: str, request: CompareRequest) -> CompatibilityResult:
        """Validate comparison semantics before displaying selected rows."""
        items = [self.detail(snapshot_id, artifact_id) for artifact_id in request.artifact_ids]
        reasons: list[str] = []
        changed: list[str] = []
        baseline = items[0]
        hard_fields = (
            "study_revision",
            "bars_sha256",
            "base_protocol_sha256",
            "initial_cash",
        )
        for item in items[1:]:
            for field in hard_fields:
                if getattr(item.compatibility, field) != getattr(baseline.compatibility, field):
                    reasons.append(f"{field} 不一致")
            if item.period != baseline.period:
                reasons.append("数据期间不一致")
        if any(item.data_evaluability is not DataEvaluability.VALID for item in items):
            reasons.append("至少一项绝对结果不可评价")
            mode = ComparisonMode.NOT_EVALUABLE
        elif reasons:
            mode = ComparisonMode.DESCRIPTIVE_ONLY
        else:
            scenarios = {item.scenario_id for item in items}
            strategies = {item.strategy_id for item in items}
            if len(scenarios) == 1:
                mode = ComparisonMode.COMPARABLE
            elif len(strategies) == 1:
                for field in ("cost_mode", "execution_delay_sessions"):
                    values = {getattr(item.compatibility, field) for item in items}
                    if len(values) > 1:
                        changed.append(field)
                if changed:
                    mode = ComparisonMode.CONTROLLED_SCENARIO_COMPARISON
                else:
                    reasons.append("场景差异没有可识别的预注册轴")
                    mode = ComparisonMode.DESCRIPTIVE_ONLY
            else:
                reasons.append("策略与场景同时变化")
                mode = ComparisonMode.DESCRIPTIVE_ONLY
        benchmark_limited = any(
            item.benchmark_comparability
            not in {
                BenchmarkComparability.COMPARABLE,
                BenchmarkComparability.SELF_BENCHMARK,
                BenchmarkComparability.NOT_APPLICABLE,
            }
            for item in items
        )
        if benchmark_limited:
            reasons.append("匹配基准不可评价,只能查看绝对结果")
        return CompatibilityResult(
            snapshot_id=snapshot_id,
            mode=mode,
            reasons=sorted(set(reasons)),
            changed_fields=sorted(changed),
            economic_inference_allowed=mode
            in {ComparisonMode.COMPARABLE, ComparisonMode.CONTROLLED_SCENARIO_COMPARISON}
            and not benchmark_limited,
            items=items,
        )

    def signals(self, snapshot_id: str) -> SignalsSummary:
        """Return existing signal diagnostics without deriving new research."""
        view = self.repository.view(snapshot_id)
        return SignalsSummary.model_validate({"snapshot_id": snapshot_id, **view.signals})

    def prospective(self, snapshot_id: str) -> ProspectiveSummary:
        """Return JSON-only prospective publication state."""
        view = self.repository.view(snapshot_id)
        return ProspectiveSummary.model_validate({"snapshot_id": snapshot_id, **view.prospective})

    def health(self, snapshot_id: str) -> HealthSummary:
        """Return source and system observations frozen into one snapshot."""
        view = self.repository.view(snapshot_id)
        return HealthSummary.model_validate({"snapshot_id": snapshot_id, **view.health})

    def runtime_status(self) -> RuntimeStatus:
        """Return current Console-only runtime status."""
        return RuntimeStatus.model_validate(self.repository.runtime_status())

    def evidence(self, snapshot_id: str, evidence_id: str) -> EvidenceSummary:
        """Resolve one opaque evidence identity without exposing a source path."""
        view = self.repository.view(snapshot_id)
        value = view.evidence.get(evidence_id)
        if value is None:
            raise KeyError(evidence_id)
        return EvidenceSummary.model_validate({"evidence_id": evidence_id, **value})

    def export(self, snapshot_id: str, request: ExportRequest) -> ExportPayload:
        """Encode a server-whitelisted aggregate export."""
        view = self.repository.view(snapshot_id)
        if request.scope is ExportScope.SELECTED:
            selected = set(request.artifact_ids)
            rows = [row for row in view.experiments if str(row["artifact_id"]) in selected]
            if len(rows) != len(selected):
                raise KeyError("one or more selected experiments do not exist")
        else:
            rows = _filter(view.experiments, request.filters)
        rows = _sort(rows, request.sort, request.direction)
        safe = [_export_row(row) for row in rows]
        if request.format is ExportFormat.JSON:
            body = json.dumps(
                {"snapshot_id": snapshot_id, "scope": request.scope, "items": safe},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
            return ExportPayload(
                body=body,
                media_type="application/json; charset=utf-8",
                filename=f"quant-console-{snapshot_id[:12]}.json",
                snapshot_id=snapshot_id,
            )
        fieldnames = list(safe[0]) if safe else list(_empty_export_row())
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(safe)
        return ExportPayload(
            body=b"\xef\xbb\xbf" + buffer.getvalue().encode(),
            media_type="text/csv; charset=utf-8",
            filename=f"quant-console-{snapshot_id[:12]}.csv",
            snapshot_id=snapshot_id,
        )


def _filter(rows: list[JsonObject], filters: ExperimentFilters) -> list[JsonObject]:
    needle = filters.q.casefold().strip()
    output: list[JsonObject] = []
    for row in rows:
        if needle and not any(
            needle in str(row.get(field, "")).casefold()
            for field in ("experiment_id", "strategy_id", "family")
        ):
            continue
        if filters.study and row.get("study_id") != filters.study:
            continue
        if filters.family and row.get("family") != filters.family:
            continue
        if filters.status and row.get("data_evaluability") != filters.status.value:
            continue
        if filters.economic_outcome and row.get("economic_outcome") != filters.economic_outcome:
            continue
        output.append(row)
    return output


def _sort(rows: list[JsonObject], field: str, direction: SortDirection) -> list[JsonObject]:
    if field not in ALLOWED_SORTS:
        raise ValueError("unsupported sort field")
    non_null: list[tuple[str | int | float | bool, JsonObject]] = []
    nulls: list[JsonObject] = []
    for row in rows:
        value: JsonValue
        if field in {
            "cagr",
            "maximum_drawdown",
            "turnover",
            "total_transaction_costs",
        }:
            metrics = row.get("metrics")
            metric = metrics.get(field) if isinstance(metrics, dict) else None
            value = metric.get("value") if isinstance(metric, dict) else None
        else:
            value = row.get(field)
        if not isinstance(value, str | int | float | bool):
            nulls.append(row)
        else:
            non_null.append((value, row))
    stable = sorted(non_null, key=lambda item: str(item[1].get("artifact_id", "")))
    stable.sort(key=lambda item: item[0], reverse=direction is SortDirection.DESC)
    return [row for _, row in stable] + sorted(
        nulls, key=lambda row: str(row.get("artifact_id", ""))
    )


def _export_row(row: JsonObject) -> dict[str, str | int | float | None]:
    raw_metrics = row.get("metrics")
    metrics = raw_metrics if isinstance(raw_metrics, dict) else {}

    def metric(name: str) -> float | None:
        value = metrics.get(name)
        if not isinstance(value, dict):
            return None
        number = value.get("value")
        return float(number) if isinstance(number, int | float) else None

    return {
        "artifact_id": _csv_text(str(row.get("artifact_id", ""))),
        "study_id": _csv_text(str(row.get("study_id", ""))),
        "experiment_id": _csv_text(str(row.get("experiment_id", ""))),
        "scenario_id": _csv_text(str(row.get("scenario_id", ""))),
        "data_evaluability": _csv_text(str(row.get("data_evaluability", ""))),
        "benchmark_comparability": _csv_text(str(row.get("benchmark_comparability", ""))),
        "economic_outcome": _csv_text(str(row.get("economic_outcome", ""))),
        "cagr": metric("cagr"),
        "maximum_drawdown": metric("maximum_drawdown"),
        "turnover": metric("turnover"),
        "total_transaction_costs": metric("total_transaction_costs"),
        "data_use_level": _csv_text(str(row.get("data_use_level", ""))),
        "source_hash": _csv_text(str(row.get("run_identity", ""))),
    }


def _empty_export_row() -> dict[str, None]:
    return {
        key: None
        for key in (
            "artifact_id",
            "study_id",
            "experiment_id",
            "scenario_id",
            "data_evaluability",
            "benchmark_comparability",
            "economic_outcome",
            "cagr",
            "maximum_drawdown",
            "turnover",
            "total_transaction_costs",
            "data_use_level",
            "source_hash",
        )
    }


def _csv_text(value: str) -> str:
    if value.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value
