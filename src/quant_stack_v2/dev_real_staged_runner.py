"""Two-stage DEV-001 runner that freezes predictions before validation labels."""

from __future__ import annotations

import json
import math
import os
import pickle
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal, Protocol, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from quant_stack_v2.dev_contract import canonical, digest, read_blob, write_blob
from quant_stack_v2.dev_real_contract import RealModelSpec
from quant_stack_v2.dev_real_staged_view import (
    LABEL_COLUMN,
    VerifiedStagedView,
    load_features,
    load_staged_view,
    load_train_labels,
    load_validation_labels,
    load_validation_target_manifest,
)


class StagedRunnerError(ValueError):
    """Raised when a staged real run violates its frozen identities or ordering."""


class _Estimator(Protocol):
    def fit(self, features: NDArray[np.float64], labels: NDArray[np.float64]) -> object: ...

    def predict(self, features: NDArray[np.float64]) -> object: ...


@dataclass(frozen=True)
class PredictionReceipt:
    """One immutable model/prediction identity created before validation targets."""

    sha256: str
    run_sha256: str
    model: str
    training_rows: int
    prediction_rows: int


@dataclass(frozen=True)
class StagedRealResult:
    """Completed real-development diagnostic result."""

    manifest_sha256: str
    run_sha256: str
    model: str
    training_rows: int
    prediction_rows: int
    evaluated_rows: int
    mse: float | None
    daily_ic: float | None
    daily_rank_ic: float | None
    time_segments: dict[str, dict[str, object]]
    status: str


class StagedRealRunner:
    """Fit fixed models and keep validation labels unopened until predictions exist."""

    def __init__(
        self,
        *,
        authority: Path,
        view_root: Path,
        result_root: Path,
        contract_sha256: str,
        evidence_sha256: str,
        view_pin_sha256: str,
    ) -> None:
        self.authority = authority
        self.view_root = view_root
        self.result_root = result_root
        self.contract_sha256 = contract_sha256
        self.evidence_sha256 = evidence_sha256
        self.view_pin_sha256 = view_pin_sha256

    def freeze_predictions(self, model: Literal["linear", "lightgbm"]) -> PredictionReceipt:
        """Fit on training data and publish label-free validation predictions."""
        view = self._view()
        specification = _specification(view, model)
        request = _request(view, specification)
        run_sha = digest(request)
        train_features = load_features(view, "train")
        train_labels = load_train_labels(view)
        valid = load_features(view, "validation")
        train = train_features.merge(
            train_labels, on=["session", "symbol"], how="left", validate="one_to_one"
        )
        train = train[train[LABEL_COLUMN].notna()].copy()
        if train.empty or valid.empty:
            raise StagedRunnerError("real development train or validation sample is empty")
        names = list(view.manifest.feature_names)
        train_x = train.loc[:, names].to_numpy(dtype=float)
        train_y = train[LABEL_COLUMN].to_numpy(dtype=float)
        valid_x = valid.loc[:, names].to_numpy(dtype=float)
        if (
            not np.isfinite(train_x).all()
            or not np.isfinite(train_y).all()
            or not np.isfinite(valid_x).all()
        ):
            raise StagedRunnerError("complete-feature or finite-training-label policy failed")
        estimator = _estimator(specification)
        estimator.fit(train_x, train_y)
        direct = _vector(estimator.predict(valid_x))
        model_body = pickle.dumps(estimator, protocol=pickle.HIGHEST_PROTOCOL)
        restored = _loads_model(model_body)
        rebuilt = _vector(restored.predict(valid_x))
        if not np.array_equal(direct, rebuilt):
            raise StagedRunnerError("model reload changed pre-target predictions")
        model_sha = write_blob(self.result_root / "models", model_body, ".bin")
        prediction_payload = {
            "schema_version": 1,
            "run_id": "DEV-001",
            "model": model,
            "rows": [
                {"session": day.isoformat(), "symbol": symbol, "prediction": float(value)}
                for day, symbol, value in zip(
                    valid["session"], valid["symbol"], rebuilt, strict=True
                )
            ],
        }
        prediction_sha = write_blob(self.result_root / "predictions", canonical(prediction_payload))
        receipt = {
            "schema_version": 1,
            "run_id": "DEV-001",
            "status": "PREDICTIONS_FROZEN_BEFORE_VALIDATION_TARGETS",
            "run_sha256": run_sha,
            "model": model,
            "contract_sha256": self.contract_sha256,
            "evidence_sha256": self.evidence_sha256,
            "view_sha256": view.manifest_sha256,
            "view_pin_sha256": self.view_pin_sha256,
            "request": request,
            "model_sha256": model_sha,
            "predictions_sha256": prediction_sha,
            "training_rows": len(train),
            "prediction_rows": len(valid),
            "validation_targets_opened": False,
        }
        receipt_sha = write_blob(self.authority / "prediction_receipts", canonical(receipt))
        return PredictionReceipt(receipt_sha, run_sha, model, len(train), len(valid))

    def evaluate(self, receipt_sha256: str, target_sha256: str) -> StagedRealResult:
        """Evaluate one frozen prediction only against the post-prediction target release."""
        view = self._view()
        receipt = _json_blob(self.authority / "prediction_receipts", receipt_sha256)
        _check_receipt(receipt, view, self)
        target_manifest = load_validation_target_manifest(view, self.view_root, target_sha256)
        if receipt_sha256 not in target_manifest.prediction_receipt_sha256:
            raise StagedRunnerError("validation target release does not bind this prediction")
        valid = load_features(view, "validation")
        labels = load_validation_labels(view, self.view_root, target_sha256)
        evaluated = valid.merge(labels, on=["session", "symbol"], how="left", validate="one_to_one")
        artifacts = receipt
        model_body = read_blob(self.result_root / "models", str(artifacts["model_sha256"]), ".bin")
        model = _loads_model(model_body)
        rebuilt = _vector(
            model.predict(valid.loc[:, list(view.manifest.feature_names)].to_numpy(dtype=float))
        )
        predictions = _json_blob(
            self.result_root / "predictions", str(artifacts["predictions_sha256"])
        )
        stored = np.asarray(
            [row["prediction"] for row in cast(list[dict[str, object]], predictions["rows"])],
            dtype=float,
        )
        if not np.array_equal(rebuilt, stored):
            raise StagedRunnerError(
                "independent prediction rebuild differs from frozen predictions"
            )
        labels_vector = evaluated[LABEL_COLUMN].to_numpy(dtype=float)
        sessions = tuple(cast(date, item) for item in evaluated["session"])
        metrics = _metrics(sessions, labels_vector, rebuilt)
        segments: dict[str, dict[str, object]] = {}
        for span in view.contract.diagnostic_segments:
            mask = np.fromiter((span.start <= day <= span.end for day in sessions), dtype=bool)
            segments[f"{span.start.isoformat()}_{span.end.isoformat()}"] = _metrics(
                tuple(day for day in sessions if span.start <= day <= span.end),
                labels_vector[mask],
                rebuilt[mask],
            )
        result_payload = {
            "schema_version": 1,
            "kind": "v2_dev_real_baseline_result",
            "run_id": "DEV-001",
            "run_sha256": receipt["run_sha256"],
            "model": receipt["model"],
            "seed": 0,
            "training_rows": receipt["training_rows"],
            "prediction_rows": receipt["prediction_rows"],
            "evaluated_rows": metrics["evaluated_rows"],
            "metrics": metrics,
            "time_segments": segments,
            "model_reload_exact": True,
            "prediction_rebuild_exact": True,
            "portfolio_metrics": None,
            "status": "DEV_REAL_RUN_COMPLETED",
            "formal_research": "BLOCKED_DATA",
            "csi500": "NOT_STARTED",
        }
        result_sha = write_blob(self.result_root / "results", canonical(result_payload))
        manifest = {
            "schema_version": 1,
            "kind": "v2_dev_real_baseline_manifest",
            "run_id": "DEV-001",
            "run_sha256": receipt["run_sha256"],
            "contract_sha256": self.contract_sha256,
            "evidence_sha256": self.evidence_sha256,
            "view_sha256": view.manifest_sha256,
            "view_pin_sha256": self.view_pin_sha256,
            "prediction_receipt_sha256": receipt_sha256,
            "validation_target_sha256": target_sha256,
            "artifacts": {
                "model_sha256": receipt["model_sha256"],
                "predictions_sha256": receipt["predictions_sha256"],
                "result_sha256": result_sha,
            },
            "status": "LIMITED_DEV_RESEARCH",
        }
        manifest_sha = write_blob(self.result_root / "manifests", canonical(manifest))
        _complete(self.result_root / "completions", str(receipt["run_sha256"]), manifest_sha)
        return StagedRealResult(
            manifest_sha256=manifest_sha,
            run_sha256=str(receipt["run_sha256"]),
            model=str(receipt["model"]),
            training_rows=_integer(receipt["training_rows"]),
            prediction_rows=_integer(receipt["prediction_rows"]),
            evaluated_rows=_integer(metrics["evaluated_rows"]),
            mse=_optional(metrics["mse"]),
            daily_ic=_optional(metrics["daily_ic"]),
            daily_rank_ic=_optional(metrics["daily_rank_ic"]),
            time_segments=segments,
            status="DEV_REAL_RUN_COMPLETED",
        )

    def _view(self) -> VerifiedStagedView:
        return load_staged_view(
            self.authority,
            self.view_root,
            self.contract_sha256,
            self.evidence_sha256,
            self.view_pin_sha256,
        )


def _specification(view: VerifiedStagedView, model: str) -> RealModelSpec:
    matches = [item for item in view.contract.models if item.kind == model]
    if len(matches) != 1:
        raise StagedRunnerError("model is not uniquely frozen in DEV-001")
    return matches[0]


def _request(view: VerifiedStagedView, specification: RealModelSpec) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": "DEV-001",
        "contract_sha256": view.manifest.contract_sha256,
        "evidence_sha256": view.manifest.evidence_sha256,
        "view_sha256": view.manifest_sha256,
        "model": specification.model_dump(mode="json"),
        "code_sha256": view.contract.code_sha256,
        "preprocessing": view.contract.preprocessing,
        "preprocessing_params": view.contract.preprocessing_params,
    }


def _estimator(specification: RealModelSpec) -> _Estimator:
    from sklearn.pipeline import Pipeline  # type: ignore[import-untyped]
    from sklearn.preprocessing import StandardScaler  # type: ignore[import-untyped]

    if specification.kind == "linear":
        from sklearn.linear_model import LinearRegression  # type: ignore[import-untyped]

        model = LinearRegression(**specification.params)
    else:
        from lightgbm import LGBMRegressor

        model = LGBMRegressor(**specification.params)  # type: ignore[arg-type]
    scaler = StandardScaler(copy=True, with_mean=True, with_std=True).set_output(transform="pandas")
    return cast(
        _Estimator,
        Pipeline(
            [
                ("standardize", scaler),
                ("model", model),
            ]
        ),
    )


def _check_receipt(
    receipt: dict[str, object], view: VerifiedStagedView, runner: StagedRealRunner
) -> None:
    if (
        receipt.get("status") != "PREDICTIONS_FROZEN_BEFORE_VALIDATION_TARGETS"
        or receipt.get("contract_sha256") != runner.contract_sha256
        or receipt.get("evidence_sha256") != runner.evidence_sha256
        or receipt.get("view_sha256") != view.manifest_sha256
        or receipt.get("view_pin_sha256") != runner.view_pin_sha256
        or receipt.get("validation_targets_opened") is not False
    ):
        raise StagedRunnerError("prediction receipt identity or ordering mismatch")


def _metrics(
    sessions: tuple[date, ...], labels: NDArray[np.float64], predictions: NDArray[np.float64]
) -> dict[str, object]:
    mask = np.isfinite(labels)
    if not mask.any():
        return {
            "evaluated_rows": 0,
            "mse": None,
            "daily_ic": None,
            "daily_rank_ic": None,
            "defined_ic_days": 0,
            "defined_rank_ic_days": 0,
            "undefined_reason": "NO_FINITE_VALIDATION_LABELS",
        }
    actual, predicted = labels[mask], predictions[mask]
    days = np.asarray(sessions, dtype=object)[mask]
    pearson: list[float] = []
    rank: list[float] = []
    for day in dict.fromkeys(days.tolist()):
        selected = days == day
        if selected.sum() < 2 or np.var(actual[selected]) == 0 or np.var(predicted[selected]) == 0:
            continue
        value = float(np.corrcoef(predicted[selected], actual[selected])[0, 1])
        if math.isfinite(value):
            pearson.append(value)
        predicted_rank = pd.Series(predicted[selected]).rank(method="average").to_numpy()
        actual_rank = pd.Series(actual[selected]).rank(method="average").to_numpy()
        if np.var(predicted_rank) > 0 and np.var(actual_rank) > 0:
            value = float(np.corrcoef(predicted_rank, actual_rank)[0, 1])
            if math.isfinite(value):
                rank.append(value)
    return {
        "evaluated_rows": int(mask.sum()),
        "mse": float(np.mean(np.square(predicted - actual))),
        "daily_ic": float(np.mean(pearson)) if pearson else None,
        "daily_rank_ic": float(np.mean(rank)) if rank else None,
        "defined_ic_days": len(pearson),
        "defined_rank_ic_days": len(rank),
        "undefined_reason": None
        if pearson and rank
        else "INSUFFICIENT_OR_CONSTANT_DAILY_CROSS_SECTIONS",
    }


def _complete(root: Path, run_sha: str, manifest_sha: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{run_sha}.json"
    body = canonical({"schema_version": 1, "run_sha256": run_sha, "manifest_sha256": manifest_sha})
    if target.exists():
        if target.read_bytes() != body:
            raise StagedRunnerError("completed DEV-001 run changed under identical identity")
        return
    temporary = root / (".stage-" + os.urandom(8).hex())
    temporary.write_bytes(body)
    try:
        os.link(temporary, target)
    except FileExistsError:
        if target.read_bytes() != body:
            raise StagedRunnerError(
                "completed DEV-001 run changed under identical identity"
            ) from None
    finally:
        temporary.unlink(missing_ok=True)


def _json_blob(root: Path, identity: str) -> dict[str, object]:
    value = json.loads(read_blob(root, identity))
    if not isinstance(value, dict):
        raise StagedRunnerError("content-addressed result must be a JSON object")
    return cast(dict[str, object], value)


def _loads_model(body: bytes) -> _Estimator:
    model = pickle.loads(body)
    if not callable(getattr(model, "predict", None)):
        raise StagedRunnerError("saved model is invalid")
    return cast(_Estimator, model)


def _vector(value: object) -> NDArray[np.float64]:
    result = np.asarray(value, dtype=float)
    if result.ndim != 1 or not np.isfinite(result).all():
        raise StagedRunnerError("model returned invalid predictions")
    return cast(NDArray[np.float64], result)


def _integer(value: object) -> int:
    if type(value) is not int:
        raise StagedRunnerError("sample count is not an integer")
    return value


def _optional(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float) or not math.isfinite(float(cast(float, value))):
        raise StagedRunnerError("metric is neither finite nor null")
    return float(cast(float, value))
