"""Internal child-process entrypoint for one V3 controlled-recovery build."""

from __future__ import annotations

import argparse
from pathlib import Path

from quant_stack.issue009_runner import run_issue009_controlled_build


def main() -> None:
    """Parse fixed orchestration paths and execute one non-publishing child build."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--precommit", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--qualification", type=Path, required=True)
    parser.add_argument("--build-directory", type=Path, required=True)
    parser.add_argument("--build-name", choices=("build_a", "build_b"), required=True)
    arguments = parser.parse_args()
    run_issue009_controlled_build(
        arguments.precommit.resolve(),
        arguments.repository_root.resolve(),
        arguments.data_root.resolve(),
        arguments.qualification.resolve(),
        arguments.build_directory.resolve(),
        arguments.build_name,
    )


if __name__ == "__main__":
    main()
