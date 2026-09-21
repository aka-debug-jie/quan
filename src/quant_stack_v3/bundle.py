"""Safe, content-addressed capture and inspection of one RQAlpha bundle."""

from __future__ import annotations

import json
import os
import shutil
import tarfile
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from quant_stack.research_json import canonical_json
from quant_stack.snapshot import write_immutable

RQALPHA_BUNDLE_URL = "https://bundle.assets.ricequant.com/bundles_v4/rqbundle_202609.tar.bz2"
MAX_COMPRESSED_BYTES = 1_342_177_280
MAX_EXPANDED_BYTES = 20 * 1024**3
REQUIRED_FILES = (
    "dividends.h5",
    "ex_cum_factor.h5",
    "instruments.pk",
    "share_transformation.json",
    "split_factor.h5",
    "st_stock_days.h5",
    "stocks.h5",
    "suspended_days.h5",
    "trading_dates.npy",
)


class BundleError(ValueError):
    """Raised when external bundle bytes cannot satisfy the research contract."""


@dataclass(frozen=True)
class BundleReceipt:
    """Immutable provenance for one downloaded bundle object."""

    schema_version: int
    provider: str
    source_url: str
    final_url: str
    retrieved_at_utc: str
    sha256: str
    size_bytes: int
    etag: str | None
    last_modified: str | None
    content_type: str | None


@dataclass(frozen=True)
class BundleInspection:
    """Schema and coverage facts read from an extracted RQAlpha bundle."""

    schema_version: int
    bundle_sha256: str
    tree_sha256: str
    first_session: str
    last_session: str
    calendar_sessions: int
    stock_symbols: int
    stock_fields: tuple[str, ...]
    dividend_symbols: int
    split_symbols: int
    factor_symbols: int
    suspended_symbols: int
    st_symbols: int
    required_files: tuple[str, ...]
    status: str


def capture_bundle(
    data_root: Path,
    *,
    allow_network: bool,
    url: str = RQALPHA_BUNDLE_URL,
    attempts: int = 3,
) -> tuple[Path, Path, BundleReceipt]:
    """Download one exact HTTPS object with bounded retries and publish by SHA-256."""
    if not allow_network:
        raise BundleError("--allow-network is required")
    if url != RQALPHA_BUNDLE_URL or not url.startswith("https://"):
        raise BundleError("only the frozen HTTPS RQAlpha bundle URL is allowed")
    if not 1 <= attempts <= 3:
        raise BundleError("bundle attempts must be between one and three")
    staging = data_root / "staging"
    staging.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="rqbundle-", suffix=".partial", dir=staging
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    response_headers: dict[str, str] = {}
    final_url = url
    try:
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                digest, size, response_headers, final_url = _download_once(url, temporary)
                break
            except (HTTPError, URLError, TimeoutError, OSError, BundleError) as error:
                last_error = error
                temporary.unlink(missing_ok=True)
                if attempt + 1 == attempts:
                    raise BundleError(
                        f"bundle download failed after {attempts} attempts"
                    ) from error
                time.sleep(2**attempt)
        else:  # pragma: no cover - loop always exits by break or raise
            raise BundleError("bundle download failed") from last_error
        raw = data_root / "raw" / digest / "rqbundle_202609.tar.bz2"
        raw.parent.mkdir(parents=True, exist_ok=True)
        if raw.exists():
            if _file_sha256(raw) != digest or raw.stat().st_size != size:
                raise BundleError("existing content-addressed bundle is corrupt")
        else:
            temporary.replace(raw)
            _fsync_file(raw)
        receipt = BundleReceipt(
            schema_version=1,
            provider="rqalpha_monthly_bundle",
            source_url=url,
            final_url=final_url,
            retrieved_at_utc=datetime.now(UTC).isoformat(),
            sha256=digest,
            size_bytes=size,
            etag=response_headers.get("etag"),
            last_modified=response_headers.get("last-modified"),
            content_type=response_headers.get("content-type"),
        )
        encoded = canonical_json(asdict(receipt)) + b"\n"
        receipt_path = data_root / "receipts" / f"{sha256(encoded).hexdigest()}.json"
        write_immutable(receipt_path, encoded)
        return raw, receipt_path, receipt
    finally:
        temporary.unlink(missing_ok=True)


def extract_and_inspect(
    archive: Path,
    data_root: Path,
    *,
    expected_sha256: str,
) -> tuple[Path, Path, BundleInspection]:
    """Safely extract verified bytes and publish a deterministic schema inspection."""
    if _file_sha256(archive) != expected_sha256:
        raise BundleError("bundle SHA-256 does not match the requested snapshot")
    extraction_root = data_root / "extracted" / expected_sha256
    extraction_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".extract-", dir=extraction_root))
    try:
        with tarfile.open(archive, "r:bz2") as handle:
            members = handle.getmembers()
            _validate_members(members)
            handle.extractall(temporary, members=members, filter="data")
        bundle_root = _find_bundle_root(temporary)
        missing = [name for name in REQUIRED_FILES if not (bundle_root / name).is_file()]
        if missing:
            raise BundleError(f"bundle lacks required files: {', '.join(missing)}")
        tree_digest = tree_sha256(bundle_root)
        destination = extraction_root / "trees" / tree_digest
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if tree_sha256(destination) != tree_digest:
                raise BundleError("existing extraction tree differs from its identity")
        else:
            bundle_root.replace(destination)
        inspection = inspect_bundle(destination, expected_sha256, tree_digest)
        encoded = canonical_json(asdict(inspection)) + b"\n"
        report = data_root / "inspections" / inspection.tree_sha256 / "inspection.json"
        write_immutable(report, encoded)
        return destination, report, inspection
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def inspect_bundle(
    root: Path, bundle_sha256: str, tree_digest: str | None = None
) -> BundleInspection:
    """Read only bounded metadata from a previously extracted bundle."""
    import h5py  # type: ignore[import-not-found]

    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise BundleError(f"bundle lacks required files: {', '.join(missing)}")
    calendar = np.load(root / "trading_dates.npy", allow_pickle=False)
    if calendar.ndim != 1 or len(calendar) < 2:
        raise BundleError("trading calendar is empty or malformed")
    sessions = tuple(str(int(item))[:8] for item in calendar)
    if sessions != tuple(sorted(set(sessions))):
        raise BundleError("trading calendar is not unique and ascending")
    with h5py.File(root / "stocks.h5", "r") as stocks:
        symbols = tuple(sorted(stocks.keys()))
        if not symbols:
            raise BundleError("stocks.h5 is empty")
        fields = tuple(sorted(stocks[symbols[0]].dtype.fields or {}))
        required_fields = {
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "total_turnover",
            "limit_up",
            "limit_down",
        }
        if not required_fields.issubset(fields):
            raise BundleError("stock bars lack required raw execution fields")
    inspection = BundleInspection(
        schema_version=1,
        bundle_sha256=bundle_sha256,
        tree_sha256=tree_digest or tree_sha256(root),
        first_session=_calendar_date(sessions[0]),
        last_session=_calendar_date(sessions[-1]),
        calendar_sessions=len(sessions),
        stock_symbols=len(symbols),
        stock_fields=fields,
        dividend_symbols=_h5_keys(root / "dividends.h5"),
        split_symbols=_h5_keys(root / "split_factor.h5"),
        factor_symbols=_h5_keys(root / "ex_cum_factor.h5"),
        suspended_symbols=_h5_keys(root / "suspended_days.h5"),
        st_symbols=_h5_keys(root / "st_stock_days.h5"),
        required_files=REQUIRED_FILES,
        status="SCHEMA_READY_FOR_HISTORICAL_RESEARCH",
    )
    return inspection


def tree_sha256(root: Path) -> str:
    """Return a stable digest over relative names and file bytes."""
    digest = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(_file_sha256(path).encode() + b"\n")
    return digest.hexdigest()


def _download_once(url: str, destination: Path) -> tuple[str, int, dict[str, str], str]:
    request = Request(url, headers={"User-Agent": "quant-stack-cn-historical-v3/1.0"})
    with urlopen(request, timeout=60) as response, destination.open("wb") as output:
        length_text = response.headers.get("Content-Length")
        if length_text and int(length_text) > MAX_COMPRESSED_BYTES:
            raise BundleError("compressed bundle exceeds the frozen size cap")
        digest = sha256()
        size = _copy_limited(response, output, digest)
        output.flush()
        os.fsync(output.fileno())
        headers = {key.lower(): value for key, value in response.headers.items()}
        return digest.hexdigest(), size, headers, response.geturl()


def _copy_limited(source: BinaryIO, destination: BinaryIO, digest: object) -> int:
    size = 0
    while chunk := source.read(1024 * 1024):
        size += len(chunk)
        if size > MAX_COMPRESSED_BYTES:
            raise BundleError("compressed bundle exceeds the frozen size cap")
        destination.write(chunk)
        digest.update(chunk)  # type: ignore[attr-defined]
    if size == 0:
        raise BundleError("downloaded bundle is empty")
    return size


def _validate_members(members: list[tarfile.TarInfo]) -> None:
    if not members:
        raise BundleError("bundle archive is empty")
    expanded = 0
    for member in members:
        path = PurePosixPath(member.name)
        expanded += max(member.size, 0)
        if (
            path.is_absolute()
            or ".." in path.parts
            or member.issym()
            or member.islnk()
            or member.isdev()
            or not (member.isdir() or member.isfile())
        ):
            raise BundleError(f"unsafe archive member: {member.name}")
    if expanded > MAX_EXPANDED_BYTES:
        raise BundleError("expanded bundle exceeds the frozen size cap")


def _find_bundle_root(root: Path) -> Path:
    candidates = [path for path in root.rglob("stocks.h5") if path.is_file()]
    if len(candidates) != 1:
        raise BundleError("bundle must contain exactly one stocks.h5")
    return candidates[0].parent


def _h5_keys(path: Path) -> int:
    import h5py

    with h5py.File(path, "r") as handle:
        return len(handle.keys())


def _calendar_date(value: str) -> str:
    if len(value) != 8 or not value.isdigit():
        raise BundleError("calendar value is not YYYYMMDD")
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def load_receipt(path: Path) -> BundleReceipt:
    """Load a captured receipt without touching the network."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    return BundleReceipt(**payload)
