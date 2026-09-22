"""Fork-based orchestration that shares the read-only upgrade cache."""

from __future__ import annotations

import json
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from hashlib import sha256

from quant_stack.research_json import canonical_json
from quant_stack_v3.protocol import Protocol
from quant_stack_v3.upgrade_portfolio import policy_for
from quant_stack_v3.upgrade_runner import (
    PreparedUpgradeData,
    UpgradeInputs,
    UpgradeRunSpec,
    _identities,
    _run_loaded,
    prepare_upgrade_data,
)

_FORK_STATE: tuple[Protocol, UpgradeInputs, PreparedUpgradeData] | None = None


def run_upgrade_registry_parallel(
    base_protocol: Protocol,
    specs: tuple[UpgradeRunSpec, ...],
    inputs: UpgradeInputs,
    *,
    maximum_workers: int = 8,
) -> dict[str, dict[str, object]]:
    """Run uncached registry members in forked workers sharing immutable inputs."""
    if maximum_workers < 1 or maximum_workers > 16:
        raise ValueError("upgrade worker count must remain between one and sixteen")
    prepared = prepare_upgrade_data(base_protocol, inputs)
    results: dict[str, dict[str, object]] = {}
    pending: list[UpgradeRunSpec] = []
    for spec in specs:
        identities = _identities(spec, inputs)
        run_identity = sha256(canonical_json(identities)).hexdigest()
        result_path = inputs.artifact_root / "runs" / run_identity / "result.json"
        if result_path.exists():
            results[spec.experiment_id] = json.loads(result_path.read_text(encoding="utf-8"))
        else:
            pending.append(spec)
    if not pending:
        return results
    global _FORK_STATE
    _FORK_STATE = (base_protocol, inputs, prepared)
    context = multiprocessing.get_context("fork")
    try:
        with ProcessPoolExecutor(
            max_workers=min(maximum_workers, len(pending)), mp_context=context
        ) as executor:
            futures = {executor.submit(_run_forked, spec): spec for spec in pending}
            for future in as_completed(futures):
                experiment_id, result = future.result()
                results[experiment_id] = result
    finally:
        _FORK_STATE = None
    return {spec.experiment_id: results[spec.experiment_id] for spec in specs}


def _run_forked(spec: UpgradeRunSpec) -> tuple[str, dict[str, object]]:
    if _FORK_STATE is None:
        raise RuntimeError("upgrade fork state is not initialized")
    base_protocol, inputs, prepared = _FORK_STATE
    identities = _identities(spec, inputs)
    run_identity = sha256(canonical_json(identities)).hexdigest()
    run_root = inputs.artifact_root / "runs" / run_identity
    result_path = run_root / "result.json"
    if run_root.exists() and any(run_root.iterdir()):
        raise ValueError(f"incomplete upgrade run directory already exists: {run_identity}")
    run_root.mkdir(parents=True, exist_ok=True)
    _, result = _run_loaded(
        base_protocol,
        spec,
        policy_for(spec.strategy_id),
        inputs,
        identities,
        run_identity,
        run_root,
        result_path,
        prepared,
    )
    return spec.experiment_id, result
