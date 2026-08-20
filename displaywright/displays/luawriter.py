"""Render a layout into Omarchy's Lua monitor config.

Omarchy configures Hyprland in Lua, so persisting a layout means emitting
``hl.monitor({ ... })`` calls into ``~/.config/hypr/monitors.lua``.  The field
names come from Hyprland's own ``HL.MonitorSpec`` stub
(``/usr/share/hypr/stubs/hl.meta.lua``).

Writes are conservative: everything the user wrote outside our managed block is
preserved, pre-existing ``hl.monitor`` calls are commented out rather than
deleted, and a timestamped backup is taken first.
"""

from __future__ import annotations

import difflib
import os
import re
import time
from collections.abc import Sequence
from pathlib import Path

from ..model import MonitorState

BEGIN = "-- >>> displaywright managed block: edited by `displaywright`, safe to move as a whole >>>"
END = "-- <<< displaywright managed block <<<"

#: The markers hyprlayout wrote, before it and wallwright became one app. A
#: config that still carries them is rewritten in place rather than given a
#: second block underneath the first.
LEGACY_MARKERS = (
    (
        "-- >>> hyprlayout managed block: edited by `hyprlayout`, safe to move as a whole >>>",
        "-- <<< hyprlayout managed block <<<",
    ),
)

_HEADER = (
    "-- Generated from the displaywright GUI. Anything outside this block is left\n"
    "-- alone; anything inside it is replaced on the next save.\n"
)


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hypr" / "monitors.lua"


def render_call(state: MonitorState) -> str:
    """One ``hl.monitor`` call for a single output.

    The same text is what :func:`displaywright.hypr.apply_states` evaluates
    live, so what you preview is exactly what runs.
    """
    return state.lua_call()


def render_block(states: Sequence[MonitorState], toggle_builtin: bool = False) -> str:
    """The full managed block, including its markers.

    With ``toggle_builtin`` set, a switched-off laptop panel is still written as
    an *enabled* rule. Its "off" lives in Omarchy's
    ``internal-monitor-disable.lua`` toggle instead, which is the only place that
    something removes again when the external display goes away. The rule left
    here is what Omarchy reads to restore the panel's mode, position and scale.
    """
    lines = [BEGIN, _HEADER.rstrip("\n")]
    for state in sorted(states, key=lambda s: (not s.enabled, s.x, s.y, s.name)):
        via_toggle = toggle_builtin and state.is_builtin and not state.enabled
        written = state
        if via_toggle:
            written = state.copy()
            written.enabled = True
        label = written.pretty_name
        detail = written.summary()
        if label and label != written.name:
            lines.append(f"-- {written.name}: {label} — {detail}")
        else:
            lines.append(f"-- {written.name}: {detail}")
        if via_toggle:
            lines.append(
                "-- currently switched off via Omarchy's internal-monitor-disable "
                "toggle,\n-- which comes back automatically when no external display "
                "is left."
            )
        lines.append(render_call(written))
    lines.append(END)
    return "\n".join(lines) + "\n"


_OUTPUT_RE = re.compile(r'output\s*=\s*"([^"]*)"')


def _call_spans(lines: Sequence[str]) -> list[tuple[int, int]]:
    """Inclusive line ranges of top-level ``hl.monitor(...)`` calls."""
    spans: list[tuple[int, int]] = []
    start = -1
    depth = 0
    for index, line in enumerate(lines):
        if depth == 0 and line.lstrip().startswith("hl.monitor("):
            start = index
            depth = 0
        elif start < 0:
            continue
        depth += line.count("(") - line.count(")")
        if start >= 0 and depth <= 0:
            spans.append((start, index))
            start = -1
            depth = 0
    if start >= 0:  # unbalanced file; treat the rest as one call
        spans.append((start, len(lines) - 1))
    return spans


def _comment_out_monitor_calls(text: str, managed: set[str] | None) -> tuple[str, int]:
    """Comment out the ``hl.monitor`` calls this tool now owns.

    Rules for outputs we are *not* managing are left untouched: the catch-all
    (``output = ""``) that configures displays on first plug-in, and rules for
    monitors that simply are not connected right now.
    """
    lines = text.splitlines()
    doomed: set[int] = set()
    commented = 0
    for start, end in _call_spans(lines):
        match = _OUTPUT_RE.search("\n".join(lines[start : end + 1]))
        name = match.group(1) if match else None
        if name in (None, "", "*"):
            continue
        if managed is not None and name not in managed:
            continue
        doomed.update(range(start, end + 1))
        commented += 1

    out = [
        ("-- [displaywright] replaced: " + line) if index in doomed else line
        for index, line in enumerate(lines)
    ]
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), commented


def _existing_markers(text: str) -> tuple[str, str] | None:
    """The marker pair already in the file, current or inherited."""
    for begin, end in ((BEGIN, END), *LEGACY_MARKERS):
        if begin in text and end in text:
            return begin, end
    return None


def merge(existing: str, block: str, managed: set[str] | None = None) -> str:
    """Splice ``block`` into ``existing``, preserving the user's own lines."""
    markers = _existing_markers(existing)
    if markers is not None:
        begin, end = markers
        head, rest = existing.split(begin, 1)
        _, tail = rest.split(end, 1)
        return head + block.rstrip("\n") + tail

    body, commented = _comment_out_monitor_calls(existing, managed)
    if body and not body.endswith("\n"):
        body += "\n"
    note = ""
    if commented:
        note = (
            f"-- displaywright commented out {commented} earlier hl.monitor call(s);\n"
            "-- delete them once you are happy with the block below.\n"
        )
    separator = "\n" if body.strip() else ""
    return f"{body}{separator}{note}{block}"


def render_file(
    existing: str, states: Sequence[MonitorState], toggle_builtin: bool = False
) -> str:
    return merge(existing, render_block(states, toggle_builtin), {s.name for s in states})


def diff(old: str, new: str, path: str = "monitors.lua") -> str:
    lines = difflib.unified_diff(
        old.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        n=3,
    )
    return "".join(lines)


def preview(
    path: Path, states: Sequence[MonitorState], toggle_builtin: bool = False
) -> tuple[str, str]:
    """``(new_text, unified_diff)`` for what :func:`save` would write."""
    existing = path.read_text() if path.exists() else ""
    new_text = render_file(existing, states, toggle_builtin)
    return new_text, diff(existing, new_text, path.name)


def save(
    path: Path,
    states: Sequence[MonitorState],
    backup: bool = True,
    toggle_builtin: bool = False,
) -> Path | None:
    """Write the layout to ``path``; returns the backup path if one was made."""
    existing = path.read_text() if path.exists() else ""
    new_text = render_file(existing, states, toggle_builtin)

    backup_path: Path | None = None
    if backup and existing:
        backup_path = path.with_name(f"{path.name}.bak.{int(time.time())}")
        backup_path.write_text(existing)

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.displaywright.tmp")
    tmp.write_text(new_text)
    tmp.replace(path)  # atomic: never leave a half-written config behind
    return backup_path
