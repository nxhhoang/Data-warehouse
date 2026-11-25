"""Monitor and clean up processes of an emulator replay run.

Read PID registration files from a run directory (default
build/emulator_replay/pids), periodically report each process's resident RAM
and the free space of the current drive (C: on Windows), and stop only the
registered processes on request. No third-party packages are required.

Registered JSON example: {"pid": 1234, "label": "pipeline",
"token": "dataflow_pipeline.py"}. The token is checked against the OS command
line before terminating a process, protecting against PID reuse.

Usage:
    python scripts/watch_resources.py [--pid-dir build/emulator_replay/pids]
    python scripts/watch_resources.py --once
    python scripts/watch_resources.py --stop-dir build/emulator_replay/pids

The monitor keeps running until interrupted. Resource-limit violations do not
silently kill anything: they are printed and reflected in the exit status.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_PID_DIR = Path("build/emulator_replay/pids")
DEFAULT_INTERVAL = 15.0
MAX_PROCESS_MB = 4096
MIN_FREE_DISK_MB = 2048


def read_registrations(pid_dir: Path) -> list[dict]:
    """Load live registration files, ignoring malformed entries."""
    if not pid_dir.exists():
        return []
    registrations = []
    for path in sorted(pid_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data.get("pid"), int):
                registrations.append(data)
        except (OSError, ValueError):
            continue
    return registrations


def _windows_snapshot(pid: int) -> tuple[float | None, str]:
    """Return (RAM MB, command line) via PowerShell CIM, or (None, "")."""
    command = (
        "$p = Get-CimInstance Win32_Process -Filter "
        f"\"ProcessId = {pid}\" -ErrorAction SilentlyContinue; "
        "if ($p) { $p | Select-Object ProcessId,WorkingSetSize,CommandLine "
        "| ConvertTo-Json -Compress }"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True, text=True, timeout=20, check=False,
        )
        data = json.loads(result.stdout.strip())
        if not data:
            return None, ""
        return float(data["WorkingSetSize"]) / (1024 * 1024), data.get("CommandLine") or ""
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return None, ""


def process_snapshot(pid: int) -> tuple[float | None, str]:
    """Return (resident RAM MB, command line), or (None, "") when gone."""
    if os.name == "nt":
        return _windows_snapshot(pid)
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        ram_kb = next(int(line.split()[1]) for line in status.splitlines()
                      if line.startswith("VmRSS:"))
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace")
        return ram_kb / 1024, cmdline
    except (OSError, ValueError, StopIteration):
        return None, ""


def free_disk_mb() -> int:
    """Free MiB on the drive holding the current working directory."""
    return int(shutil.disk_usage(Path.cwd().anchor or "/").free / (1024 * 1024))


def collect_samples(registrations: list[dict]) -> list[dict]:
    """Attach a live RAM reading and command line to each registration."""
    samples = []
    for record in registrations:
        ram_mb, cmdline = process_snapshot(record["pid"])
        if ram_mb is not None:
            samples.append({**record, "ram_mb": ram_mb, "cmdline": cmdline})
    return samples


def format_status(samples: list[dict], disk_mb: int) -> str:
    """Format one compact watchdog status line."""
    parts = [f"{sample['label']}={sample['ram_mb']:.0f} MB" for sample in samples]
    parts.append(f"disk free={disk_mb / 1024:.1f} GB")
    return "[watch] " + " | ".join(parts) if parts else f"[watch] disk free={disk_mb / 1024:.1f} GB"


def violations(samples: list[dict], disk_mb: int,
               max_process_mb: int = MAX_PROCESS_MB,
               min_free_disk_mb: int = MIN_FREE_DISK_MB) -> list[str]:
    """Return human-readable resource-limit violations for one sample cycle."""
    issues = [f"{sample['label']} uses {sample['ram_mb']:.0f} MB (> {max_process_mb} MB)"
              for sample in samples if sample["ram_mb"] > max_process_mb]
    if disk_mb < min_free_disk_mb:
        issues.append(f"only {disk_mb} MB free on drive (< {min_free_disk_mb} MB)")
    return issues


def stop_registered(pid_dir: Path, grace_seconds: float = 3.0) -> None:
    """Stop every registered live process, then remove its PID file.

    Command lines are validated against the registered token first. On Windows
    taskkill /T also stops descendants such as the Beam local worker.
    """
    for path in sorted(pid_dir.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pid = record.get("pid")
        token = str(record.get("token", ""))
        ram_mb, cmdline = process_snapshot(pid)
        if ram_mb is None:
            path.unlink(missing_ok=True)
            continue
        if token and token.lower() not in cmdline.lower():
            print(f"[stop] skip {record.get('label')} pid={pid}: command line does not match")
            continue
        print(f"[stop] stopping {record.get('label')} pid={pid}")
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/T"],
                               capture_output=True, timeout=15, check=False)
            else:
                os.kill(pid, signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(grace_seconds)
        ram_mb, _ = process_snapshot(pid)
        if ram_mb is not None:
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True, timeout=15, check=False)
                else:
                    os.kill(pid, signal.SIGKILL)
            except (OSError, subprocess.SubprocessError):
                pass
        path.unlink(missing_ok=True)


def monitor(pid_dir: Path, interval: float, once: bool) -> int:
    """Print RAM/disk usage until interrupted; return 2 on repeated violations."""
    over_limit = 0
    try:
        while True:
            samples = collect_samples(read_registrations(pid_dir))
            disk_mb = free_disk_mb()
            print(format_status(samples, disk_mb), flush=True)
            issues = violations(samples, disk_mb)
            for issue in issues:
                print(f"[watch] WARNING: {issue}", flush=True)
            over_limit = over_limit + 1 if issues else 0
            if once:
                return 2 if issues else 0
            if over_limit >= 3:
                print("[watch] resource limits exceeded three times; stopping run", flush=True)
                return 2
            time.sleep(interval)
    except KeyboardInterrupt:
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid-dir", type=Path, default=DEFAULT_PID_DIR)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL)
    parser.add_argument("--once", action="store_true", help="one sample, then exit")
    parser.add_argument("--stop-dir", type=Path, default=None,
                        help="stop registered processes and exit")
    args = parser.parse_args()
    if args.stop_dir:
        stop_registered(args.stop_dir)
        return 0
    return monitor(args.pid_dir, args.interval, args.once)


if __name__ == "__main__":
    sys.exit(main())
