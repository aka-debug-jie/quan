"""Staged Qlib view that withholds validation targets until predictions exist."""

from __future__ import annotations

import json
import os
import pickle
import re
import shutil
import stat
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from hashlib import sha256
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, cast
from uuid import uuid4

import numpy as np
import pandas as pd
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import Field, model_validator

from quant_stack_v2.dev_contract import (
    Digest,
    Member,
    StrictModel,
    canonical,
    digest,
    read_blob,
    write_blob,
)
from quant_stack_v2.dev_real_contract import (
    AccessScopeManifest,
    RealDevContract,
    RealDevEvidence,
    RealViewPin,
    load_real_evidence,
)

LABEL_COLUMN = "LABEL_T2_OVER_T1"
MAX_SHARD_BYTES = 512 * 1024 * 1024


class StagedShard(StrictModel):
    """One content-named Parquet shard."""

    kind: Literal["train_features", "train_labels", "validation_features", "validation_labels"]
    year: int
    filename: str
    sha256: Digest
    rows: Annotated[int, Field(ge=0)]
    first_session: date | None
    last_session: date | None

    @model_validator(mode="after")
    def content_named(self) -> StagedShard:
        if self.filename != self.sha256 + ".parquet":
            raise ValueError("Parquet shard filename must equal its SHA-256")
        return self


class StagedExclusions(StrictModel):
    """Counts from the complete member-at-T grid, including entirely absent rows."""

    member_signal_rows: int
    missing_source_rows: int
    incomplete_feature_rows: int
    complete_feature_rows: int
    missing_label_rows: int
    finite_label_rows: int
    feature_cells: int
    missing_feature_cells: int


class StagedViewManifest(StrictModel):
    """Features and training labels available before validation target release."""

    schema_version: Literal[1]
    status: Literal["PREDICTION_INPUTS_READY"]
    run_id: Literal["DEV-001"]
    contract_sha256: Digest
    evidence_sha256: Digest
    access_scope_sha256: Digest
    feature_names: tuple[str, ...]
    shards: tuple[StagedShard, ...]
    exclusions: dict[Literal["train", "validation"], StagedExclusions]
    total_feature_rows: Annotated[int, Field(gt=0)]
    exposure: Literal["CSI300_FEATURES_AND_TRAIN_LABELS_ONLY_NO_RAW_OHLC_NO_CSI500"]
    formal_qualification: Literal["BLOCKED_DATA"]
    sealed_test: Literal["NOT_STARTED"]


class ValidationTargetManifest(StrictModel):
    """Validation labels released after both fixed prediction receipts are immutable."""

    schema_version: Literal[1]
    status: Literal["VALIDATION_TARGETS_RELEASED_AFTER_PREDICTIONS"]
    run_id: Literal["DEV-001"]
    contract_sha256: Digest
    evidence_sha256: Digest
    view_sha256: Digest
    prediction_receipt_sha256: tuple[Digest, Digest]
    shards: tuple[StagedShard, ...]
    total_rows: Annotated[int, Field(gt=0)]


@dataclass(frozen=True)
class VerifiedStagedView:
    """A real view reopened through an exporter-owned authority pin."""

    contract: RealDevContract
    evidence: RealDevEvidence
    access: AccessScopeManifest
    manifest: StagedViewManifest
    root: Path
    manifest_sha256: str


def corrected_members(
    source: Iterable[Member], correction: dict[str, object]
) -> tuple[Member, ...]:
    """Apply exactly the five archived end-boundary replacements and nothing else."""
    if (
        correction.get("scope") != "SIX_SYMBOL_END_BOUNDARY_RECONCILIATION_NOT_FULL_PIT"
        or correction.get("membership_gate") != "BLOCKED_DATA"
        or correction.get("raw_member_file_modified") is not False
    ):
        raise ValueError("member correction claim boundary changed")
    edits = correction.get("official_end_boundary_edits")
    if not isinstance(edits, list) or len(edits) != 5:
        raise ValueError("member correction must contain exactly five archived edits")
    replacements: dict[tuple[str, date, date], Member] = {}
    for item in edits:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("before"), dict)
            or not isinstance(item.get("after"), dict)
        ):
            raise ValueError("invalid member correction edit")
        before = cast(dict[str, str], item["before"])
        after = cast(dict[str, str], item["after"])
        key = (
            before["symbol"].lower(),
            date.fromisoformat(before["effective_from"]),
            date.fromisoformat(before["effective_to"]),
        )
        replacement = Member(
            symbol=after["symbol"].lower(),
            start=date.fromisoformat(after["effective_from"]),
            end=date.fromisoformat(after["effective_to"]),
        )
        if (
            key in replacements
            or key[0] != replacement.symbol
            or key[1] != replacement.start
            or replacement.end >= key[2]
        ):
            raise ValueError("member correction is duplicated or not an exact contraction")
        replacements[key] = replacement
    found: set[tuple[str, date, date]] = set()
    output: list[Member] = []
    for member in source:
        if member.start > member.end:
            raise ValueError("source membership interval is reversed")
        key = (member.symbol.lower(), member.start, member.end)
        if key in replacements:
            found.add(key)
            output.append(replacements[key])
        else:
            output.append(Member(symbol=member.symbol.lower(), start=member.start, end=member.end))
    if found != set(replacements):
        raise ValueError("archived correction does not match the actual full roster")
    ordered = tuple(sorted(output, key=lambda item: (item.symbol, item.start, item.end)))
    for left, right in pairwise(ordered):
        if left.symbol == right.symbol and left.end >= right.start:
            raise ValueError("corrected membership intervals overlap")
    return ordered


def membership_identity(members: tuple[Member, ...]) -> str:
    """Hash the complete corrected roster."""
    return digest([item.model_dump(mode="json") for item in members])


def export_prediction_inputs(
    *,
    authority: Path,
    contract_sha256: str,
    evidence_sha256: str,
    members: tuple[Member, ...],
    provider_uri: Path,
    view_root: Path,
) -> tuple[str, str]:
    """Publish Alpha158 features and training targets through the fixed Qlib adapter."""
    contract, evidence, access = load_real_evidence(authority, contract_sha256, evidence_sha256)
    _runtime_scope(contract, access, members, provider_uri, view_root)
    staging = _stage(view_root)
    try:
        shards: list[StagedShard] = []
        exclusions: dict[Literal["train", "validation"], StagedExclusions] = {}
        for split, split_start, split_end in (
            ("train", contract.train.start, contract.train.end),
            ("validation", contract.validation.start, contract.validation.end),
        ):
            counts = _empty_counts()
            for year in range(split_start.year, split_end.year + 1):
                start, end = max(split_start, date(year, 1, 1)), min(split_end, date(year, 12, 31))
                expected = _expected_keys(contract.sessions, members, start, end)
                raw = _read_qlib(
                    provider_uri,
                    members,
                    contract.alpha158.expressions,
                    contract.alpha158.names,
                    (start, end),
                )
                features, local = _project_features(raw, expected, contract.alpha158.names)
                counts = _add_counts(counts, local)
                if features.empty:
                    continue
                kind = cast(Literal["train_features", "validation_features"], f"{split}_features")
                shards.append(_write_shard(staging, kind, year, features))
                if split == "train":
                    labels_raw = _read_qlib(
                        provider_uri,
                        members,
                        ("Ref($close,-2)/Ref($close,-1)-1",),
                        (LABEL_COLUMN,),
                        (start, end),
                    )
                    labels = _project_labels(labels_raw, features[["session", "symbol"]], expected)
                    shards.append(_write_shard(staging, "train_labels", year, labels))
                    finite = int(labels[LABEL_COLUMN].notna().sum())
                    counts = counts.model_copy(
                        update={
                            "missing_label_rows": counts.missing_label_rows + len(labels) - finite,
                            "finite_label_rows": counts.finite_label_rows + finite,
                        }
                    )
            split_key: Literal["train", "validation"] = (
                "train" if split == "train" else "validation"
            )
            exclusions[split_key] = counts
        total = sum(item.rows for item in shards if item.kind.endswith("features"))
        if total == 0 or not any(item.kind == "train_labels" for item in shards):
            raise ValueError("real development prediction view is empty")
        manifest = StagedViewManifest(
            schema_version=1,
            status="PREDICTION_INPUTS_READY",
            run_id="DEV-001",
            contract_sha256=contract_sha256,
            evidence_sha256=evidence_sha256,
            access_scope_sha256=evidence.access_scope_sha256,
            feature_names=contract.alpha158.names,
            shards=tuple(shards),
            exclusions=exclusions,
            total_feature_rows=total,
            exposure="CSI300_FEATURES_AND_TRAIN_LABELS_ONLY_NO_RAW_OHLC_NO_CSI500",
            formal_qualification="BLOCKED_DATA",
            sealed_test="NOT_STARTED",
        )
        view_sha = _publish_directory(staging, view_root, canonical(manifest))
        pin = RealViewPin(
            schema_version=1,
            kind="dev001_real_view_pin",
            contract_sha256=contract_sha256,
            evidence_sha256=evidence_sha256,
            view_sha256=view_sha,
        )
        return view_sha, write_blob(authority, canonical(pin))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def export_validation_targets(
    *,
    authority: Path,
    view_root: Path,
    contract_sha256: str,
    evidence_sha256: str,
    view_pin_sha256: str,
    provider_uri: Path,
    members: tuple[Member, ...],
    prediction_receipts: tuple[str, str],
    result_root: Path,
) -> str:
    """Read validation targets only after both model prediction receipts are frozen."""
    view = load_staged_view(authority, view_root, contract_sha256, evidence_sha256, view_pin_sha256)
    if len(set(prediction_receipts)) != 2:
        raise ValueError("two distinct fixed-model prediction receipts are required")
    validation_features = load_features(view, "validation")
    expected_keys = [
        (day.isoformat(), str(symbol))
        for day, symbol in zip(
            validation_features["session"], validation_features["symbol"], strict=True
        )
    ]
    receipt_models: set[str] = set()
    for identity in prediction_receipts:
        payload = json.loads(read_blob(authority / "prediction_receipts", identity))
        request = payload.get("request")
        model = payload.get("model")
        if not isinstance(request, dict) or model not in {"linear", "lightgbm"}:
            raise ValueError("prediction receipt request or model is invalid")
        request_model = request.get("model")
        predictions = json.loads(
            read_blob(result_root / "predictions", str(payload.get("predictions_sha256")))
        )
        specification = next(item for item in view.contract.models if item.kind == model)
        expected_request = {
            "schema_version": 1,
            "run_id": "DEV-001",
            "contract_sha256": contract_sha256,
            "evidence_sha256": evidence_sha256,
            "view_sha256": view.manifest_sha256,
            "model": specification.model_dump(mode="json"),
            "code_sha256": view.contract.code_sha256,
            "preprocessing": view.contract.preprocessing,
            "preprocessing_params": view.contract.preprocessing_params,
        }
        prediction_rows = predictions.get("rows") if isinstance(predictions, dict) else None
        prediction_keys = (
            [
                (str(row.get("session")), str(row.get("symbol")))
                for row in prediction_rows
                if isinstance(row, dict)
            ]
            if isinstance(prediction_rows, list)
            else []
        )
        prediction_rows_valid = isinstance(prediction_rows, list) and all(
            isinstance(row, dict)
            and set(row) == {"session", "symbol", "prediction"}
            and type(row["prediction"]) in (int, float)
            and np.isfinite(float(row["prediction"]))
            for row in prediction_rows
        )
        if (
            set(payload)
            != {
                "schema_version",
                "run_id",
                "status",
                "run_sha256",
                "model",
                "contract_sha256",
                "evidence_sha256",
                "view_sha256",
                "view_pin_sha256",
                "request",
                "model_sha256",
                "predictions_sha256",
                "training_rows",
                "prediction_rows",
                "validation_targets_opened",
            }
            or payload.get("schema_version") != 1
            or payload.get("run_id") != "DEV-001"
            or payload.get("view_sha256") != view.manifest_sha256
            or payload.get("view_pin_sha256") != view_pin_sha256
            or payload.get("contract_sha256") != contract_sha256
            or payload.get("evidence_sha256") != evidence_sha256
            or payload.get("status") != "PREDICTIONS_FROZEN_BEFORE_VALIDATION_TARGETS"
            or payload.get("validation_targets_opened") is not False
            or payload.get("run_sha256") != digest(request)
            or request != expected_request
            or not isinstance(request_model, dict)
            or request_model.get("kind") != model
            or not isinstance(predictions, dict)
            or set(predictions) != {"schema_version", "run_id", "model", "rows"}
            or predictions.get("schema_version") != 1
            or predictions.get("run_id") != "DEV-001"
            or predictions.get("model") != model
            or not prediction_rows_valid
            or prediction_keys != expected_keys
            or len(prediction_keys) != payload.get("prediction_rows")
        ):
            raise ValueError("prediction receipt does not bind the approved view")
        model_body = read_blob(result_root / "models", str(payload.get("model_sha256")), ".bin")
        estimator = pickle.loads(model_body)
        named_steps = getattr(estimator, "named_steps", {})
        model_step = named_steps.get("model") if isinstance(named_steps, dict) else None
        scaler_step = named_steps.get("standardize") if isinstance(named_steps, dict) else None
        if (
            model_step is None
            or scaler_step is None
            or model_step.get_params(deep=False) != specification.params
            or scaler_step.get_params(deep=False)
            != {"copy": True, "with_mean": True, "with_std": True}
        ):
            raise ValueError("prediction model does not match the frozen estimator")
        rebuilt = np.asarray(
            estimator.predict(
                validation_features.loc[:, list(view.manifest.feature_names)].to_numpy(dtype=float)
            ),
            dtype=float,
        )
        stored = np.asarray(
            [row["prediction"] for row in cast(list[dict[str, object]], prediction_rows)],
            dtype=float,
        )
        if rebuilt.ndim != 1 or not np.array_equal(rebuilt, stored):
            raise ValueError("prediction artifact does not rebuild from the frozen model")
        receipt_models.add(cast(str, model))
    if receipt_models != {"linear", "lightgbm"}:
        raise ValueError("prediction receipts must cover exactly Linear and LightGBM")
    _runtime_scope(view.contract, view.access, members, provider_uri, view_root)
    target_root = view_root / "validation_targets"
    staging = _stage(target_root)
    try:
        shards: list[StagedShard] = []
        features = validation_features
        years = features["session"].map(lambda value: value.year)
        for year, keys in features.groupby(years, sort=True):
            start, end = cast(date, keys["session"].min()), cast(date, keys["session"].max())
            raw = _read_qlib(
                provider_uri,
                members,
                ("Ref($close,-2)/Ref($close,-1)-1",),
                (LABEL_COLUMN,),
                (start, end),
            )
            allowed = _expected_keys(view.contract.sessions, members, start, end)
            labels = _project_labels(raw, keys[["session", "symbol"]], allowed)
            shards.append(_write_shard(staging, "validation_labels", int(year), labels))
        ordered_receipts = tuple(sorted(prediction_receipts))
        manifest = ValidationTargetManifest(
            schema_version=1,
            status="VALIDATION_TARGETS_RELEASED_AFTER_PREDICTIONS",
            run_id="DEV-001",
            contract_sha256=contract_sha256,
            evidence_sha256=evidence_sha256,
            view_sha256=view.manifest_sha256,
            prediction_receipt_sha256=(ordered_receipts[0], ordered_receipts[1]),
            shards=tuple(shards),
            total_rows=sum(item.rows for item in shards),
        )
        return _publish_directory(staging, target_root, canonical(manifest))
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def load_staged_view(
    authority: Path,
    view_root: Path,
    contract_sha256: str,
    evidence_sha256: str,
    view_pin_sha256: str,
) -> VerifiedStagedView:
    """Require an authority pin and verify all pre-target shards."""
    contract, evidence, access = load_real_evidence(authority, contract_sha256, evidence_sha256)
    pin = RealViewPin.model_validate_json(read_blob(authority, view_pin_sha256))
    if pin.contract_sha256 != contract_sha256 or pin.evidence_sha256 != evidence_sha256:
        raise ValueError("real view pin is cross-contract")
    root = _child(view_root, pin.view_sha256)
    body = _regular_bytes(root / "manifest.json", 4 * 1024 * 1024)
    if sha256(body).hexdigest() != pin.view_sha256:
        raise ValueError("real view manifest SHA-256 mismatch")
    manifest = StagedViewManifest.model_validate_json(body)
    if (
        manifest.contract_sha256 != contract_sha256
        or manifest.evidence_sha256 != evidence_sha256
        or manifest.access_scope_sha256 != evidence.access_scope_sha256
        or manifest.feature_names != contract.alpha158.names
    ):
        raise ValueError("real view binding mismatch")
    for shard in manifest.shards:
        _verify_shard(root, shard)
    return VerifiedStagedView(contract, evidence, access, manifest, root, pin.view_sha256)


def load_features(view: VerifiedStagedView, split: Literal["train", "validation"]) -> pd.DataFrame:
    """Load features without opening validation targets."""
    frames = [
        pd.read_parquet(view.root / item.filename)
        for item in view.manifest.shards
        if item.kind == f"{split}_features"
    ]
    return _combine(frames, ["session", "symbol", *view.manifest.feature_names])


def load_train_labels(view: VerifiedStagedView) -> pd.DataFrame:
    """Load only the training-label shards."""
    frames = [
        pd.read_parquet(view.root / item.filename)
        for item in view.manifest.shards
        if item.kind == "train_labels"
    ]
    return _combine(frames, ["session", "symbol", LABEL_COLUMN])


def load_validation_labels(
    view: VerifiedStagedView, view_root: Path, target_sha256: str
) -> pd.DataFrame:
    """Load validation labels from a release bound to the prediction-input view."""
    root = _child(view_root / "validation_targets", target_sha256)
    body = _regular_bytes(root / "manifest.json", 4 * 1024 * 1024)
    if sha256(body).hexdigest() != target_sha256:
        raise ValueError("validation target manifest SHA-256 mismatch")
    manifest = ValidationTargetManifest.model_validate_json(body)
    if (
        manifest.contract_sha256 != view.manifest.contract_sha256
        or manifest.evidence_sha256 != view.manifest.evidence_sha256
        or manifest.view_sha256 != view.manifest_sha256
    ):
        raise ValueError("validation targets are cross-view")
    frames: list[pd.DataFrame] = []
    for shard in manifest.shards:
        _verify_shard(root, shard)
        frames.append(pd.read_parquet(root / shard.filename))
    return _combine(frames, ["session", "symbol", LABEL_COLUMN])


def load_validation_target_manifest(
    view: VerifiedStagedView, view_root: Path, target_sha256: str
) -> ValidationTargetManifest:
    """Validate target identity and path before reading its manifest bytes."""
    root = _child(view_root / "validation_targets", target_sha256)
    body = _regular_bytes(root / "manifest.json", 4 * 1024 * 1024)
    if sha256(body).hexdigest() != target_sha256:
        raise ValueError("validation target manifest SHA-256 mismatch")
    manifest = ValidationTargetManifest.model_validate_json(body)
    if (
        manifest.contract_sha256 != view.manifest.contract_sha256
        or manifest.evidence_sha256 != view.manifest.evidence_sha256
        or manifest.view_sha256 != view.manifest_sha256
    ):
        raise ValueError("validation targets are cross-view")
    return manifest


def _read_qlib(
    provider_uri: Path,
    members: tuple[Member, ...],
    fields: tuple[str, ...],
    names: tuple[str, ...],
    span: tuple[date, date],
) -> pd.DataFrame:
    """Read full-span members together and partial members only on approved T spans."""
    import qlib  # type: ignore[import-untyped]
    from qlib.constant import REG_CN  # type: ignore[import-untyped]
    from qlib.data import D  # type: ignore[import-untyped]

    qlib.init(
        provider_uri=str(provider_uri), region=REG_CN, expression_cache=None, dataset_cache=None
    )
    frames: list[pd.DataFrame] = []
    for symbols, start, end in _scoped_requests(members, span):
        frame = D.features(
            list(symbols),
            list(fields),
            start_time=start.isoformat(),
            end_time=end.isoformat(),
            freq="day",
            disk_cache=0,
        )
        if len(frame.columns) != len(names):
            raise ValueError("Qlib returned an unexpected column count")
        frame.columns = list(names)
        if set(frame.index.names) != {"datetime", "instrument"}:
            raise ValueError("Qlib frame requires named datetime/instrument levels")
        frames.append(cast(pd.DataFrame, frame.reorder_levels(["instrument", "datetime"])))
    if not frames:
        return pd.DataFrame(
            columns=list(names),
            index=pd.MultiIndex.from_arrays([[], []], names=["instrument", "datetime"]),
        )
    normalized = pd.concat(frames).reset_index()
    normalized["instrument"] = normalized["instrument"].astype(str).str.lower()
    normalized["datetime"] = pd.to_datetime(normalized["datetime"])
    return normalized.set_index(["instrument", "datetime"]).sort_index()


def _scoped_requests(
    members: tuple[Member, ...], span: tuple[date, date]
) -> tuple[tuple[tuple[str, ...], date, date], ...]:
    """Group only symbols whose approved T coverage is the complete requested span."""
    by_symbol: dict[str, list[tuple[date, date]]] = {}
    for member in members:
        start, end = max(span[0], member.start), min(span[1], member.end)
        if start <= end:
            by_symbol.setdefault(member.symbol, []).append((start, end))
    merged: dict[str, list[tuple[date, date]]] = {}
    for symbol, intervals in by_symbol.items():
        for start, end in sorted(intervals):
            if merged.get(symbol) and start <= merged[symbol][-1][1] + timedelta(days=1):
                previous = merged[symbol][-1]
                merged[symbol][-1] = (previous[0], max(previous[1], end))
            else:
                merged.setdefault(symbol, []).append((start, end))
    full = tuple(
        sorted(symbol for symbol, intervals in merged.items() if intervals == [(span[0], span[1])])
    )
    requests: list[tuple[tuple[str, ...], date, date]] = []
    if full:
        requests.append((full, span[0], span[1]))
    for symbol, intervals in sorted(merged.items()):
        if symbol in full:
            continue
        requests.extend(((symbol,), start, end) for start, end in intervals)
    return tuple(requests)


def _expected_keys(
    sessions: tuple[date, ...], members: tuple[Member, ...], start: date, end: date
) -> pd.MultiIndex:
    days = [day for day in sessions if start <= day <= end]
    values = [
        (member.symbol, pd.Timestamp(day))
        for day in days
        for member in members
        if member.start <= day <= member.end
    ]
    return pd.MultiIndex.from_tuples(values, names=["instrument", "datetime"])


def _project_features(
    frame: pd.DataFrame, expected: pd.MultiIndex, names: tuple[str, ...]
) -> tuple[pd.DataFrame, StagedExclusions]:
    if (
        not isinstance(frame.index, pd.MultiIndex)
        or list(frame.index.names) != ["instrument", "datetime"]
        or frame.index.has_duplicates
    ):
        raise ValueError("Qlib feature frame index is invalid or duplicated")
    extra = frame.index.difference(expected)
    if len(extra):
        raise ValueError("Qlib returned rows outside the frozen member/date grid")
    aligned = frame.reindex(expected).replace([np.inf, -np.inf], np.nan)
    complete = aligned.notna().all(axis=1)
    projected = aligned.loc[complete].reset_index()
    projected.columns = ["symbol", "session", *names]
    projected["symbol"] = projected["symbol"].astype(str).str.lower()
    projected["session"] = pd.to_datetime(projected["session"]).dt.date
    projected = projected[["session", "symbol", *names]]
    counts = StagedExclusions(
        member_signal_rows=len(expected),
        missing_source_rows=len(expected.difference(frame.index)),
        incomplete_feature_rows=int((~complete).sum()),
        complete_feature_rows=int(complete.sum()),
        missing_label_rows=0,
        finite_label_rows=0,
        feature_cells=len(expected) * len(names),
        missing_feature_cells=int(aligned.isna().sum().sum()),
    )
    return projected.sort_values(["session", "symbol"], kind="mergesort").reset_index(
        drop=True
    ), counts


def _project_labels(
    frame: pd.DataFrame, keys: pd.DataFrame, allowed: pd.MultiIndex
) -> pd.DataFrame:
    if (
        not isinstance(frame.index, pd.MultiIndex)
        or list(frame.index.names) != ["instrument", "datetime"]
        or frame.index.has_duplicates
    ):
        raise ValueError("Qlib label frame index is invalid or duplicated")
    key_frame = keys.rename(columns={"symbol": "instrument", "session": "datetime"})[
        ["instrument", "datetime"]
    ].copy()
    key_frame["datetime"] = pd.to_datetime(key_frame["datetime"])
    expected = pd.MultiIndex.from_frame(key_frame)
    if len(frame.index.difference(allowed)):
        raise ValueError("Qlib returned labels outside the frozen member/date grid")
    aligned = frame.reindex(expected).replace([np.inf, -np.inf], np.nan).reset_index()
    aligned.columns = ["symbol", "session", LABEL_COLUMN]
    aligned["symbol"] = aligned["symbol"].astype(str).str.lower()
    aligned["session"] = pd.to_datetime(aligned["session"]).dt.date
    aligned = aligned[["session", "symbol", LABEL_COLUMN]]
    return aligned.sort_values(["session", "symbol"], kind="mergesort").reset_index(drop=True)


def _runtime_scope(
    contract: RealDevContract,
    access: AccessScopeManifest,
    members: tuple[Member, ...],
    provider_uri: Path,
    view_root: Path,
) -> None:
    symbols = tuple(
        sorted(
            {
                item.symbol
                for item in members
                if item.start <= contract.validation_candidate.end
                and item.end >= contract.train_candidate.start
            }
        )
    )
    if (
        membership_identity(members) != contract.corrected_membership_sha256
        or symbols != access.symbols
    ):
        raise ValueError("runtime membership differs from frozen access scope")
    if (
        not (provider_uri / "calendars/day.txt").is_file()
        or not (provider_uri / "instruments/csi300.txt").is_file()
    ):
        raise ValueError("fixed Qlib provider tree is incomplete")
    if str(view_root.resolve()).startswith("/srv/quant-v2/sealed_holdout"):
        raise ValueError("development view cannot be published under sealed holdout")


def _write_shard(
    root: Path,
    kind: Literal["train_features", "train_labels", "validation_features", "validation_labels"],
    year: int,
    frame: pd.DataFrame,
) -> StagedShard:
    temporary = root / f"{kind}-{year}.parquet"
    pq.write_table(
        pa.Table.from_pandas(frame, preserve_index=False),
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        version="2.6",
    )
    identity = _file_sha256(temporary)
    filename = identity + ".parquet"
    temporary.rename(root / filename)
    return StagedShard(
        kind=kind,
        year=year,
        filename=filename,
        sha256=identity,
        rows=len(frame),
        first_session=cast(date, frame["session"].min()),
        last_session=cast(date, frame["session"].max()),
    )


def _publish_directory(staging: Path, root: Path, manifest_body: bytes) -> str:
    identity = sha256(manifest_body).hexdigest()
    (staging / "manifest.json").write_bytes(manifest_body)
    _fsync_tree(staging)
    destination = root / identity
    try:
        staging.rename(destination)
    except FileExistsError:
        if _regular_bytes(destination / "manifest.json", 4 * 1024 * 1024) != manifest_body:
            raise ValueError("immutable directory identity collision") from None
        shutil.rmtree(staging)
    return identity


def _verify_shard(root: Path, shard: StagedShard) -> None:
    path = _child(root, shard.filename)
    body = _regular_bytes(path, MAX_SHARD_BYTES)
    if sha256(body).hexdigest() != shard.sha256:
        raise ValueError("real view shard identity mismatch")


def _child(root: Path, name: str) -> Path:
    if re.fullmatch(r"[a-f0-9]{64}(?:\.parquet)?", name) is None:
        raise ValueError("invalid content-addressed child name")
    path = root / name
    if path.resolve().parent != root.resolve() or path.is_symlink():
        raise ValueError("content-addressed path escapes its approved root")
    return path


def _regular_bytes(path: Path, limit: int) -> bytes:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
        raise ValueError("artifact is not a bounded single-link regular file")
    return path.read_bytes()


def _combine(frames: list[pd.DataFrame], columns: list[str]) -> pd.DataFrame:
    if not frames:
        raise ValueError("required real view shard set is empty")
    frame = pd.concat(frames, ignore_index=True)
    if list(frame.columns) != columns:
        raise ValueError("real view shard schema mismatch")
    frame["session"] = pd.to_datetime(frame["session"]).dt.date
    if frame.duplicated(["session", "symbol"]).any():
        raise ValueError("real view contains duplicate sample keys")
    return frame.sort_values(["session", "symbol"], kind="mergesort").reset_index(drop=True)


def _stage(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    staging = root / (".stage-" + uuid4().hex)
    staging.mkdir(mode=0o700)
    return staging


def _empty_counts() -> StagedExclusions:
    return StagedExclusions(
        member_signal_rows=0,
        missing_source_rows=0,
        incomplete_feature_rows=0,
        complete_feature_rows=0,
        missing_label_rows=0,
        finite_label_rows=0,
        feature_cells=0,
        missing_feature_cells=0,
    )


def _add_counts(left: StagedExclusions, right: StagedExclusions) -> StagedExclusions:
    return StagedExclusions(
        **{
            name: getattr(left, name) + getattr(right, name)
            for name in StagedExclusions.model_fields
        }
    )


def _file_sha256(path: Path) -> str:
    value = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def _fsync_tree(root: Path) -> None:
    for path in root.iterdir():
        if path.is_file():
            with path.open("rb") as handle:
                os.fsync(handle.fileno())
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
