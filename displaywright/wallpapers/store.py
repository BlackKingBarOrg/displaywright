"""Reading and writing ``~/.config/displaywright/wallpapers.json``.

The renderer watches this file, so a half-written one is a black desktop for as
long as it takes to notice. Every write therefore goes to a temporary file in
the same directory and is renamed over the target, which is atomic on a POSIX
filesystem: a reader sees either the whole old file or the whole new one.

A config left behind by wallwright, the tool this half of displaywright grew
out of, is still read if no current one exists. That is a fallback, not a
migration -- writing goes to the new path regardless, and
:mod:`displaywright.migrate` is what actually moves things over.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..paths import config_dir, config_home, temp_sibling
from .model import Config

FILENAME = "wallpapers.json"

#: Where wallwright kept the same file. Read as a last resort so an unmigrated
#: machine still shows its wallpapers instead of an empty window.
LEGACY_DIR = "wallwright"
LEGACY_FILENAME = "config.json"


def config_path() -> Path:
    return config_dir() / FILENAME


def legacy_config_path() -> Path:
    return config_home() / LEGACY_DIR / LEGACY_FILENAME


def load(path: Path | None = None) -> Config:
    """Read the config, or an empty one if it is missing or unreadable.

    A corrupt file is treated as absent rather than fatal. The alternative --
    refusing to start -- would leave the user with no GUI to fix it from.
    """
    if path is not None:
        return _read(path)
    target = config_path()
    if target.exists():
        return _read(target)
    legacy = legacy_config_path()
    return _read(legacy) if legacy.exists() else Config()


def _read(target: Path) -> Config:
    try:
        raw = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return Config()
    try:
        return Config.from_json(json.loads(raw))
    except json.JSONDecodeError:
        return Config()


def save(config: Config, path: Path | None = None) -> Path:
    """Write the config atomically. Returns the path written."""
    target = path or config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_sibling(target)
    payload = json.dumps(config.to_json(), indent=2, ensure_ascii=False) + "\n"
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target
