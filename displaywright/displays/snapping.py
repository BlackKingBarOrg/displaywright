"""Layout geometry: edge snapping, collision push-out and sanity checks.

All coordinates here are Hyprland *logical* pixels -- the same space monitor
positions live in -- so the numbers the canvas produces can go straight into a
monitor rule.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from ..model import MonitorState, Rect, bounding_box

# How close (in logical px) an edge has to be before it snaps.  Generous,
# because the canvas is heavily zoomed out: 120px of layout space is only a few
# px of mouse travel on a 3440-wide desktop drawn 600px wide.
SNAP_THRESHOLD = 120.0


@dataclass
class SnapResult:
    x: int
    y: int
    #: guides to draw: ("v", coordinate) for vertical, ("h", coordinate)
    guides: list[tuple[str, float]] = field(default_factory=list)


def _candidates(pos: float, size: float, others: Sequence[Rect], axis: str) -> list[tuple[float, float]]:
    """Candidate positions for one axis as ``(position, guide_coordinate)``."""
    out: list[tuple[float, float]] = []
    for o in others:
        if axis == "x":
            lo, hi, o_size = o.x, o.right, o.w
        else:
            lo, hi, o_size = o.y, o.bottom, o.h
        center = lo + o_size / 2
        out += [
            (hi, hi),                        # attach after
            (lo - size, lo),                 # attach before
            (lo, lo),                        # align leading edges
            (hi - size, hi),                 # align trailing edges
            (center - size / 2, center),     # align centres
        ]
    return out


def snap_position(
    moving: Rect,
    others: Sequence[Rect],
    threshold: float = SNAP_THRESHOLD,
) -> SnapResult:
    """Snap ``moving`` to the nearest edges of ``others``.

    Each axis is snapped independently, which is what makes "drag roughly to the
    right and let go" produce a pixel-perfect side-by-side layout.
    """
    x, y = moving.x, moving.y
    guides: list[tuple[str, float]] = []

    if others:
        best_x = min(
            _candidates(moving.x, moving.w, others, "x"),
            key=lambda c: abs(c[0] - moving.x),
            default=None,
        )
        if best_x is not None and abs(best_x[0] - moving.x) <= threshold:
            x = best_x[0]
            guides.append(("v", best_x[1]))

        best_y = min(
            _candidates(moving.y, moving.h, others, "y"),
            key=lambda c: abs(c[0] - moving.y),
            default=None,
        )
        if best_y is not None and abs(best_y[0] - moving.y) <= threshold:
            y = best_y[0]
            guides.append(("h", best_y[1]))

    return SnapResult(round(x), round(y), guides)


def push_out(moving: Rect, others: Sequence[Rect]) -> tuple[int, int]:
    """Resolve overlap by shifting ``moving`` along its cheapest escape axis."""
    x, y = moving.x, moving.y
    for _ in range(len(others) + 1):
        current = moving.moved(x, y)
        hit = next((o for o in others if current.overlaps(o)), None)
        if hit is None:
            break
        # Four ways out; take the shortest.
        options = [
            (hit.right - current.x, (hit.right, y)),
            (current.right - hit.x, (hit.x - current.w, y)),
            (hit.bottom - current.y, (x, hit.bottom)),
            (current.bottom - hit.y, (x, hit.y - current.h)),
        ]
        _, (x, y) = min(options, key=lambda o: o[0])
    return round(x), round(y)


def snap_and_resolve(
    moving: Rect,
    others: Sequence[Rect],
    threshold: float = SNAP_THRESHOLD,
) -> SnapResult:
    """Snap, then guarantee the result does not overlap anything."""
    snapped = snap_position(moving, others, threshold)
    x, y = push_out(moving.moved(snapped.x, snapped.y), others)
    if (x, y) != (snapped.x, snapped.y):
        # Pushing out invalidates the guides we were about to draw.
        return SnapResult(x, y, [])
    return snapped


# --------------------------------------------------------------------- layout ops


def normalize(states: Iterable[MonitorState]) -> bool:
    """Shift everything so the top-left of the desktop sits at (0, 0).

    Returns True if anything moved.  Hyprland accepts negative coordinates, but
    keeping the origin at zero makes generated config far easier to read.
    """
    states = [s for s in states if s.enabled]
    if not states:
        return False
    box = bounding_box([s.rect for s in states])
    dx, dy = -round(box.x), -round(box.y)
    if dx == 0 and dy == 0:
        return False
    for s in states:
        s.x += dx
        s.y += dy
    return True


def auto_arrange(states: Iterable[MonitorState]) -> None:
    """Lay the enabled monitors out left to right, vertically centred."""
    enabled = [s for s in states if s.enabled]
    if not enabled:
        return
    enabled.sort(key=lambda s: (s.x, s.y))
    tallest = max(s.logical_size[1] for s in enabled)
    cursor = 0.0
    for s in enabled:
        w, h = s.logical_size
        # Positions must stay integral: Hyprland parses "1600x0", not "1600.0x0".
        s.x = round(cursor)
        s.y = round((tallest - h) / 2)
        cursor += w


def _touches(a: Rect, b: Rect, tol: float = 1.0) -> bool:
    """True when two rectangles share a border segment of non-zero length."""
    vertical_touch = (
        abs(a.right - b.x) <= tol or abs(b.right - a.x) <= tol
    ) and min(a.bottom, b.bottom) - max(a.y, b.y) > tol
    horizontal_touch = (
        abs(a.bottom - b.y) <= tol or abs(b.bottom - a.y) <= tol
    ) and min(a.right, b.right) - max(a.x, b.x) > tol
    return vertical_touch or horizontal_touch


def validate(states: Sequence[MonitorState]) -> list[str]:
    """Human-readable problems with a layout; empty list means all good."""
    problems: list[str] = []
    enabled = [s for s in states if s.enabled]

    if not enabled:
        problems.append("Every display is disabled — you would end up with a black screen.")
        return problems

    for i, a in enumerate(enabled):
        for b in enabled[i + 1 :]:
            if a.rect.overlaps(b.rect):
                problems.append(f"{a.name} and {b.name} overlap.")

    # Islands: Hyprland allows gaps, but the pointer cannot cross them.
    if len(enabled) > 1:
        groups: list[set[int]] = []
        for i, a in enumerate(enabled):
            linked = {i}
            for j, b in enumerate(enabled):
                if i != j and _touches(a.rect, b.rect):
                    linked.add(j)
            merged = [g for g in groups if g & linked]
            for g in merged:
                groups.remove(g)
                linked |= g
            groups.append(linked)
        if len(groups) > 1:
            stranded = [
                ", ".join(sorted(enabled[i].name for i in g))
                for g in sorted(groups, key=len)[:-1]
            ]
            problems.append(
                "Not all displays touch — the pointer cannot reach "
                + "; ".join(stranded)
                + "."
            )

    mirrors = {s.name for s in states}
    for s in states:
        if s.mirror_of and s.mirror_of not in mirrors:
            problems.append(f"{s.name} mirrors unknown output {s.mirror_of}.")
        if s.mirror_of == s.name:
            problems.append(f"{s.name} cannot mirror itself.")

    return problems
