"""Immutable, content-addressed registry records for every frozen experiment attempt."""

from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from typing import Any

from quant_stack.snapshot import write_immutable


def register_experiment(
    registry_root: Path,
    *,
    experiment_id: str,
    run_kind: str,
    git_commit: str,
    data_snapshot_id: str,
    config_hashes: Mapping[str, str],
    random_seed: int,
    payload: Mapping[str, Any],
) -> tuple[str, Path]:
    """Persist one immutable record so every executed configuration remains auditable."""
    if not all((experiment_id, run_kind, git_commit, data_snapshot_id)):
        raise ValueError("experiment identity fields must be non-empty")
    if not config_hashes or any(not key or not value for key, value in config_hashes.items()):
        raise ValueError("experiment requires non-empty named configuration hashes")
    record = {
        "experiment_id": experiment_id,
        "run_kind": run_kind,
        "git_commit": git_commit,
        "data_snapshot_id": data_snapshot_id,
        "config_hashes": dict(sorted(config_hashes.items())),
        "random_seed": random_seed,
        "payload": payload,
    }
    content = _canonical_json(record)
    record_id = sha256(content).hexdigest()
    destination = registry_root / record_id / "record.json"
    write_immutable(destination, content)
    return record_id, destination


def _canonical_json(record: Mapping[str, Any]) -> bytes:
    """Serialize a registry record deterministically without a mutable run-time timestamp."""
    serialized = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return serialized.encode() + b"\n"
