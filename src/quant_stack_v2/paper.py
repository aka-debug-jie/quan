"""Isolated V2-013 paper-account gate; no V1 ledger path or brokerage transport is used."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack_v2.champion import CandidateDecision, ChampionRegistry


class V2PaperError(ValueError):
    """Raised when a V2 account is initialized without a selected, isolated candidate."""


@dataclass(frozen=True)
class V2PaperAccount:
    """Identity of one currency-isolated paper ledger."""

    candidate_id: str
    currency: str
    initial_cash: Decimal
    database_path: Path


def initialize_v2_paper_account(
    registry: ChampionRegistry,
    *,
    candidate_id: str,
    currency: str,
    artifact_root: Path,
) -> V2PaperAccount:
    """Create an idempotent V2-only 100,000-unit SQLite/WAL account for one Champion."""
    candidate = _require_candidate(registry, candidate_id)
    if currency not in {"CNY", "USD"}:
        raise V2PaperError("V2 paper account currency must be CNY or USD")
    if candidate.currency != currency:
        raise V2PaperError("V2 paper currency must match the selected Champion")
    root = artifact_root.resolve()
    if root.name != "paper" or root.parent.name != "v2":
        raise V2PaperError("V2 paper account must be below artifacts/v2/paper only")
    database = root / candidate_id / currency / "ledger.sqlite3"
    database.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS events ("
            "sequence INTEGER PRIMARY KEY, event_id TEXT UNIQUE, payload TEXT)"
        )
        payload = json.dumps(
            {
                "candidate_id": candidate_id,
                "currency": currency,
                "cash": "100000",
                "event_type": "initial_cash",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        event_id = sha256(f"v2-paper/{candidate_id}/{currency}/initial_cash".encode()).hexdigest()
        connection.execute(
            "INSERT OR IGNORE INTO events(event_id, payload) VALUES (?, ?)", (event_id, payload)
        )
    return V2PaperAccount(candidate_id, currency, Decimal("100000"), database)


def require_v2_paper_run(
    registry: ChampionRegistry,
    *,
    candidate_id: str,
    currency: str,
    raw_qualified: bool,
    corporate_actions_qualified: bool,
    cost_model_qualified: bool,
) -> None:
    """Reject daily execution unless a Champion has qualified raw/action/cost inputs."""
    candidate = _require_candidate(registry, candidate_id)
    if currency not in {"CNY", "USD"}:
        raise V2PaperError("V2 paper run currency is invalid")
    if candidate.currency != currency:
        raise V2PaperError("V2 paper currency must match the selected Champion")
    if not raw_qualified or not corporate_actions_qualified or not cost_model_qualified:
        raise V2PaperError("V2 paper run requires qualified raw, actions and cost model")


def _require_candidate(registry: ChampionRegistry, candidate_id: str) -> CandidateDecision:
    for decision in registry.decisions:
        if decision.strategy_id == candidate_id and decision.status == "PAPER_CANDIDATE":
            return decision
    raise V2PaperError("V2 paper account requires a PAPER_CANDIDATE")
