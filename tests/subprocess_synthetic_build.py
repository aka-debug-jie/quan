"""Standalone fresh-process synthetic build used by the runner hardening test."""

from __future__ import annotations

import socket
import sys
from pathlib import Path

from test_research_runner_hardening import REPOSITORY, synthetic_panels, synthetic_precommit

from quant_stack import issue009_runner as runner


def _network_forbidden(*args: object, **kwargs: object) -> None:
    raise AssertionError("network forbidden in synthetic subprocess build")


def main() -> None:
    """Run all 16 real computation paths over synthetic in-memory prices."""
    socket.socket.connect = _network_forbidden  # type: ignore[method-assign]
    socket.socket.connect_ex = _network_forbidden  # type: ignore[method-assign]
    socket.create_connection = _network_forbidden  # type: ignore[assignment]
    destination = Path(sys.argv[1]).resolve()
    panels = synthetic_panels()
    runner._load_panels = lambda *_: panels  # type: ignore[assignment]
    precommit = synthetic_precommit()
    run_directory = runner._claim_locked_attempt(destination, precommit)
    runner._execute_issue009(
        precommit,
        REPOSITORY,
        destination / "no-real-data",
        destination,
        run_directory,
        evidence_scope="SYNTHETIC_ENGINEERING_ONLY",
    )


if __name__ == "__main__":
    main()
