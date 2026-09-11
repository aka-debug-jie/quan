"""PIT fundamental-evidence gate and deterministic V2-B factor ranking."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

from quant_stack.snapshot import write_immutable
from quant_stack_v2.pit import PITUniverse

REQUIRED_FIELDS = ("book_to_price", "return_on_equity", "momentum_12_1")


class FundamentalGateError(ValueError):
    """Raised when PIT fundamental evidence cannot support V2-B research."""


@dataclass(frozen=True)
class FundamentalObservation:
    """One value with separate publication and strategy-availability dates."""

    symbol: str
    field: str
    value: Decimal
    industry: str
    effective_date: date
    published_at: date
    available_from: date
    raw_sha256: str


@dataclass(frozen=True)
class FundamentalQualificationReport:
    """Immutable forward/reverse audit for a PIT fundamental source."""

    schema_version: int
    source_id: str
    source_snapshot_sha256: str
    pit_universe_sha256: str
    required_fields: tuple[str, ...]
    unexplained: tuple[str, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a stable identity for qualification evidence."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


@dataclass(frozen=True)
class FactorScore:
    """A transparent industry-standardized V2-B score at one signal date."""

    symbol: str
    value_z: Decimal
    quality_z: Decimal
    momentum_z: Decimal
    composite_score: Decimal


@dataclass(frozen=True)
class FactorRankingReport:
    """Immutable V2-B factor output, publishable only from qualified synthetic or real inputs."""

    schema_version: int
    signal_date: date
    pit_universe_sha256: str
    fundamental_qualification_sha256: str
    scores: tuple[FactorScore, ...]
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return the deterministic ranking-report identity."""
        return sha256(_canonical_json(asdict(self))).hexdigest()


def qualify_fundamentals(
    observations: tuple[FundamentalObservation, ...],
    *,
    source_id: str,
    source_snapshot_sha256: str,
    pit_universe_sha256: str,
) -> FundamentalQualificationReport:
    """Audit evidence identities and date semantics without inferring missing fundamentals."""
    problems: list[str] = []
    if len(source_snapshot_sha256) != 64 or len(pit_universe_sha256) != 64:
        problems.append("missing_immutable_source_or_pit_identity")
    seen: set[tuple[str, str, date]] = set()
    for observation in observations:
        key = (observation.symbol, observation.field, observation.effective_date)
        if observation.field not in REQUIRED_FIELDS:
            problems.append(f"unsupported_field:{observation.field}")
        if key in seen:
            problems.append(f"duplicate_observation:{observation.symbol}:{observation.field}")
        seen.add(key)
        if len(observation.raw_sha256) != 64:
            problems.append(f"missing_raw_hash:{observation.symbol}:{observation.field}")
        if observation.available_from < observation.published_at:
            problems.append(
                f"availability_before_publication:{observation.symbol}:{observation.field}"
            )
        if observation.published_at < observation.effective_date:
            problems.append(
                f"publication_before_effective_date:{observation.symbol}:{observation.field}"
            )
    if not observations:
        problems.append("no_pit_fundamental_observations")
    unresolved = tuple(sorted(set(problems)))
    return FundamentalQualificationReport(
        schema_version=1,
        source_id=source_id,
        source_snapshot_sha256=source_snapshot_sha256,
        pit_universe_sha256=pit_universe_sha256,
        required_fields=REQUIRED_FIELDS,
        unexplained=unresolved,
        status="QUALIFIED" if not unresolved else "BLOCKED_DATA",
    )


def rank_deterministic_factors(
    *,
    session: date,
    universe: PITUniverse,
    qualification: FundamentalQualificationReport,
    observations: tuple[FundamentalObservation, ...],
) -> tuple[FactorScore, ...]:
    """Rank only PIT members with all verified values available on the signal date."""
    if qualification.status != "QUALIFIED" or qualification.unexplained:
        raise FundamentalGateError("V2-B ranking requires qualified PIT fundamental evidence")
    members = universe.members_on(session)
    if not members:
        raise FundamentalGateError("V2-B ranking requires non-empty PIT membership")
    chosen: dict[str, dict[str, FundamentalObservation]] = {symbol: {} for symbol in members}
    for observation in observations:
        if (
            observation.symbol in chosen
            and observation.effective_date <= session
            and observation.available_from <= session
        ):
            prior = chosen[observation.symbol].get(observation.field)
            if prior is None or observation.effective_date > prior.effective_date:
                chosen[observation.symbol][observation.field] = observation
    missing = [symbol for symbol, rows in chosen.items() if set(rows) != set(REQUIRED_FIELDS)]
    if missing:
        raise FundamentalGateError(
            "V2-B ranking has PIT members with missing verified factor inputs"
        )
    groups: dict[str, list[str]] = {}
    for symbol, rows in chosen.items():
        groups.setdefault(rows["book_to_price"].industry, []).append(symbol)
    scores: list[FactorScore] = []
    for symbols in groups.values():
        fields = {
            field: _z_scores({symbol: chosen[symbol][field].value for symbol in symbols})
            for field in REQUIRED_FIELDS
        }
        for symbol in symbols:
            value_z = fields["book_to_price"][symbol]
            quality_z = fields["return_on_equity"][symbol]
            momentum_z = fields["momentum_12_1"][symbol]
            scores.append(
                FactorScore(
                    symbol, value_z, quality_z, momentum_z, (value_z + quality_z + momentum_z) / 3
                )
            )
    return tuple(sorted(scores, key=lambda item: (-item.composite_score, item.symbol)))


def persist_fundamental_qualification(
    report: FundamentalQualificationReport, artifact_root: Path
) -> Path:
    """Persist immutable qualification output; a blocked report is valid evidence."""
    path = artifact_root / "fundamental_qualification" / f"{report.identity_sha256}.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def build_factor_ranking_report(
    *,
    session: date,
    universe: PITUniverse,
    pit_universe_sha256: str,
    qualification: FundamentalQualificationReport,
    observations: tuple[FundamentalObservation, ...],
) -> FactorRankingReport:
    """Bind a transparent factor ranking to its PIT and fundamental qualifications."""
    if len(pit_universe_sha256) != 64:
        raise FundamentalGateError("V2-B ranking report requires a PIT qualification identity")
    scores = rank_deterministic_factors(
        session=session,
        universe=universe,
        qualification=qualification,
        observations=observations,
    )
    return FactorRankingReport(
        schema_version=1,
        signal_date=session,
        pit_universe_sha256=pit_universe_sha256,
        fundamental_qualification_sha256=qualification.identity_sha256,
        scores=scores,
        status="RESEARCH_RANKING_ONLY",
    )


def persist_factor_ranking_report(report: FactorRankingReport, artifact_root: Path) -> Path:
    """Persist an immutable audit report; portfolio construction remains a separately gated step."""
    if report.status != "RESEARCH_RANKING_ONLY":
        raise FundamentalGateError("unexpected V2-B ranking report status")
    path = artifact_root / "deterministic_factor" / report.identity_sha256 / "report.json"
    write_immutable(path, _canonical_json(asdict(report)) + b"\n")
    return path


def _z_scores(values: dict[str, Decimal]) -> dict[str, Decimal]:
    mean = sum(values.values(), Decimal("0")) / Decimal(len(values))
    variance = sum(((value - mean) ** 2 for value in values.values()), Decimal("0")) / Decimal(
        len(values)
    )
    if variance == 0:
        return {symbol: Decimal("0") for symbol in values}
    deviation = variance.sqrt()
    return {symbol: (value - mean) / deviation for symbol, value in values.items()}


def _canonical_json(value: object) -> bytes:
    return json.dumps(value, default=str, sort_keys=True, separators=(",", ":")).encode()
