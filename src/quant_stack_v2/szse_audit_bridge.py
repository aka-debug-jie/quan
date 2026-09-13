"""Finite offline audit mailbox: data-only requests, frozen verifier, reduced replies."""

from __future__ import annotations

import argparse
import json
import os
import re
import resource
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from unittest.mock import patch

SOURCE_SHA256 = "b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873"
SOURCE = Path("/run/quant-szse-source") / (SOURCE_SHA256 + ".json")
HEX = re.compile(r"[0-9a-f]{64}")
MAX_MANIFEST = 1_048_576
MAX_BLOB = 30_000_000
MAX_TOTAL = 256_000_000
MAX_TEXT = 16_000_000
MAX_CLAIMS = 256
BLOB_FIELDS = {
    "raw_sha256": ".pdf",
    "identity_raw_sha256": ".pdf",
    "start_raw_sha256": ".pdf",
    "catalog_raw_sha256": ".catalog.json",
}


def encoded(value: object) -> bytes:
    """Encode one deterministic mailbox record."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _hash(value: str) -> str:
    if HEX.fullmatch(value) is None:
        raise ValueError("invalid content hash")
    return value


def read_blob(directory: Path, name: str, limit: int) -> bytes:
    """Read a bounded regular file through anchored descriptors without following links."""
    if re.fullmatch(r"[0-9a-f]{64}\.(?:request\.json|json|pdf|catalog\.json)", name) is None:
        raise ValueError("invalid input filename")
    root_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=root_fd)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                raise ValueError("invalid input size or type")
            body = stream.read(limit + 1)
            if len(body) > limit:
                raise ValueError("input grew beyond limit")
            return body
    finally:
        os.close(root_fd)


def publish(path: Path, body: bytes, *, replace: bool = False) -> None:
    """Atomically publish a caller-readable record into an already provisioned mailbox."""
    fd, temporary = tempfile.mkstemp(prefix=".bridge-", dir=path.parent)
    temp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o640)
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(temp, path)
        else:
            try:
                os.link(temp, path)
            except FileExistsError:
                if path.is_symlink() or path.read_bytes() != body:
                    raise ValueError("mailbox content collision") from None
    finally:
        temp.unlink(missing_ok=True)


def snapshot_manifest(inputs: Path, private: Path, identity: str) -> Path:
    """Copy only verified, hash-named evidence bytes into the private execution directory."""
    identity = _hash(identity)
    body = read_blob(inputs, identity + ".json", MAX_MANIFEST)
    if sha256(body).hexdigest() != identity:
        raise ValueError("manifest hash mismatch")
    payload = json.loads(body)
    claims = payload["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= MAX_CLAIMS:
        raise ValueError("claim limit exceeded")
    names: set[str] = set()
    for claim in claims:
        if not isinstance(claim, dict) or "raw_sha256" not in claim:
            raise ValueError("invalid claim")
        for field, suffix in BLOB_FIELDS.items():
            if field in claim:
                names.add(_hash(claim[field]) + suffix)
    if len(names) > 512:
        raise ValueError("file limit exceeded")
    total = len(body)
    for name in sorted(names):
        data = read_blob(inputs, name, MAX_BLOB)
        total += len(data)
        if total > MAX_TOTAL or sha256(data).hexdigest() != name[:64]:
            raise ValueError("evidence size or hash mismatch")
        (private / name).write_bytes(data)
    target = private / (identity + ".json")
    target.write_bytes(body)
    return target


def _child_limits() -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_TEXT, MAX_TEXT))


def _pdf_page_count(path: Path) -> int:
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        subprocess.run(
            ["/usr/bin/pdfinfo", str(path)],
            check=True,
            stdout=out,
            stderr=err,
            timeout=10,
            preexec_fn=_child_limits,
            env={"LC_ALL": "C", "PATH": "/usr/bin:/bin"},
        )
        out.seek(0)
        header = out.read(1_048_577)
    match = re.search(rb"(?m)^Pages:\s+(\d+)\s*$", header)
    if len(header) > 1_048_576 or match is None or not 1 <= int(match[1]) <= 2048:
        raise ValueError("PDF page or metadata limit exceeded")
    return int(match[1])


def evaluate_request(home: Path, state: Path, source: Path, request_id: str) -> dict[str, Any]:
    """Evaluate the fixed report with request data; return only approved summary fields."""
    from quant_stack_v2 import szse_issuer_supplement
    from quant_stack_v2.szse_evidence_queue import build_queue
    from quant_stack_v2.szse_verification import persist_report

    request_id = _hash(request_id)
    body = read_blob(home / "requests", request_id + ".request.json", 4096)
    if sha256(body).hexdigest() != request_id:
        raise ValueError("request hash mismatch")
    request = json.loads(body)
    if set(request) != {"operation", "manifest_sha256"} or request["operation"] != "verify":
        raise ValueError("unsupported request")
    jobs = state / "jobs"
    jobs.mkdir(exist_ok=True)
    original_run = subprocess.run

    def bounded_run(command: list[str], **options: Any) -> subprocess.CompletedProcess[bytes]:
        if command[:2] != ["/usr/bin/pdftotext", "-layout"] or command[-1] != "-":
            raise ValueError("unsupported subprocess")
        with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            completed = original_run(
                command,
                check=True,
                stdout=out,
                stderr=err,
                timeout=min(float(options.get("timeout", 30)), 30),
                preexec_fn=_child_limits,
            )
            out.seek(0)
            text = out.read(MAX_TEXT + 1)
            if len(text) > MAX_TEXT:
                raise ValueError("extracted text limit exceeded")
            return subprocess.CompletedProcess(command, completed.returncode, text, b"")

    with tempfile.TemporaryDirectory(prefix=request_id + "-", dir=jobs) as temporary:
        manifest = snapshot_manifest(home / "requests", Path(temporary), request["manifest_sha256"])
        if sum(_pdf_page_count(path) for path in Path(temporary).glob("*.pdf")) > 16_384:
            raise ValueError("total PDF page limit exceeded")
        with patch("subprocess.run", bounded_run):
            result = szse_issuer_supplement.supplement(source, manifest)
        report = persist_report(result, state / "reports")
        allow = (
            "scope",
            "source_report_sha256",
            "manifest_sha256",
            "supplement_source_sha256",
            "source_missing_sessions",
            "original_covered_sessions",
            "original_uncovered_sessions",
            "newly_explained_sessions",
            "newly_explained_by_symbol",
            "covered_sessions",
            "uncovered_sessions",
            "conflict_sessions",
            "interval_counts",
            "gap_gate",
            "membership_gate",
            "top_residual_tasks",
        )
        return {key: result[key] for key in allow} | {
            "report_sha256": report.stem,
            "residual_evidence_queue": build_queue(report),
        }


def _status(home: Path, status: str, completed: int, job: str | None = None) -> None:
    publish(
        home / "responses" / "status.json",
        encoded(
            {
                "status": status,
                "completed_jobs": completed,
                "active_job": job,
                "updated_at_utc": datetime.now(UTC).isoformat(),
                "uid": os.getuid(),
            }
        ),
        replace=True,
    )


def _stop_requested(home: Path) -> bool:
    body = encoded({"operation": "stop"})
    name = sha256(body).hexdigest() + ".request.json"
    try:
        return read_blob(home / "requests", name, 4096) == body
    except (OSError, ValueError):
        return False


def _probes(home: Path) -> bool:
    if os.getuid() in (0, 1000):
        return False
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        pass
    else:
        sock.close()
        return False
    try:
        fd = os.open("/srv/quant-v2/sealed_holdout", os.O_RDONLY | os.O_DIRECTORY)
    except OSError:
        pass
    else:
        os.close(fd)
        return False
    try:
        fd = os.open(
            home / "requests" / ".write-probe", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
    except OSError:
        return True
    else:
        os.close(fd)
        (home / "requests" / ".write-probe").unlink()
        return False


def serve(home: Path, state: Path, entry: Path, *, seconds: int = 14_400) -> None:
    """Run a finite single-job evaluator, enforcing process-group deadlines and stop requests."""
    deadline = time.monotonic() + seconds
    while not (home / "READY").is_file():
        if time.monotonic() >= deadline:
            return
        time.sleep(0.2)
    if not _probes(home) or sha256(SOURCE.read_bytes()).hexdigest() != SOURCE_SHA256:
        _status(home, "SECURITY_PREFLIGHT_FAILED", 0)
        return
    completed = 0
    _status(home, "READY", completed)
    while time.monotonic() < deadline and completed < 128:
        if _stop_requested(home):
            break
        names = sorted(p.name for p in (home / "requests").glob("*.request.json"))
        for name in names:
            if re.fullmatch(r"[0-9a-f]{64}\.request\.json", name) is None:
                continue
            job = name[:64]
            reply = home / "responses" / (job + ".json")
            if reply.exists() or _stop_requested(home):
                continue
            _status(home, "RUNNING", completed, job)
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    str(entry),
                    "evaluate",
                    "--home",
                    str(home),
                    "--job",
                    job,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            job_deadline = min(deadline, time.monotonic() + 300)
            while (
                process.poll() is None
                and time.monotonic() < job_deadline
                and not _stop_requested(home)
            ):
                time.sleep(0.2)
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not reply.exists():
                publish(
                    reply,
                    encoded(
                        {
                            "status": "ERROR",
                            "error_code": "JOB_FAILED_OR_TIMED_OUT",
                            "request_id": job,
                        }
                    ),
                )
            jobs = state / "jobs"
            if jobs.exists():
                for temporary in jobs.glob(job + "-*"):
                    shutil.rmtree(temporary)
            completed += 1
            _status(home, "READY", completed)
            if time.monotonic() >= deadline or completed >= 128:
                break
        time.sleep(1)
    _status(home, "STOPPED", completed)


def submit(info: Path, manifest: Path | None) -> str:
    """Submit data or stop to an already provisioned bridge without sudo."""
    descriptor = json.loads(info.read_bytes())
    home = Path(descriptor["mailbox"])
    health = json.loads((home / "responses/status.json").read_bytes())
    if health["status"] not in ("READY", "RUNNING"):
        raise ValueError("bridge is not running; start a new session")
    if manifest is None:
        request = {"operation": "stop"}
    else:
        from quant_stack_v2 import szse_issuer_supplement

        if (
            sha256(Path(szse_issuer_supplement.__file__).read_bytes()).hexdigest()
            != descriptor["verifier_sha256"]
        ):
            raise ValueError("frozen verifier differs; restart bridge before submitting new rules")
        with tempfile.TemporaryDirectory(prefix="quant-public-check-") as temporary:
            copied = snapshot_manifest(manifest.parent, Path(temporary), manifest.stem)
            szse_issuer_supplement.load_claims(copied)
            for source in sorted(Path(temporary).iterdir()):
                publish(home / "requests" / source.name, source.read_bytes())
        request = {"operation": "verify", "manifest_sha256": manifest.stem}
    body = encoded(request)
    identity = sha256(body).hexdigest()
    publish(home / "requests" / (identity + ".request.json"), body)
    return identity


def main() -> None:
    """Serve/evaluate in the fixed worker, or submit and inspect from the development account."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "mode", choices=("serve", "evaluate", "submit", "status", "stop", "publish-info")
    )
    parser.add_argument("--home", type=Path)
    parser.add_argument("--info", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--job")
    args = parser.parse_args()
    if args.mode == "publish-info":
        descriptor = json.loads(sys.stdin.buffer.read(16_384))
        args.info.parent.mkdir(parents=True, exist_ok=True)
        publish(args.info, encoded(descriptor), replace=True)
        return
    if args.mode in ("submit", "stop"):
        print(
            json.dumps(
                {"request_id": submit(args.info, args.manifest if args.mode == "submit" else None)}
            )
        )
        return
    if args.mode == "status":
        info = json.loads(args.info.read_bytes())
        responses = Path(info["mailbox"]) / "responses"
        name = _hash(args.job) + ".json" if args.job else "status.json"
        print((responses / name).read_text())
        return
    state = Path(os.environ["STATE_DIRECTORY"])
    if args.mode == "serve":
        serve(args.home, state, Path(sys.argv[0]))
        return
    try:
        summary = evaluate_request(args.home, state, SOURCE, args.job)
        response = {"status": "COMPLETED", "request_id": args.job, "summary": summary}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        response = {"status": "ERROR", "request_id": args.job, "error_code": "EVIDENCE_REJECTED"}
    publish(args.home / "responses" / (_hash(args.job) + ".json"), encoded(response))


if __name__ == "__main__":
    main()
