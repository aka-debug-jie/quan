"""FastAPI application serving one local, same-origin read-only console."""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Annotated
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import FastAPI, Query, Request
from fastapi import Path as ApiPath
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from quant_console.config import load_config
from quant_console.models import (
    CompareRequest,
    CompatibilityResult,
    DataEvaluability,
    ErrorDetail,
    ErrorEnvelope,
    EvidenceSummary,
    ExperimentDetail,
    ExperimentFilters,
    ExperimentPage,
    ExportRequest,
    HealthSummary,
    Overview,
    ProspectiveSummary,
    ReloadResult,
    RuntimeStatus,
    SeriesResponse,
    SignalsSummary,
    SnapshotMeta,
    SortDirection,
    StudyList,
)
from quant_console.repository import SnapshotRepository
from quant_console.service import ConsoleService
from quant_console.snapshot import SnapshotError, build_snapshot

Identifier = Annotated[str, ApiPath(max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$")]
Digest = Annotated[str, ApiPath(pattern=r"^[0-9a-f]{64}$")]
LOGGER = logging.getLogger("quant_console.request")


class ApiError(Exception):
    """Safe expected API failure."""

    def __init__(self, status_code: int, code: str, message: str, *, recoverable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.recoverable = recoverable


def create_app(
    runtime: Path, config_path: Path | None = None, static_dir: Path | None = None
) -> FastAPI:
    """Create the local-only application; source roots are immutable process settings."""
    app = FastAPI(
        title="Quant Console V1.5",
        version="1.5.0",
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"],
    )
    repository = SnapshotRepository(runtime)
    service = ConsoleService(repository)
    reload_lock = Lock()

    @app.middleware("http")
    async def request_boundary(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        origin = request.headers.get("origin")
        if origin:
            parsed = urlsplit(origin)
            loopback = parsed.hostname in {"127.0.0.1", "localhost", "::1", "testserver"}
            same_host = parsed.netloc == request.headers.get("host")
            if parsed.scheme != "http" or not loopback or not same_host:
                return _error_response(
                    request,
                    403,
                    "ORIGIN_NOT_ALLOWED",
                    "请求来源不允许",
                    recoverable=False,
                )
        started = perf_counter()
        response = await call_next(request)
        elapsed_ms = round((perf_counter() - started) * 1000, 3)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
        )
        if request.url.path == "/api/v1/snapshot" or request.url.path == "/api/v1/runtime":
            response.headers["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/api/v1/snapshots/"):
            response.headers["Cache-Control"] = "private, max-age=31536000, immutable"
        LOGGER.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "route": getattr(request.scope.get("route"), "path", request.url.path),
                    "status": response.status_code,
                    "elapsed_ms": elapsed_ms,
                },
                sort_keys=True,
            )
        )
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return _error_response(
            request,
            error.status_code,
            error.code,
            error.message,
            recoverable=error.recoverable,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        return _error_response(
            request,
            422,
            "REQUEST_VALIDATION_FAILED",
            "请求参数不符合接口契约",
            recoverable=True,
        )

    @app.exception_handler(SnapshotError)
    async def snapshot_error(request: Request, _error: SnapshotError) -> JSONResponse:
        return _error_response(
            request,
            409,
            "SNAPSHOT_INVALID",
            "请求的展示快照不存在或完整性校验失败",
            recoverable=True,
        )

    @app.exception_handler(ValidationError)
    async def contract_error(request: Request, _error: ValidationError) -> JSONResponse:
        return _error_response(
            request,
            409,
            "SNAPSHOT_SCHEMA_MISMATCH",
            "展示快照与当前接口契约不一致",
            recoverable=True,
        )

    @app.get("/api/v1/snapshot", response_model=SnapshotMeta)
    def snapshot_meta() -> SnapshotMeta:
        try:
            return repository.current_meta()
        except (OSError, ValueError, KeyError) as error:
            raise ApiError(
                503,
                "SNAPSHOT_UNAVAILABLE",
                "当前展示快照不可用",
                recoverable=True,
            ) from error

    @app.get("/api/v1/runtime", response_model=RuntimeStatus)
    def runtime_status() -> RuntimeStatus:
        return service.runtime_status()

    @app.get("/api/v1/snapshots/{snapshot_id}/overview", response_model=Overview)
    def overview(snapshot_id: Digest) -> Overview:
        return service.overview(snapshot_id)

    @app.get("/api/v1/snapshots/{snapshot_id}/studies", response_model=StudyList)
    def studies(snapshot_id: Digest) -> StudyList:
        return service.studies(snapshot_id)

    @app.get("/api/v1/snapshots/{snapshot_id}/experiments", response_model=ExperimentPage)
    def experiments(
        snapshot_id: Digest,
        q: str = Query(default="", max_length=200),
        study: str | None = Query(default=None, max_length=100),
        family: str | None = Query(default=None, max_length=100),
        status: DataEvaluability | None = None,
        economic_outcome: str | None = Query(default=None, max_length=100),
        page: int = Query(default=1, ge=1),
        page_size: int = Query(default=100, ge=1, le=10_000),
        sort: str = Query(default="experiment_id", max_length=64),
        direction: SortDirection = SortDirection.ASC,
    ) -> ExperimentPage:
        try:
            return service.experiments(
                snapshot_id,
                filters=ExperimentFilters(
                    q=q,
                    study=study,
                    family=family,
                    status=status,
                    economic_outcome=economic_outcome,
                ),
                page=page,
                page_size=page_size,
                sort=sort,
                direction=direction,
            )
        except ValueError as error:
            raise ApiError(422, "UNSUPPORTED_SORT", "不支持的排序字段", recoverable=True) from error

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/experiments/{artifact_id}",
        response_model=ExperimentDetail,
    )
    def experiment_detail(snapshot_id: Digest, artifact_id: Identifier) -> ExperimentDetail:
        try:
            return service.detail(snapshot_id, artifact_id)
        except KeyError as error:
            raise ApiError(404, "EXPERIMENT_NOT_FOUND", "实验不存在", recoverable=True) from error

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/series/{series_id}",
        response_model=SeriesResponse,
    )
    def series(snapshot_id: Digest, series_id: Digest) -> SeriesResponse:
        try:
            return service.series(snapshot_id, series_id)
        except KeyError as error:
            raise ApiError(404, "SERIES_NOT_FOUND", "时序不存在", recoverable=True) from error

    @app.post(
        "/api/v1/snapshots/{snapshot_id}/comparisons/validate",
        response_model=CompatibilityResult,
    )
    def validate_comparison(snapshot_id: Digest, payload: CompareRequest) -> CompatibilityResult:
        try:
            return service.compare(snapshot_id, payload)
        except KeyError as error:
            raise ApiError(404, "EXPERIMENT_NOT_FOUND", "比较项不存在", recoverable=True) from error

    @app.get("/api/v1/snapshots/{snapshot_id}/signals", response_model=SignalsSummary)
    def signals(snapshot_id: Digest) -> SignalsSummary:
        return service.signals(snapshot_id)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/prospective",
        response_model=ProspectiveSummary,
    )
    def prospective(snapshot_id: Digest) -> ProspectiveSummary:
        return service.prospective(snapshot_id)

    @app.get("/api/v1/snapshots/{snapshot_id}/health", response_model=HealthSummary)
    def health(snapshot_id: Digest) -> HealthSummary:
        return service.health(snapshot_id)

    @app.get(
        "/api/v1/snapshots/{snapshot_id}/evidence/{evidence_id}",
        response_model=EvidenceSummary,
    )
    def evidence(snapshot_id: Digest, evidence_id: Identifier) -> EvidenceSummary:
        try:
            return service.evidence(snapshot_id, evidence_id)
        except KeyError as error:
            raise ApiError(404, "EVIDENCE_NOT_FOUND", "证据不存在", recoverable=True) from error

    @app.post("/api/v1/snapshots/{snapshot_id}/exports/experiments")
    def export_experiments(snapshot_id: Digest, payload: ExportRequest) -> Response:
        try:
            result = service.export(snapshot_id, payload)
        except (KeyError, ValueError) as error:
            raise ApiError(422, "EXPORT_INVALID", "导出范围无效", recoverable=True) from error
        return Response(
            content=result.body,
            media_type=result.media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{result.filename}"',
                "X-Quant-Snapshot-ID": result.snapshot_id,
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/v1/snapshot/reload", response_model=ReloadResult)
    def reload_snapshot() -> ReloadResult:
        if config_path is None:
            raise ApiError(
                409,
                "DEMO_RELOAD_FORBIDDEN",
                "演示模式不能重载真实来源",
                recoverable=False,
            )
        if not reload_lock.acquire(blocking=False):
            raise ApiError(
                409,
                "RELOAD_IN_PROGRESS",
                "已有快照重载正在进行",
                recoverable=True,
            )
        try:
            previous = repository.runtime_status().get("current_snapshot_id")
            build_snapshot(load_config(config_path), runtime, runtime / "system-observation.json")
            repository.clear()
            current = repository.current_meta()
            return ReloadResult(
                status="PASS",
                snapshot=current,
                changed=previous != current.snapshot_id,
            )
        except (OSError, ValueError, KeyError) as error:
            raise ApiError(
                503,
                "RELOAD_FAILED",
                "来源重载失败,继续保留上一可用快照",
                recoverable=True,
            ) from error
        finally:
            reload_lock.release()

    if static_dir is not None and static_dir.is_dir():
        assets = static_dir / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> Response:
            if path.startswith("api/"):
                raise ApiError(404, "ROUTE_NOT_FOUND", "接口不存在", recoverable=True)
            candidate = static_dir / path
            if candidate.is_file() and candidate.resolve().is_relative_to(static_dir.resolve()):
                return FileResponse(candidate)
            return FileResponse(static_dir / "index.html")

    return app


def _error_response(
    request: Request,
    status_code: int,
    code: str,
    message: str,
    *,
    recoverable: bool,
) -> JSONResponse:
    request_id = str(getattr(request.state, "request_id", uuid4().hex))
    payload = ErrorEnvelope(
        error=ErrorDetail(
            code=code,
            message=message,
            request_id=request_id,
            recoverable=recoverable,
        )
    )
    return JSONResponse(payload.model_dump(mode="json"), status_code=status_code)
