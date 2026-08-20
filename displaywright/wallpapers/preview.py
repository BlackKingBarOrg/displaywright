"""Where a picture lands inside a rectangle, for each fit.

The GUI draws the same arithmetic the renderer does, so what the preview shows
is what the display gets. Keeping it here -- pure, in logical pixels, with no
toolkit types -- is what makes that claim testable rather than aspirational.

Everything is in *logical* pixels, the coordinate space Hyprland lays displays
out in. Two fits are defined in device pixels instead: Center draws the file at
its own resolution and Tile repeats it at its own resolution, so both take the
output's device pixel ratio and divide through by it.
"""

from __future__ import annotations

from .model import Fit


def natural_size(image: tuple[float, float], dpr: float = 1.0) -> tuple[float, float]:
    """The size a 1:1 rendering of the file occupies, in logical pixels."""
    scale = dpr if dpr > 0 else 1.0
    return image[0] / scale, image[1] / scale


def fitted_rect(
    fit: Fit,
    image: tuple[float, float],
    box: tuple[float, float],
    dpr: float = 1.0,
) -> tuple[float, float, float, float]:
    """``(x, y, width, height)`` of the drawn image, relative to the box.

    A negative x or y means the picture overflows and gets cropped, which is
    what Fill does on every display whose aspect ratio differs from the file's.
    """
    iw, ih = image
    bw, bh = box
    if iw <= 0 or ih <= 0 or bw <= 0 or bh <= 0:
        return 0.0, 0.0, bw, bh

    if fit is Fit.STRETCH:
        return 0.0, 0.0, bw, bh

    if fit is Fit.CENTER:
        w, h = natural_size(image, dpr)
        return (bw - w) / 2, (bh - h) / 2, w, h

    if fit is Fit.TILE:
        # The tile itself; the caller repeats it from the top-left corner.
        w, h = natural_size(image, dpr)
        return 0.0, 0.0, w, h

    # Fill crops to cover, Fit letterboxes to contain. Both keep the aspect.
    scale = max(bw / iw, bh / ih) if fit is Fit.FILL else min(bw / iw, bh / ih)
    w, h = iw * scale, ih * scale
    return (bw - w) / 2, (bh - h) / 2, w, h


def span_rect(
    image: tuple[float, float],
    box: tuple[float, float],
    offset: tuple[float, float],
) -> tuple[float, float, float, float]:
    """Where a spanned picture sits relative to *one* output's top-left corner.

    ``box`` is the bounding box of every output and ``offset`` is where this
    output sits inside it. The picture covers the whole box the way Fill covers
    one display, and each output shows the slice that falls on it.
    """
    x, y, w, h = fitted_rect(Fit.FILL, image, box)
    return x - offset[0], y - offset[1], w, h
