"""Moving a wallwright / hyprlayout installation over to displaywright.

The two tools this one is made of each had their own config directory, their
own cache, their own pictures folder, and -- in wallwright's case -- their own
omarchy-shell plugin holding the background layer. Renaming the app without
moving those would look, from the user's side, like losing every wallpaper they
had chosen.

Everything here is idempotent and refuses to overwrite: a step whose target
already exists is reported as skipped rather than clobbering what is there. Run
it twice and the second run does nothing.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .paths import cache_dir, cache_home, config_dir, config_home
from .wallpapers import library, plugin, store
from .wallpapers.model import Config

LEGACY_WALLPAPER_CONFIG = "wallwright"
LEGACY_LAYOUT_CONFIG = "hyprlayout"


@dataclass(frozen=True)
class Step:
    """One thing to move. ``done`` is false when there was nothing to do."""

    description: str
    done: bool = True


def _move(source: Path, target: Path, what: str) -> Step | None:
    """Rename ``source`` to ``target``, or explain why not."""
    if not source.exists():
        return None
    if target.exists():
        return Step(f"{what}: {target} already exists, leaving {source} alone", done=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(target))
    return Step(f"{what}: {source} → {target}")


def legacy_pictures_dir() -> Path:
    return library.pictures_dir() / library.LEGACY_FOLDER_NAME


def _rewrite_paths(config: Config, old: Path, new: Path) -> bool:
    """Point every source that lived under ``old`` at ``new``. True if any did."""
    changed = False
    sources = list(config.monitors.values())
    if config.span is not None:
        sources.append(config.span)
    for source in sources:
        if not source.path:
            continue
        candidate = Path(source.path)
        try:
            relative = candidate.relative_to(old)
        except ValueError:
            continue
        source.path = str(new / relative)
        changed = True
    folders = []
    for folder in config.folders:
        candidate = Path(folder).expanduser()
        if candidate == old:
            folders.append(str(new))
            changed = True
        else:
            folders.append(folder)
    config.folders = folders
    return changed


def pending() -> bool:
    """True when there is anything left to migrate."""
    return any(
        path.exists()
        for path in (
            config_home() / LEGACY_WALLPAPER_CONFIG,
            config_home() / LEGACY_LAYOUT_CONFIG,
            cache_home() / LEGACY_WALLPAPER_CONFIG,
            legacy_pictures_dir(),
            plugin.legacy_install_dir(),
        )
    )


def run(install_renderer: bool = True, link: bool = True) -> list[str]:
    """Do the move. Returns a line per thing that happened."""
    changed: list[str] = []

    def record(step: Step | None) -> None:
        if step is not None:
            changed.append(step.description)

    # Pictures first: the wallpaper config points into this folder, so it has to
    # be where it is going before the paths inside the config are rewritten.
    old_pictures = legacy_pictures_dir()
    new_pictures = library.wallpaper_dir()
    record(_move(old_pictures, new_pictures, "wallpaper folder"))

    old_config = config_home() / LEGACY_WALLPAPER_CONFIG / "config.json"
    new_config = store.config_path()
    if old_config.exists() and not new_config.exists():
        config = store.load(old_config)
        rewritten = _rewrite_paths(config, old_pictures, new_pictures)
        store.save(config, new_config)
        old_config.unlink()
        changed.append(f"wallpaper config: {old_config} → {new_config}")
        if rewritten:
            changed.append(f"rewrote wallpaper paths from {old_pictures} to {new_pictures}")
    elif old_config.exists():
        changed.append(f"wallpaper config: {new_config} already exists, left {old_config} alone")

    legacy_config_dir = config_home() / LEGACY_WALLPAPER_CONFIG
    if legacy_config_dir.is_dir() and not any(legacy_config_dir.iterdir()):
        legacy_config_dir.rmdir()
        changed.append(f"removed empty {legacy_config_dir}")

    record(_move(
        config_home() / LEGACY_LAYOUT_CONFIG / "profiles.json",
        config_dir() / "profiles.json",
        "layout profiles",
    ))
    legacy_layout_dir = config_home() / LEGACY_LAYOUT_CONFIG
    if legacy_layout_dir.is_dir() and not any(legacy_layout_dir.iterdir()):
        legacy_layout_dir.rmdir()
        changed.append(f"removed empty {legacy_layout_dir}")

    # The thumbnail cache keys on the source file's path, not on its own
    # location, so moving the directory keeps every thumbnail valid.
    record(_move(cache_home() / LEGACY_WALLPAPER_CONFIG, cache_dir(), "thumbnail cache"))

    if install_renderer and plugin.is_omarchy():
        # install() clears wallwright's plugin out of shell.json and off disk on
        # its way past, which is what stops two surfaces fighting for the layer.
        try:
            changed += plugin.install(link=link)
        except (OSError, FileNotFoundError) as exc:
            changed.append(f"could not install the renderer: {exc}")

    return changed
