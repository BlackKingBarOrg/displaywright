"""Turning the built-in panel off, safely, through Omarchy's own toggle.

Writing ``disabled = true`` for a laptop panel into ``monitors.lua`` is a trap:
nothing removes it, so unplugging the external display leaves a black machine.

Omarchy already solves that, and it does so without any app running:

* ``~/.local/state/omarchy/toggles/hypr/internal-monitor-disable.lua`` is
  ``require``\\ d by the Hyprland config (after ``monitors.lua``, so it wins).
* ``omarchy-recover-internal-monitor.service`` deletes that file before the
  graphical session starts if no external display is physically connected.
* ``omarchy-hyprland-monitor-watch`` re-enables the internal panel on hotplug
  once no external output is active any more.

Omarchy consumes the file but ships nothing that creates it -- that is the gap
this module fills.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from .model import MonitorState

TOGGLE_NAME = "internal-monitor-disable.lua"


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def toggles_dir() -> Path:
    return state_home() / "omarchy" / "toggles" / "hypr"


def toggle_path() -> Path:
    return toggles_dir() / TOGGLE_NAME


def available() -> bool:
    """True when this looks like an Omarchy system that honours the toggle."""
    return toggles_dir().is_dir() or shutil.which("omarchy") is not None


def has_safety_net() -> bool:
    """True when the pieces that put the panel back are actually installed."""
    return all(
        shutil.which(name)
        for name in (
            "omarchy-hyprland-monitor-clamshell",
            "omarchy-hw-recover-internal-monitor",
        )
    )


def builtin(states: list[MonitorState]) -> MonitorState | None:
    """The laptop panel, matched the way Omarchy matches it."""
    return next((s for s in states if s.is_builtin), None)


def is_disabled() -> bool:
    return toggle_path().exists()


def render_toggle(name: str) -> str:
    return f'''-- Written by hyprlayout: keep the built-in display off while an external
-- display is connected.
--
-- Deleting this file turns the panel back on. Omarchy does that for you when no
-- external display is left -- before the graphical session via
-- omarchy-recover-internal-monitor.service, and on hotplug via
-- omarchy-hyprland-monitor-watch -- so this cannot strand you with a black
-- laptop. That is also why the rule lives here rather than in monitors.lua,
-- which nothing cleans up.
hl.monitor({{ output = "{name}", disabled = true }})
'''


def disable_builtin(name: str) -> Path:
    """Write the toggle. Returns the path written."""
    path = toggle_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.hyprlayout.tmp")
    tmp.write_text(render_toggle(name))
    tmp.replace(path)
    return path


def enable_builtin() -> bool:
    """Remove the toggle. Returns True if it had been set."""
    path = toggle_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def sync(states: list[MonitorState]) -> str | None:
    """Make the toggle match the desired state of the built-in panel.

    Returns a short description of what changed, or None if nothing did.
    """
    panel = builtin(states)
    if panel is None:
        return None
    if panel.enabled:
        return f"{panel.name} switched back on" if enable_builtin() else None
    if is_disabled():
        return None
    disable_builtin(panel.name)
    return f"{panel.name} turned off (comes back when no external display is left)"
