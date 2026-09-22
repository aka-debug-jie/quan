"""Manual command line entry points for Quant Console V1."""

from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from quant_console.api import create_app
from quant_console.config import load_config
from quant_console.demo import publish_demo
from quant_console.observer import observe
from quant_console.snapshot import build_snapshot


def main() -> None:
    """Run one explicit console maintenance or local serving action."""
    parser = argparse.ArgumentParser(prog="quant-console")
    sub = parser.add_subparsers(dest="command", required=True)
    index = sub.add_parser("index")
    index.add_argument("--config", type=Path, required=True)
    index.add_argument("--runtime", type=Path, required=True)
    observation = sub.add_parser("observe-system")
    observation.add_argument("--output", type=Path, required=True)
    demo = sub.add_parser("demo")
    demo.add_argument("--runtime", type=Path, required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--runtime", type=Path, required=True)
    serve.add_argument("--config", type=Path)
    serve.add_argument("--static", type=Path)
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    if args.command == "index":
        print(
            build_snapshot(
                load_config(args.config), args.runtime, args.runtime / "system-observation.json"
            )
        )
    elif args.command == "observe-system":
        print(observe(args.output))
    elif args.command == "demo":
        print(publish_demo(args.runtime))
    else:
        app = create_app(args.runtime, args.config, args.static)
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")


if __name__ == "__main__":
    main()
