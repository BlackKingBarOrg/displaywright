"""Where the pictures come from, and how they get shown quickly.

Decoding a folder of 4K wallpapers to fill a picker grid costs more memory than
the rest of the app put together, so every entry is drawn from a small cached
thumbnail on disk instead. The cache key includes the file's size and mtime,
which means an edited file re-thumbnails itself without any invalidation logic.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from ..paths import cache_dir, config_home, state_home, temp_sibling
from .model import IMAGE_SUFFIXES, VIDEO_SUFFIXES, Kind, kind_for_path

THUMBNAIL_SIZE = 320

#: How deep a scanned folder is walked. Wallpaper collections are usually flat
#: or one level of categories deep; anything more is someone's whole home
#: directory and should not be trawled by a wallpaper picker.
MAX_DEPTH = 2


def thumbnail_dir() -> Path:
    return cache_dir() / "thumbnails"


#: The folder displaywright keeps its own copies in, under the user's pictures
#: directory. Named for the app so it is obvious who created it.
WALLPAPER_FOLDER_NAME = "Displaywright"

#: What wallwright called the same folder. Offered alongside the current one so
#: an unmigrated collection still shows up in the picker.
LEGACY_FOLDER_NAME = "Wallwright"


def _xdg_user_dir(key: str) -> Path | None:
    """One entry from xdg-user-dirs, e.g. ``XDG_PICTURES_DIR``.

    The environment wins when it is set; otherwise the file xdg-user-dirs
    writes is parsed, which is where a localised or relocated Pictures folder
    is actually recorded.
    """
    env = os.environ.get(key)
    if env:
        return Path(os.path.expandvars(env)).expanduser()
    try:
        text = (config_home() / "user-dirs.dirs").read_text(encoding="utf-8")
    except OSError:
        return None
    prefix = f"{key}="
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith(prefix):
            continue
        value = line[len(prefix):].strip().strip('"').strip("'")
        if not value:
            return None
        return Path(value.replace("$HOME", str(Path.home()))).expanduser()
    return None


def pictures_dir() -> Path:
    return _xdg_user_dir("XDG_PICTURES_DIR") or (Path.home() / "Pictures")


def wallpaper_dir() -> Path:
    """Where a picked file is copied to, so the wallpaper outlives the original."""
    return pictures_dir() / WALLPAPER_FOLDER_NAME


def ensure_wallpaper_dir() -> Path:
    path = wallpaper_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_folders() -> list[Path]:
    """The folders the picker offers before the user adds any of their own.

    Just displaywright's own. Offering the whole of ~/Pictures as well turned the
    grid into a dump of screenshots, and there is no need for it: a file picked
    from anywhere else is copied in on the way past, so the folder fills itself
    up with exactly the pictures the user chose. Anything more is one
    "Add folder" away.
    """
    folders = [wallpaper_dir(), pictures_dir() / LEGACY_FOLDER_NAME]
    return [f for f in folders if f.is_dir()]


@dataclass(frozen=True)
class Entry:
    path: Path
    kind: Kind

    @property
    def name(self) -> str:
        return self.path.stem.replace("-", " ").replace("_", " ").strip()


def scan(folders: Iterable[Path], include_video: bool = True) -> list[Entry]:
    """Every drawable file under those folders, de-duplicated and sorted."""
    wanted = set(IMAGE_SUFFIXES) | (set(VIDEO_SUFFIXES) if include_video else set())
    seen: set[Path] = set()
    entries: list[Entry] = []
    for folder in folders:
        for path in _walk(Path(folder), wanted):
            try:
                real = path.resolve()
            except OSError:
                continue
            if real in seen:
                continue
            seen.add(real)
            kind = kind_for_path(path)
            if kind is not None:
                entries.append(Entry(path=path, kind=kind))
    entries.sort(key=lambda e: (e.path.parent.as_posix(), e.path.name.lower()))
    return entries


def _walk(folder: Path, wanted: set[str], depth: int = 0) -> Iterator[Path]:
    if depth > MAX_DEPTH:
        return
    try:
        children = sorted(folder.iterdir())
    except OSError:
        return
    for child in children:
        if child.name.startswith("."):
            continue
        try:
            if child.is_dir():
                yield from _walk(child, wanted, depth + 1)
            elif child.suffix.lower() in wanted:
                yield child
        except OSError:
            continue


def thumbnail_path(path: Path, size: int = THUMBNAIL_SIZE) -> Path:
    """Cache location for one file's thumbnail, keyed by its identity."""
    try:
        stat = path.stat()
        stamp = f"{stat.st_size}:{int(stat.st_mtime)}"
    except OSError:
        stamp = "0:0"
    digest = hashlib.sha256(f"{path.resolve()}|{stamp}|{size}".encode()).hexdigest()
    return thumbnail_dir() / f"{digest}.png"


def ensure_thumbnail(path: Path, size: int = THUMBNAIL_SIZE) -> Path | None:
    """Return a cached thumbnail for ``path``, making one if needed.

    Returns None when the file cannot be decoded -- a broken JPEG in a folder
    should leave a gap in the grid, not take the window down with it.
    """
    target = thumbnail_path(path, size)
    if target.is_file():
        return target

    kind = kind_for_path(path)
    if kind is None:
        return None

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_sibling(target)
    try:
        if kind == Kind.VIDEO:
            if not _grab_video_frame(path, tmp, size):
                return None
        else:
            import gi

            gi.require_version("GdkPixbuf", "2.0")
            from gi.repository import GdkPixbuf

            pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_scale(str(path), size, size, True)
            pixbuf.savev(str(tmp), "png", [], [])
        tmp.replace(target)
        return target
    except Exception:
        return None
    finally:
        tmp.unlink(missing_ok=True)


def _grab_video_frame(path: Path, target: Path, size: int) -> bool:
    """One frame from a video, for the picker grid. Needs ffmpeg."""
    import shutil
    import subprocess

    if shutil.which("ffmpeg") is None:
        return False
    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-loglevel", "error", "-y",
                # A second in, so a title card that fades up from black does not
                # become an all-black thumbnail.
                "-ss", "1", "-i", str(path), "-frames:v", "1",
                "-vf", f"scale={size}:{size}:force_original_aspect_ratio=decrease",
                str(target),
            ],
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and target.is_file()


def theme_background() -> Path | None:
    """The picture Omarchy's theme currently points at, if any.

    Outputs displaywright has no opinion about draw this, so the preview needs it
    to show them honestly rather than as empty rectangles.
    """
    link = state_home() / "omarchy" / "current" / "background"
    try:
        resolved = link.resolve()
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def image_size(path: Path) -> tuple[int, int] | None:
    """A file's pixel dimensions without decoding it.

    Centre and Tile are defined in terms of the file's own resolution, so the
    preview cannot use the thumbnail's size and be truthful about either.
    """
    try:
        import gi

        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf

        info, width, height = GdkPixbuf.Pixbuf.get_file_info(str(path))
    except Exception:
        return None
    if info is None or width <= 0 or height <= 0:
        return None
    return width, height


def is_inside(path: Path, folder: Path) -> bool:
    try:
        return path.resolve().is_relative_to(folder.expanduser().resolve())
    except (OSError, ValueError):
        return False


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _same_contents(left: Path, right: Path) -> bool:
    try:
        if left.stat().st_size != right.stat().st_size:
            return False
    except OSError:
        return False
    return _digest(left) == _digest(right)


def _unused_name(folder: Path, source: Path) -> Path:
    """A free filename in ``folder`` for ``source``, suffixed if it has to be."""
    candidate = folder / source.name
    if not candidate.exists():
        return candidate
    stem, suffix = source.stem, source.suffix
    for n in range(2, 1000):
        candidate = folder / f"{stem}-{n}{suffix}"
        if not candidate.exists():
            return candidate
    raise OSError(f"no free name for {source.name} in {folder}")


@dataclass(frozen=True)
class Adoption:
    """What :func:`adopt` did. ``copied`` is false when nothing was written."""

    path: Path
    copied: bool = False
    #: True when an identical file was already in the wallpaper folder.
    reused: bool = False

    def describe(self) -> str:
        if self.copied:
            return f"copied to {self.path}"
        if self.reused:
            return f"already in your wallpaper folder: {self.path}"
        return ""


def adopt(path: Path, folders: Iterable[Path] | None = None) -> Adoption:
    """Copy a picked file into the wallpaper folder and report where it landed.

    The point is that a wallpaper should not break when the file it came from
    is moved out of ``~/Downloads`` or emptied out of ``/tmp``.

    Files the picker can already see are left where they are -- clicking a
    thumbnail must not clone what the grid is showing. A file whose contents
    are already in the folder resolves to that copy instead of a second one, so
    picking the same download twice does not accumulate duplicates.

    Raises ``OSError`` if the copy fails; callers are expected to fall back to
    the original path rather than refuse to set a wallpaper.
    """
    source = Path(path).expanduser()
    if not source.is_file():
        return Adoption(source)

    known = list(folders) if folders is not None else default_folders()
    known.append(wallpaper_dir())
    if any(is_inside(source, folder) for folder in known):
        return Adoption(source)

    target_dir = ensure_wallpaper_dir()
    for existing in sorted(target_dir.iterdir()):
        if existing.is_file() and _same_contents(source, existing):
            return Adoption(existing, reused=True)

    target = _unused_name(target_dir, source)
    # Copy to a temporary name first: the folder is one the picker scans, and a
    # half-written file there would be offered as a wallpaper.
    tmp = temp_sibling(target, "part")
    try:
        shutil.copy2(source, tmp)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
    return Adoption(target, copied=True)
