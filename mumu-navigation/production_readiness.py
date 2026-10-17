"""Read-only diagnostics for the MuMu/ADB setup.

This module intentionally does not tap, type, send messages, or change device state.
It is safe to run before connecting any higher-level workflow.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from typing import Callable, Sequence


@dataclass
class Check:
    name: str
    ok: bool
    summary: str
    details: dict[str, str]


def _run(
    command: Sequence[str],
    *,
    timeout: float = 5.0,
    runner: Callable = subprocess.run,
) -> subprocess.CompletedProcess:
    return runner(
        list(command),
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _clean(value: str, limit: int = 240) -> str:
    """Keep diagnostic output bounded and avoid printing full device identifiers."""
    value = (value or "").strip().replace("\r", "")
    return value[:limit]


def collect_diagnostics(
    adb_path: str | None = None,
    *,
    runner: Callable = subprocess.run,
) -> dict:
    """Return a JSON-serializable, read-only setup report."""
    candidate = adb_path or os.environ.get("ADB_PATH") or shutil.which("adb")
    checks: list[Check] = []

    if not candidate:
        checks.append(Check(
            "adb", False, "ADB executable was not found.",
            {"hint": "Install Android platform-tools or set ADB_PATH to adb.exe."},
        ))
        return {"schema_version": 1, "checks": [asdict(c) for c in checks], "ready": False}

    try:
        version = _run([candidate, "version"], runner=runner)
        version_text = _clean(version.stdout or version.stderr)
        adb_ok = version.returncode == 0
        checks.append(Check("adb", adb_ok, version_text or "ADB version command returned no output.", {}))
        if not adb_ok:
            return {"schema_version": 1, "checks": [asdict(c) for c in checks], "ready": False}

        devices = _run([candidate, "devices"], runner=runner)
        device_lines = [
            line.strip() for line in (devices.stdout or "").splitlines()[1:]
            if line.strip() and "\t" in line
        ]
        states = [line.rsplit("\t", 1)[-1] for line in device_lines]
        online = sum(state == "device" for state in states)
        unauthorized = sum(state == "unauthorized" for state in states)
        offline = sum(state == "offline" for state in states)
        checks.append(Check(
            "device_connection", devices.returncode == 0 and online > 0,
            f"{online} online, {unauthorized} unauthorized, {offline} offline device(s).",
            {"online_count": str(online), "unauthorized_count": str(unauthorized),
             "offline_count": str(offline)},
        ))
    except (OSError, subprocess.TimeoutExpired) as exc:
        checks.append(Check(
            "adb_execution", False, f"Could not complete ADB diagnostics: {type(exc).__name__}.",
            {"hint": "Check the executable path and whether ADB is responsive."},
        ))

    ready = bool(checks) and all(check.ok for check in checks)
    return {"schema_version": 1, "checks": [asdict(c) for c in checks], "ready": ready}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only MuMu/ADB diagnostics")
    parser.add_argument("--adb", help="Path to adb.exe (optional; ADB_PATH/PATH used otherwise)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    args = parser.parse_args(argv)

    report = collect_diagnostics(args.adb)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if report["ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
