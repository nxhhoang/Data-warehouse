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
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if isinstance(data.get("pid"), int):
                registrations.append(data)
        except (OSError, ValueError):
            continue
    return registrations


def _windows_snapshot(pid: int) -> tuple[float | None, str]:
    """Return (RAM MB, command line) via PowerShell CIM, or (None, "")."""
    command = (
        "$queue = New-Object 'System.Collections.Generic.Queue[int]'; "
        f"$queue.Enqueue([int]{pid}); $seen = @{{}}; "
        "$ram = [long]0; $rootCommand = ''; "
        "while ($queue.Count -gt 0) { "
        "$current = $queue.Dequeue(); "
        "$p = Get-CimInstance Win32_Process -Filter "
        '"ProcessId = $($current)" -ErrorAction SilentlyContinue; '
        "if ($p -and -not $seen.ContainsKey($current)) { "
        "$seen[$current] = $true; $ram += [long]$p.WorkingSetSize; "
        f"if ($current -eq {pid}) {{ $rootCommand = $p.CommandLine }}; "
        "$children = Get-CimInstance Win32_Process -Filter "
        '"ParentProcessId = $($current)" -ErrorAction SilentlyContinue; '
        "foreach ($child in $children) { $queue.Enqueue([int]$child.ProcessId) } "
        "} }; if ($rootCommand) { "
        "[PSCustomObject]@{WorkingSetSize = $ram; CommandLine = $rootCommand} "
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


def _linux_emulator_group_ram_kb(pid: int) -> int:
    """Read RSS of processes in a dedicated emulator process group."""
    try:
        if os.getpgid(pid) != pid:
            return 0
    except OSError:
        return 0
    total = 0
    for stat_path in Path("/proc").glob("[0-9]*/stat"):
        try:
            stat = stat_path.read_text(encoding="utf-8")
            if int(stat[stat.rfind(")") + 2:].split()[2]) != pid:
                continue
            status = stat_path.with_name("status").read_text(encoding="utf-8")
            rss_line = next(line for line in status.splitlines()
                            if line.startswith("VmRSS:"))
            total += int(rss_line.split()[1])
        except (OSError, ValueError, IndexError, StopIteration):
            continue
    return total


def process_snapshot(pid: int, include_group: bool = False) -> tuple[float | None, str]:
    """Return (resident RAM MB, command line), or (None, "") when gone."""
    if os.name == "nt":
        return _windows_snapshot(pid)
    try:
        status = Path(f"/proc/{pid}/status").read_text(encoding="utf-8")
        ram_kb = next(int(line.split()[1]) for line in status.splitlines()
                      if line.startswith("VmRSS:"))
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode(
            "utf-8", errors="replace")
        if include_group:
            group_ram_kb = _linux_emulator_group_ram_kb(pid)
            if group_ram_kb:
                ram_kb = group_ram_kb
        return ram_kb / 1024, cmdline
    except (OSError, ValueError, StopIteration):
        return None, ""


def register_windows_listener(pid_dir: Path, port: int, label: str, token: str) -> dict:
    """Register the real Windows listener rather than a gcloud shell wrapper.

    Git Bash may start cmd -> java and then exit without owning that tree.
    Matching the token before saving the listener PID protects unrelated users
    of the port from cleanup.

    Parameters
    ----------
    pid_dir : pathlib.Path
        Directory holding process registration JSON files.
    port : int
        Local emulator TCP port.
    label : str
        Logical name used for monitoring and cleanup.
    token : str
        Required substring of the listener's command line.

    Returns
    -------
    dict
        Registration containing the native process ID, label and token.

    Raises
    ------
    RuntimeError
        If no listener exists or its command line does not match the token.
    """
    if os.name != "nt":
        raise ValueError("Listener registration is only needed on Windows")
    command = (
        "$connection = Get-NetTCPConnection -LocalPort "
        f"{int(port)} -State Listen -ErrorAction SilentlyContinue | "
        "Select-Object -First 1; if ($connection) { $connection.OwningProcess }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True, text=True, timeout=20, check=False,
    )
    try:
        pid = int(result.stdout.strip())
    except ValueError as err:
        raise RuntimeError(f"No listener found on port {port}") from err
    ram_mb, cmdline = process_snapshot(pid)
    if ram_mb is None:
        raise RuntimeError(f"Listener process {pid} no longer exists")
    if token.lower() not in cmdline.lower():
        raise RuntimeError(
            f"Refusing to register port {port}: command line does not contain {token!r}")
    record = {"pid": pid, "label": label, "token": token}
    pid_dir.mkdir(parents=True, exist_ok=True)
    (pid_dir / f"{label}.json").write_text(json.dumps(record), encoding="utf-8")
    return record


def free_disk_mb() -> int:
    """Free MiB on the drive holding the current working directory."""
    return int(shutil.disk_usage(Path.cwd().anchor or "/").free / (1024 * 1024))


def collect_samples(registrations: list[dict]) -> list[dict]:
    """Attach a live RAM reading and command line to each registration."""
    samples = []
    labels = {record.get("label") for record in registrations}
    for record in registrations:
        # The wrapper contains the Java listener. Count it only if listener
        # registration failed, so their two process trees are not double-counted.
        if record.get("label") == "emulator-wrapper" and "emulator" in labels:
            continue
        ram_mb, cmdline = process_snapshot(
            record["pid"], include_group=record.get("label") == "emulator")
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


def _terminate_posix(record: dict, pid: int, sig: int) -> None:
    """Stop the emulator's dedicated process group, protecting unrelated jobs."""
    if record.get("label") == "emulator":
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, sig)
                return
        except OSError:
            pass
    os.kill(pid, sig)


def stop_registered(pid_dir: Path, grace_seconds: float = 3.0) -> None:
    """Stop every registered live process, then remove its PID file.

    Command lines are validated against the registered token first. On Windows
    taskkill /T also stops descendants such as the Beam local worker.
    """
    priority = {
        "pipeline": 0, "publisher": 1, "monitor": 2,
        "emulator": 3, "emulator-wrapper": 4,
    }
    paths = sorted(
        pid_dir.glob("*.json"),
        key=lambda path: (priority.get(path.stem, 2), path.stem),
    )
    for path in paths:
        try:
            record = json.loads(path.read_text(encoding="utf-8-sig"))
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
                _terminate_posix(record, pid, signal.SIGTERM)
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
                    _terminate_posix(record, pid, signal.SIGKILL)
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
    parser.add_argument("--register-listener", type=int, default=None, metavar="PORT",
                        help="register a Windows listener PID for reliable cleanup")
    parser.add_argument("--label", default="emulator")
    parser.add_argument("--token", default="cloud-pubsub-emulator")
    args = parser.parse_args()
    if args.register_listener is not None:
        try:
            record = register_windows_listener(
                args.pid_dir, args.register_listener, args.label, args.token)
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as err:
            parser.error(str(err))
        print(f"[watch] registered {record['label']} listener pid={record['pid']}")
        return 0
    if args.stop_dir:
        stop_registered(args.stop_dir)
        return 0
    return monitor(args.pid_dir, args.interval, args.once)


if __name__ == "__main__":
    sys.exit(main())
