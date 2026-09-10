"""Hash-verified loading of one explicitly selected provider-native raw series."""

from __future__ import annotations

from pathlib import Path

from quant_stack.data.akshare_crosscheck import load_akshare_raw_crosscheck
from quant_stack.data.models import ProviderId, ProviderSeriesManifest
from quant_stack.data.sina_etf import load_sina_provider_bars
from quant_stack.data.sse_official import load_sse_provider_bars
from quant_stack.data.szse_official import load_szse_provider_bars
from quant_stack.models import DailyBar


def load_provider_series(
    manifest_id: str, data_root: Path
) -> tuple[ProviderSeriesManifest, list[DailyBar]]:
    """Load one provider series by immutable manifest ID without provider blending."""
    provider_path = data_root / "manifests" / "providers" / f"{manifest_id}.json"
    if provider_path.is_file():
        manifest = ProviderSeriesManifest.model_validate_json(
            provider_path.read_text(encoding="utf-8")
        )
        if manifest.provider is ProviderId.SINA:
            return manifest, load_sina_provider_bars(manifest, data_root)
        if manifest.provider is ProviderId.SSE_OFFICIAL:
            return manifest, load_sse_provider_bars(manifest, data_root)
        if manifest.provider is ProviderId.SZSE_OFFICIAL:
            return manifest, load_szse_provider_bars(manifest, data_root)
        raise ValueError(f"unsupported provider-native manifest: {manifest.provider.value}")
    ingest_path = data_root / "manifests" / f"{manifest_id}.json"
    if ingest_path.is_file():
        return load_akshare_raw_crosscheck(ingest_path, data_root)
    raise ValueError(f"provider manifest not found: {manifest_id}")
