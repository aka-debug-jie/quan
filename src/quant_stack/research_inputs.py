"""Content-addressed causal-data preflight for a frozen research universe."""

from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import yaml

from quant_stack.models import PriceBasis


@dataclass(frozen=True)
class CanonicalInput:
    """One verified causal series selected from an immutable canonical manifest."""

    symbol: str
    exchange: str
    manifest_id: str
    output_path: Path
    output_sha256: str


@dataclass(frozen=True)
class ResearchInputPreflight:
    """A conservative preflight result that never treats missing causal data as usable."""

    inputs: tuple[CanonicalInput, ...]
    missing_symbols: tuple[str, ...]

    @property
    def complete(self) -> bool:
        """Return true only when every frozen-universe symbol has a verified causal series."""
        return not self.missing_symbols

    @property
    def snapshot_id(self) -> str:
        """Derive a stable aggregate identity from selected canonical manifest identities."""
        if not self.complete:
            raise ValueError("cannot identify an incomplete research input snapshot")
        return sha256("|".join(item.manifest_id for item in self.inputs).encode()).hexdigest()


def preflight_causal_universe(
    universe_path: Path, canonical_manifest_dir: Path, data_root: Path
) -> ResearchInputPreflight:
    """Require one hash-verified causal-adjusted canonical output for every frozen instrument."""
    universe = yaml.safe_load(universe_path.read_text(encoding="utf-8"))
    instruments = universe.get("instruments") if isinstance(universe, dict) else None
    if not isinstance(instruments, list):
        raise ValueError("universe must declare instruments")
    selected = _causal_manifests(canonical_manifest_dir, data_root)
    inputs: list[CanonicalInput] = []
    missing: list[str] = []
    for instrument in instruments:
        if not isinstance(instrument, dict):
            raise ValueError("universe instruments must be mappings")
        symbol = instrument.get("symbol")
        exchange = instrument.get("exchange")
        if not isinstance(symbol, str) or not isinstance(exchange, str):
            raise ValueError("universe instruments require symbol and exchange")
        candidate = selected.get((symbol, exchange))
        if candidate is None:
            missing.append(symbol)
        else:
            inputs.append(candidate)
    return ResearchInputPreflight(tuple(inputs), tuple(missing))


def require_complete_causal_universe(preflight: ResearchInputPreflight) -> None:
    """Stop before experiment execution when any frozen-universe causal series is absent."""
    if not preflight.complete:
        raise ValueError(
            "locked research input is incomplete; missing causal series: "
            + ", ".join(preflight.missing_symbols)
        )


def _causal_manifests(manifest_dir: Path, data_root: Path) -> dict[tuple[str, str], CanonicalInput]:
    """Load only hash-valid causal manifests and reject ambiguous duplicate candidates."""
    result: dict[tuple[str, str], CanonicalInput] = {}
    for path in sorted(manifest_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("price_basis") != PriceBasis.CAUSAL_ADJUSTED.value:
            continue
        instrument = payload.get("instrument")
        output = payload.get("output_file")
        if not isinstance(instrument, dict) or not isinstance(output, dict):
            raise ValueError(f"canonical manifest has invalid structure: {path}")
        symbol = instrument.get("symbol")
        exchange = instrument.get("exchange")
        manifest_id = payload.get("manifest_id")
        relative_path = output.get("relative_path")
        output_sha256 = output.get("sha256")
        identity = (symbol, exchange, manifest_id, relative_path, output_sha256)
        if not all(isinstance(value, str) for value in identity):
            raise ValueError(f"canonical manifest has invalid identity: {path}")
        assert isinstance(symbol, str)
        assert isinstance(exchange, str)
        assert isinstance(manifest_id, str)
        assert isinstance(relative_path, str)
        assert isinstance(output_sha256, str)
        output_path = data_root / relative_path
        output_matches_manifest = (
            output_path.is_file() and sha256(output_path.read_bytes()).hexdigest() == output_sha256
        )
        if not output_matches_manifest:
            raise ValueError(f"canonical output does not match manifest: {path}")
        key = (symbol, exchange)
        if key in result:
            raise ValueError(f"ambiguous causal canonical manifests for {symbol}/{exchange}")
        result[key] = CanonicalInput(symbol, exchange, manifest_id, output_path, output_sha256)
    return result
