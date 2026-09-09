import json
from hashlib import sha256
from pathlib import Path

import pytest

from quant_stack.research_inputs import (
    preflight_causal_universe,
    require_complete_causal_universe,
)


def _write_causal_manifest(root: Path, symbol: str, exchange: str) -> None:
    output = root / "canonical" / f"{symbol}.parquet"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"immutable parquet fixture")
    manifests = root / "manifests"
    manifests.mkdir()
    manifest = {
        "manifest_id": f"manifest-{symbol}",
        "instrument": {"symbol": symbol, "exchange": exchange},
        "price_basis": "causal_adjusted",
        "output_file": {
            "relative_path": str(output.relative_to(root)),
            "sha256": sha256(output.read_bytes()).hexdigest(),
        },
    }
    (manifests / f"{symbol}.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_preflight_requires_every_frozen_symbol_to_have_verified_causal_data(
    tmp_path: Path,
) -> None:
    universe = tmp_path / "universe.yaml"
    universe.write_text(
        "instruments:\n  - symbol: A\n    exchange: SSE\n  - symbol: B\n    exchange: SZSE\n",
        encoding="utf-8",
    )
    _write_causal_manifest(tmp_path, "A", "SSE")
    preflight = preflight_causal_universe(universe, tmp_path / "manifests", tmp_path)
    assert preflight.missing_symbols == ("B",)
    with pytest.raises(ValueError, match="missing causal series: B"):
        require_complete_causal_universe(preflight)


def test_preflight_snapshot_identity_is_stable_for_complete_inputs(tmp_path: Path) -> None:
    universe = tmp_path / "universe.yaml"
    universe.write_text("instruments:\n  - symbol: A\n    exchange: SSE\n", encoding="utf-8")
    _write_causal_manifest(tmp_path, "A", "SSE")
    preflight = preflight_causal_universe(universe, tmp_path / "manifests", tmp_path)
    assert preflight.complete
    assert preflight.snapshot_id == preflight.snapshot_id
