"""Command-line entry points for the M0 research skeleton."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Annotated
from zoneinfo import ZoneInfo

import typer
import yaml

from quant_stack.data.akshare_etf import AKShareETFAdapter, DataFetchError
from quant_stack.data.calendar import (
    CalendarNotFoundError,
    CalendarSourceError,
    ExchangeCalendarStore,
    IncompleteSessionError,
)
from quant_stack.data.corporate_actions import (
    CorporateActionLedgerError,
    load_corporate_action_ledger,
)
from quant_stack.data.evidence import (
    EvidenceArchiveError,
    archive_corporate_action_source,
    capture_corporate_action_evidence,
    capture_non_trading_evidence,
    require_non_trading_evidence,
)
from quant_stack.data.ingest import (
    CoverageError,
    ProvenanceError,
    ingest_universe,
    load_etf_universe,
    normalized_dates,
    verify_normalized_parquet,
)
from quant_stack.data.models import ETFHistoryRequest, ProviderSeriesManifest
from quant_stack.data.sina_etf import (
    SinaProviderError,
    fetch_sina_adjustment_candidate,
    fetch_sina_etf_history,
    load_sina_provider_bars,
    persist_sina_adjustment_candidate,
    persist_sina_etf_history,
)
from quant_stack.data.sse_fund_inventory import (
    SSEFundInventoryError,
    fetch_sse_fund_inventory,
    persist_sse_fund_inventory,
)
from quant_stack.data.sse_official import (
    SSEProviderError,
    fetch_sse_daily_history,
    persist_sse_daily_history,
)
from quant_stack.data.szse_official import (
    SZSEProviderError,
    fetch_szse_daily_history,
    load_szse_provider_bars,
    persist_szse_daily_history,
    reattest_szse_daily_history,
)
from quant_stack.data_qualification import persist_qualification_report, qualify_frozen_universe
from quant_stack.issue009_runner import run_issue009_controlled_recovery, run_issue009_locked_test
from quant_stack.locked_test import create_locked_test_precommit, persist_locked_test_precommit
from quant_stack.models import Exchange, PriceBasis
from quant_stack.paper_broker import PaperLedgerError
from quant_stack.paper_service import PaperDailyError, initialize_paper_account, run_paper_catchup
from quant_stack.research_result import recover_controlled_publication, recover_publication
from quant_stack.snapshot import create_raw_snapshot
from quant_stack.validation import load_daily_bars_csv
from quant_stack_v2.baseline import create_baseline_precommit
from quant_stack_v2.champion import load_champion_registry
from quant_stack_v2.dataset_registry import (
    DatasetRegistryError,
    capture_dataset,
    list_dataset_registries,
    load_dataset_registry,
    validate_dataset,
)
from quant_stack_v2.dual_momentum import (
    build_dual_momentum_report,
    persist_dual_momentum_report,
)
from quant_stack_v2.external_validation import (
    persist_external_qualification,
    qualify_external_market,
)
from quant_stack_v2.foundation_gate import GateEvidence, persist_qualification, qualify_foundation
from quant_stack_v2.paper import initialize_v2_paper_account
from quant_stack_v2.pit import (
    build_pit_universe,
    load_pit_qualification,
    persist_pit_qualification,
    qualify_pit_universe,
)
from quant_stack_v2.qlib_import import (
    QlibImportReport,
    import_qlib_archive,
    load_qlib_import_report,
    tree_sha256,
)
from quant_stack_v2.qlib_qualification import (
    audit_qlib_member_sessions,
    persist_daily_audit,
)
from quant_stack_v2.qlib_semantics import capture_factor_semantics
from quant_stack_v2.tushare_pro import capture_tushare_response
from quant_stack_v2.yahoo_etf import (
    load_yahoo_universe_report,
    persist_yahoo_universe_report,
    snapshot_yahoo_universe,
)

app = typer.Typer(help="Offline-first quantitative research commands.")
data_app = typer.Typer(help="Validate and snapshot local data.")
calendar_app = typer.Typer(help="Validate local exchange calendar snapshots.")
backtest_app = typer.Typer(help="Backtest commands (M0 placeholders).")
signal_app = typer.Typer(help="Signal commands (M0 placeholders).")
paper_app = typer.Typer(help="Paper-trading commands (M0 placeholders).")
v2_app = typer.Typer(help="Isolated Quant V2 research-factory commands.")
v2_dataset_app = typer.Typer(help="Inspect and capture registered V2 datasets.")
v2_qlib_app = typer.Typer(help="Offline Qlib archive import and PIT qualification.")
v2_etf_app = typer.Typer(help="Research-only global ETF provider snapshots.")
v2_strategy_app = typer.Typer(help="V2 research strategy signals and blocked research gates.")
v2_baseline_app = typer.Typer(help="Frozen Qlib baseline precommits and sealed evidence.")
v2_external_app = typer.Typer(help="Fail-closed V2 external-history qualification.")
v2_paper_app = typer.Typer(help="Isolated V2 Champion paper-account commands.")
v2_tushare_app = typer.Typer(help="Tushare Pro raw-response capture for V2 qualification.")

app.add_typer(data_app, name="data")
app.add_typer(calendar_app, name="calendar")
app.add_typer(backtest_app, name="backtest")
app.add_typer(signal_app, name="signal")
app.add_typer(paper_app, name="paper")
app.add_typer(v2_app, name="v2")
v2_app.add_typer(v2_dataset_app, name="dataset")
v2_app.add_typer(v2_qlib_app, name="qlib")
v2_app.add_typer(v2_etf_app, name="etf")
v2_app.add_typer(v2_strategy_app, name="strategy")
v2_app.add_typer(v2_baseline_app, name="baseline")
v2_app.add_typer(v2_external_app, name="external")
v2_app.add_typer(v2_paper_app, name="paper")
v2_app.add_typer(v2_tushare_app, name="tushare")

UniverseOption = Annotated[Path, typer.Option(..., exists=True, readable=True)]
RequiredDateOption = Annotated[str, typer.Option(...)]
DataRootOption = Annotated[Path, typer.Option()]
CalendarRootOption = Annotated[Path, typer.Option(exists=True, readable=True)]
AllowNetworkOption = Annotated[bool, typer.Option()]
V2DatasetRootOption = Annotated[Path, typer.Option(exists=True, readable=True)]
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SEALED_EXTERNAL_ROOT = Path("/srv/quant-v2/sealed_holdout/data/external")
SEALED_ARTIFACT_ROOT = Path("/srv/quant-v2/sealed_holdout/artifacts/v2")


def _v2_dataset_path(dataset_id: str, registry_root: Path) -> Path:
    """Resolve one dataset ID only inside the configured registry directory."""
    resolved_root = _v2_registry_root(registry_root)
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", dataset_id) is None:
        raise typer.BadParameter("invalid V2 dataset ID")
    path = resolved_root / f"{dataset_id}.yaml"
    if not path.is_file():
        raise typer.BadParameter(f"unknown V2 dataset: {dataset_id}")
    return path


def _v2_repository_root() -> Path:
    """Resolve the source repository explicitly when the CLI is installed from a wheel."""
    configured = os.environ.get("QUANT_V2_REPOSITORY_ROOT")
    if configured is None:
        return REPOSITORY_ROOT
    root = Path(configured).resolve()
    if not (root / "configs/v2/datasets").is_dir():
        raise typer.BadParameter("QUANT_V2_REPOSITORY_ROOT lacks configs/v2/datasets")
    return root


def _v2_registry_root(registry_root: Path) -> Path:
    resolved = registry_root.resolve()
    if tuple(resolved.parts[-3:]) != ("configs", "v2", "datasets"):
        raise typer.BadParameter("V2 registry root must end with configs/v2/datasets")
    return resolved


def _v2_external_root(data_root: Path) -> Path:
    """Reject V2 data reads redirected into V1 authorities or arbitrary directories."""
    resolved = data_root.resolve()
    accepted = (REPOSITORY_ROOT / "data" / "external", SEALED_EXTERNAL_ROOT)
    if resolved not in accepted:
        raise typer.BadParameter("V2 data root must be the repository or sealed data/external root")
    return resolved


def _v2_artifact_root(artifact_root: Path) -> Path:
    """Keep V2 derived reports outside V1 artifact and locked-run authorities."""
    resolved = artifact_root.resolve()
    accepted = (REPOSITORY_ROOT / "artifacts" / "v2", SEALED_ARTIFACT_ROOT)
    if not any(resolved.is_relative_to(root) for root in accepted):
        raise typer.BadParameter(
            "V2 artifact root must be below a repository or sealed artifacts/v2 root"
        )
    return resolved


def _verified_qlib_report(report_path: Path, artifact_root: Path) -> QlibImportReport:
    """Bind a Qlib report to the pinned V2 registry and its content-addressed location."""
    registry = load_dataset_registry(
        _v2_dataset_path("qlib_cn_community_v1", _v2_repository_root() / "configs/v2/datasets")
    )
    if registry.artifacts.archive_sha256 is None or registry.artifacts.manifest_sha256 is None:
        raise typer.BadParameter("Qlib registry lacks immutable artifact identities")
    report = load_qlib_import_report(report_path)
    expected = (
        artifact_root
        / registry.artifacts.archive_sha256
        / "reports"
        / f"{report.identity_sha256}.json"
    )
    if report_path.resolve() != expected.resolve():
        raise typer.BadParameter("Qlib import report is outside its content-addressed authority")
    if (
        report.archive_sha256 != registry.artifacts.archive_sha256
        or report.manifest_sha256 != registry.artifacts.manifest_sha256
    ):
        raise typer.BadParameter("Qlib import report differs from the pinned registry")
    tree_path = (
        artifact_root / registry.artifacts.archive_sha256 / "trees" / report.extracted_tree_sha256
    )
    if not tree_path.is_dir() or tree_sha256(tree_path) != report.extracted_tree_sha256:
        raise typer.BadParameter("Qlib extraction tree differs from import evidence")
    return report


@v2_dataset_app.command("list")
def list_v2_datasets(
    registry_root: V2DatasetRootOption = Path("configs/v2/datasets"),
) -> None:
    """List V2 dataset identities and their maximum declared usage levels offline."""
    try:
        records = list_dataset_registries(_v2_registry_root(registry_root))
    except DatasetRegistryError as error:
        typer.echo(f"V2 dataset registry failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    for record in records:
        typer.echo(
            f"{record.dataset_id}\t{record.usage_level.value}\t{record.qualification_status}"
        )


@v2_dataset_app.command("inspect")
def inspect_v2_dataset(
    dataset_id: str,
    registry_root: V2DatasetRootOption = Path("configs/v2/datasets"),
) -> None:
    """Print one strict V2 registry without downloading its artifacts."""
    record = load_dataset_registry(_v2_dataset_path(dataset_id, registry_root))
    typer.echo(json.dumps(record.model_dump(mode="json"), ensure_ascii=False, sort_keys=True))


@v2_dataset_app.command("validate")
def validate_v2_dataset(
    dataset_id: str,
    registry_root: V2DatasetRootOption = Path("configs/v2/datasets"),
    data_root: DataRootOption = Path("data/external"),
) -> None:
    """Validate one captured dataset locally and fail closed while qualification is pending."""
    result = validate_dataset(
        _v2_dataset_path(dataset_id, registry_root), _v2_external_root(data_root)
    )
    typer.echo(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    if not result.qualified:
        raise typer.Exit(code=1)


@v2_dataset_app.command("capture")
def capture_v2_dataset(
    dataset_id: str,
    registry_root: V2DatasetRootOption = Path("configs/v2/datasets"),
    data_root: DataRootOption = Path("data/external"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly capture pre-hashed GitHub artifacts without qualifying their semantics."""
    try:
        paths = capture_dataset(
            _v2_dataset_path(dataset_id, registry_root),
            _v2_external_root(data_root),
            allow_network=allow_network,
        )
    except DatasetRegistryError as error:
        typer.echo(f"V2 dataset capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    for path in paths:
        typer.echo(f"captured: {path}")


@v2_qlib_app.command("import")
def import_v2_qlib(
    registry_root: V2DatasetRootOption = Path("configs/v2/datasets"),
    data_root: DataRootOption = Path("data/external"),
    output_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/qlib_import"),
) -> None:
    """Safely import only the locally captured and hash-pinned Qlib community archive."""
    external_root = _v2_external_root(data_root)
    registry = load_dataset_registry(_v2_dataset_path("qlib_cn_community_v1", registry_root))
    if (
        registry.artifacts.archive_url is None
        or registry.artifacts.archive_sha256 is None
        or registry.artifacts.manifest_url is None
        or registry.artifacts.manifest_sha256 is None
    ):
        raise typer.BadParameter("Qlib registry lacks a pinned archive or manifest")
    archive = (
        external_root
        / registry.dataset_id
        / registry.artifacts.archive_sha256
        / Path(registry.artifacts.archive_url.path or "qlib_bin.tar.gz").name
    )
    manifest = (
        external_root
        / registry.dataset_id
        / registry.artifacts.manifest_sha256
        / Path(registry.artifacts.manifest_url.path or "qlib_bin.manifest.json").name
    )
    try:
        report_path, report = import_qlib_archive(
            archive,
            manifest,
            _v2_artifact_root(output_root),
            expected_archive_sha256=registry.artifacts.archive_sha256,
            expected_manifest_sha256=registry.artifacts.manifest_sha256,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"V2 Qlib import failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps({"report_path": str(report_path), "status": report.status}, sort_keys=True)
    )
    if report.status != "IMPORT_READY":
        raise typer.Exit(code=1)


@v2_qlib_app.command("inspect")
def inspect_v2_qlib(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
) -> None:
    """Print an already-created Qlib import report without reading market data."""
    loaded = load_qlib_import_report(report)
    typer.echo(json.dumps(loaded.__dict__, default=str, sort_keys=True))


@v2_qlib_app.command("archive-factor-semantics")
def archive_v2_qlib_factor_semantics(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
    data_root: Annotated[Path, typer.Option()] = SEALED_EXTERNAL_ROOT,
    allow_network: AllowNetworkOption = False,
) -> None:
    """Archive the pinned build sources proving Qlib factor and binary semantics."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for factor semantics capture")
    sealed_qlib_root = SEALED_ARTIFACT_ROOT / "qlib_import"
    qlib_root = (
        sealed_qlib_root
        if report.resolve().is_relative_to(sealed_qlib_root)
        else _v2_artifact_root(Path("artifacts/v2/qlib_import"))
    )
    loaded = _verified_qlib_report(report, qlib_root)
    try:
        path, semantics = capture_factor_semantics(
            _v2_external_root(data_root),
            archive_sha256=loaded.archive_sha256,
            allow_network=True,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"V2 Qlib factor semantics capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps({"report_path": str(path), "status": semantics.status}, sort_keys=True))


@v2_tushare_app.command("capture")
def capture_v2_tushare(
    api_name: Annotated[str, typer.Option()],
    parameters: Annotated[str, typer.Option(help="JSON object of API parameters")],
    data_root: Annotated[Path, typer.Option()] = SEALED_EXTERNAL_ROOT,
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture one Tushare response under explicit network and runtime-token authority."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for Tushare capture")
    try:
        parsed = json.loads(parameters)
        if not isinstance(parsed, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in parsed.items()
        ):
            raise ValueError("parameters must be a JSON object of strings")
        path, manifest = capture_tushare_response(
            _v2_external_root(data_root),
            api_name=api_name,
            parameters=parsed,
            allow_network=True,
        )
    except (OSError, ValueError) as error:
        typer.echo(f"V2 Tushare capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps({"manifest_path": str(path), "status": manifest.status}, sort_keys=True))


@v2_qlib_app.command("audit-daily")
def audit_v2_qlib_daily(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
    universe: Annotated[str, typer.Option()] = "csi300",
    config: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/v2/evaluations/qlib_csi300_csi500_v1.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/qlib_daily_audit"),
) -> None:
    """Audit every active PIT member/session and retain all data-quality failures."""
    sealed_qlib_root = SEALED_ARTIFACT_ROOT / "qlib_import"
    qlib_root = (
        sealed_qlib_root
        if report.resolve().is_relative_to(sealed_qlib_root)
        else _v2_artifact_root(Path("artifacts/v2/qlib_import"))
    )
    loaded = _verified_qlib_report(report, qlib_root)
    if universe not in {"csi300", "csi500"}:
        raise typer.BadParameter("universe must be csi300 or csi500")
    config_payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(config_payload, dict):
        raise typer.BadParameter("V2 evaluation configuration must be a mapping")
    effective_from = date.fromisoformat(str(config_payload["research_effective_from"]))
    effective_to = date.fromisoformat(str(config_payload["research_snapshot_as_of"]))
    intervals = loaded.csi300_intervals if universe == "csi300" else loaded.csi500_intervals
    tree = qlib_root / loaded.archive_sha256 / "trees" / loaded.extracted_tree_sha256
    try:
        audit = audit_qlib_member_sessions(
            tree / "qlib_bin",
            universe=universe,
            intervals=intervals,
            sessions=tuple(date.fromisoformat(item) for item in loaded.sessions),
            import_report_sha256=loaded.identity_sha256,
            research_effective_from=effective_from,
            research_effective_to=effective_to,
        )
        path = persist_daily_audit(audit, _v2_artifact_root(artifact_root))
    except (OSError, ValueError) as error:
        typer.echo(f"V2 Qlib daily audit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "report_path": str(path),
                "status": audit.status,
                "member_sessions_checked": audit.member_sessions_checked,
                "issue_count": len(audit.issues),
            },
            sort_keys=True,
        )
    )
    if audit.status != "QUALIFIED":
        raise typer.Exit(code=1)


@v2_qlib_app.command("qualify-foundation")
def qualify_v2_foundation(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
    evidence: Annotated[
        list[str] | None, typer.Option(help="gate_name=/absolute/path/to/report")
    ] = None,
    config: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/v2/evaluations/qlib_csi300_csi500_v1.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/foundation_gate"),
) -> None:
    """Join independent qualification evidence into the only V2-003 promotion report."""
    sealed_qlib_root = SEALED_ARTIFACT_ROOT / "qlib_import"
    qlib_root = (
        sealed_qlib_root
        if report.resolve().is_relative_to(sealed_qlib_root)
        else _v2_artifact_root(Path("artifacts/v2/qlib_import"))
    )
    loaded = _verified_qlib_report(report, qlib_root)
    config_bytes = config.read_bytes()
    config_payload = yaml.safe_load(config_bytes)
    if not isinstance(config_payload, dict):
        raise typer.BadParameter("V2 evaluation configuration must be a mapping")
    parsed: list[GateEvidence] = []
    for value in evidence or []:
        name, separator, raw_path = value.partition("=")
        path = Path(raw_path)
        if not separator or not path.is_file():
            raise typer.BadParameter("evidence must be gate_name=/existing/report.json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            status = str(payload["status"])
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError) as error:
            raise typer.BadParameter("evidence report must be JSON with a status") from error
        parsed.append(
            GateEvidence(
                name=name,
                path=str(path.resolve()),
                sha256=sha256(path.read_bytes()).hexdigest(),
                status="QUALIFIED"
                if status in {"QUALIFIED", "VERIFIED_FACTOR_SEMANTICS"}
                else status,
            )
        )
    try:
        code_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=Path.cwd()
        ).strip()
        qualification = qualify_foundation(
            universe="csi300",
            research_effective_from=str(config_payload["research_effective_from"]),
            research_effective_to=str(config_payload["research_snapshot_as_of"]),
            import_report_sha256=loaded.identity_sha256,
            config_sha256=sha256(config_bytes).hexdigest(),
            code_commit=code_commit,
            evidence=tuple(parsed),
        )
        path = persist_qualification(qualification, _v2_artifact_root(artifact_root))
    except (OSError, ValueError) as error:
        typer.echo(f"V2 Foundation Gate failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "report_path": str(path),
                "status": qualification.status,
                "reasons": qualification.reasons,
            },
            sort_keys=True,
        )
    )
    if qualification.status != "QUALIFIED":
        raise typer.Exit(code=1)


@v2_qlib_app.command("qualify-pit")
def qualify_v2_qlib_pit(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
    universe: Annotated[str, typer.Option()] = "csi300",
    config: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/v2/evaluations/qlib_csi300_csi500_v1.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/pit_qualification"),
) -> None:
    """Audit source PIT membership from an immutable Qlib import report."""
    sealed_qlib_root = SEALED_ARTIFACT_ROOT / "qlib_import"
    qlib_root = (
        sealed_qlib_root
        if report.resolve().is_relative_to(sealed_qlib_root)
        else _v2_artifact_root(Path("artifacts/v2/qlib_import"))
    )
    loaded = _verified_qlib_report(report, qlib_root)
    if (
        loaded.status != "IMPORT_READY"
        or loaded.factor_reconstruction_status != "VERIFIED_FACTOR_SEMANTICS"
    ):
        typer.echo("V2 PIT qualification requires verified Qlib factor semantics", err=True)
        raise typer.Exit(code=1)
    intervals = loaded.csi300_intervals if universe == "csi300" else loaded.csi500_intervals
    if universe not in {"csi300", "csi500"}:
        raise typer.BadParameter("universe must be csi300 or csi500")
    sessions = tuple(date.fromisoformat(item) for item in loaded.sessions)
    config_payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(config_payload, dict):
        raise typer.BadParameter("V2 evaluation configuration must be a mapping")
    effective_from = date.fromisoformat(str(config_payload["research_effective_from"]))
    effective_to = date.fromisoformat(str(config_payload["research_snapshot_as_of"]))
    declared = {item.symbol for item in intervals}
    available = declared - set(loaded.missing_price_or_factor_symbols)
    try:
        qualification = qualify_pit_universe(
            build_pit_universe(universe, intervals),
            sessions,
            available,
            loaded.identity_sha256,
            effective_from,
            effective_to,
        )
        path = persist_pit_qualification(qualification, _v2_artifact_root(artifact_root))
    except ValueError as error:
        typer.echo(f"V2 PIT qualification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps({"report_path": str(path), "status": qualification.status}, sort_keys=True)
    )
    if qualification.status != "QUALIFIED":
        raise typer.Exit(code=1)


@v2_qlib_app.command("report")
def report_v2_qlib(
    report: Annotated[Path, typer.Option(exists=True, readable=True)],
) -> None:
    """Emit the stable identity and status of an immutable Qlib import report."""
    loaded = load_qlib_import_report(report)
    typer.echo(json.dumps({"report_id": loaded.identity_sha256, "status": loaded.status}))


@v2_etf_app.command("snapshot-yahoo")
def snapshot_v2_yahoo_etfs(
    data_root: DataRootOption = Path("data/external"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture the fixed global ETF universe as research-only adjusted-price snapshots."""
    try:
        external_root = _v2_external_root(data_root)
        report = snapshot_yahoo_universe(external_root, allow_network=allow_network)
        report_path = persist_yahoo_universe_report(report, external_root)
    except ValueError as error:
        typer.echo(f"V2 Yahoo snapshot failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "usage_level": "RESEARCH_ADJUSTED_ONLY",
                "report_path": str(report_path),
                "symbols": [item.manifest.symbol for item in report.symbol_snapshots],
                "common_dates": len(report.common_trading_dates),
                "anomalies": [item.__dict__ for item in report.anomalies],
            },
            default=str,
            sort_keys=True,
        )
    )
    if report.anomalies:
        raise typer.Exit(code=1)


@v2_strategy_app.command("dual-momentum")
def build_v2_dual_momentum(
    yahoo_report: Annotated[Path, typer.Option(exists=True, readable=True)],
    config: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/v2/strategies/dual_momentum_12_1_v1.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/strategies"),
) -> None:
    """Build research-only V2-A adjusted-price signals; no execution or performance occurs."""
    external_root = _v2_external_root(Path("data/external"))
    if not yahoo_report.resolve().is_relative_to(external_root.resolve()):
        raise typer.BadParameter("Yahoo report is outside the V2 external-data authority")
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("status") != "frozen_research_signal_only":
        raise typer.BadParameter("V2-A configuration is not the frozen research-only contract")
    try:
        snapshot = load_yahoo_universe_report(yahoo_report)
        report = build_dual_momentum_report(
            snapshot,
            dataset_report_sha256=sha256(yahoo_report.read_bytes()).hexdigest(),
            config_sha256=sha256(config.read_bytes()).hexdigest(),
        )
        path = persist_dual_momentum_report(report, _v2_artifact_root(artifact_root))
    except ValueError as error:
        typer.echo(f"V2 dual-momentum signal build failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "report_path": str(path),
                "status": report.status,
                "usage_level": report.usage_level,
                "signals": len(report.signals),
                "forbidden": ["execution", "backtest", "paper_broker", "performance"],
            },
            sort_keys=True,
        )
    )


@v2_external_app.command("qualify")
def qualify_v2_external_market(
    config: Annotated[Path, typer.Option(exists=True, readable=True)],
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/external"),
) -> None:
    """Write a blocked-or-qualified V2-010 report without a provider fetch or backtest."""
    expected_root = (REPOSITORY_ROOT / "configs" / "v2" / "external").resolve()
    if not config.resolve().is_relative_to(expected_root):
        raise typer.BadParameter("V2 external configuration must be below configs/v2/external")
    payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise typer.BadParameter("V2 external configuration must be a mapping")
    try:
        report = qualify_external_market(
            dataset_id=str(payload["dataset_id"]),
            market=str(payload["market"]),
            currency=str(payload["currency"]),
            source_approval=str(payload["source_approval"]),
        )
        path = persist_external_qualification(report, _v2_artifact_root(artifact_root))
    except (KeyError, ValueError) as error:
        typer.echo(f"V2 external qualification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps({"report_path": str(path), "status": report.status}, sort_keys=True))
    if report.status != "QUALIFIED":
        raise typer.Exit(code=1)


@v2_paper_app.command("initialize")
def initialize_v2_paper(
    champion_registry: Annotated[Path, typer.Option(exists=True, readable=True)],
    candidate_id: Annotated[str, typer.Option()],
    currency: Annotated[str, typer.Option()],
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/paper"),
) -> None:
    """Create one isolated V2 Champion ledger; non-Champions are rejected before any write."""
    try:
        registry = load_champion_registry(champion_registry)
        account = initialize_v2_paper_account(
            registry,
            candidate_id=candidate_id,
            currency=currency,
            artifact_root=_v2_artifact_root(artifact_root),
        )
    except ValueError as error:
        typer.echo(f"V2 paper initialization failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(
        json.dumps(
            {
                "candidate_id": account.candidate_id,
                "currency": account.currency,
                "ledger": str(account.database_path),
            },
            sort_keys=True,
        )
    )


@v2_baseline_app.command("precommit")
def precommit_v2_baseline(
    qlib_report: Annotated[Path, typer.Option(exists=True, readable=True)],
    pit_report: Annotated[Path, typer.Option(exists=True, readable=True)],
    config: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/v2/models/qlib_baseline_v1.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/v2/baseline_precommits"),
) -> None:
    """Freeze V2-004 only after import and PIT qualification reports have both passed."""
    qlib_root = _v2_artifact_root(Path("artifacts/v2/qlib_import"))
    pit_root = _v2_artifact_root(Path("artifacts/v2/pit_qualification"))
    imported = _verified_qlib_report(qlib_report, qlib_root)
    qualified_pit = load_pit_qualification(pit_report)
    expected_pit = pit_root / "csi300" / f"{qualified_pit.identity_sha256}.json"
    if pit_report.resolve() != expected_pit.resolve():
        raise typer.BadParameter("PIT report is outside its content-addressed authority")
    config_payload = yaml.safe_load(config.read_text(encoding="utf-8"))
    if not isinstance(config_payload, dict) or (
        config_payload.get("models") != ["linear", "lightgbm"]
        or config_payload.get("tracks") != ["qlib_compat", "project_20_session"]
        or config_payload.get("seeds") != list(range(20))
        or config_payload.get("execution_delay_sessions") != 1
        or config_payload.get("project_horizon_sessions") != 20
        or config_payload.get("purge_sessions") != 20
        or config_payload.get("embargo_sessions") != 20
    ):
        raise typer.BadParameter("V2 baseline configuration differs from the frozen contract")
    if (
        imported.status != "IMPORT_READY"
        or imported.factor_reconstruction_status != "VERIFIED_FACTOR_SEMANTICS"
        or qualified_pit.status != "QUALIFIED"
        or qualified_pit.unexplained_sessions
        or qualified_pit.source_import_report_sha256 != imported.identity_sha256
    ):
        typer.echo(
            "V2 baseline precommit requires IMPORT_READY and QUALIFIED PIT evidence", err=True
        )
        raise typer.Exit(code=1)
    try:
        if subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=no"], text=True, cwd=Path.cwd()
        ):
            raise ValueError("baseline precommit requires a clean tracked worktree")
        code_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, cwd=Path.cwd()
        ).strip()
        path, precommit = create_baseline_precommit(
            _v2_artifact_root(artifact_root),
            dataset_snapshot_sha256=imported.identity_sha256,
            pit_universe_sha256=sha256(pit_report.read_bytes()).hexdigest(),
            code_commit=code_commit,
            config_sha256=sha256(config.read_bytes()).hexdigest(),
        )
    except (OSError, ValueError) as error:
        typer.echo(f"V2 baseline precommit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps({"precommit_path": str(path), "precommit_id": precommit.identity_sha256}))


@data_app.command("validate")
def validate_data(path: Path) -> None:
    """Validate a local daily-bar CSV against the M0 schema."""
    bars = load_daily_bars_csv(path)
    typer.echo(f"valid bars: {len(bars)}")


@data_app.command("qualify-universe")
def qualify_universe(
    universe: UniverseOption,
    data_root: DataRootOption = Path("data"),
    ledger_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/corporate_actions"
    ),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/data_qualification"),
    source_registry: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/data_qualification/d0_sources_v1.yaml"
    ),
) -> None:
    """Qualify every frozen-universe asset and refuse promotion when any D0 gate is unmet."""
    try:
        report = qualify_frozen_universe(
            universe,
            data_root,
            ledger_root,
            calendar_root,
            artifact_root,
            source_registry,
        )
        path = persist_qualification_report(report, artifact_root)
    except ValueError as error:
        typer.echo(f"universe qualification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"qualification report: {path}")
    for asset in report.assets:
        typer.echo(f"{asset.symbol}: {asset.result}; reasons={','.join(asset.reasons) or 'none'}")
    if not report.all_qualified:
        raise typer.Exit(code=1)


@data_app.command("snapshot")
def snapshot_data(path: Path, raw_root: Path) -> None:
    """Create an immutable, content-addressed snapshot from a local file."""
    snapshot_path, manifest = create_raw_snapshot(raw_root, path, source="local-file")
    typer.echo(f"snapshot: {manifest.snapshot_id}")
    typer.echo(f"path: {snapshot_path}")


@data_app.command("ingest-etf")
def ingest_etf(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Ingest missing raw and qfq ETF sessions through the explicit network boundary."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for AKShare ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        result = ingest_universe(
            load_etf_universe(universe),
            start_date,
            as_of_date,
            data_root,
            ExchangeCalendarStore(calendar_root),
            AKShareETFAdapter(),
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        CoverageError,
        DataFetchError,
        EvidenceArchiveError,
        IncompleteSessionError,
        ValueError,
    ) as error:
        typer.echo(f"ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"immutable ingestions: {len(result.ingestions)}")
    typer.echo(f"coverage reports: {len(result.coverage_reports)} complete")
    for ingestion in result.ingestions:
        typer.echo(f"manifest: {ingestion.manifest_path}")


@data_app.command("capture-non-trading-evidence")
def capture_non_trading_evidence_command(
    universe: UniverseOption,
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly fetch and hash-check configured official non-trading evidence documents."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture non-trading evidence")
    events = tuple(
        event
        for instrument in load_etf_universe(universe).instruments
        for event in instrument.documented_non_trading_events
    )
    try:
        paths = capture_non_trading_evidence(events, data_root)
    except EvidenceArchiveError as error:
        typer.echo(f"non-trading evidence capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified non-trading evidence archives: {len(paths)}")


@data_app.command("capture-corporate-action-evidence")
def capture_corporate_action_evidence_command(
    ledger: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly capture and verify the official source bodies named by one action ledger."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture corporate-action evidence")
    try:
        paths = capture_corporate_action_evidence(
            load_corporate_action_ledger(ledger).events,
            data_root,
        )
    except (CorporateActionLedgerError, EvidenceArchiveError) as error:
        typer.echo(f"corporate-action evidence capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified corporate-action evidence archives: {len(paths)}")


@data_app.command("archive-corporate-action-source")
def archive_corporate_action_source_command(
    url: Annotated[str, typer.Option(...)],
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Archive a first-party corporate-action source and print its identity for ledger review."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required to archive corporate-action evidence")
    try:
        evidence = archive_corporate_action_source(url, data_root)
    except EvidenceArchiveError as error:
        typer.echo(f"corporate-action source archive failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"evidence sha256: {evidence.sha256}")


@data_app.command("ingest-szse-raw")
def ingest_szse_raw(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture a provider-native SZSE raw series; no adjusted values are requested or created."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SZSE ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        instruments = load_etf_universe(universe).instruments
        instrument = next(
            item for item in instruments if item.symbol == symbol and item.exchange is Exchange.SZSE
        )
        calendar = ExchangeCalendarStore(calendar_root)
        calendar.require_completed_as_of(instrument.exchange, as_of_date)
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        manifest = persist_szse_daily_history(
            request,
            fetch_szse_daily_history(instrument.symbol),
            data_root,
        )
        bars = load_szse_provider_bars(manifest, data_root)
        coverage = calendar.coverage_report(
            instrument,
            PriceBasis.RAW,
            {bar.trading_date for bar in bars},
            request.start_date,
            request.as_of_date,
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        IncompleteSessionError,
        SZSEProviderError,
        StopIteration,
        ValueError,
    ) as error:
        typer.echo(f"SZSE ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {manifest.manifest_id}")
    typer.echo(f"raw provider rows: {len(bars)}")
    typer.echo(f"coverage complete: {coverage.is_complete}")
    if not coverage.is_complete:
        typer.echo(
            "SZSE provider series is retained but cannot pass the Issue 003 coverage gate", err=True
        )
        raise typer.Exit(code=1)


@data_app.command("audit-szse-history")
def audit_szse_history(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Record three bounded official SZSE parameter probes without creating canonical data."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SZSE history auditing")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    probes = {
        "base": {},
        "pagination": {"page": "2", "pageSize": "5000"},
        "date_window": {"beginDate": start_date.isoformat(), "endDate": as_of_date.isoformat()},
    }
    try:
        instrument = next(
            item for item in load_etf_universe(universe).instruments if item.symbol == symbol
        )
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        summaries = []
        for name, parameters in probes.items():
            manifest = persist_szse_daily_history(
                request,
                fetch_szse_daily_history(instrument.symbol, parameters),
                data_root,
            )
            summaries.append(
                {
                    "probe": name,
                    "manifest_id": manifest.manifest_id,
                    "request_parameters": manifest.request_parameters,
                    "row_count": manifest.row_count,
                    "first_trading_date": manifest.first_trading_date.isoformat(),
                    "last_trading_date": manifest.last_trading_date.isoformat(),
                }
            )
    except (SZSEProviderError, StopIteration, ValueError) as error:
        typer.echo(f"SZSE history audit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(json.dumps(summaries, ensure_ascii=False, indent=2))


@data_app.command("reattest-szse-raw")
def reattest_szse_raw(
    manifest: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
) -> None:
    """Re-normalize a retained SZSE raw response under the current parser without network access."""
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        source_manifest = ProviderSeriesManifest.model_validate_json(
            manifest.read_text(encoding="utf-8")
        )
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if (
                item.symbol == source_manifest.instrument.symbol
                and item.exchange is source_manifest.instrument.exchange
            )
        )
        result = reattest_szse_daily_history(
            ETFHistoryRequest(
                instrument=instrument,
                start_date=max(start_date, instrument.effective_from),
                as_of_date=as_of_date,
                price_basis=PriceBasis.RAW,
            ),
            source_manifest,
            data_root,
        )
    except (SZSEProviderError, StopIteration, ValueError) as error:
        typer.echo(f"SZSE re-attestation failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {result.manifest_id}")


@data_app.command("capture-sina-adjustment-candidate")
def capture_sina_adjustment_candidate(
    symbol: Annotated[str, typer.Option()] = "159919",
    exchange: Annotated[Exchange, typer.Option()] = Exchange.SZSE,
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture a Sina factor candidate for audit only; it cannot publish qfq data."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for Sina adjustment capture")
    try:
        path = persist_sina_adjustment_candidate(
            fetch_sina_adjustment_candidate(symbol, exchange), data_root
        )
    except SinaProviderError as error:
        typer.echo(f"Sina adjustment candidate failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"candidate path: {path}")


@data_app.command("capture-sse-fund-inventory")
def capture_sse_fund_inventory(
    symbol: Annotated[str, typer.Option(...)],
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture a complete official SSE announcement directory for one fund."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SSE inventory capture")
    try:
        payload = fetch_sse_fund_inventory(
            symbol, _parse_cli_date(start, "start"), _parse_cli_date(as_of, "as-of")
        )
        path = persist_sse_fund_inventory(payload, data_root)
    except SSEFundInventoryError as error:
        typer.echo(f"SSE fund inventory capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"SSE fund inventory: {path}")


@data_app.command("ingest-sse-raw")
def ingest_sse_raw(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option(...)],
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture an independent SSE official raw series for D0 adjudication."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for SSE raw ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if item.symbol == symbol and item.exchange is Exchange.SSE
        )
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        manifest = persist_sse_daily_history(request, fetch_sse_daily_history(symbol), data_root)
    except (SSEProviderError, StopIteration, ValueError) as error:
        typer.echo(f"SSE raw ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {manifest.manifest_id}")


@data_app.command("ingest-sina-raw")
def ingest_sina_raw(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    symbol: Annotated[str, typer.Option()] = "159919",
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Capture an independent Sina raw series; it is never joined to another provider."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for Sina ingestion")
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    try:
        instrument = next(
            item
            for item in load_etf_universe(universe).instruments
            if item.symbol == symbol and item.exchange is Exchange.SZSE
        )
        calendar = ExchangeCalendarStore(calendar_root)
        calendar.require_completed_as_of(instrument.exchange, as_of_date)
        request = ETFHistoryRequest(
            instrument=instrument,
            start_date=max(start_date, instrument.effective_from),
            as_of_date=as_of_date,
            price_basis=PriceBasis.RAW,
        )
        manifest = persist_sina_etf_history(
            request,
            fetch_sina_etf_history(instrument.symbol, instrument.exchange),
            data_root,
        )
        bars = load_sina_provider_bars(manifest, data_root)
        coverage = calendar.coverage_report(
            instrument,
            PriceBasis.RAW,
            {bar.trading_date for bar in bars},
            request.start_date,
            request.as_of_date,
        )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        IncompleteSessionError,
        SinaProviderError,
        StopIteration,
        ValueError,
    ) as error:
        typer.echo(f"Sina ingestion failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"provider manifest: {manifest.manifest_id}")
    typer.echo(f"raw provider rows: {len(bars)}")
    typer.echo(f"coverage complete: {coverage.is_complete}")
    if not coverage.is_complete:
        typer.echo(
            "Sina provider series is retained but cannot pass the Issue 003 coverage gate", err=True
        )
        raise typer.Exit(code=1)


@data_app.command("coverage")
def show_coverage(
    universe: UniverseOption,
    start: RequiredDateOption,
    as_of: RequiredDateOption,
    data_root: DataRootOption = Path("data"),
    calendar_root: CalendarRootOption = Path("configs/calendars"),
) -> None:
    """Report local raw and qfq coverage without accessing the network."""
    start_date = _parse_cli_date(start, "start")
    as_of_date = _parse_cli_date(as_of, "as-of")
    calendar = ExchangeCalendarStore(calendar_root)
    try:
        reports = []
        for instrument in load_etf_universe(universe).instruments:
            if instrument.effective_from > as_of_date:
                continue
            bounded_start = max(start_date, instrument.effective_from)
            bounded_end = min(as_of_date, instrument.effective_to or as_of_date)
            calendar.require_completed_as_of(instrument.exchange, bounded_end)
            require_non_trading_evidence(instrument.documented_non_trading_events, data_root)
            for price_basis in (PriceBasis.RAW, PriceBasis.QFQ):
                reports.append(
                    calendar.coverage_report(
                        instrument,
                        price_basis,
                        normalized_dates(
                            data_root,
                            instrument.exchange.value,
                            instrument.symbol,
                            price_basis,
                        ),
                        bounded_start,
                        bounded_end,
                        documented_non_trading_events=instrument.documented_non_trading_events,
                    )
                )
    except (
        CalendarNotFoundError,
        CalendarSourceError,
        EvidenceArchiveError,
        IncompleteSessionError,
        ProvenanceError,
        ValueError,
    ) as error:
        typer.echo(f"coverage check failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    summaries = [
        {
            "instrument": f"{report.instrument.exchange.value}:{report.instrument.symbol}",
            "price_basis": report.price_basis.value,
            "present_session_count": len(report.present_dates),
            "coverage_complete": report.is_complete,
            "missing": [
                {"trading_date": record.trading_date.isoformat(), "kind": record.kind.value}
                for record in report.missing
            ],
            "documented_non_trading": [
                {
                    "trading_date": record.trading_date.isoformat(),
                    "reason": record.reason,
                    "evidence_sha256": record.evidence.sha256,
                }
                for record in report.documented_non_trading
            ],
        }
        for report in reports
    ]
    typer.echo(json.dumps(summaries, ensure_ascii=False, indent=2))
    if any(not report.is_complete for report in reports):
        raise typer.Exit(code=1)


@data_app.command("verify")
def verify_data(path: Path, data_root: DataRootOption = Path("data")) -> None:
    """Verify one normalized Parquet file against its immutable raw source and manifest."""
    try:
        manifest = verify_normalized_parquet(path, data_root)
    except (EvidenceArchiveError, ProvenanceError) as error:
        typer.echo(f"verification failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified manifest: {manifest.manifest_id}")


@calendar_app.command("validate")
def validate_calendar(
    exchange: Annotated[str, typer.Option(...)],
    year: Annotated[int, typer.Option(min=1990, max=2100)],
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    verify_sources: AllowNetworkOption = False,
    data_root: DataRootOption = Path("data"),
) -> None:
    """Validate one local annual calendar snapshot and display its session count."""
    from quant_stack.models import Exchange

    try:
        parsed_exchange = Exchange(exchange.upper())
    except ValueError as error:
        raise typer.BadParameter("exchange must be SSE or SZSE") from error
    if parsed_exchange is Exchange.TEST:
        raise typer.BadParameter("exchange must be SSE or SZSE")
    store = ExchangeCalendarStore(calendar_root)
    calendar = store.load_year(parsed_exchange, year)
    if verify_sources:
        store.require_source_archives(
            parsed_exchange,
            date(year, 1, 1),
            date(year, 12, 31),
            data_root,
        )
    typer.echo(f"{calendar.exchange.value} {calendar.year}: {len(calendar.sessions)} sessions")


@calendar_app.command("capture-sources")
def capture_calendar_sources(
    start_year: Annotated[int, typer.Option(min=1990, max=2100)],
    end_year: Annotated[int, typer.Option(min=1990, max=2100)],
    calendar_root: CalendarRootOption = Path("configs/calendars"),
    data_root: DataRootOption = Path("data"),
    allow_network: AllowNetworkOption = False,
) -> None:
    """Explicitly fetch and hash-check official notices into the local raw archive."""
    from quant_stack.models import Exchange

    if not allow_network:
        raise typer.BadParameter("--allow-network is required to capture calendar sources")
    if start_year > end_year:
        raise typer.BadParameter("start-year must not exceed end-year")
    store = ExchangeCalendarStore(calendar_root)
    try:
        paths = [
            path
            for exchange in (Exchange.SSE, Exchange.SZSE)
            for path in store.capture_source_archives(
                exchange,
                date(start_year, 1, 1),
                date(end_year, 12, 31),
                data_root,
            )
        ]
    except (CalendarNotFoundError, CalendarSourceError) as error:
        typer.echo(f"calendar source capture failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"verified calendar source archives: {len(paths)}")


def _m0_placeholder(capability: str) -> None:
    """State an unimplemented boundary without performing financial actions."""
    typer.echo(f"{capability} is not implemented in M0; no action was taken")


def _parse_cli_date(value: str, option_name: str) -> date:
    """Parse an explicit local trading-date boundary from the CLI."""
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise typer.BadParameter(f"{option_name} must use YYYY-MM-DD") from error


@backtest_app.command("run")
def run_backtest() -> None:
    """Reserve the future backtest interface."""
    _m0_placeholder("backtest")


@backtest_app.command("precommit-v2")
def backtest_precommit_v2(
    experiment: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    qualification: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    source_registry: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    output: Annotated[Path, typer.Option()] = Path(
        "configs/experiments/LOCKED_TEST_PRECOMMIT_V2.json"
    ),
    repository_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("."),
    data_root: DataRootOption = Path("data"),
) -> None:
    """Create the immutable Issue 009 V2 precommit before locked-result access."""
    try:
        precommit = create_locked_test_precommit(
            repository_root.resolve(),
            data_root.resolve(),
            experiment.resolve(),
            qualification.resolve(),
            source_registry.resolve(),
            output.resolve(),
        )
        persist_locked_test_precommit(precommit, output)
    except ValueError as error:
        typer.echo(f"locked-test precommit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"locked-test precommit: {output}")
    typer.echo(f"precommit id: {precommit.precommit_id}")


@backtest_app.command("locked-run-v2")
def backtest_locked_run_v2(
    precommit: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    qualification: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    repository_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("."),
    data_root: DataRootOption = Path("data"),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/issue009"),
) -> None:
    """Execute one verified precommit exactly once and retain every frozen run."""
    try:
        path, result = run_issue009_locked_test(
            precommit.resolve(),
            repository_root.resolve(),
            data_root.resolve(),
            qualification.resolve(),
            artifact_root,
        )
    except ValueError as error:
        typer.echo(f"locked test failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"locked result: {path}")
    typer.echo(f"outcome: {result['outcome']}")


@backtest_app.command("precommit-v3-recovery")
def backtest_precommit_v3_recovery(
    experiment: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    qualification: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    source_registry: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    output: Annotated[Path, typer.Option()] = Path(
        "configs/experiments/CONTROLLED_RECOVERY_AUTHORIZATION_V3.json"
    ),
    repository_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("."),
    data_root: DataRootOption = Path("data"),
) -> None:
    """Freeze the one explicitly authorized V3 controlled-recovery attempt."""
    try:
        precommit = create_locked_test_precommit(
            repository_root.resolve(),
            data_root.resolve(),
            experiment.resolve(),
            qualification.resolve(),
            source_registry.resolve(),
            output.resolve(),
        )
        if precommit.protocol_mode != "controlled_recovery_after_persistence_failure":
            raise ValueError("experiment is not the V3 controlled recovery")
        persist_locked_test_precommit(precommit, output)
    except ValueError as error:
        typer.echo(f"controlled recovery precommit failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"controlled recovery precommit: {output}")
    typer.echo(f"precommit id: {precommit.precommit_id}")


@backtest_app.command("locked-run-v3-recovery")
def backtest_locked_run_v3_recovery(
    precommit: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    qualification: Annotated[Path, typer.Option(..., exists=True, readable=True)],
    repository_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("."),
    data_root: DataRootOption = Path("data"),
) -> None:
    """Execute the two preregistered V3 builds once and require byte equality."""
    try:
        path, result = run_issue009_controlled_recovery(
            precommit.resolve(),
            repository_root.resolve(),
            data_root.resolve(),
            qualification.resolve(),
            repository_root.resolve() / "artifacts/issue009",
        )
    except (ValueError, OSError, TypeError) as error:
        typer.echo(f"controlled recovery failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"controlled recovery result: {path}")
    typer.echo(f"outcome: {result['outcome']}")


@backtest_app.command("recover-publication")
def recover_issue009_publication(
    run_directory: Annotated[Path, typer.Option(..., exists=True, file_okay=False)],
    expected_sha256: Annotated[str, typer.Option(...)],
    registry_root: Annotated[Path, typer.Option(...)],
) -> None:
    """Recover complete synthetic publications only; never recompute or replay old V2."""
    try:
        path, _ = recover_publication(run_directory, registry_root, expected_sha256=expected_sha256)
    except (ValueError, OSError) as error:
        typer.echo(f"publication recovery refused: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"synthetic publication recovered: {path}")


@backtest_app.command("recover-v3-publication")
def recover_issue009_v3_publication(
    precommit_id: Annotated[str, typer.Option(...)],
    repository_root: Annotated[Path, typer.Option(exists=True, readable=True)] = Path("."),
) -> None:
    """Publish complete V3 builds from an independently supplied receipt hash; never recompute."""
    authority = repository_root.resolve() / "artifacts/issue009"
    run_directory = authority / "locked_runs" / precommit_id
    try:
        path, _ = recover_controlled_publication(
            run_directory,
            authority / "experiment_registry",
        )
    except (ValueError, OSError) as error:
        typer.echo(f"V3 publication recovery refused: {error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"V3 publication recovered: {path}")


@signal_app.command("generate")
def generate_signal() -> None:
    """Reserve the future signal interface."""
    _m0_placeholder("signal generation")


@paper_app.command("reconcile")
def reconcile_paper(
    environment: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/environments/paper.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/paper"),
) -> None:
    """Replay the local strategy ledger and print its reconciled state."""
    broker = initialize_paper_account(environment, artifact_root)
    result = broker.reconcile()
    typer.echo(f"events: {result.event_count}")
    typer.echo(f"ledger head: {result.head_hash}")
    typer.echo(f"nav: {result.snapshot.net_asset_value}")


@paper_app.command("initialize")
def initialize_paper(
    environment: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/environments/paper.yaml"
    ),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/paper"),
) -> None:
    """Initialize the local CNY paper strategy and benchmark accounts."""
    broker = initialize_paper_account(environment, artifact_root)
    snapshot = broker.snapshot()
    typer.echo(f"paper account initialized: {broker.config.account_id}")
    typer.echo(f"cash: {snapshot.cash}")


@paper_app.command("run-daily")
def run_daily_paper(
    environment: Annotated[Path, typer.Option(exists=True, readable=True)] = Path(
        "configs/environments/paper.yaml"
    ),
    data_root: DataRootOption = Path("data"),
    artifact_root: Annotated[Path, typer.Option()] = Path("artifacts/paper"),
    as_of: Annotated[str | None, typer.Option()] = None,
    allow_network: AllowNetworkOption = False,
) -> None:
    """Refresh approved raw data and process one confirmed paper session locally."""
    if not allow_network:
        raise typer.BadParameter("--allow-network is required for paper data refresh")
    trading_date = (
        date.fromisoformat(as_of) if as_of else datetime.now(ZoneInfo("Asia/Shanghai")).date()
    )
    try:
        reports = run_paper_catchup(
            environment, data_root, artifact_root, trading_date, allow_network=True
        )
    except (PaperDailyError, PaperLedgerError, ValueError, OSError) as error:
        typer.echo(f"paper daily run failed: {error}", err=True)
        raise typer.Exit(code=1) from error
    for report in reports:
        typer.echo(f"paper report: {report}")


if __name__ == "__main__":
    app()
