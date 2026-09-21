from __future__ import annotations

import platform
import subprocess


def show_macos_notification(title: str, message: str) -> None:
    """Show a best-effort native macOS notification without blocking the job."""
    if platform.system() != "Darwin":
        return

    script = "display notification " + _apple_script_string(message)
    script += " with title " + _apple_script_string(title)
    try:
        subprocess.Popen(  # noqa: S603 - arguments are passed without a shell
            ["/usr/bin/osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        # Notifications are a convenience and must never fail a render job.
        return


def _apple_script_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
