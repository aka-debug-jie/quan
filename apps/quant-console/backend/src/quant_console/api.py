"""FastAPI application serving one local, same-origin read-only console."""

from __future__ import annotations

import csv
import io
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from quant_console.config import load_config
from quant_console.models import CompareRequest, ExportRequest
from quant_console.snapshot import build_snapshot, load_current

JSON = dict[str, Any]


def create_app(
    runtime: Path, config_path: Path | None = None, static_dir: Path | None = None
) -> FastAPI:
    """Create the local-only application; source roots are immutable process settings."""
    app = FastAPI(title="Quant Console V1", docs_url=None, redoc_url=None)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}
            same_host = parsed.netloc == request.headers.get("host")
            if parsed.scheme != "http" or not loopback or not same_host:
                return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def snapshot() -> JSON:
        try:
            return load_current(runtime)
        except (OSError, ValueError, KeyError) as error:
            raise HTTPException(status_code=503, detail=f"snapshot unavailable: {error}") from error

    @app.get("/api/v1/snapshot")
    def snapshot_meta() -> JSON:
        value = snapshot()
        return {
            "snapshot_id": value["snapshot_id"],
            "generated_at": value["generated_at"],
            "mode": value["mode"],
        }

    @app.get("/api/v1/overview")
    def overview() -> JSON:
        value = snapshot()
        return {"snapshot_id": value["snapshot_id"], **cast(JSON, value["overview"])}

    @app.get("/api/v1/studies")
    def studies() -> JSON:
        value = snapshot()
        return {"items": value["studies"]}

    @app.get("/api/v1/experiments")
    def experiments(
        q: str = "",
        study: str | None = None,
        family: str | None = None,
        status: str | None = None,
        page: int = Query(1, ge=1),
        page_size: int = Query(20, ge=1, le=100),
        sort: str = "experiment_id",
        direction: str = "asc",
    ) -> JSON:
        value = snapshot()
        rows = list(cast(list[JSON], value["experiments"]))
        needle = q.casefold().strip()
        if needle:
            rows = [
                row
                for row in rows
                if needle in str(row["experiment_id"]).casefold()
                or needle in str(row["strategy_id"]).casefold()
            ]
        if study:
            rows = [row for row in rows if row["study_id"] == study]
        if family:
            rows = [row for row in rows if row["family"] == family]
        if status:
            rows = [row for row in rows if row["data_evaluability"] == status]
        allowed_sort = {
            "experiment_id",
            "study_id",
            "family",
            "scenario_id",
            "data_evaluability",
        }
        if sort not in allowed_sort:
            raise HTTPException(status_code=422, detail="unsupported sort field")
        rows.sort(key=lambda row: str(row.get(sort, "")), reverse=direction == "desc")
        start = (page - 1) * page_size
        return {
            "total": len(rows),
            "page": page,
            "page_size": page_size,
            "items": rows[start : start + page_size],
        }

    @app.get("/api/v1/experiments/{artifact_id}")
    def experiment_detail(artifact_id: str) -> JSON:
        value = snapshot()
        detail = cast(JSON, value["experiment_details"]).get(artifact_id)
        if not isinstance(detail, dict):
            raise HTTPException(status_code=404, detail="experiment not found")
        return cast(JSON, detail)

    @app.post("/api/v1/comparisons/validate")
    def validate_comparison(request: CompareRequest) -> JSON:
        value = snapshot()
        details = cast(JSON, value["experiment_details"])
        selected: list[JSON] = []
        for artifact_id in request.artifact_ids:
            item = details.get(artifact_id)
            if not isinstance(item, dict):
                raise HTTPException(status_code=404, detail=f"experiment not found: {artifact_id}")
            selected.append(cast(JSON, item))
        baseline = cast(JSON, selected[0]["compatibility"])
        reasons: list[str] = []
        for item in selected[1:]:
            current = cast(JSON, item["compatibility"])
            for field in (
                "study_revision",
                "scenario_id",
                "bars_sha256",
                "protocol_sha256",
                "initial_cash",
            ):
                if current.get(field) != baseline.get(field):
                    reasons.append(f"{field} 不一致")
            if item.get("period") != selected[0].get("period"):
                reasons.append("数据期间不一致")
        mode = "COMPARABLE" if not reasons else "DESCRIPTIVE_ONLY"
        return {"mode": mode, "reasons": sorted(set(reasons)), "items": selected}

    @app.get("/api/v1/signals")
    def signals() -> JSON:
        return cast(JSON, snapshot()["signals"])

    @app.get("/api/v1/prospective")
    def prospective() -> JSON:
        return cast(JSON, snapshot()["prospective"])

    @app.get("/api/v1/health")
    def health() -> JSON:
        value = snapshot()
        refresh_path = runtime / "last_refresh.json"
        refresh: JSON | None = None
        if refresh_path.exists():
            import json

            parsed = json.loads(refresh_path.read_bytes())
            refresh = cast(JSON, parsed) if isinstance(parsed, dict) else None
        return {**cast(JSON, value["health"]), "last_refresh": refresh}

    @app.get("/api/v1/evidence/{evidence_id:path}")
    def evidence(evidence_id: str) -> JSON:
        value = snapshot()
        evidence_key = (
            evidence_id if evidence_id.startswith("evidence:") else f"evidence:{evidence_id}"
        )
        item = cast(JSON, value["evidence"]).get(evidence_key)
        if not isinstance(item, dict):
            raise HTTPException(status_code=404, detail="evidence not found")
        return cast(JSON, item)

    @app.post("/api/v1/exports/experiments")
    def export_experiments(request: ExportRequest) -> Response:
        value = snapshot()
        details = cast(JSON, value["experiment_details"])
        safe_rows: list[JSON] = []
        for artifact_id in request.artifact_ids:
            item = details.get(artifact_id)
            if not isinstance(item, dict):
                raise HTTPException(status_code=404, detail=f"experiment not found: {artifact_id}")
            row = cast(JSON, item)
            safe_rows.append(
                {
                    "artifact_id": artifact_id,
                    "study_id": row.get("study_id"),
                    "experiment_id": row.get("experiment_id"),
                    "scenario_id": row.get("scenario_id"),
                    "data_evaluability": row.get("data_evaluability"),
                    "benchmark_comparability": row.get("benchmark_comparability"),
                    "economic_outcome": row.get("economic_outcome"),
                    "cagr": _metric_value(row, "cagr"),
                    "maximum_drawdown": _metric_value(row, "maximum_drawdown"),
                    "turnover": _metric_value(row, "turnover"),
                    "total_transaction_costs": _metric_value(row, "total_transaction_costs"),
                    "data_use_level": row.get("data_use_level"),
                    "source_hash": cast(JSON, row.get("source", {})).get("sha256"),
                }
            )
        if request.format == "json":
            return JSONResponse(
                {"mode": value["mode"], "snapshot_id": value["snapshot_id"], "items": safe_rows}
            )
        buffer = io.StringIO()
        writer = csv.DictWriter(buffer, fieldnames=list(safe_rows[0]))
        writer.writeheader()
        writer.writerows(safe_rows)
        filename = f"quant-console-{str(value['snapshot_id'])[:12]}.csv"
        return StreamingResponse(
            iter([buffer.getvalue()]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.post("/api/v1/snapshot/reload")
    def reload_snapshot() -> JSON:
        if config_path is None:
            raise HTTPException(status_code=409, detail="demo snapshot cannot reload real sources")
        path = build_snapshot(
            load_config(config_path), runtime, runtime / "system-observation.json"
        )
        value = load_current(runtime)
        return {
            "status": "PASS",
            "snapshot_id": value["snapshot_id"],
            "path_exposed": False,
            "source": path.name,
        }

    if static_dir is not None and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                raise HTTPException(status_code=404)
            candidate = static_dir / path
            if candidate.is_file() and candidate.resolve().is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


def _metric_value(row: JSON, key: str) -> Any:
    metrics = row.get("metrics")
    if not isinstance(metrics, dict):
        return None
    metric = metrics.get(key)
    return metric.get("value") if isinstance(metric, dict) else None
