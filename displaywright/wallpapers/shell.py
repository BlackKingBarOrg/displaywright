"""Talking to the running omarchy-shell.

The wallpaper renderer is a plugin inside that shell, so everything
displaywright wants to say to it goes over Quickshell's IPC. The config file is
the source of truth and the plugin watches it; these calls only exist to skip
the watch latency and to ask the shell to notice a freshly installed plugin.

Every call here is best-effort. A displaywright that cannot reach the shell has
still written the config, and the plugin will pick it up when it next starts.
"""

from __future__ import annotations

import shutil
import subprocess

TARGET = "displaywright"


def available() -> bool:
    return shutil.which("omarchy-shell") is not None


def call(target: str, method: str, *args: str, timeout: float = 3.0) -> str | None:
    """Invoke one IPC method. Returns the reply, or None if it did not land."""
    if not available():
        return None
    try:
        proc = subprocess.run(
            ["omarchy-shell", target, method, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip()


def is_running() -> bool:
    return call("shell", "ping") == "ok"


def reload() -> bool:
    """Ask the renderer to re-read the config now instead of on its next poll."""
    return call(TARGET, "reload") is not None


def rescan_plugins() -> bool:
    return call("shell", "rescanPlugins") is not None


def restart() -> bool:
    """Full shell restart. Only needed when a plugin fails to hot-reload."""
    if shutil.which("omarchy-restart-shell") is None:
        return False
    try:
        subprocess.run(["omarchy-restart-shell"], capture_output=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True
