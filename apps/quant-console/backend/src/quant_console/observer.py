"""Fixed-target, read-only observation of the existing prospective deployment."""

from __future__ import annotations

import json
import subprocess
import tempfile
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path


def observe(output: Path) -> Path:
    """Record sanitized systemd state for two fixed units; never alter either unit."""
    timer = _show(
        "quant-prospective.timer",
        ("ActiveState", "SubState", "UnitFileState", "LastTriggerUSec", "NextElapseUSecRealtime"),
    )
    service = _show(
        "quant-prospective.service",
        ("ActiveState", "SubState", "Result", "ExecMainStatus"),
    )
    user_units = Path.home() / ".config" / "systemd" / "user"
    unit_hashes = {
        name: _sha256(user_units / name)
        for name in ("quant-prospective.service", "quant-prospective.timer")
        if (user_units / name).is_file()
    }
    value = {
        "schema_version": 1,
        "status": "OBSERVED_READ_ONLY",
        "observed_at": datetime.now(UTC).isoformat(),
        "timer": timer,
        "service": service,
        "unit_hashes": unit_hashes,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=output.parent, delete=False, encoding="utf-8"
    ) as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True)
        temporary = Path(handle.name)
    temporary.replace(output)
    return output


def _show(unit: str, fields: tuple[str, ...]) -> dict[str, str]:
    command = ["systemctl", "--user", "show", unit]
    for field in fields:
        command.extend(("-p", field))
    result = subprocess.run(command, check=True, capture_output=True, text=True, timeout=10)
    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in fields:
            values[key] = value
    return values


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()
