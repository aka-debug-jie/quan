"""User-run, one-time bootstrap for a frozen, four-hour offline audit service."""

from __future__ import annotations

import json
import os
import pwd
import secrets
import stat
import subprocess
import time
from hashlib import sha256
from pathlib import Path

BUNDLE_ID = "__BUNDLE_ID__"
REPOSITORY = Path("__REPOSITORY__")
BASE = Path("/srv/quant-v2/audit_bridge")
SOURCE_ID = "b31fc67f7707cb728f1606b45ce909e0d1907991e62075be050b95a3ad186873"
ORIGINAL = Path(
    "/srv/quant-v2/sealed_holdout/artifacts/v2/free_suspension/szse_monthly_verification"
) / (SOURCE_ID + ".json")
EXPECTED_FILES = {
    "quant_stack_v2/szse_monthly.py",
    "quant_stack_v2/szse_verification.py",
    "quant_stack_v2/szse_issuer_supplement.py",
    "quant_stack_v2/szse_evidence_queue.py",
    "quant_stack_v2/szse_audit_bridge.py",
    "quant_stack_v2/__init__.py",
    "quant_stack/__init__.py",
    "quant_stack/snapshot.py",
    "entry.py",
    "seal_responses.py",
}


def trusted_directory(path: Path, mode: int = 0o755) -> None:
    """Create only new bridge directories, refusing writable or linked existing parents."""
    path.mkdir(mode=mode, exist_ok=True)
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
        raise ValueError("bridge directory is not root controlled")


def start() -> None:
    """Provision one isolated service without modifying sudoers or source permissions."""
    if os.geteuid() != 0:
        raise ValueError("run this reviewed launcher once with sudo")
    os.umask(0o022)
    caller = pwd.getpwnam("hgdl1012")
    if os.environ.get("SUDO_USER") not in (None, caller.pw_name):
        raise ValueError("unexpected caller")
    bundle = Path(__file__).resolve().parent
    body = (bundle / "package.json").read_bytes()
    if sha256(body).hexdigest() != BUNDLE_ID:
        raise ValueError("bundle manifest hash mismatch")
    package = json.loads(body)
    template = (
        Path(__file__)
        .read_text()
        .replace(BUNDLE_ID, "__BUNDLE_" + "ID__")
        .replace(str(REPOSITORY), "__REPO" + "SITORY__")
    )
    if sha256(template.encode()).hexdigest() != package["launcher_template_sha256"]:
        raise ValueError("launcher differs from reviewed template")
    if set(package["files"]) != EXPECTED_FILES:
        raise ValueError("unexpected executable import closure")
    files = {}
    for name, digest in package["files"].items():
        content = (bundle / name).read_bytes()
        if sha256(content).hexdigest() != digest:
            raise ValueError("frozen file hash mismatch")
        files[name] = content
    source = ORIGINAL.read_bytes()
    if sha256(source).hexdigest() != SOURCE_ID:
        raise ValueError("fixed source report hash mismatch")
    for path in (Path("/srv"), Path("/srv/quant-v2"), BASE, BASE / "code", BASE / "runs"):
        trusted_directory(path)
    trusted_directory(BASE / "sealed", 0o700)
    code = BASE / "code" / BUNDLE_ID
    trusted_directory(code)
    for name, content in files.items():
        target = code / name
        if target.parent != code:
            trusted_directory(target.parent)
        if target.exists():
            info = target.lstat()
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
                raise ValueError("untrusted frozen code file")
            if target.read_bytes() != content:
                raise ValueError("frozen code changed")
        else:
            with target.open("xb") as stream:
                stream.write(content)
            target.chmod(0o444)
    session = secrets.token_hex(8)
    home = BASE / "runs" / session
    home.mkdir(mode=0o755)
    (home / "requests").mkdir(mode=0o700)
    (home / "responses").mkdir(mode=0o700)
    secret = BASE / "sealed" / session
    secret.mkdir(mode=0o700)
    copy = secret / (SOURCE_ID + ".json")
    copy.write_bytes(source)
    copy.chmod(0o444)
    unit = "q-szse-" + session
    properties = {
        "DynamicUser": "yes",
        "User": unit,
        "StateDirectory": unit,
        "StateDirectoryMode": "0700",
        "NoNewPrivileges": "yes",
        "ProtectSystem": "strict",
        "ProtectHome": "yes",
        "PrivateNetwork": "yes",
        "PrivateTmp": "yes",
        "PrivateDevices": "yes",
        "ProtectProc": "invisible",
        "RestrictAddressFamilies": "AF_UNIX",
        "CapabilityBoundingSet": "",
        "InaccessiblePaths": "/srv/quant-v2/sealed_holdout",
        "BindReadOnlyPaths": str(copy) + ":/run/quant-szse-source/" + SOURCE_ID + ".json",
        "ReadOnlyPaths": str(home / "requests"),
        "ReadWritePaths": str(home / "responses"),
        "RuntimeMaxSec": "4h",
        "TimeoutStopSec": "10s",
        "KillMode": "control-group",
        "MemoryMax": "1G",
        "CPUQuota": "200%",
        "TasksMax": "16",
        "LimitNOFILE": "128",
        "LimitFSIZE": "64M",
        "UMask": "0077",
        "StandardOutput": "null",
        "StandardError": "null",
        "ExecStopPost": "+/usr/bin/python3 -I -S "
        + str(code / "seal_responses.py")
        + " "
        + str(home),
    }
    command = ["/usr/bin/systemd-run", "--quiet", "--collect", "--unit=" + unit]
    command += ["--property=" + key + "=" + value for key, value in properties.items()]
    command += [
        "/usr/bin/python3",
        "-I",
        "-S",
        str(code / "entry.py"),
        "serve",
        "--home",
        str(home),
    ]
    started = False
    try:
        subprocess.run(command, check=True)
        started = True
        for _ in range(100):
            try:
                worker = pwd.getpwnam(unit)
                break
            except KeyError:
                time.sleep(0.1)
        else:
            raise ValueError("dynamic worker identity not available")
        os.chown(home / "requests", caller.pw_uid, worker.pw_gid)
        (home / "requests").chmod(0o2750)
        os.chown(home / "responses", worker.pw_uid, caller.pw_gid)
        (home / "responses").chmod(0o2750)
        identity = {"worker_uid": worker.pw_uid, "caller_gid": caller.pw_gid}
        (home / "identity.json").write_text(json.dumps(identity))
        (home / "identity.json").chmod(0o444)
        (home / "READY").write_bytes(b"ready\n")
        (home / "READY").chmod(0o444)
        for _ in range(100):
            status = home / "responses/status.json"
            if status.exists():
                value = json.loads(status.read_bytes())
                if value["status"] != "READY" or value["uid"] != worker.pw_uid:
                    raise ValueError("worker security preflight failed")
                break
            time.sleep(0.1)
        else:
            raise ValueError("worker did not become ready")
        shown = subprocess.check_output(
            [
                "/usr/bin/systemctl",
                "show",
                unit + ".service",
                "--no-pager",
                "-p",
                "DynamicUser",
                "-p",
                "User",
                "-p",
                "NoNewPrivileges",
                "-p",
                "ProtectSystem",
                "-p",
                "ProtectHome",
                "-p",
                "PrivateNetwork",
                "-p",
                "KillMode",
                "-p",
                "RuntimeMaxUSec",
                "-p",
                "InaccessiblePaths",
                *[
                    argument
                    for prop in (
                        "ReadOnlyPaths",
                        "ReadWritePaths",
                        "RestrictAddressFamilies",
                        "MemoryMax",
                        "TasksMax",
                        "LimitFSIZE",
                        "LimitNOFILE",
                        "CapabilityBoundingSet",
                        "StateDirectoryMode",
                    )
                    for argument in ("-p", prop)
                ],
            ],
            text=True,
        )
        settings = dict(line.split("=", 1) for line in shown.splitlines() if "=" in line)
        for key, expected in {
            "DynamicUser": "yes",
            "User": unit,
            "NoNewPrivileges": "yes",
            "ProtectSystem": "strict",
            "ProtectHome": "yes",
            "PrivateNetwork": "yes",
            "KillMode": "control-group",
            "RuntimeMaxUSec": "4h",
            "MemoryMax": "1073741824",
            "TasksMax": "16",
            "LimitFSIZE": "67108864",
            "LimitNOFILE": "128",
            "CapabilityBoundingSet": "",
            "StateDirectoryMode": "0700",
        }.items():
            if settings.get(key) != expected:
                raise ValueError("service isolation property mismatch: " + key)
        if "/srv/quant-v2/sealed_holdout" not in settings.get("InaccessiblePaths", ""):
            raise ValueError("raw sealed directory was not hidden")
        if str(home / "requests") not in settings.get("ReadOnlyPaths", "").split():
            raise ValueError("request filesystem is not read-only")
        if settings.get("ReadWritePaths", "").split() != [str(home / "responses")]:
            raise ValueError("unexpected public write paths")
        if settings.get("RestrictAddressFamilies", "").split() != ["AF_UNIX"]:
            raise ValueError("unexpected network address families")
        descriptor = {
            "protocol_version": 1,
            "mailbox": str(home),
            "unit": unit + ".service",
            "bundle_sha256": BUNDLE_ID,
            "verifier_sha256": package["verifier_sha256"],
            "worker_uid": worker.pw_uid,
            "private_reports": "/var/lib/private/" + unit + "/reports",
            "limits": {"lifetime_seconds": 14_400, "job_seconds": 300, "max_jobs": 128},
        }
        destination = REPOSITORY / "artifacts/v2/szse_audit_bridge/current.json"
        subprocess.run(
            [
                "/usr/sbin/runuser",
                "-u",
                caller.pw_name,
                "--",
                "/usr/bin/python3",
                "-I",
                "-S",
                str(code / "entry.py"),
                "publish-info",
                "--info",
                str(destination),
            ],
            input=json.dumps(descriptor).encode(),
            check=True,
        )
        print(json.dumps({"status": "READY", "connection_file": str(destination), "unit": unit}))
    except Exception:
        if started:
            subprocess.run(["/usr/bin/systemctl", "stop", unit + ".service"], check=False)
        raise
    finally:
        copy.unlink(missing_ok=True)
        secret.rmdir()


if __name__ == "__main__":
    try:
        start()
    except Exception as error:
        raise SystemExit("Bridge startup failed: " + str(error)) from None
