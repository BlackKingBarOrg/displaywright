"""Geometry for one image stretched across every display.

Windows calls this fit "Span". The image covers the bounding box of all the
outputs, and each output shows whatever part of that box it happens to sit on.

Two consequences worth knowing before you use it:

* Displays are rarely flush. A laptop panel sitting hundreds of logical pixels
  below the top of an external one makes the bounding box taller than either
  display, and a band of the image falls in the gap between them, where nothing
  can draw it. :func:`coverage` reports how much of the image lands on glass.
* The renderer computes the same box from Quickshell's own screen list rather
  than reading it from the config, so moving a display re-cuts the image
  without displaywright having to be running.

The boxes here are :class:`~displaywright.model.Rect` in logical coordinates --
the same type and the same space the arrangement half snaps displays in.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from itertools import pairwise

from ..model import MonitorState, Rect, bounding_box


def _live(outputs: Sequence[MonitorState]) -> list[MonitorState]:
    """Only lit displays: a disabled one has no surface to draw into."""
    return [o for o in outputs if o.enabled]


def span_box(outputs: Sequence[MonitorState]) -> Rect | None:
    """The smallest box containing every lit output, in logical coordinates."""
    live = _live(outputs)
    if not live:
        return None
    return bounding_box([o.rect for o in live])


def offsets(outputs: Sequence[MonitorState]) -> dict[str, tuple[int, int]]:
    """Where each output sits inside the bounding box.

    The renderer draws a box-sized image at ``(-dx, -dy)`` within each output's
    surface, which lines the pieces up into one picture across the desktop.
    """
    box = span_box(outputs)
    if box is None:
        return {}
    return {o.name: (round(o.x - box.x), round(o.y - box.y)) for o in _live(outputs)}


def coverage(outputs: Sequence[MonitorState]) -> float:
    """Fraction of the spanned image that lands on a display, 0..1.

    Overlapping outputs (a mirrored pair) would double-count, so the covered
    area is measured by sweeping distinct x bands rather than by summing.
    """
    box = span_box(outputs)
    if box is None or box.w * box.h == 0:
        return 0.0
    return _union_area(_live(outputs)) / (box.w * box.h)


def _union_area(outputs: Iterable[MonitorState]) -> float:
    """Area covered by at least one output, counting overlaps once."""
    rects = [o.rect for o in outputs if o.rect.w > 0 and o.rect.h > 0]
    if not rects:
        return 0.0
    xs = sorted({edge for r in rects for edge in (r.x, r.right)})
    total = 0.0
    for left, right in pairwise(xs):
        strip = right - left
        if strip <= 0:
            continue
        spans = sorted((r.y, r.bottom) for r in rects if r.x < right and r.right > left)
        covered = 0.0
        cursor: float | None = None
        end = 0.0
        for y1, y2 in spans:
            if cursor is None or y1 > end:
                if cursor is not None:
                    covered += end - cursor
                cursor, end = y1, y2
            else:
                end = max(end, y2)
        if cursor is not None:
            covered += end - cursor
        total += strip * covered
    return total
