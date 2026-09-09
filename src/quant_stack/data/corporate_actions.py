"""Versioned, official corporate-action ledgers used by local canonicalization only."""

from __future__ import annotations

from pathlib import Path

import yaml

from quant_stack.data.models import CorporateActionLedger


class CorporateActionLedgerError(ValueError):
    """Raised when an action ledger cannot be loaded as an immutable configuration record."""


def load_corporate_action_ledger(path: Path) -> CorporateActionLedger:
    """Load one versioned ledger; completeness is never inferred from prices or coverage."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as error:
        raise CorporateActionLedgerError(
            f"unable to read corporate-action ledger: {path}"
        ) from error
    if not isinstance(payload, dict):
        raise CorporateActionLedgerError("corporate-action ledger must be a mapping")
    try:
        return CorporateActionLedger.model_validate(payload)
    except ValueError as error:
        raise CorporateActionLedgerError(f"invalid corporate-action ledger: {path}") from error
