"""Proposal-only V2-014 RD-Agent contract; it cannot execute research work."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable


class RDAgentError(ValueError):
    """Raised when a proposal contains an execution capability or protected input."""


@dataclass(frozen=True)
class RDProposal:
    """A human-reviewable preregistration proposal without model or data execution rights."""

    schema_version: int
    hypothesis: str
    required_data_qualifications: tuple[str, ...]
    features: tuple[str, ...]
    label: str
    split: str
    cost_model: str
    risks: tuple[str, ...]
    expected_failure_conditions: tuple[str, ...]
    requested_capabilities: tuple[str, ...]

    @property
    def identity_sha256(self) -> str:
        return sha256(_canonical_json(asdict(self))).hexdigest()


FORBIDDEN_CAPABILITIES = frozenset(
    {
        "network",
        "raw_data",
        "sealed_data",
        "config_write",
        "precommit",
        "train",
        "backtest",
        "champion_selection",
        "paper_account",
        "v1_access",
    }
)


def validate_rd_proposal(proposal: RDProposal) -> None:
    """Accept only complete text proposals with no execution or protected-data capability."""
    required_text = (proposal.hypothesis, proposal.label, proposal.split, proposal.cost_model)
    if not all(item.strip() for item in required_text):
        raise RDAgentError("RD proposal requires hypothesis, label, split and cost model")
    if not proposal.required_data_qualifications or not proposal.expected_failure_conditions:
        raise RDAgentError("RD proposal requires data gates and expected failure conditions")
    forbidden = set(proposal.requested_capabilities) & FORBIDDEN_CAPABILITIES
    if forbidden:
        raise RDAgentError("RD proposal requests forbidden execution capability")


def persist_rd_proposal(proposal: RDProposal, artifact_root: Path) -> Path:
    """Persist an immutable proposal after capability validation; it is not an experiment."""
    validate_rd_proposal(proposal)
    path = artifact_root / "rd_proposals" / f"{proposal.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(proposal)) + b"\n")
    return path


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
