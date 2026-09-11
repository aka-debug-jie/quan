"""Fixture-only V2-011 exact reconciliation against an independently produced LEAN timeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256


class LeanReconciliationError(ValueError):
    """Raised when a LEAN fixture is missing or two engine timelines diverge."""


@dataclass(frozen=True)
class EngineState:
    """One normalized end-of-session state with Decimal values retained as exact strings."""

    session: str
    orders: tuple[str, ...]
    fills: tuple[str, ...]
    cash: Decimal
    positions: tuple[tuple[str, Decimal], ...]
    nav: Decimal
    drawdown: Decimal
    fees: Decimal


@dataclass(frozen=True)
class LeanReconciliationReport:
    """An immutable exact reconciliation outcome, never a performance result."""

    fixture_sha256: str | None
    project_timeline_sha256: str
    lean_timeline_sha256: str | None
    status: str
    first_difference: str | None

    @property
    def identity_sha256(self) -> str:
        return sha256(_canonical_json(self.__dict__)).hexdigest()


def reconcile_lean_fixture(
    project: tuple[EngineState, ...],
    lean: tuple[EngineState, ...] | None,
    *,
    fixture_sha256: str | None,
) -> LeanReconciliationReport:
    """Compare exact normalized state records and locate the first mismatch deterministically."""
    project_hash = sha256(_canonical_json(project)).hexdigest()
    if lean is None or fixture_sha256 is None:
        return LeanReconciliationReport(
            fixture_sha256=fixture_sha256,
            project_timeline_sha256=project_hash,
            lean_timeline_sha256=None,
            status="BLOCKED_ENGINE",
            first_difference="lean_fixture_not_captured",
        )
    if len(fixture_sha256) != 64:
        raise LeanReconciliationError("LEAN fixture hash must be SHA-256")
    lean_hash = sha256(_canonical_json(lean)).hexdigest()
    for index, (left, right) in enumerate(zip(project, lean, strict=False)):
        if left != right:
            return LeanReconciliationReport(
                fixture_sha256,
                project_hash,
                lean_hash,
                "BLOCKED_ENGINE",
                _difference(index, left, right),
            )
    if len(project) != len(lean):
        return LeanReconciliationReport(
            fixture_sha256, project_hash, lean_hash, "BLOCKED_ENGINE", "timeline_length"
        )
    return LeanReconciliationReport(fixture_sha256, project_hash, lean_hash, "PASS", None)


def _difference(index: int, left: EngineState, right: EngineState) -> str:
    for field in ("session", "orders", "fills", "cash", "positions", "nav", "drawdown", "fees"):
        if getattr(left, field) != getattr(right, field):
            return f"index:{index}:session:{left.session}:field:{field}"
    raise AssertionError("difference called for equal engine state")


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
