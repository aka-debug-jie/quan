"""Independent, synthetic-only V2 development baseline runner."""

from __future__ import annotations

import ctypes
import json
import math
import os
import pickle
import stat
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Protocol, cast
from uuid import uuid4

import numpy as np
from numpy.typing import NDArray

from quant_stack_v2.dev_contract import (
    DevContract,
    FeatureSpec,
    Member,
    ModelSpec,
    UsePins,
    canonical,
    digest,
    directory,
    read_blob,
    write_blob,
)
from quant_stack_v2.dev_view import VerifiedView, load_view


class DevBaselineError(ValueError):
    """Raised when a dev run violates scope, time, or immutable identity."""


@dataclass(frozen=True)
class DevBaselineResult:
    """Aggregate development result plus content-addressed artifact identities."""

    manifest_sha256: str
    run_sha256: str
    model: str
    seed: int
    training_rows: int
    prediction_rows: int
    evaluated_rows: int
    mse: float | None
    ic: float | None
    status: str


class _Estimator(Protocol):
    def fit(self, features: NDArray[np.float64], labels: NDArray[np.float64]) -> _Estimator: ...

    def predict(self, features: NDArray[np.float64]) -> NDArray[np.float64]: ...


class _Scaler(Protocol):
    def set_output(self, *, transform: str) -> _Scaler: ...


@dataclass(frozen=True)
class _Samples:
    train_x: NDArray[np.float64]
    train_y: NDArray[np.float64]
    valid_x: NDArray[np.float64]
    valid_keys: tuple[tuple[date, str], ...]
    valid_y: NDArray[np.float64]
    evaluation_mask: NDArray[np.bool_]


class DevBaselineRunner:
    """Run only the exact synthetic view and fixed models selected by trusted pins."""

    def __init__(
        self,
        *,
        authority: Path,
        view_root: Path,
        result_root: Path,
        pins: UsePins,
        view_sha256: str,
    ) -> None:
        self._authority = authority
        self._view_root = view_root
        self._result_root = result_root
        self._pins = pins
        self._view_sha256 = view_sha256

    def run(self, model: str) -> DevBaselineResult:
        """Reload the trusted view, fit one declared model, and publish manifest last."""
        view = load_view(self._authority, self._view_root, self._pins, self._view_sha256)
        specification = _model_spec(view, model)
        request = _request(view, specification)
        run_sha256 = digest(request)
        try:
            _claim_slot(self._result_root / "claims", request, run_sha256)
            samples = _assemble(view)
            estimator = _make_estimator(specification)
            estimator.fit(samples.train_x, samples.train_y)
            direct = _vector(estimator.predict(samples.valid_x))

            model_body = pickle.dumps(estimator, protocol=pickle.HIGHEST_PROTOCOL)
            restored = _loads_estimator(model_body)
            predictions = _vector(restored.predict(samples.valid_x))
            if not np.array_equal(direct, predictions, equal_nan=True):
                raise DevBaselineError("saved model changed validation predictions")

            model_sha256 = write_blob(self._result_root / "models", model_body, ".bin")
            prediction_body = canonical(_prediction_payload(samples.valid_keys, predictions))
            prediction_sha256 = write_blob(self._result_root / "predictions", prediction_body)
            metrics = _metrics(samples, predictions)
            result_payload = {
                "schema_version": 1,
                "kind": "v2_dev_baseline_result",
                "run_sha256": run_sha256,
                "model": specification.kind,
                "seed": specification.seed,
                "training_rows": len(samples.train_y),
                "prediction_rows": len(predictions),
                "evaluated_rows": metrics["evaluated_rows"],
                "metrics": {"mse": metrics["mse"], "ic": metrics["ic"]},
                "roundtrip_exact": True,
                "status": "DEV_SMOKE_SYNTHETIC_COMPLETED",
            }
            result_sha256 = write_blob(self._result_root / "results", canonical(result_payload))
            manifest_payload = {
                "schema_version": 1,
                "kind": "v2_dev_baseline_manifest",
                "status": "LIMITED_DEV_RESEARCH",
                "run_sha256": run_sha256,
                "use": {
                    "contract_sha256": view.contract_sha256,
                    "evidence_sha256": view.evidence_sha256,
                },
                "view_sha256": view.view_sha256,
                "model_identity": request["model_identity"],
                "config_sha256": request["config_sha256"],
                "code_sha256": request["code_sha256"],
                "artifacts": {
                    "model_sha256": model_sha256,
                    "predictions_sha256": prediction_sha256,
                    "result_sha256": result_sha256,
                },
            }
            manifest_sha256 = write_blob(
                self._result_root / "manifests", canonical(manifest_payload)
            )
            _complete_run(self._result_root / "completions", run_sha256, manifest_sha256)
            return _load_result(self._result_root, manifest_sha256, request, run_sha256)
        except BaseException as error:
            status = (
                "INTERRUPTED" if isinstance(error, (KeyboardInterrupt, SystemExit)) else "FAILED"
            )
            _record_failure(self._result_root, request, run_sha256, status, error)
            raise

    def load_model(self, result: DevBaselineResult) -> _Estimator:
        """Reload a model only after revalidating the trusted view and manifest chain."""
        view = load_view(self._authority, self._view_root, self._pins, self._view_sha256)
        specification = _model_spec(view, result.model)
        request = _request(view, specification)
        loaded = _load_result(self._result_root, result.manifest_sha256, request, result.run_sha256)
        if loaded != result:
            raise DevBaselineError("result object does not match its immutable manifest")
        manifest = _json_blob(self._result_root / "manifests", result.manifest_sha256)
        artifacts = _mapping(manifest["artifacts"], "manifest artifacts")
        body = read_blob(self._result_root / "models", str(artifacts["model_sha256"]), ".bin")
        return _loads_estimator(body)


def _model_spec(view: VerifiedView, model: str) -> ModelSpec:
    if view.contract.data_kind != "SYNTHETIC":
        raise DevBaselineError("real development data is not executable")
    matches = [item for item in view.contract.models if item.kind == model]
    if len(matches) != 1:
        raise DevBaselineError("model is not uniquely declared by the dev contract")
    return matches[0]


def _request(view: VerifiedView, model: ModelSpec) -> dict[str, object]:
    runtime = {
        "device": "cpu",
        "n_jobs": 1,
        "deterministic": True,
        "preprocessing": view.contract.preprocessing,
        "scikit_learn_version": version("scikit-learn"),
        "lightgbm_version": version("lightgbm") if model.kind == "lightgbm" else None,
    }
    model_identity = {
        "kind": model.kind,
        "seed": model.seed,
        "params": dict(sorted(model.params.items())),
        "runtime": runtime,
    }
    configuration = {
        "contract_sha256": view.contract_sha256,
        "features": [feature.model_dump(mode="json") for feature in view.contract.features],
        "label": view.contract.label.model_dump(mode="json"),
        "train": view.contract.train.model_dump(mode="json"),
        "valid": view.contract.valid.model_dump(mode="json"),
        "train_label_end": view.contract.train_label_end.isoformat(),
        "valid_label_end": view.contract.valid_label_end.isoformat(),
        "embargo_sessions": view.contract.embargo_sessions,
        "model": model_identity,
    }
    return {
        "schema_version": 1,
        "use": {
            "contract_sha256": view.contract_sha256,
            "evidence_sha256": view.evidence_sha256,
        },
        "view_sha256": view.view_sha256,
        "model_identity": model_identity,
        "config_sha256": digest(configuration),
        "code_sha256": _code_sha256(),
    }


def _assemble(view: VerifiedView) -> _Samples:
    contract = view.contract
    positions = {session: index for index, session in enumerate(contract.sessions)}
    rows = {(row.symbol, row.session): row.values for row in view.data.rows}
    members = view.data.members
    train_x: list[list[float]] = []
    train_y: list[float] = []
    valid_x: list[list[float]] = []
    valid_y: list[float] = []
    valid_keys: list[tuple[date, str]] = []
    evaluation_mask: list[bool] = []

    for session in contract.sessions:
        in_train = contract.train.start <= session <= contract.train.end
        in_valid = contract.valid.start <= session <= contract.valid.end
        if not in_train and not in_valid:
            continue
        index = positions[session]
        label_end = contract.sessions[index + contract.label.end_offset]
        label_allowed = (
            label_end <= contract.train_label_end
            if in_train
            else label_end <= contract.valid_label_end
        )
        for symbol in contract.symbols:
            if not _is_member(symbol, session, members):
                continue
            features = _features(rows, symbol, index, contract.sessions, contract.features)
            if features is None:
                continue
            if in_train:
                label = _label(rows, symbol, index, contract)
                if label_allowed and label is not None:
                    train_x.append(features)
                    train_y.append(label)
            else:
                # Prediction membership is decided before and independently of label access.
                valid_x.append(features)
                valid_keys.append((session, symbol))
                label = _label(rows, symbol, index, contract) if label_allowed else None
                valid_y.append(float("nan") if label is None else label)
                evaluation_mask.append(label is not None)
    if not train_x:
        raise DevBaselineError("no complete mature training samples")
    if not valid_x:
        raise DevBaselineError("no point-in-time eligible validation predictions")
    return _Samples(
        train_x=np.asarray(train_x, dtype=float),
        train_y=np.asarray(train_y, dtype=float),
        valid_x=np.asarray(valid_x, dtype=float),
        valid_keys=tuple(valid_keys),
        valid_y=np.asarray(valid_y, dtype=float),
        evaluation_mask=np.asarray(evaluation_mask, dtype=bool),
    )


def _features(
    rows: Mapping[tuple[str, date], Mapping[str, float | None]],
    symbol: str,
    index: int,
    sessions: Sequence[date],
    specifications: Sequence[FeatureSpec],
) -> list[float] | None:
    values: list[float] = []
    for feature in specifications:
        lag = feature.lag
        field = feature.field
        source = rows[(symbol, sessions[index - lag])][field]
        if source is None or not math.isfinite(source):
            return None
        values.append(float(source))
    return values


def _label(
    rows: Mapping[tuple[str, date], Mapping[str, float | None]],
    symbol: str,
    index: int,
    contract: DevContract,
) -> float | None:
    label = contract.label
    sessions = contract.sessions
    start = rows[(symbol, sessions[index + label.start_offset])][label.field]
    end = rows[(symbol, sessions[index + label.end_offset])][label.field]
    if (
        start is None
        or end is None
        or not math.isfinite(start)
        or not math.isfinite(end)
        or start <= 0
    ):
        return None
    return float(end / start - 1.0)


def _is_member(symbol: str, session: date, members: Sequence[Member]) -> bool:
    return any(item.symbol == symbol and item.start <= session <= item.end for item in members)


def _make_estimator(specification: ModelSpec) -> _Estimator:
    scaler_type = cast(
        Callable[..., _Scaler],
        import_module("sklearn.preprocessing").StandardScaler,
    )
    pipeline_type = cast(Callable[..., _Estimator], import_module("sklearn.pipeline").Pipeline)
    parameters = cast(dict[str, object], dict(specification.params))
    if specification.kind == "linear":
        model_type = cast(
            Callable[..., _Estimator],
            import_module("sklearn.linear_model").LinearRegression,
        )
        parameters["n_jobs"] = 1
    else:
        model_type = cast(Callable[..., _Estimator], import_module("lightgbm").LGBMRegressor)
        parameters.update(
            {
                "random_state": specification.seed,
                "device_type": "cpu",
                "n_jobs": 1,
                "deterministic": True,
                "force_col_wise": True,
                "subsample": 1.0,
                "colsample_bytree": 1.0,
                "verbosity": -1,
            }
        )
    # Pandas output also avoids LightGBM 4.5's obsolete ndarray validation call
    # under the locked scikit-learn runtime, without changing fitted values.
    scaler = scaler_type().set_output(transform="pandas")
    return pipeline_type(steps=[("standardize", scaler), ("model", model_type(**parameters))])


def _metrics(samples: _Samples, predictions: NDArray[np.float64]) -> dict[str, object]:
    mask = samples.evaluation_mask
    if not mask.any():
        return {"evaluated_rows": 0, "mse": None, "ic": None}
    actual = samples.valid_y[mask]
    predicted = predictions[mask]
    mse = float(np.mean(np.square(predicted - actual)))
    sessions = np.asarray([key[0] for key in samples.valid_keys], dtype=object)[mask]
    correlations: list[float] = []
    for session in dict.fromkeys(sessions.tolist()):
        selected = sessions == session
        if selected.sum() < 2 or np.var(actual[selected]) == 0 or np.var(predicted[selected]) == 0:
            continue
        correlation = float(np.corrcoef(predicted[selected], actual[selected])[0, 1])
        if math.isfinite(correlation):
            correlations.append(correlation)
    return {
        "evaluated_rows": int(mask.sum()),
        "mse": mse,
        "ic": float(np.mean(correlations)) if correlations else None,
    }


def _prediction_payload(
    keys: Sequence[tuple[date, str]], predictions: NDArray[np.float64]
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "rows": [
            {"session": day.isoformat(), "symbol": symbol, "prediction": float(value)}
            for (day, symbol), value in zip(keys, predictions, strict=True)
        ],
    }


def _claim_slot(root: Path, request: Mapping[str, object], run_sha256: str) -> None:
    model = _mapping(request["model_identity"], "model identity")
    use = _mapping(request["use"], "use identity")
    slot = {
        "contract_sha256": use["contract_sha256"],
        "evidence_sha256": use["evidence_sha256"],
        "view_sha256": request["view_sha256"],
        "model": model["kind"],
    }
    body = canonical(
        {"schema_version": 1, "slot": slot, "run_sha256": run_sha256, "request": request}
    )
    name = digest(slot) + ".json"
    _write_named_once(root, name, body, "code or configuration drift for existing dev slot")


def _complete_run(root: Path, run_sha256: str, manifest_sha256: str) -> None:
    body = canonical(
        {
            "schema_version": 1,
            "run_sha256": run_sha256,
            "manifest_sha256": manifest_sha256,
        }
    )
    _write_named_once(
        root,
        run_sha256 + ".json",
        body,
        "reproducibility drift for completed dev run",
    )


def _write_named_once(root: Path, name: str, body: bytes, drift_message: str) -> None:
    with directory(root, create=True) as descriptor:
        temporary = ".stage-claim-" + uuid4().hex
        handle = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=descriptor,
        )
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                _publish_no_replace(descriptor, temporary, name)
            except FileExistsError:
                if _read_named(descriptor, name) != body:
                    raise DevBaselineError(drift_message) from None
            os.fsync(descriptor)
        finally:
            try:
                os.unlink(temporary, dir_fd=descriptor)
            except FileNotFoundError:
                pass


def _read_named(descriptor: int, name: str) -> bytes:
    handle = os.open(
        name,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
        dir_fd=descriptor,
    )
    with os.fdopen(handle, "rb") as stream:
        information = os.fstat(stream.fileno())
        if (
            not stat.S_ISREG(information.st_mode)
            or information.st_nlink != 1
            or information.st_size > 1024 * 1024
        ):
            raise DevBaselineError("existing dev claim is not a bounded regular file")
        body = stream.read(1024 * 1024 + 1)
    if len(body) > 1024 * 1024:
        raise DevBaselineError("existing dev claim exceeds its size limit")
    return body


def _publish_no_replace(descriptor: int, temporary: str, target: str) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    rename = library.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(descriptor, temporary.encode(), descriptor, target.encode(), 1) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), target)


def _load_result(
    root: Path,
    manifest_sha256: str,
    request: Mapping[str, object],
    run_sha256: str,
) -> DevBaselineResult:
    if run_sha256 != digest(request):
        raise DevBaselineError("run identity differs from bound request")
    manifest = _json_blob(root / "manifests", manifest_sha256)
    if set(manifest) != {
        "schema_version",
        "kind",
        "status",
        "run_sha256",
        "use",
        "view_sha256",
        "model_identity",
        "config_sha256",
        "code_sha256",
        "artifacts",
    }:
        raise DevBaselineError("manifest schema contains missing or undeclared fields")
    if (
        manifest["schema_version"] != 1
        or manifest["kind"] != "v2_dev_baseline_manifest"
        or manifest["status"] != "LIMITED_DEV_RESEARCH"
        or manifest["run_sha256"] != run_sha256
    ):
        raise DevBaselineError("manifest run identity mismatch")
    for field in ("use", "view_sha256", "model_identity", "config_sha256", "code_sha256"):
        if manifest.get(field) != request[field]:
            raise DevBaselineError("manifest binding mismatch: " + field)
    artifacts = _mapping(manifest.get("artifacts"), "manifest artifacts")
    if set(artifacts) != {"model_sha256", "predictions_sha256", "result_sha256"}:
        raise DevBaselineError("manifest artifact schema mismatch")
    result = _json_blob(root / "results", str(artifacts["result_sha256"]))
    if set(result) != {
        "schema_version",
        "kind",
        "run_sha256",
        "model",
        "seed",
        "training_rows",
        "prediction_rows",
        "evaluated_rows",
        "metrics",
        "roundtrip_exact",
        "status",
    }:
        raise DevBaselineError("result schema contains missing or undeclared fields")
    model_identity = _mapping(request["model_identity"], "model identity")
    if (
        result["schema_version"] != 1
        or result["kind"] != "v2_dev_baseline_result"
        or result["run_sha256"] != run_sha256
        or result["model"] != model_identity["kind"]
        or result["seed"] != model_identity["seed"]
        or result["roundtrip_exact"] is not True
        or result["status"] != "DEV_SMOKE_SYNTHETIC_COMPLETED"
    ):
        raise DevBaselineError("result identity or status mismatch")
    metrics = _mapping(result.get("metrics"), "result metrics")
    if set(metrics) != {"mse", "ic"}:
        raise DevBaselineError("result contains undeclared or combined metrics")
    training_rows = _integer(result["training_rows"])
    prediction_rows = _integer(result["prediction_rows"])
    evaluated_rows = _integer(result["evaluated_rows"])
    if training_rows <= 0 or prediction_rows <= 0 or not 0 <= evaluated_rows <= prediction_rows:
        raise DevBaselineError("result counts violate development sample bounds")
    read_blob(root / "models", str(artifacts["model_sha256"]), ".bin")
    predictions = _json_blob(root / "predictions", str(artifacts["predictions_sha256"]))
    if (
        set(predictions) != {"schema_version", "rows"}
        or predictions["schema_version"] != 1
        or not isinstance(predictions["rows"], list)
        or len(predictions["rows"]) != prediction_rows
    ):
        raise DevBaselineError("prediction artifact schema or count mismatch")
    mse, ic = _optional_metric(metrics["mse"]), _optional_metric(metrics["ic"])
    if evaluated_rows == 0 and (mse is not None or ic is not None):
        raise DevBaselineError("undefined metrics must be null")
    if evaluated_rows > 0 and (mse is None or mse < 0):
        raise DevBaselineError("evaluated MSE must be defined and nonnegative")
    if ic is not None and (evaluated_rows < 2 or not -1 <= ic <= 1):
        raise DevBaselineError("invalid defined IC")
    expected_completion = canonical(
        {"schema_version": 1, "run_sha256": run_sha256, "manifest_sha256": manifest_sha256}
    )
    try:
        with directory(root / "completions") as fd:
            completion = _read_named(fd, run_sha256 + ".json")
    except OSError as error:
        raise DevBaselineError("missing or invalid completion pointer") from error
    if completion != expected_completion:
        raise DevBaselineError("completion identity mismatch")
    return DevBaselineResult(
        manifest_sha256=manifest_sha256,
        run_sha256=run_sha256,
        model=str(result["model"]),
        seed=_integer(result["seed"]),
        training_rows=training_rows,
        prediction_rows=prediction_rows,
        evaluated_rows=evaluated_rows,
        mse=mse,
        ic=ic,
        status=str(result["status"]),
    )


def _record_failure(
    root: Path,
    request: Mapping[str, object],
    run_sha256: str,
    status: str,
    error: BaseException,
) -> None:
    payload = {
        "schema_version": 1,
        "kind": "v2_dev_baseline_failure",
        "run_sha256": run_sha256,
        "request": request,
        "status": status,
        "exception": type(error).__name__,
        "message": str(error),
    }
    try:
        write_blob(root / "failures" / run_sha256, canonical(payload))
    except Exception as record_error:
        error.add_note(f"failure receipt could not be written: {record_error}")


def _json_blob(root: Path, identity: str) -> dict[str, object]:
    try:
        value = json.loads(read_blob(root, identity))
    except (json.JSONDecodeError, OSError, ValueError) as error:
        raise DevBaselineError("invalid content-addressed JSON artifact") from error
    if not isinstance(value, dict):
        raise DevBaselineError("artifact must be a JSON object")
    return cast(dict[str, object], value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise DevBaselineError(label + " must be an object")
    return cast(Mapping[str, object], value)


def _loads_estimator(body: bytes) -> _Estimator:
    value = pickle.loads(body)
    if not hasattr(value, "predict"):
        raise DevBaselineError("model artifact is invalid")
    return cast(_Estimator, value)


def _vector(value: object) -> NDArray[np.float64]:
    vector = np.asarray(value, dtype=float)
    if vector.ndim != 1 or not np.isfinite(vector).all():
        raise DevBaselineError("model returned invalid predictions")
    return cast(NDArray[np.float64], vector)


def _optional_metric(value: object) -> float | None:
    if value is None:
        return None
    if type(value) not in (int, float):
        raise DevBaselineError("metric must be numeric or null")
    result = float(cast(float, value))
    if not math.isfinite(result):
        raise DevBaselineError("metric must be finite or null")
    return result


def _integer(value: object) -> int:
    if type(value) is not int:
        raise DevBaselineError("result count or seed must be an integer")
    return value


def _code_sha256() -> str:
    files = {
        "dev_baseline_runner.py": Path(__file__),
        "dev_contract.py": Path(cast(str, import_module("quant_stack_v2.dev_contract").__file__)),
        "dev_view.py": Path(cast(str, import_module("quant_stack_v2.dev_view").__file__)),
    }
    return digest(
        {name: sha256(path.read_bytes()).hexdigest() for name, path in sorted(files.items())}
    )
