from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ToolProbe:
    name: str
    path: str | None
    found: bool
    version: str | None = None


def common_tool_dirs(home: Path | None = None) -> list[Path]:
    user_home = (home or Path.home()).expanduser()
    return [
        user_home / ".npm-global" / "bin",
        user_home / ".local" / "bin",
        user_home / ".cargo" / "bin",
        Path("/opt/homebrew/bin"),
        Path("/usr/local/bin"),
        Path("/usr/bin"),
        Path("/bin"),
    ]


def tool_candidates(name: str, home: Path | None = None) -> list[Path]:
    return [directory / name for directory in common_tool_dirs(home)]


def resolve_tool(name: str, extra_candidates: list[str] | None = None) -> str | None:
    candidates = [*tool_candidates(name), *(Path(item).expanduser() for item in (extra_candidates or []))]
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which(name)


def inject_tool_paths(environ: dict[str, str] | None = None) -> str:
    env = environ if environ is not None else os.environ
    current = env.get("PATH", "")
    existing = [item for item in current.split(os.pathsep) if item]
    prefix = [
        str(directory)
        for directory in common_tool_dirs()
        if directory.is_dir() and str(directory) not in existing
    ]
    path = os.pathsep.join([*prefix, *existing])
    env["PATH"] = path
    return path


def probe_tool(name: str) -> ToolProbe:
    path = resolve_tool(name)
    if not path:
        return ToolProbe(name=name, path=None, found=False)
    try:
        completed = subprocess.run(
            [path, "-version" if name in {"ffmpeg", "ffprobe"} else "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        version = (completed.stdout or completed.stderr).splitlines()[0].strip()
    except Exception as exc:  # pragma: no cover - defensive reporting path
        version = f"version probe failed: {exc}"
    return ToolProbe(name=name, path=path, found=True, version=version)


def probe_required_tools() -> dict[str, dict[str, str | bool | None]]:
    return {name: asdict(probe_tool(name)) for name in ("ffmpeg", "ffprobe", "codex")}
