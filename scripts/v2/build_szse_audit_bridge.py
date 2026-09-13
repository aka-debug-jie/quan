"""Build a content-addressed, standard-library-only copy of the reviewed audit code."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path

MODULES = (
    "quant_stack_v2/szse_monthly.py",
    "quant_stack_v2/szse_verification.py",
    "quant_stack_v2/szse_issuer_supplement.py",
    "quant_stack_v2/szse_evidence_queue.py",
    "quant_stack_v2/szse_audit_bridge.py",
)


def build(repository: Path) -> Path:
    """Freeze the audit modules and exact immutable-write functions without site dependencies."""
    files = {name: (repository / "src" / name).read_bytes() for name in MODULES}
    files["quant_stack/__init__.py"] = b""
    files["quant_stack_v2/__init__.py"] = b""
    snapshot = (repository / "src/quant_stack/snapshot.py").read_text()
    functions = [
        ast.get_source_segment(snapshot, node)
        for node in ast.parse(snapshot).body
        if isinstance(node, ast.FunctionDef)
        and node.name in ("write_immutable", "_fsync_directory")
    ]
    if len(functions) != 2 or any(f is None for f in functions):
        raise ValueError("immutable writer contract changed")
    files["quant_stack/snapshot.py"] = (
        "from __future__ import annotations\nimport os\nimport tempfile\n"
        "from pathlib import Path\n\n" + "\n\n".join(f for f in functions if f is not None) + "\n"
    ).encode()
    files["entry.py"] = (
        b"import sys\nfrom pathlib import Path\n"
        b"sys.path.insert(0, str(Path(__file__).resolve().parent))\n"
        b"from quant_stack_v2.szse_audit_bridge import main\n"
        b"try:\n    main()\nexcept Exception:\n    raise SystemExit(2) from None\n"
    )
    files["seal_responses.py"] = (repository / "scripts/v2/szse_bridge_seal.py").read_bytes()
    template = (repository / "scripts/v2/szse_bridge_start_template.py").read_text()
    package = {
        "schema_version": 1,
        "files": {name: sha256(body).hexdigest() for name, body in files.items()},
        "upstream_snapshot_sha256": sha256(snapshot.encode()).hexdigest(),
        "verifier_sha256": sha256(files["quant_stack_v2/szse_issuer_supplement.py"]).hexdigest(),
        "launcher_template_sha256": sha256(template.encode()).hexdigest(),
    }
    body = json.dumps(package, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    identity = sha256(body).hexdigest()
    target = repository / "artifacts/v2/szse_audit_bridge_bundles" / identity
    launcher = template.replace("__BUNDLE_ID__", identity).replace(
        "__REPOSITORY__", str(repository)
    )
    files["package.json"] = body
    files["start.py"] = launcher.encode()
    for name, data in files.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if path.read_bytes() != data:
                raise ValueError("existing bundle differs")
        else:
            with path.open("xb") as stream:
                stream.write(data)
    return target


if __name__ == "__main__":
    print(build(Path(__file__).resolve().parents[2]))
