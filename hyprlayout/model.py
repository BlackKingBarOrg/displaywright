"""Monitor data model.

Everything the GUI edits lives in :class:`MonitorState`.  A state is a *desired*
configuration: it starts as a copy of what Hyprland currently reports and is
mutated by the canvas and the sidebar until the user applies it.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

# transform -> (label, rotates 90 degrees?)
TRANSFORMS: dict[int, tuple[str, bool]] = {
    0: ("Normal", False),
    1: ("90°", True),
    2: ("180°", False),
    3: ("270°", True),
    4: ("Flipped", False),
    5: ("Flipped + 90°", True),
    6: ("Flipped + 180°", False),
    7: ("Flipped + 270°", True),
}

def lua_string(value: str) -> str:
    """Quote a value for Lua source."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


_MODE_RE = re.compile(
    r"^\s*(?P<w>\d+)\s*x\s*(?P<h>\d+)\s*(?:@\s*(?P<r>[\d.]+)\s*(?:Hz)?)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True, order=True)
class Mode:
    """A single output mode, e.g. ``3440x1440@50.00Hz``."""

    width: int
    height: int
    refresh: float = 0.0

    @classmethod
    def parse(cls, text: str) -> Mode | None:
        m = _MODE_RE.match(text)
        if not m:
            return None
        return cls(
            int(m.group("w")),
            int(m.group("h")),
            float(m.group("r")) if m.group("r") else 0.0,
        )

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    def hypr(self) -> str:
        """The form Hyprland accepts in a monitor rule."""
        if not self.refresh:
            return self.resolution
        # Hyprland matches refresh rates with a tolerance, so two decimals is
        # plenty -- and dropping a trailing ".00" keeps generated config tidy.
        text = f"{self.refresh:.2f}"
        if text.endswith(".00"):
            text = text[:-3]
        return f"{self.resolution}@{text}"

    def label(self) -> str:
        if not self.refresh:
            return f"{self.width}×{self.height}"
        return f"{self.width}×{self.height} @ {self.refresh:g} Hz"


@dataclass
class MonitorState:
    """Desired configuration for one output."""

    name: str
    description: str = ""
    make: str = ""
    model: str = ""
    serial: str = ""

    physical_width: int = 0  # mm, as reported by the EDID
    physical_height: int = 0

    enabled: bool = True
    mode: Mode | None = None  # None -> "preferred"
    scale: float = 1.0
    transform: int = 0
    x: int = 0
    y: int = 0
    vrr: int | None = None  # None -> inherit the global setting
    mirror_of: str | None = None

    available_modes: list[Mode] = field(default_factory=list)
    connected: bool = True

    # ---------------------------------------------------------------- geometry

    @property
    def pixel_size(self) -> tuple[int, int]:
        """Native pixel size of the selected mode, before rotation/scaling."""
        if self.mode is not None:
            return self.mode.width, self.mode.height
        if self.available_modes:
            best = self.preferred_mode()
            return best.width, best.height
        return 1920, 1080

    def preferred_mode(self) -> Mode:
        """Highest resolution, then highest refresh -- Hyprland's own choice."""
        if not self.available_modes:
            return Mode(1920, 1080, 60.0)
        return max(self.available_modes, key=lambda m: (m.width * m.height, m.refresh))

    @property
    def rotated(self) -> bool:
        return TRANSFORMS.get(self.transform, ("", False))[1]

    @property
    def logical_size(self) -> tuple[float, float]:
        """Size in layout (logical) coordinates, after rotation and scaling."""
        w, h = self.pixel_size
        if self.rotated:
            w, h = h, w
        scale = self.scale or 1.0
        return w / scale, h / scale

    @property
    def rect(self) -> Rect:
        w, h = self.logical_size
        return Rect(float(self.x), float(self.y), w, h)

    @property
    def diagonal_inches(self) -> float:
        """0.0 when the EDID does not report a physical size."""
        if self.physical_width <= 0 or self.physical_height <= 0:
            return 0.0
        return math.hypot(self.physical_width, self.physical_height) / 25.4

    @property
    def dpi(self) -> float:
        """Native pixel density, or 0.0 if the physical size is unknown."""
        if self.physical_width <= 0:
            return 0.0
        px_w, _ = self.pixel_size
        return px_w / (self.physical_width / 25.4)

    # ------------------------------------------------------------------ labels

    @property
    def pretty_name(self) -> str:
        parts = [p for p in (self.make, self.model) if p and not p.startswith("0x")]
        if parts:
            return " ".join(parts)
        return self.description or self.name

    def summary(self) -> str:
        if not self.enabled:
            return "disabled"
        if self.mirror_of:
            return f"mirrors {self.mirror_of}"
        w, h = self.logical_size
        bits = [self.mode.label() if self.mode else "preferred"]
        if abs(self.scale - 1.0) > 1e-6:
            bits.append(f"scale {self.scale:g} → {round(w)}×{round(h)}")
        if self.transform:
            bits.append(TRANSFORMS[self.transform][0])
        return " · ".join(bits)

    # ------------------------------------------------------------------- misc

    def copy(self) -> MonitorState:
        return replace(self, available_modes=list(self.available_modes))

    def config_equals(self, other: MonitorState) -> bool:
        """Compare only the fields we actually push to Hyprland."""
        keys = ("enabled", "mode", "scale", "transform", "x", "y", "vrr", "mirror_of")
        return all(getattr(self, k) == getattr(other, k) for k in keys)

    # ------------------------------------------------------------- hyprland I/O

    @classmethod
    def from_hyprctl(cls, data: dict) -> MonitorState:
        """Build a state from one entry of ``hyprctl monitors all -j``."""
        modes: list[Mode] = []
        for raw in data.get("availableModes", []) or []:
            parsed = Mode.parse(raw)
            if parsed is not None and parsed not in modes:
                modes.append(parsed)
        modes.sort(key=lambda m: (m.width * m.height, m.refresh), reverse=True)

        disabled = bool(data.get("disabled", False))
        scale = float(data.get("scale") or 1.0)
        transform = int(data.get("transform") or 0)

        mode: Mode | None = None
        width, height = int(data.get("width") or 0), int(data.get("height") or 0)
        if width and height:
            # hyprctl reports the *rotated* size; undo that to recover the mode.
            if TRANSFORMS.get(transform, ("", False))[1]:
                width, height = height, width
            mode = Mode(width, height, float(data.get("refreshRate") or 0.0))
            mode = _closest_mode(mode, modes) or mode
            # NB: if the running refresh rate is not advertised at all (link
            # bandwidth limits do this on high-res ultrawides), _closest_mode
            # keeps the reported rate rather than silently retuning the panel.

        mirror = data.get("mirrorOf") or "none"
        return cls(
            name=data.get("name", "?"),
            description=data.get("description", ""),
            make=data.get("make", ""),
            model=data.get("model", ""),
            serial=data.get("serial", ""),
            physical_width=int(data.get("physicalWidth") or 0),
            physical_height=int(data.get("physicalHeight") or 0),
            enabled=not disabled,
            mode=None if disabled else mode,
            scale=scale if scale > 0 else 1.0,
            transform=transform,
            x=int(data.get("x") or 0),
            y=int(data.get("y") or 0),
            vrr=None,
            mirror_of=None if mirror in ("none", "", None) else mirror,
            available_modes=modes,
            connected=True,
        )

    def rule_args(self) -> str:
        """Comma-separated argument list of a legacy (hyprlang) monitor rule."""
        if not self.enabled:
            return f"{self.name},disable"
        mode = self.mode.hypr() if self.mode else "preferred"
        parts = [self.name, mode, f"{self.x}x{self.y}", f"{self.scale:g}"]
        if self.transform:
            parts += ["transform", str(self.transform)]
        if self.mirror_of:
            parts += ["mirror", self.mirror_of]
        if self.vrr is not None:
            parts += ["vrr", str(self.vrr)]
        return ",".join(parts)

    def lua_call(self) -> str:
        """``hl.monitor({ ... })`` -- the Lua form of the same rule.

        Field names come from Hyprland's own ``HL.MonitorSpec`` stub.  This is
        both what gets written to monitors.lua and what gets sent to a running
        Lua-configured Hyprland via ``hyprctl eval``.
        """
        fields = [f"output = {lua_string(self.name)}"]
        if not self.enabled:
            fields.append("disabled = true")
        else:
            fields.append(
                f"mode = {lua_string(self.mode.hypr() if self.mode else 'preferred')}"
            )
            fields.append(f"position = {lua_string(f'{self.x}x{self.y}')}")
            fields.append(f"scale = {self.scale:g}")
            if self.transform:
                fields.append(f"transform = {self.transform}")
            if self.mirror_of:
                fields.append(f"mirror = {lua_string(self.mirror_of)}")
            if self.vrr is not None:
                fields.append(f"vrr = {self.vrr}")
        return "hl.monitor({ " + ", ".join(fields) + " })"


#: How far a reported refresh rate may drift from an advertised one and still be
#: considered the same mode. Covers 99.99-vs-100 rounding, nothing more.
REFRESH_TOLERANCE = 1.5


def _closest_mode(target: Mode, modes: Iterable[Mode], tolerance: float = REFRESH_TOLERANCE) -> Mode | None:
    """Match a reported mode back to the advertised list.

    Returns ``None`` when no advertised mode is within ``tolerance`` Hz, so a
    genuinely off-list rate (e.g. a 50Hz link-limited ultrawide) is preserved
    verbatim instead of being rewritten to a neighbouring rate.
    """
    same_res = [m for m in modes if m.width == target.width and m.height == target.height]
    if not same_res:
        return None
    best = min(same_res, key=lambda m: abs(m.refresh - target.refresh))
    if target.refresh and abs(best.refresh - target.refresh) > tolerance:
        return None
    return best


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    def contains(self, px: float, py: float) -> bool:
        return self.x <= px <= self.right and self.y <= py <= self.bottom

    def overlaps(self, other: Rect, tol: float = 0.5) -> bool:
        return (
            self.x < other.right - tol
            and other.x < self.right - tol
            and self.y < other.bottom - tol
            and other.y < self.bottom - tol
        )

    def moved(self, x: float, y: float) -> Rect:
        return Rect(x, y, self.w, self.h)


def bounding_box(rects: Iterable[Rect]) -> Rect:
    rects = list(rects)
    if not rects:
        return Rect(0, 0, 0, 0)
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.right for r in rects)
    y1 = max(r.bottom for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def scale_warning(state: MonitorState) -> str | None:
    """Hyprland nudges scales that do not yield an integer logical size."""
    if not state.enabled:
        return None
    w, h = state.logical_size
    for value, axis in ((w, "width"), (h, "height")):
        if abs(value - round(value)) > 0.001:
            return (
                f"scale {state.scale:g} gives a fractional logical {axis} "
                f"({value:.3f}px) — Hyprland will nudge it to the nearest usable scale"
            )
    return None


#: Scales worth suggesting. Hyprland accepts arbitrary values, but these are the
#: ones that stay predictable across toolkits.
COMMON_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0)

#: Effective DPI that lands on comfortable text at a normal viewing distance.
TARGET_DPI = 110.0


def suggest_scale(state: MonitorState) -> float:
    """Pick a scale that puts this panel near :data:`TARGET_DPI`.

    Uses the EDID physical size when the panel reports one -- density, not
    resolution, is what decides how big text ends up.  Scales that would give a
    fractional logical size are avoided unless nothing else fits.
    """
    px_w, px_h = state.pixel_size
    dpi = state.dpi
    if dpi <= 0:
        # No physical size: tall-and-dense panels are the ones that need 2x.
        return 2.0 if px_h >= 1800 else 1.0

    def integral(scale: float) -> bool:
        return all(abs(px / scale - round(px / scale)) < 0.001 for px in (px_w, px_h))

    candidates = [s for s in COMMON_SCALES if integral(s)] or list(COMMON_SCALES)
    return min(candidates, key=lambda s: abs(dpi / s - TARGET_DPI))
