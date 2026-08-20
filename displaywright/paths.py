"""Where displaywright keeps things, and how it writes them safely.

Both halves of the app persist state, and one of them -- the wallpaper config --
is watched by a renderer running in another process. A half-written file there
is a black desktop until it is noticed, so every write in this app goes through
:func:`temp_sibling` and an atomic rename.

Everything lands under one directory per XDG base, named for the app:

* ``~/.config/displaywright/`` — ``wallpapers.json``, ``profiles.json``
* ``~/.cache/displaywright/`` — thumbnails
* ``~/.local/state/omarchy/`` — read, never written; Omarchy's own state
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from . import APP_NAME


def config_home() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")


def cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")


def state_home() -> Path:
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")


def config_dir() -> Path:
    return config_home() / APP_NAME


def cache_dir() -> Path:
    return cache_home() / APP_NAME


def temp_sibling(target: Path, suffix: str = "tmp") -> Path:
    """A scratch path next to ``target``, on the same filesystem so the rename
    that replaces ``target`` is atomic.

    The name has to be unique per *call*, not per process: two threads writing
    the same target -- the picker's thumbnail worker and a canvas repaint, say
    -- would otherwise share one scratch file, and whichever finished first
    would delete the other's out from under it.
    """
    return target.with_name(f".{target.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.{suffix}")


def display_path(path: Path) -> str:
    """A path as the user would write it, with ``~`` for their home."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)
