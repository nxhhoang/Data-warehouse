"""Offline checks for replay argument safety and managed-process liveness."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "scripts" / "run_emulator_replay.sh"


def _find_bash():
    if os.name == "nt":
        git_bash = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe"
        if git_bash.exists():
            return str(git_bash)
    return shutil.which("bash")


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="replay orchestration requires Bash")


def _run_bash(code, timeout=10):
    """Run a local Bash harness and preserve diagnostics on an assertion failure."""
    return subprocess.run(
        [BASH, "-c", code], cwd=ROOT, capture_output=True,
        text=True, check=False, timeout=timeout,
    )


def _script():
    return REPLAY.read_text(encoding="utf-8")


def test_replay_script_has_valid_bash_syntax():
    result = subprocess.run(
        [BASH, "-n", "scripts/run_emulator_replay.sh"], cwd=ROOT,
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("replace_day, expect_overwrite_flag", [("0", False), ("1", True)])
def test_replay_forwards_overwrite_flag_only_on_explicit_choice(replace_day, expect_overwrite_flag):
    source = _script()
    start = '  load_args=(--from-jsonl "$OUT_DIR")\n'
    assert start in source
    block = start + source.split(start, 1)[1].split('  echo "[replay] loaded.', 1)[0]
    block = block.replace('"$PY"', "mock_loader")
    # Exercise the real array construction, but replace the Python loader by printf.
    harness = f'''mock_loader() {{ printf '%s\\n' "$@"; }}
OUT_DIR=build/test
REPLACE_DAY={replace_day}
{block}
'''
    result = _run_bash(harness)
    assert result.returncode == 0, result.stderr
    arguments = result.stdout.splitlines()
    assert arguments[:3] == ["scripts/load_raw_to_bigquery.py", "--from-jsonl", "build/test"]
    assert ("--replace-day" in arguments) is expect_overwrite_flag
    assert len(arguments) == (4 if expect_overwrite_flag else 3)


def _process_helpers():
    start = "pid_is_running() {\n"
    end = "\ncleanup() {\n"
    source = _script()
    assert start in source and end in source
    return start + source.split(start, 1)[1].split(end, 1)[0]


def test_process_helpers_recognize_a_running_pipeline():
    code = _process_helpers() + '''
sleep 0.5 &
PIPELINE_PID=$!
ensure_pipeline_running
status=$?
wait "$PIPELINE_PID"
exit "$status"
'''
    result = _run_bash(code)
    assert result.returncode == 0, result.stderr


def test_completed_pipeline_job_is_not_treated_as_running():
    code = _process_helpers() + '''
sleep 0.1 &
PIPELINE_PID=$!
while pid_is_running "$PIPELINE_PID"; do
  :
done
if ensure_pipeline_running; then
  exit 1
fi
'''
    result = _run_bash(code)
    assert result.returncode == 0, result.stderr
