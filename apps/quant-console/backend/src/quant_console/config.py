"""Runtime source configuration with explicit, fixed source roots."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ConsoleConfigError(ValueError):
    """Raised when the local source registry is invalid."""


@dataclass(frozen=True)
class SourcePair:
    """One structured manifest and its immutable artifact root."""

    manifest: Path
    artifacts: Path


@dataclass(frozen=True)
class ConsoleConfig:
    """Approved inputs for one real-mode console snapshot."""

    mode: str
    historical_v3: SourcePair
    upgrade_v1: SourcePair
    prospective_artifacts: Path
    prospective_acceptance: Path
    closure_next: SourcePair | None = None


def load_config(path: Path) -> ConsoleConfig:
    """Load a TOML registry; paths can only be supplied at process startup."""
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ConsoleConfigError(f"cannot load source config: {error}") from error
    mode = _text(raw, "mode")
    if mode != "real":
        raise ConsoleConfigError("real source config must set mode = 'real'")
    return ConsoleConfig(
        mode=mode,
        historical_v3=_pair(raw, "historical_v3"),
        upgrade_v1=_pair(raw, "upgrade_v1"),
        prospective_artifacts=_path(raw, "prospective", "artifacts"),
        prospective_acceptance=_path(raw, "prospective", "acceptance_manifest"),
        closure_next=_pair(raw, "closure_next") if "closure_next" in raw else None,
    )


def _pair(raw: dict[str, Any], section: str) -> SourcePair:
    return SourcePair(
        manifest=_path(raw, section, "manifest"),
        artifacts=_path(raw, section, "artifacts"),
    )


def _path(raw: dict[str, Any], section: str, field: str) -> Path:
    value = raw.get(section)
    if not isinstance(value, dict) or not isinstance(value.get(field), str):
        raise ConsoleConfigError(f"missing [{section}].{field}")
    path = Path(value[field]).expanduser().resolve(strict=True)
    lowered = {part.casefold() for part in path.parts}
    if "sealed" in lowered or any("csi500" in part for part in lowered):
        raise ConsoleConfigError("sealed and CSI500 sources are not allowed")
    return path


def _text(raw: dict[str, Any], field: str) -> str:
    value = raw.get(field)
    if not isinstance(value, str):
        raise ConsoleConfigError(f"missing {field}")
    return value
