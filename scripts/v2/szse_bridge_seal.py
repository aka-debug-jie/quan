"""Root-only closeout of one bridge response directory, preventing dynamic-UID reuse writes."""

from __future__ import annotations

import json
import os
import re
import stat
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def seal(home: Path) -> None:
    """Seal only this root-provisioned run's regular response files; never follow links."""
    if os.geteuid() != 0 or home.parent != Path("/srv/quant-v2/audit_bridge/runs"):
        raise ValueError("invalid closeout authority or target")
    if re.fullmatch(r"[a-f0-9]{16}", home.name) is None:
        raise ValueError("invalid run identity")
    metadata = home / "identity.json"
    info = metadata.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("untrusted run identity")
    identity = json.loads(metadata.read_bytes())
    fd = os.open(home / "responses", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for name in os.listdir(fd):
            try:
                item = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            except OSError:
                continue
            try:
                entry = os.fstat(item)
                if stat.S_ISREG(entry.st_mode) and entry.st_uid == identity["worker_uid"]:
                    os.fchown(item, 0, identity["caller_gid"])
                    os.fchmod(item, 0o440)
            finally:
                os.close(item)
        os.fchown(fd, 0, identity["caller_gid"])
        os.fchmod(fd, 0o550)
        handle, name = tempfile.mkstemp(prefix=".closed-", dir=home / "responses")
        temporary = Path(name)
        try:
            with os.fdopen(handle, "wb") as stream:
                os.fchown(stream.fileno(), 0, identity["caller_gid"])
                os.fchmod(stream.fileno(), 0o440)
                stream.write(
                    json.dumps(
                        {
                            "status": "STOPPED",
                            "updated_at_utc": datetime.now(UTC).isoformat(),
                        }
                    ).encode()
                    + b"\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, home / "responses/status.json")
        finally:
            temporary.unlink(missing_ok=True)
    finally:
        os.close(fd)


if __name__ == "__main__":
    try:
        seal(Path(sys.argv[1]))
    except Exception:
        raise SystemExit(2) from None
