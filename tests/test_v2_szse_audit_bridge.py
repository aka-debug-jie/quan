"""Data-only mailbox, private snapshots and frozen-runtime equivalence regressions."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest
from test_v2_szse_issuer_supplement import claim, pages
from test_v2_szse_monthly import fixture, hashed

from quant_stack_v2 import szse_issuer_supplement
from quant_stack_v2.szse_audit_bridge import (
    encoded,
    evaluate_request,
    publish,
    read_blob,
    snapshot_manifest,
    submit,
)
from quant_stack_v2.szse_verification import persist_report, verify_monthly


def pdf(text: str) -> bytes:
    content = b"BT /F1 8 Tf 20 780 Td <" + text.encode("utf-16-be").hex().encode() + b"> Tj ET"
    cmap = (
        b"/CIDInit /ProcSet findresource begin 12 dict begin begincmap "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) /Supplement 0 >> def "
        b"/CMapName /Test def /CMapType 2 def 1 begincodespacerange <0000> <FFFF> "
        b"endcodespacerange 1 beginbfrange <0000> <FFFF> <0000> endbfrange "
        b"endcmap CMapName currentdict /CMap defineresource pop end end"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 842] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light /Encoding /Identity-H "
        b"/DescendantFonts [5 0 R] /ToUnicode 7 0 R >>",
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 4 >> /DW 1000 >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Length " + str(len(cmap)).encode() + b" >>\nstream\n" + cmap + b"\nendstream",
    ]
    result = b"%PDF-1.4\n"
    offsets = [0]
    for number, obj in enumerate(objects, 1):
        offsets.append(len(result))
        result += str(number).encode() + b" 0 obj\n" + obj + b"\nendobj\n"
    xref = len(result)
    result += b"xref\n0 8\n0000000000 65535 f \n"
    result += b"".join(f"{n:010} 00000 n \n".encode() for n in offsets[1:])
    return (
        result
        + b"trailer << /Size 8 /Root 1 0 R >>\nstartxref\n"
        + str(xref).encode()
        + b"\n%%EOF\n"
    )


def setup(tmp_path: Path) -> tuple[Path, Path, Path, str]:
    home = tmp_path / "mailbox"
    (home / "requests").mkdir(parents=True)
    (home / "responses").mkdir()
    publish(home / "responses/status.json", encoded({"status": "READY"}))
    state = tmp_path / "private"
    state.mkdir()
    index, plan, audit, _ = fixture(tmp_path)
    source = persist_report(verify_monthly(index, plan, audit), tmp_path)
    raw = pdf(pages()[0])
    identity = sha256(raw).hexdigest()
    (home / "requests" / (identity + ".pdf")).write_bytes(raw)
    manifest = hashed(home / "requests", {"claims": [claim() | {"raw_sha256": identity}]})
    request = encoded({"operation": "verify", "manifest_sha256": manifest.stem})
    job = sha256(request).hexdigest()
    publish(home / "requests" / (job + ".request.json"), request)
    return home, state, source, job


def test_no_links_devices_or_path_escape(tmp_path: Path) -> None:
    name = "a" * 64 + ".pdf"
    outside = tmp_path / "outside"
    outside.write_bytes(b"sensitive")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / name).symlink_to(outside)
    with pytest.raises(OSError):
        read_blob(inbox, name, 100)
    (inbox / name).unlink()
    os.mkfifo(inbox / name)
    with pytest.raises(ValueError, match="type"):
        read_blob(inbox, name, 100)
    with pytest.raises(ValueError, match="filename"):
        read_blob(inbox, "../outside", 100)
    linked = tmp_path / "linked"
    linked.symlink_to(inbox, target_is_directory=True)
    with pytest.raises(OSError):
        read_blob(linked, name, 100)


def test_snapshot_is_independent_of_later_public_edits(tmp_path: Path) -> None:
    home, state, _, _ = setup(tmp_path)
    manifest = next(p for p in (home / "requests").glob("*.json") if ".request." not in p.name)
    copied = snapshot_manifest(home / "requests", state, manifest.stem)
    assert copied.read_bytes() == manifest.read_bytes()
    raw = next((home / "requests").glob("*.pdf"))
    before = (state / raw.name).read_bytes()
    raw.write_bytes(b"changed")
    assert (state / raw.name).read_bytes() == before
    with pytest.raises(ValueError, match="hash"):
        snapshot_manifest(home / "requests", state, manifest.stem)
    with pytest.raises(ValueError, match="size"):
        read_blob(home / "requests", raw.name, 1)


def test_request_cannot_select_commands_or_source_paths(tmp_path: Path) -> None:
    home, state, source, _ = setup(tmp_path)
    requests = [
        {"operation": "shell", "command": "id"},
        {"operation": "verify", "manifest_sha256": "a" * 64, "report": "/etc/shadow"},
    ]
    for request in requests:
        body = encoded(request)
        job = sha256(body).hexdigest()
        publish(home / "requests" / (job + ".request.json"), body)
        with pytest.raises(ValueError, match="unsupported"):
            evaluate_request(home, state, source, job)


def test_actual_pdf_matches_original_and_exports_only_summary(tmp_path: Path) -> None:
    home, state, source, job = setup(tmp_path)
    before = source.read_bytes()
    manifest = next(p for p in (home / "requests").glob("*.json") if ".request." not in p.name)
    direct = szse_issuer_supplement.supplement(source, manifest)
    summary = evaluate_request(home, state, source, job)
    assert summary["covered_sessions"] == direct["covered_sessions"] == 3
    assert summary["gap_gate"] == "PASS"
    assert summary["membership_gate"] == "BLOCKED_DATA"
    assert summary["residual_evidence_queue"]["rows"] == []
    assert not {"results", "residual", "claims", "notice_conflicts"} & summary.keys()
    assert source.read_bytes() == before
    assert not list((state / "jobs").iterdir())


def test_client_has_no_sudo_and_rejects_engine_drift(tmp_path: Path) -> None:
    home, _, _, _ = setup(tmp_path)
    descriptor = {
        "mailbox": str(home),
        "verifier_sha256": sha256(Path(szse_issuer_supplement.__file__).read_bytes()).hexdigest(),
    }
    info = tmp_path / "connection.json"
    info.write_bytes(encoded(descriptor))
    manifest = next(p for p in (home / "requests").glob("*.json") if ".request." not in p.name)
    job = submit(info, manifest)
    assert json.loads((home / "requests" / (job + ".request.json")).read_bytes()) == {
        "operation": "verify",
        "manifest_sha256": manifest.stem,
    }
    assert (home / "requests" / (job + ".request.json")).stat().st_mode & 0o777 == 0o640
    stop = submit(info, None)
    assert json.loads((home / "requests" / (stop + ".request.json")).read_bytes()) == {
        "operation": "stop"
    }
    descriptor["verifier_sha256"] = "0" * 64
    info.write_bytes(encoded(descriptor))
    with pytest.raises(ValueError, match="restart"):
        submit(info, manifest)


def test_immutable_publication(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    publish(path, b"first")
    publish(path, b"first")
    with pytest.raises(ValueError, match="collision"):
        publish(path, b"different")
    assert path.read_bytes() == b"first"


def test_stopped_bridge_rejects_submission(tmp_path: Path) -> None:
    home, _, _, _ = setup(tmp_path)
    publish(home / "responses/status.json", encoded({"status": "STOPPED"}), replace=True)
    info = tmp_path / "info.json"
    info.write_bytes(encoded({"mailbox": str(home)}))
    with pytest.raises(ValueError, match="not running"):
        submit(info, None)


def test_pdf_page_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import quant_stack_v2.szse_audit_bridge as bridge

    path = tmp_path / "test.pdf"
    path.write_bytes(pdf(pages()[0]))
    assert bridge._pdf_page_count(path) == 1

    def oversized(*args: object, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        kwargs["stdout"].write(b"Pages: 2049\n")
        return subprocess.CompletedProcess([], 0)

    monkeypatch.setattr(subprocess, "run", oversized)
    with pytest.raises(ValueError, match="page"):
        bridge._pdf_page_count(path)


def test_server_deadline_kills_job_and_child_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import quant_stack_v2.szse_audit_bridge as bridge

    home, state, source, job = setup(tmp_path)
    (home / "READY").touch()
    monkeypatch.setattr(bridge, "SOURCE", source)
    monkeypatch.setattr(bridge, "SOURCE_SHA256", sha256(source.read_bytes()).hexdigest())
    monkeypatch.setattr(bridge, "_probes", lambda _: True)
    child_pid = tmp_path / "child.pid"
    entry = tmp_path / "slow.py"
    entry.write_text(
        "import subprocess,sys,time\nfrom pathlib import Path\n"
        "p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])\n"
        + f"Path({str(child_pid)!r}).write_text(str(p.pid))\n"
        + "time.sleep(60)\n"
    )
    bridge.serve(home, state, entry, seconds=1)
    reply = json.loads((home / "responses" / (job + ".json")).read_bytes())
    assert reply["error_code"] == "JOB_FAILED_OR_TIMED_OUT"
    assert json.loads((home / "responses/status.json").read_bytes())["status"] == "STOPPED"
    proc = Path("/proc") / child_pid.read_text() / "stat"
    assert not proc.exists() or proc.read_text().split(") ", 1)[1].startswith("Z")


def test_frozen_host_runtime_has_closed_imports_and_identical_results(tmp_path: Path) -> None:
    repository = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "bridge_builder", repository / "scripts/v2/build_szse_audit_bridge.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    stage = tmp_path / "repo"
    for name in (*builder.MODULES, "quant_stack/snapshot.py"):
        target = stage / "src" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((repository / "src" / name).read_bytes())
    for name in ("szse_bridge_start_template.py", "szse_bridge_seal.py"):
        target = stage / "scripts/v2" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((repository / "scripts/v2" / name).read_bytes())
    bundle = builder.build(stage)
    package = json.loads((bundle / "package.json").read_bytes())
    assert bundle.name == sha256((bundle / "package.json").read_bytes()).hexdigest()
    for name, digest in package["files"].items():
        assert sha256((bundle / name).read_bytes()).hexdigest() == digest
    template = (
        (bundle / "start.py")
        .read_text()
        .replace(bundle.name, "__BUNDLE_" + "ID__")
        .replace(str(stage), "__REPO" + "SITORY__")
    )
    assert sha256(template.encode()).hexdigest() == package["launcher_template_sha256"]
    home, state, source, job = setup(tmp_path)
    expected = evaluate_request(home, state, source, job)
    code = (
        "import sys,json;from pathlib import Path;sys.path.insert(0,sys.argv[1]);"
        "from quant_stack_v2.szse_audit_bridge import evaluate_request;"
        "import quant_stack.snapshot as snap;"
        "assert 'site' not in sys.modules and 'pydantic' not in sys.modules;"
        "assert str(Path(snap.__file__)).startswith(sys.argv[1]);"
        "print(json.dumps(evaluate_request(Path(sys.argv[2]),Path(sys.argv[3]),Path(sys.argv[4]),sys.argv[5])))"
    )
    completed = subprocess.run(
        [
            "/usr/bin/python3",
            "-I",
            "-S",
            "-c",
            code,
            str(bundle),
            str(home),
            str(state),
            str(source),
            job,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(completed.stdout) == expected
    assert builder.build(stage) == bundle
