from __future__ import annotations

import contextlib
import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any


_CURRENT: ContextVar[ProcessRegistry | None] = ContextVar("reels_process_registry", default=None)


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: set[subprocess.Popen] = set()
        self._cancelled = threading.Event()

    @property
    def cancelled(self) -> bool:
        return self._cancelled.is_set()

    def popen(self, args: list[str], **kwargs: Any) -> subprocess.Popen:
        kwargs.setdefault("start_new_session", True)
        with self._lock:
            if self.cancelled:
                raise RuntimeError("job was cancelled")
            process = subprocess.Popen(args, **kwargs)
            self._processes.add(process)
        return process

    def unregister(self, process: subprocess.Popen) -> None:
        with self._lock:
            self._processes.discard(process)

    def terminate_all(self, *, kill_after: float = 2.0) -> None:
        self._cancelled.set()
        with self._lock:
            processes = [process for process in self._processes if process.poll() is None]
        for process in processes:
            _signal_process(process, signal.SIGTERM)
        deadline = time.monotonic() + kill_after
        while processes and time.monotonic() < deadline:
            if all(process.poll() is not None for process in processes):
                return
            time.sleep(0.02)
        with self._lock:
            processes = [process for process in self._processes if process.poll() is None]
        for process in processes:
            _signal_process(process, signal.SIGKILL)


@contextlib.contextmanager
def use_process_registry(registry: ProcessRegistry) -> Iterator[None]:
    token = _CURRENT.set(registry)
    try:
        yield
    finally:
        _CURRENT.reset(token)


def popen(args: list[str], **kwargs: Any) -> subprocess.Popen:
    registry = _CURRENT.get()
    if registry is None:
        return subprocess.Popen(args, **kwargs)
    return registry.popen(args, **kwargs)


def current_registry() -> ProcessRegistry | None:
    return _CURRENT.get()


def run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    registry = _CURRENT.get()
    if registry is None:
        return subprocess.run(args, **kwargs)
    timeout = kwargs.pop("timeout", None)
    input_data = kwargs.pop("input", None)
    check = bool(kwargs.pop("check", False))
    capture_output = bool(kwargs.pop("capture_output", False))
    if capture_output:
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    process = registry.popen(args, **kwargs)
    try:
        stdout, stderr = process.communicate(input=input_data, timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal_process(process, signal.SIGKILL)
        stdout, stderr = process.communicate()
        registry.unregister(process)
        raise
    finally:
        registry.unregister(process)
    if registry.cancelled:
        raise RuntimeError("job was cancelled")
    completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check and completed.returncode:
        raise subprocess.CalledProcessError(completed.returncode, args, stdout, stderr)
    return completed


def _signal_process(process: subprocess.Popen, sig: signal.Signals) -> None:
    try:
        os.killpg(process.pid, sig)
    except (ProcessLookupError, PermissionError):
        return
    except OSError:
        try:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except OSError:
            return
