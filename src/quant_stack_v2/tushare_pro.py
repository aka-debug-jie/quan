"""Explicit-network, content-addressed Tushare Pro raw-response capture."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from urllib.request import Request, urlopen

from quant_stack.snapshot import write_immutable

TUSHARE_ENDPOINT = "https://api.tushare.pro"
ADAPTER_VERSION = "1.0.0"
ALLOWED_APIS = frozenset({"daily", "suspend_d", "stock_basic", "index_weight"})


@dataclass(frozen=True)
class TushareResponseManifest:
    """Provenance for one unmodified Tushare API response."""

    api_name: str
    parameters: dict[str, str]
    raw_sha256: str
    adapter_version: str
    status: str

    @property
    def identity_sha256(self) -> str:
        """Return a stable request-and-content identity."""
        return sha256(
            json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


Fetcher = Callable[[bytes], tuple[bytes, dict[str, str]]]


def capture_tushare_response(
    data_root: Path,
    *,
    api_name: str,
    parameters: dict[str, str],
    allow_network: bool,
    token: str | None = None,
    fetcher: Fetcher | None = None,
) -> tuple[Path, TushareResponseManifest]:
    """Capture one supported API response without storing the credential."""
    if not allow_network:
        raise ValueError("--allow-network is required for Tushare capture")
    if api_name not in ALLOWED_APIS:
        raise ValueError("Tushare API is not declared by the V2 Foundation Gate")
    resolved_token = token or os.environ.get("TUSHARE_TOKEN")
    if not resolved_token:
        raise ValueError("TUSHARE_TOKEN is required at runtime")
    request_body = json.dumps(
        {"api_name": api_name, "token": resolved_token, "params": parameters},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    raw, metadata = (fetcher or _fetch)(request_body)
    _validate_response(raw)
    digest = sha256(raw).hexdigest()
    manifest = TushareResponseManifest(
        api_name=api_name,
        parameters=dict(sorted(parameters.items())),
        raw_sha256=digest,
        adapter_version=ADAPTER_VERSION,
        status="CAPTURED",
    )
    base = data_root / "tushare_pro" / digest
    write_immutable(base / "response.json", raw)
    receipt = {
        "schema_version": 1,
        "manifest_sha256": manifest.identity_sha256,
        "retrieved_at_utc": datetime.now(UTC).isoformat(),
        "endpoint": TUSHARE_ENDPOINT,
        "http_metadata": metadata,
    }
    receipt_bytes = json.dumps(receipt, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    write_immutable(base / "receipts" / f"{sha256(receipt_bytes).hexdigest()}.json", receipt_bytes)
    path = data_root / "tushare_pro_manifests" / manifest.identity_sha256 / "manifest.json"
    write_immutable(
        path, json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":")).encode() + b"\n"
    )
    return path, manifest


def _validate_response(raw: bytes) -> None:
    try:
        payload = json.loads(raw)
    except UnicodeDecodeError as error:
        raise ValueError("Tushare response is not UTF-8 JSON") from error
    except json.JSONDecodeError as error:
        raise ValueError("Tushare response is not JSON") from error
    if not isinstance(payload, dict) or "code" not in payload or "data" not in payload:
        raise ValueError("Tushare response lacks code or data")
    if payload["code"] != 0:
        raise ValueError("Tushare response returned provider error")


def _fetch(body: bytes) -> tuple[bytes, dict[str, str]]:
    request = Request(
        TUSHARE_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "quant-stack-v2/1.0"},
    )
    with urlopen(request, timeout=30) as response:
        return response.read(), {key.lower(): value for key, value in response.headers.items()}
