"""Cairo odds and ends both canvases need.

Nothing here knows what a monitor is. It is the small shared vocabulary --
rounded corners, the desktop's accent colour, the hatch that means "nothing
here" -- that keeps the arrangement view and the wallpaper view looking like
one program rather than two that happen to share a window.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gtk, Pango, PangoCairo

#: Used when the style context has no accent colour, which happens in a
#: headless test and on very old libadwaita.
FALLBACK_ACCENT = "#3584e4"


def rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()


def accent(style: Gtk.StyleContext) -> Gdk.RGBA:
    ok, rgba = style.lookup_color("accent_color")
    if ok:
        return rgba
    fallback = Gdk.RGBA()
    fallback.parse(FALLBACK_ACCENT)
    return fallback


def paint_hatch(cr, x: float, y: float, w: float, h: float) -> None:
    """The flat grey that stands in for a picture we could not draw."""
    cr.set_source_rgba(0.5, 0.5, 0.5, 0.18)
    cr.rectangle(x, y, w, h)
    cr.fill()


def draw_centered(cr, width: float, height: float, text: str, rgb: tuple[float, float, float]) -> None:
    """One line of text in the middle of the widget, for empty states."""
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(Pango.FontDescription("Sans 11"))
    layout.set_text(text, -1)
    ink = layout.get_pixel_extents()[1]
    cr.set_source_rgb(*rgb)
    cr.move_to((width - ink.width) / 2, (height - ink.height) / 2)
    PangoCairo.show_layout(cr, layout)


class Palette:
    """Flat colour set for the arrangement view, swapped wholesale for dark mode.

    The wallpaper view draws over pictures instead and takes its two colours
    from the style context, so it has no use for this.
    """

    def __init__(self, dark: bool) -> None:
        if dark:
            self.bg = (0.11, 0.12, 0.14)
            self.grid = (0.17, 0.18, 0.21)
            self.tile = (0.20, 0.23, 0.29)
            self.tile_selected = (0.16, 0.28, 0.42)
            self.tile_disabled = (0.15, 0.16, 0.18)
            self.border = (0.35, 0.38, 0.44)
            self.border_selected = (0.42, 0.66, 0.96)
            self.text = (0.93, 0.94, 0.96)
            self.text_dim = (0.66, 0.69, 0.74)
            self.guide = (0.42, 0.66, 0.96)
        else:
            self.bg = (0.96, 0.96, 0.97)
            self.grid = (0.90, 0.90, 0.92)
            self.tile = (0.85, 0.87, 0.90)
            self.tile_selected = (0.79, 0.87, 0.98)
            self.tile_disabled = (0.91, 0.91, 0.92)
            self.border = (0.60, 0.63, 0.68)
            self.border_selected = (0.18, 0.45, 0.80)
            self.text = (0.13, 0.14, 0.16)
            self.text_dim = (0.40, 0.43, 0.48)
            self.guide = (0.18, 0.45, 0.80)
