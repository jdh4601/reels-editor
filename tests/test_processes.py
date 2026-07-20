from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import pytest

from reels_editor import processes


def test_managed_run_honors_check_true() -> None:
    registry = processes.ProcessRegistry()

    with processes.use_process_registry(registry):
        with pytest.raises(subprocess.CalledProcessError) as exc:
            processes.run(
                [sys.executable, "-c", "import sys; print('bad'); sys.exit(7)"],
                capture_output=True,
                text=True,
                check=True,
            )

    assert exc.value.returncode == 7
    assert exc.value.output.strip() == "bad"


def test_terminate_all_stops_registered_process_quickly(tmp_path: Path) -> None:
    registry = processes.ProcessRegistry()
    pid_file = tmp_path / "sleep.pid"
    with processes.use_process_registry(registry):
        process = processes.popen(
            [
                sys.executable,
                "-c",
                "import os, sys, time; open(sys.argv[1], 'w').write(str(os.getpid())); time.sleep(30)",
                str(pid_file),
            ]
        )

    deadline = time.time() + 5
    while not pid_file.is_file() and time.time() < deadline:
        time.sleep(0.02)
    assert pid_file.is_file()

    started = time.time()
    registry.terminate_all(kill_after=2)
    process.wait(timeout=1)

    assert time.time() - started < 1
    assert process.returncode is not None
