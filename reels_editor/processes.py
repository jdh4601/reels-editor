from __future__ import annotations

import contextlib
import json
from pathlib import Path
import os
import signal
import subprocess
import threading
import time
from collections.abc import Iterator
from contextvars import ContextVar
from typing import Any


_CURRENT: ContextVar[ProcessRegistry | None] = ContextVar("reels_process_registry", default=None)
_AI_LANE: ContextVar[str] = ContextVar("reels_ai_lane", default="generation")


def current_ai_lane() -> str:
    return _AI_LANE.get()


@contextlib.contextmanager
def ai_lane(lane: str):
    if lane not in {'generation', 'review'}:
        raise ValueError('Unknown AI queue')
    token = _AI_LANE.set(lane)
    try:
        yield
    finally:
        _AI_LANE.reset(token)


class AIUsageLimitError(RuntimeError):
    """A batch stops making AI requests once any provider reports a limit."""


def _limit_diagnostic(result):
    stdout, stderr = result.stdout or '', result.stderr or ''
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        return ''
    # CLI streams can echo the source transcript. Inspect errors/results only.
    error_lines = [line for line in stderr.splitlines() if line.strip().lower().startswith(('error:', 'error '))]
    diagnostics = ('\n'.join(error_lines) if error_lines else stderr) if result.returncode else ''
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            if result.returncode and line.strip().lower().startswith(("you've hit", 'error:', 'error ')):
                diagnostics += '\n' + line
            continue
        if isinstance(event, dict) and event.get('type') == 'result' and event.get('is_error'):
            diagnostics += '\n' + str(event.get('result', ''))
    markers = ("you've hit your session limit", 'usage limit reached', 'usage_limit_reached',
               'insufficient_quota', 'quota exceeded', 'exceeded your current quota',
               'too many requests', 'rate_limit_exceeded', 'rate_limit_error',
               '429', 'credit balance is too low')
    matching = [line.strip() for line in diagnostics.splitlines()
                if any(marker in line.lower() for marker in markers)]
    return matching[-1][-500:] if matching else ''


class ProcessRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: set[subprocess.Popen] = set()
        self._cancelled = threading.Event()
        self._ai_locks = {lane: threading.Lock() for lane in ('generation', 'review')}
        self._ai_limit = None

    def check_ai_available(self):
        if self._ai_limit:
            raise AIUsageLimitError(self._ai_limit)

    @contextlib.contextmanager
    def ai_request(self):
        # One request per lane; both share cancellation and the quota circuit.
        lock = self._ai_locks[current_ai_lane()]
        while not lock.acquire(timeout=0.1):
            if self.cancelled:
                raise RuntimeError('job was cancelled')
            self.check_ai_available()
        try:
            self.check_ai_available()
            yield
        finally:
            lock.release()

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
    if registry is not None and Path(str(args[0])).name in {'claude', 'codex', 'gemini'}:
        with registry.ai_request():
            result = _run(args, **kwargs)
            diagnostic = _limit_diagnostic(result)
            if diagnostic:
                registry._ai_limit = ('AI 사용 한도 또는 요청 제한으로 이 작업의 남은 AI 호출을 중단했습니다. '
                                      '한도 초기화 후 재시도하세요. ' + diagnostic)
                raise AIUsageLimitError(registry._ai_limit)
            return result
    return _run(args, **kwargs)


def _run(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess:
    registry = _CURRENT.get()
    if registry is None:
        return subprocess.run(args, **kwargs)
    timeout = kwargs.pop("timeout", None)
    input_data = kwargs.pop("input", None)
    check = bool(kwargs.pop("check", False))
    capture_output = bool(kwargs.pop("capture_output", False))
    if input_data is not None:
        if kwargs.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used")
        kwargs["stdin"] = subprocess.PIPE
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
