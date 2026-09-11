"""Immutable V2-012 Champion/Challenger selection with strict external gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable


class ChampionError(ValueError):
    """Raised when a candidate is promoted without all frozen external evidence."""


@dataclass(frozen=True)
class CandidateEvidence:
    """One strategy's complete external evidence and same-cost benchmark comparison."""

    strategy_id: str
    market: str
    currency: str
    data_qualified: bool
    pit_qualified: bool
    external_test_passed: bool
    reproducible: bool
    lean_reconciled: bool
    net_return: Decimal
    net_sharpe: Decimal
    maximum_drawdown: Decimal
    benchmark_net_return: Decimal
    benchmark_sharpe: Decimal
    benchmark_maximum_drawdown: Decimal
    data_sha256: str
    config_sha256: str
    code_commit: str


@dataclass(frozen=True)
class CandidateDecision:
    """A retained Champion or Challenger outcome."""

    strategy_id: str
    market: str
    currency: str
    rank: int | None
    status: str
    reasons: tuple[str, ...]
    evidence_sha256: str


@dataclass(frozen=True)
class ChampionRegistry:
    """Content-addressed selection artifact with at most two paper candidates."""

    schema_version: int
    decisions: tuple[CandidateDecision, ...]

    @property
    def identity_sha256(self) -> str:
        return sha256(_canonical_json(asdict(self))).hexdigest()


def select_champions(candidates: tuple[CandidateEvidence, ...]) -> ChampionRegistry:
    """Select at most two strict relative-benchmark winners by external net Sharpe."""
    if len({candidate.strategy_id for candidate in candidates}) != len(candidates):
        raise ChampionError("candidate strategy IDs must be unique")
    eligible: list[CandidateEvidence] = []
    rejected: list[CandidateDecision] = []
    for candidate in candidates:
        reasons = _rejection_reasons(candidate)
        identity = sha256(_canonical_json(asdict(candidate))).hexdigest()
        if reasons:
            rejected.append(
                CandidateDecision(
                    candidate.strategy_id,
                    candidate.market,
                    candidate.currency,
                    None,
                    "REJECTED_NO_EDGE",
                    reasons,
                    identity,
                )
            )
        else:
            eligible.append(candidate)
    selected = sorted(eligible, key=lambda item: (-item.net_sharpe, item.strategy_id))[:2]
    winners = [
        CandidateDecision(
            item.strategy_id,
            item.market,
            item.currency,
            index,
            "PAPER_CANDIDATE",
            (),
            sha256(_canonical_json(asdict(item))).hexdigest(),
        )
        for index, item in enumerate(selected, start=1)
    ]
    return ChampionRegistry(
        schema_version=1,
        decisions=tuple(sorted((*winners, *rejected), key=lambda item: item.strategy_id)),
    )


def persist_champion_registry(registry: ChampionRegistry, artifact_root: Path) -> Path:
    """Publish the entire retained candidate decision set immutably."""
    path = artifact_root / "champions" / f"{registry.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(registry)) + b"\n")
    return path


def load_champion_registry(path: Path) -> ChampionRegistry:
    """Load a content-addressed Champion decision record without trusting its filename alone."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    registry = ChampionRegistry(
        schema_version=int(payload["schema_version"]),
        decisions=tuple(
            CandidateDecision(
                strategy_id=str(item["strategy_id"]),
                market=str(item["market"]),
                currency=str(item["currency"]),
                rank=int(item["rank"]) if item["rank"] is not None else None,
                status=str(item["status"]),
                reasons=tuple(str(reason) for reason in item["reasons"]),
                evidence_sha256=str(item["evidence_sha256"]),
            )
            for item in payload["decisions"]
        ),
    )
    if path.stem != registry.identity_sha256:
        raise ChampionError("Champion registry filename differs from its content identity")
    return registry


def _rejection_reasons(candidate: CandidateEvidence) -> tuple[str, ...]:
    required = {
        "data_qualified": candidate.data_qualified,
        "pit_qualified": candidate.pit_qualified,
        "external_test_passed": candidate.external_test_passed,
        "reproducible": candidate.reproducible,
        "lean_reconciled": candidate.lean_reconciled,
    }
    reasons = [name for name, passed in required.items() if not passed]
    if candidate.net_return <= candidate.benchmark_net_return:
        reasons.append("net_return_not_above_benchmark")
    if candidate.net_sharpe <= candidate.benchmark_sharpe:
        reasons.append("net_sharpe_not_above_benchmark")
    if candidate.maximum_drawdown < candidate.benchmark_maximum_drawdown - Decimal("0.05"):
        reasons.append("drawdown_more_than_five_points_worse_than_benchmark")
    if len(candidate.data_sha256) != 64 or len(candidate.config_sha256) != 64:
        reasons.append("missing_data_or_config_identity")
    if len(candidate.code_commit) != 40:
        reasons.append("missing_code_commit")
    return tuple(sorted(reasons))


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
