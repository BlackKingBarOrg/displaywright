"""Installing the renderer into omarchy-shell, and taking it back out.

One thing has to be true for displaywright to draw anything: its plugin
directory exists under ``~/.config/omarchy/plugins/`` and is listed in
``plugins[]`` in ``shell.json``. That is the whole install.

Earlier versions also disabled ``omarchy.background``, on the grounds that two
opaque surfaces on ``WlrLayer.Background`` have no defined order between them.
The renderer no longer draws anything on an output it has not been given a
wallpaper for, so there is nothing to fight over: the stock renderer stays on
and keeps the theme background, the switcher and the palette transition. An
install left over from that era is repaired here -- :func:`install` switches
``omarchy.background`` back on -- because leaving it off now would mean an
output with no wallpaper of ours draws nothing at all.

shell.json is edited directly rather than over IPC so that installing works
with the shell stopped, and it is edited *minimally* -- the file also holds the
user's whole bar layout, and none of that is ours to reformat.
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from ..paths import config_dir, config_home, temp_sibling

PLUGIN_ID = "ai.bkblab.displaywright"

#: The stock renderer. displaywright draws on top of it and must never turn it
#: off; the name is here so an install that once did can be undone.
STOCK_PLUGIN = "omarchy.background"

#: wallwright's plugin id. It draws the same layer from the same checkout, so
#: leaving it installed alongside the current one means two surfaces fighting
#: over one output. Install and uninstall both clear it out.
LEGACY_PLUGIN_ID = "ai.bkblab.wallwright"


def omarchy_path() -> Path:
    return Path(os.environ.get("OMARCHY_PATH") or "/usr/share/omarchy")


def is_omarchy() -> bool:
    return (omarchy_path() / "shell" / "shell.qml").is_file()


def plugins_dir() -> Path:
    return config_home() / "omarchy" / "plugins"


def install_dir() -> Path:
    return plugins_dir() / PLUGIN_ID


def legacy_install_dir() -> Path:
    return plugins_dir() / LEGACY_PLUGIN_ID


def shell_config_path() -> Path:
    return config_home() / "omarchy" / "shell.json"


def source_dir() -> Path:
    """The ``plugin/`` directory shipped alongside this package."""
    return Path(__file__).resolve().parents[2] / "plugin"


@dataclass(frozen=True)
class Status:
    installed: bool
    linked: bool
    enabled: bool
    #: True when something has switched the stock renderer off. Not fatal for
    #: us -- our own wallpapers still draw -- but every output we have no
    #: opinion about is left blank, which is not what anybody wants.
    stock_off: bool = False
    #: A wallwright install is still in place and would fight for the layer.
    legacy: bool = False

    @property
    def ready(self) -> bool:
        return self.installed and self.enabled and not self.stock_off and not self.legacy

    def describe(self) -> str:
        if self.ready:
            how = "linked to a checkout" if self.linked else "copied"
            return f"installed ({how}) and active"
        if not self.installed:
            return "not installed"
        problems = []
        if not self.enabled:
            problems.append(f"not enabled in {shell_config_path()}")
        if self.stock_off:
            problems.append(
                f"{STOCK_PLUGIN} is switched off, so displays without a wallpaper of "
                "their own draw nothing"
            )
        if self.legacy:
            problems.append(f"{LEGACY_PLUGIN_ID} is still installed and draws the same layer")
        return "installed but inactive — " + "; ".join(problems)


def _read_shell_config() -> dict:
    """The user's shell.json, or Omarchy's defaults if they have none yet."""
    for candidate in (shell_config_path(), omarchy_path() / "config" / "omarchy" / "shell.json"):
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            return data
    return {"version": 1, "plugins": []}


def _write_shell_config(data: dict) -> Path:
    target = shell_config_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_sibling(target)
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return target


def _plugin_entries(data: dict) -> list:
    entries = data.get("plugins")
    if not isinstance(entries, list):
        entries = []
        data["plugins"] = entries
    return entries


def _is_enabled(data: dict, plugin_id: str = PLUGIN_ID) -> bool:
    return any(
        isinstance(entry, dict) and entry.get("id") == plugin_id for entry in _plugin_entries(data)
    )


def _drop_plugin(data: dict, plugin_id: str) -> bool:
    """Remove one plugin from ``plugins[]``. True if it was there."""
    entries = _plugin_entries(data)
    kept = [e for e in entries if not (isinstance(e, dict) and e.get("id") == plugin_id)]
    if len(kept) == len(entries):
        return False
    data["plugins"] = kept
    return True


def _remove_tree(target: Path) -> bool:
    if target.is_symlink():
        target.unlink()
        return True
    if target.exists():
        shutil.rmtree(target)
        return True
    return False


def _is_disabled(data: dict, plugin_id: str) -> bool:
    disabled = data.get("disabledPlugins")
    return isinstance(disabled, list) and plugin_id in disabled


def _undisable(data: dict, plugin_id: str) -> bool:
    """Take a plugin out of ``disabledPlugins[]``. True if it was there."""
    disabled = data.get("disabledPlugins")
    if not isinstance(disabled, list) or plugin_id not in disabled:
        return False
    remaining = [entry for entry in disabled if entry != plugin_id]
    if remaining:
        data["disabledPlugins"] = remaining
    else:
        data.pop("disabledPlugins", None)
    return True


def status() -> Status:
    target = install_dir()
    data = _read_shell_config()
    legacy_target = legacy_install_dir()
    return Status(
        installed=(target / "manifest.json").is_file(),
        linked=target.is_symlink(),
        enabled=_is_enabled(data),
        stock_off=_is_disabled(data, STOCK_PLUGIN),
        legacy=legacy_target.exists() or _is_enabled(data, LEGACY_PLUGIN_ID),
    )


def install(link: bool = True) -> list[str]:
    """Put the renderer in place and switch it on. Returns what changed."""
    changed: list[str] = []
    src = source_dir()
    if not (src / "manifest.json").is_file():
        raise FileNotFoundError(f"no plugin sources at {src}")

    target = install_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    # The renderer watches this directory so that the first config.json to
    # appear is noticed without an IPC nudge. FileView cannot observe a file
    # that does not exist yet, only the directory that will hold it.
    config_dir().mkdir(parents=True, exist_ok=True)

    if target.is_symlink():
        # Already pointing where we want it: leave it, so a reinstall over a
        # running shell does not unmap every wallpaper surface for a moment.
        if not (link and Path(os.readlink(target)) == src):
            target.unlink()
    elif target.exists():
        shutil.rmtree(target)

    if not target.exists():
        if link:
            target.symlink_to(src, target_is_directory=True)
            changed.append(f"linked {target} -> {src}")
        else:
            shutil.copytree(src, target)
            changed.append(f"copied {src} -> {target}")

    data = _read_shell_config()
    dirty = False

    if not _is_enabled(data):
        _plugin_entries(data).append({"id": PLUGIN_ID})
        changed.append(f"enabled {PLUGIN_ID}")
        dirty = True

    # An install from before the renderer learned to share the layer will have
    # switched the stock one off. Put it back: we draw over it now, and without
    # it an output we have no wallpaper for shows nothing at all.
    if _undisable(data, STOCK_PLUGIN):
        changed.append(f"re-enabled {STOCK_PLUGIN} (displaywright now draws on top of it)")
        dirty = True

    # wallwright drew the same layer from the same files. Two surfaces on one
    # output is a coin flip per session, so its install goes when ours arrives.
    if _drop_plugin(data, LEGACY_PLUGIN_ID):
        changed.append(f"disabled {LEGACY_PLUGIN_ID} (superseded by {PLUGIN_ID})")
        dirty = True
    if _remove_tree(legacy_install_dir()):
        changed.append(f"removed {legacy_install_dir()}")

    if dirty:
        _write_shell_config(data)

    return changed


def uninstall(remove_files: bool = True) -> list[str]:
    """Hand the background layer back to Omarchy."""
    changed: list[str] = []
    data = _read_shell_config()
    dirty = False

    for plugin_id in (PLUGIN_ID, LEGACY_PLUGIN_ID):
        if _drop_plugin(data, plugin_id):
            changed.append(f"disabled {plugin_id}")
            dirty = True

    if _undisable(data, STOCK_PLUGIN):
        changed.append(f"re-enabled {STOCK_PLUGIN}")
        dirty = True

    if dirty:
        _write_shell_config(data)

    if remove_files:
        for target in (install_dir(), legacy_install_dir()):
            if _remove_tree(target):
                changed.append(f"removed {target}")

    return changed
