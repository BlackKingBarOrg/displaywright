"""What a wallpaper is and where it goes.

A :class:`Source` is one thing to draw.  Today that is a still image or a flat
colour; the renderer dispatches on ``kind``, so video, web and shader sources
slot in beside them without changing the shape of the config file.

A :class:`Config` binds sources to outputs.  Two things can claim an output:

* ``monitors[name]`` — that output alone shows that source.
* ``span`` — one source stretched across every output at once, the way
  Windows' "Span" fit works.  It wins over the per-output entries.

An output with no claim is *unpinned* and keeps following the Omarchy theme
background, which is what the user chose when they left it alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path

CONFIG_VERSION = 1


class Fit(StrEnum):
    """How a source is mapped onto an output. Names follow Windows'.

    ``SPAN`` is deliberately absent: spanning is a property of the whole
    desktop rather than of one output, so it lives in :attr:`Config.span`.
    """

    FILL = "fill"
    FIT = "fit"
    STRETCH = "stretch"
    TILE = "tile"
    CENTER = "center"

    @property
    def label(self) -> str:
        return _FIT_LABELS[self]

    @property
    def uses_backdrop(self) -> bool:
        """True when the fit can leave bare space that the backdrop shows through."""
        return self in (Fit.FIT, Fit.CENTER)


_FIT_LABELS: dict[Fit, str] = {
    Fit.FILL: "Fill",
    Fit.FIT: "Fit",
    Fit.STRETCH: "Stretch",
    Fit.TILE: "Tile",
    Fit.CENTER: "Center",
}


class Kind(StrEnum):
    IMAGE = "image"
    COLOR = "color"
    VIDEO = "video"
    #: Reserved for the live-wallpaper work. The renderer refuses them for now
    #: rather than silently drawing nothing, so a config written by a newer
    #: build is legible instead of mysterious.
    WEB = "web"
    SHADER = "shader"


#: Extensions the still-image renderer accepts. Qt reads more than this, but
#: these are the ones worth offering in a file picker.
IMAGE_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".avif", ".jxl"})
VIDEO_SUFFIXES = frozenset({".mp4", ".webm", ".mkv", ".mov", ".m4v"})

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")

DEFAULT_BACKDROP = "#000000"


def kind_for_path(path: str | Path) -> Kind | None:
    """Guess a source kind from a filename, or None if we would not draw it."""
    suffix = Path(path).suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return Kind.IMAGE
    if suffix in VIDEO_SUFFIXES:
        return Kind.VIDEO
    return None


def is_color(value: str) -> bool:
    return bool(_HEX_RE.match(value or ""))


@dataclass
class Source:
    """One drawable thing, plus how it sits on the output showing it."""

    kind: Kind = Kind.IMAGE
    path: str = ""
    fit: Fit = Fit.FILL
    #: Shown wherever the source does not reach: the bars of a Fit, the margin
    #: of a Center. Ignored by fits that always cover the output.
    backdrop: str = DEFAULT_BACKDROP
    #: Kind.COLOR only.
    color: str = DEFAULT_BACKDROP
    #: Kind.VIDEO only. Muted by default -- a wallpaper that makes noise is a
    #: bug report waiting to happen.
    mute: bool = True
    volume: float = 0.0
    #: Stop decoding while something is drawn over the whole output. Video
    #: wallpaper is the one kind that costs power when nobody can see it.
    pause_when_covered: bool = True

    def to_json(self) -> dict:
        data: dict = {"kind": str(self.kind)}
        if self.kind == Kind.COLOR:
            data["color"] = self.color
            return data
        data["path"] = self.path
        data["fit"] = str(self.fit)
        if self.fit.uses_backdrop and self.backdrop != DEFAULT_BACKDROP:
            data["backdrop"] = self.backdrop
        if self.kind == Kind.VIDEO:
            data["mute"] = self.mute
            data["volume"] = self.volume
            data["pauseWhenCovered"] = self.pause_when_covered
        return data

    @classmethod
    def from_json(cls, data: object) -> Source | None:
        """Read one entry back. Returns None for anything we cannot draw.

        Unknown kinds and malformed entries are dropped rather than raised on:
        a hand-edited config with one bad line should cost the user that line,
        not their whole desktop.
        """
        if not isinstance(data, dict):
            return None
        try:
            kind = Kind(str(data.get("kind", Kind.IMAGE)))
        except ValueError:
            return None
        try:
            fit = Fit(str(data.get("fit", Fit.FILL)))
        except ValueError:
            fit = Fit.FILL

        color = str(data.get("color") or DEFAULT_BACKDROP)
        backdrop = str(data.get("backdrop") or DEFAULT_BACKDROP)
        if kind == Kind.COLOR:
            if not is_color(color):
                return None
            return cls(kind=kind, color=color)

        path = str(data.get("path") or "")
        if not path:
            return None
        return cls(
            kind=kind,
            path=path,
            fit=fit,
            backdrop=backdrop if is_color(backdrop) else DEFAULT_BACKDROP,
            color=color,
            mute=bool(data.get("mute", True)),
            volume=float(data.get("volume") or 0.0),
            pause_when_covered=bool(data.get("pauseWhenCovered", True)),
        )

    def describe(self) -> str:
        if self.kind == Kind.COLOR:
            return self.color
        return f"{Path(self.path).name} · {self.fit.label}"

    def missing(self) -> bool:
        """True when the source points at a file that is not there any more."""
        return self.kind != Kind.COLOR and not Path(self.path).expanduser().is_file()


@dataclass
class Config:
    """The whole of what displaywright decides about wallpapers. Anything absent follows the theme."""

    monitors: dict[str, Source] = field(default_factory=dict)
    span: Source | None = None
    #: Folders the picker offers. Not read by the renderer -- it lives here so
    #: that one file is the whole of what the user configured.
    folders: list[str] = field(default_factory=list)

    def source_for(self, output: str) -> Source | None:
        """What that output should draw, or None when it follows the theme."""
        if self.span is not None:
            return self.span
        return self.monitors.get(output)

    def is_pinned(self, output: str) -> bool:
        return self.source_for(output) is not None

    def pin(self, output: str, source: Source) -> None:
        self.monitors[output] = source

    def unpin(self, output: str) -> bool:
        return self.monitors.pop(output, None) is not None

    def copy(self) -> Config:
        return Config(
            monitors={name: replace(src) for name, src in self.monitors.items()},
            span=replace(self.span) if self.span else None,
            folders=list(self.folders),
        )

    def to_json(self) -> dict:
        data: dict = {"version": CONFIG_VERSION, "monitors": {}}
        for name, source in sorted(self.monitors.items()):
            data["monitors"][name] = source.to_json()
        if self.span is not None:
            data["span"] = self.span.to_json()
        if self.folders:
            data["folders"] = list(self.folders)
        return data

    @classmethod
    def from_json(cls, data: object) -> Config:
        if not isinstance(data, dict):
            return cls()
        monitors: dict[str, Source] = {}
        raw = data.get("monitors")
        if isinstance(raw, dict):
            for name, entry in raw.items():
                source = Source.from_json(entry)
                if source is not None:
                    monitors[str(name)] = source
        raw_folders = data.get("folders")
        folders = [str(f) for f in raw_folders] if isinstance(raw_folders, list) else []
        return cls(
            monitors=monitors,
            span=Source.from_json(data.get("span")),
            folders=folders,
        )
