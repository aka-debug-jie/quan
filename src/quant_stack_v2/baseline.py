"""Frozen, sealed-run contracts for V2 Qlib baseline experiments."""

from __future__ import annotations

import json
import math
import os
import pwd
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable

SEEDS = tuple(range(20))
ALLOWED_MODELS = frozenset({"linear", "lightgbm", "xgboost"})
ALLOWED_TRACKS = frozenset({"qlib_compat", "project_20_session"})
SEALED_ROOT = Path("/srv/quant-v2/sealed_holdout")
RESULT_ROOT = Path("/srv/quant-v2/results")


class BaselineGateError(ValueError):
    """Raised when a baseline would bypass its frozen data or sealed-run gate."""


@dataclass(frozen=True)
class BaselinePrecommit:
    """All identities required before a CSI500 evaluator can run once."""

    schema_version: int
    dataset_snapshot_sha256: str
    pit_universe_sha256: str
    code_commit: str
    config_sha256: str
    models: tuple[str, ...]
    tracks: tuple[str, ...]
    seeds: tuple[int, ...]
    execution_delay_sessions: int
    project_horizon_sessions: int
    purge_sessions: int
    embargo_sessions: int
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return stable ID independent of execution time and result quality."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class SealedBaselineResult:
    """Schema-limited external result that cannot carry raw CSI500 observations."""

    precommit_sha256: str
    result_sha256: str
    model: str
    track: str
    seed: int
    metrics: dict[str, float]
    status: str


def create_baseline_precommit(
    artifact_root: Path,
    *,
    dataset_snapshot_sha256: str,
    pit_universe_sha256: str,
    code_commit: str,
    config_sha256: str,
) -> tuple[Path, BaselinePrecommit]:
    """Publish the one frozen configuration accepted by the sealed evaluator."""
    required = (dataset_snapshot_sha256, pit_universe_sha256, code_commit, config_sha256)
    if not all(required) or any(len(value) != 64 for value in required[:2]):
        raise BaselineGateError("baseline precommit requires dataset and PIT SHA-256 identities")
    if len(code_commit) != 40 or len(config_sha256) != 64:
        raise BaselineGateError("baseline precommit requires a Git commit and config SHA-256")
    precommit = BaselinePrecommit(
        schema_version=1,
        dataset_snapshot_sha256=dataset_snapshot_sha256,
        pit_universe_sha256=pit_universe_sha256,
        code_commit=code_commit,
        config_sha256=config_sha256,
        models=("linear", "lightgbm", "xgboost"),
        tracks=("qlib_compat", "project_20_session"),
        seeds=SEEDS,
        execution_delay_sessions=1,
        project_horizon_sessions=20,
        purge_sessions=20,
        embargo_sessions=20,
        status="FROZEN_NOT_EXECUTED",
    )
    content = _canonical_json(asdict(precommit)) + b"\n"
    path = artifact_root / precommit.identity_sha256 / "precommit.json"
    write_immutable(path, content)
    return path, precommit


def run_sealed_baseline_once(
    precommit: BaselinePrecommit,
    *,
    model: str,
    track: str,
    seed: int,
) -> tuple[Path, SealedBaselineResult]:
    """Refuse execution until a reviewed fixed runner replaces callback injection."""
    _validate_precommit(precommit)
    if model not in ALLOWED_MODELS or model not in precommit.models:
        raise BaselineGateError("sealed evaluator model is not precommitted")
    if track not in ALLOWED_TRACKS or track not in precommit.tracks or seed not in precommit.seeds:
        raise BaselineGateError("sealed evaluator track or seed is not precommitted")
    user = pwd.getpwuid(os.geteuid()).pw_name
    if user != "quant-eval":
        raise BaselineGateError("CSI500 sealed evaluation requires the quant-eval account")
    if not _sealed_root_ready():
        raise BaselineGateError("sealed holdout root is not securely provisioned")
    raise BaselineGateError("sealed baseline execution requires a reviewed fixed runner")


def _validate_precommit(precommit: BaselinePrecommit) -> None:
    if (
        precommit.status != "FROZEN_NOT_EXECUTED"
        or precommit.seeds != SEEDS
        or set(precommit.models) != ALLOWED_MODELS
        or set(precommit.tracks) != ALLOWED_TRACKS
        or precommit.execution_delay_sessions != 1
        or precommit.project_horizon_sessions != 20
        or precommit.purge_sessions != 20
        or precommit.embargo_sessions != 20
    ):
        raise BaselineGateError("baseline precommit violates the frozen V2-004 contract")


def _validate_metrics(metrics: Mapping[str, float]) -> dict[str, float]:
    required = {
        "cagr",
        "annualized_volatility",
        "sharpe_ratio",
        "maximum_drawdown",
        "turnover",
        "trade_count",
        "total_transaction_costs",
        "benchmark_cagr",
        "benchmark_sharpe_ratio",
    }
    allowed = required | {"ic", "rank_ic", "icir", "oos_total_return"}
    if not metrics or set(metrics) - allowed or not required <= set(metrics):
        raise BaselineGateError("sealed result must contain only declared aggregate metrics")
    normalized = {key: float(value) for key, value in sorted(metrics.items())}
    if not all(math.isfinite(value) for value in normalized.values()):
        raise BaselineGateError("sealed result metrics must be finite")
    return normalized


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _sealed_root_ready() -> bool:
    """Require the fixed root, an exact marker, and private quant-eval ownership."""
    marker = SEALED_ROOT / "SEALED_HOLDOUT_READY.json"
    data_root = SEALED_ROOT / "data" / "external"
    try:
        evaluator = pwd.getpwnam("quant-eval")
        root_stat = SEALED_ROOT.stat()
        data_stat = data_root.stat()
        marker_stat = marker.stat()
        payload = json.loads(marker.read_text(encoding="utf-8"))
    except (KeyError, OSError, json.JSONDecodeError):
        return False
    return (
        root_stat.st_uid == 0
        and root_stat.st_mode & 0o077 == 0o011
        and data_stat.st_uid == 0
        and data_stat.st_gid == evaluator.pw_gid
        and data_stat.st_mode & 0o077 == 0o050
        and marker_stat.st_uid == 0
        and marker_stat.st_mode & 0o077 == 0o044
        and payload == {"schema_version": 1, "status": "READY"}
    )


def _claim_once(path: Path) -> None:
    """Atomically consume one sealed evaluator request before it can read any data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as error:
        raise BaselineGateError("sealed baseline request is already claimed") from error
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(b"claimed\n")
        handle.flush()
        os.fsync(handle.fileno())


def _record_failure(claim: Path, error: Exception) -> None:
    """Retain an immutable failure receipt without making the claimed run retryable."""
    content = _canonical_json({"exception": type(error).__name__, "message": str(error)}) + b"\n"
    write_immutable(claim.with_suffix(".failure.json"), content)


def _load_sealed_result(
    path: Path, precommit: BaselinePrecommit, model: str, track: str, seed: int
) -> SealedBaselineResult:
    """Load a previous immutable sealed result for an idempotent request."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        raise BaselineGateError("existing sealed result has invalid metrics")
    result = SealedBaselineResult(
        precommit_sha256=str(payload["precommit_sha256"]),
        result_sha256=str(payload["result_sha256"]),
        model=str(payload["model"]),
        track=str(payload["track"]),
        seed=int(payload["seed"]),
        metrics=_validate_metrics({str(key): float(value) for key, value in metrics.items()}),
        status=str(payload["status"]),
    )
    expected_payload = {
        "precommit_sha256": precommit.identity_sha256,
        "model": model,
        "track": track,
        "seed": seed,
        "metrics": result.metrics,
        "status": "PROJECT_FRESH_EXTERNAL_RETROSPECTIVE",
    }
    if (
        result.precommit_sha256 != precommit.identity_sha256
        or result.model != model
        or result.track != track
        or result.seed != seed
        or result.status != "PROJECT_FRESH_EXTERNAL_RETROSPECTIVE"
        or result.result_sha256 != sha256(_canonical_json(expected_payload)).hexdigest()
    ):
        raise BaselineGateError("existing sealed result does not match its immutable request")
    return result
