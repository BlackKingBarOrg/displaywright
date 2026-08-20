"""The same arrangement, with the wallpapers actually on it.

This is the part that makes the fits legible. Every rectangle is the output's
real position and size -- the geometry comes from
:class:`~displaywright.canvas.DisplayCanvas`, so it is the identical picture the
arrangement page draws -- and the image inside it goes through
:mod:`displaywright.wallpapers.preview`, the same arithmetic the QML renderer
runs. Choosing Center on a 200%-scaled panel therefore looks wrong here in
exactly the way it will look wrong on the glass, before anything is committed.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("GdkPixbuf", "2.0")

import cairo
from gi.repository import Gdk, GdkPixbuf, Pango, PangoCairo

from ..canvas import DisplayCanvas
from ..drawing import accent, paint_hatch, rounded_rect
from ..model import MonitorState
from . import library, preview, span
from .model import Config, Fit, Kind, Source

PADDING = 18.0
#: Two lines of caption plus a little air. Measured at draw time rather than
#: fixed, because the font size follows the desktop's, not ours.
LABEL_GAP = 5
MIN_HEIGHT = 240
#: A portrait display makes the arrangement much taller than it is wide, and a
#: fixed height would shrink every rectangle to a stamp. The canvas grows to
#: suit, up to a point -- past this the picture library has no room left.
MAX_HEIGHT = 340
#: The wallpaper view is a preview, not a workspace: it may draw displays at
#: whatever size fits, without the arrangement view's "never bigger than a
#: third of life size" rule.
MAX_ZOOM = 1.0


class WallpaperCanvas(DisplayCanvas):
    """Draws every lit output with what it is showing, and reports clicks."""

    __gtype_name__ = "DisplaywrightWallpaperCanvas"

    padding = PADDING
    max_zoom = MAX_ZOOM

    def __init__(self) -> None:
        super().__init__()
        self._config = Config()
        self._pixbufs: dict[str, GdkPixbuf.Pixbuf] = {}
        self._sizes: dict[str, tuple[int, int]] = {}
        #: Paths that would not decode. Kept out of the caches above so a
        #: transient failure is retried, but remembered for the rest of this
        #: draw cycle so a genuinely broken file is not re-decoded every frame.
        self._failed: set[str] = set()
        self._theme_path = ""

        self.set_content_height(MIN_HEIGHT)

    # ------------------------------------------------------------------- state

    def set_config(self, states: list[MonitorState], config: Config, selected: str | None) -> None:
        """Everything the view depends on, in one call.

        Selection is pushed in rather than owned here so the arrangement page
        and this one stay on the same display.
        """
        self._config = config
        # Anything that failed last time gets one more chance: the usual reason
        # is a file still being written when it was first drawn.
        self._failed.clear()
        # Assigned rather than pushed through set_states(): the page owns the
        # selection so that both views agree on it, and the base class's
        # "fall back to the first output" rule would fight that.
        self.states = list(states)
        self.selected = selected
        self.set_content_height(self._preferred_height())
        self.queue_draw()

    def forget_thumbnails(self) -> None:
        """Drop the cached pictures, e.g. after the theme background changed."""
        self._pixbufs.clear()
        self._sizes.clear()
        self._failed.clear()
        self.set_content_height(self._preferred_height())
        self.queue_draw()

    def caption_band(self) -> float:
        return float(self._label_height())

    def _line_height(self) -> int:
        _, logical = self.create_pango_layout("Xg").get_pixel_extents()
        return logical.height or 17

    def _label_height(self) -> int:
        return 2 * self._line_height() + LABEL_GAP

    def _preferred_height(self) -> int:
        """Tall enough to show the arrangement at a useful size, within reason."""
        box = span.span_box(self.states)
        if box is None or box.w <= 0 or box.h <= 0:
            return MIN_HEIGHT
        width = self.get_width() or 900
        wanted = (width - 2 * PADDING) * box.h / box.w
        return int(min(MAX_HEIGHT, max(MIN_HEIGHT, wanted + 2 * PADDING + self._label_height())))

    # ---------------------------------------------------------------- pictures

    def _pixbuf(self, path: str) -> GdkPixbuf.Pixbuf | None:
        cached = self._pixbufs.get(path)
        if cached is not None or path in self._failed:
            return cached
        pixbuf = None
        thumb = library.ensure_thumbnail(Path(path))
        if thumb is not None:
            try:
                pixbuf = GdkPixbuf.Pixbuf.new_from_file(str(thumb))
            except Exception:
                pixbuf = None
        if pixbuf is None:
            self._failed.add(path)
            return None
        self._pixbufs[path] = pixbuf
        return pixbuf

    def _natural_size(self, path: str) -> tuple[int, int] | None:
        cached = self._sizes.get(path)
        if cached is not None:
            return cached
        size = library.image_size(Path(path))
        if size is None:
            # A video, or a format GdkPixbuf will not introspect. The
            # thumbnail's aspect ratio is the best guess available, and only
            # Centre and Tile are sensitive to being wrong about it.
            pixbuf = self._pixbuf(path)
            size = (pixbuf.get_width(), pixbuf.get_height()) if pixbuf else None
        if size is None:
            return None
        self._sizes[path] = size
        return size

    # ----------------------------------------------------------------- drawing

    def draw_background(self, cr, width: int, height: int) -> None:
        theme = library.theme_background()
        self._theme_path = str(theme) if theme else ""

    def draw_empty(self, cr, width: int, height: int) -> None:
        fg = self.get_style_context().get_color()
        layout = self.create_pango_layout("No displays found")
        _, logical = layout.get_pixel_extents()
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.5)
        cr.move_to((width - logical.width) / 2, (height - logical.height) / 2)
        PangoCairo.show_layout(cr, layout)

    def draw_tile(self, cr, state: MonitorState, rect: tuple[float, float, float, float]) -> None:
        style = self.get_style_context()
        fg = style.get_color()
        rx, ry, rw, rh = rect
        source = self._config.source_for(state.name)

        cr.save()
        rounded_rect(cr, rx, ry, rw, rh, 6)
        cr.clip()
        self._paint_source(cr, state, source, rect)
        cr.restore()

        selected = state.name == self.selected
        rounded_rect(cr, rx + 0.5, ry + 0.5, rw - 1, rh - 1, 6)
        if selected:
            tint = accent(style)
            cr.set_source_rgba(tint.red, tint.green, tint.blue, 1.0)
            cr.set_line_width(3)
        else:
            cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.35)
            cr.set_line_width(1)
        # Dashes mean "this one is still the theme's to decide". A solid
        # outline means displaywright has taken it over.
        cr.set_dash([] if source is not None else [5, 4])
        cr.stroke()
        cr.set_dash([])

        self._draw_label(cr, state, source, rx, ry + rh + LABEL_GAP, rw, fg, selected)

    def _paint_source(
        self,
        cr: cairo.Context,
        output: MonitorState,
        source: Source | None,
        rect: tuple[float, float, float, float],
    ) -> None:
        rx, ry, rw, rh = rect
        scale = self.zoom

        if source is not None and source.kind == Kind.COLOR:
            rgba = Gdk.RGBA()
            if rgba.parse(source.color):
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, rgba.alpha)
                cr.paint()
            return

        path = source.path if source is not None else self._theme_path
        if not path:
            paint_hatch(cr, rx, ry, rw, rh)
            return

        pixbuf = self._pixbuf(path)
        natural = self._natural_size(path)
        if pixbuf is None or natural is None:
            paint_hatch(cr, rx, ry, rw, rh)
            return

        # Backdrop first: Fit and Centre both leave some of it showing.
        if source is not None and source.fit.uses_backdrop:
            rgba = Gdk.RGBA()
            if rgba.parse(source.backdrop):
                cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
                cr.paint()

        logical = output.logical_size
        if self._config.span is not None and source is not None:
            box = span.span_box(self.states)
            if box is None:
                return
            offset = (output.x - box.x, output.y - box.y)
            x, y, w, h = preview.span_rect(natural, (box.w, box.h), offset)
        else:
            fit = source.fit if source is not None else Fit.FILL
            if fit is Fit.TILE:
                self._paint_tile(cr, pixbuf, natural, rect, output.scale)
                return
            x, y, w, h = preview.fitted_rect(fit, natural, logical, dpr=output.scale)

        cr.save()
        cr.translate(rx + x * scale, ry + y * scale)
        cr.scale(w * scale / pixbuf.get_width(), h * scale / pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.get_source().set_filter(cairo.Filter.GOOD)
        cr.paint()
        cr.restore()

    def _paint_tile(
        self,
        cr: cairo.Context,
        pixbuf: GdkPixbuf.Pixbuf,
        natural: tuple[int, int],
        rect: tuple[float, float, float, float],
        dpr: float,
    ) -> None:
        rx, ry, _, _ = rect
        scale = self.zoom
        tile_w, tile_h = preview.natural_size(natural, dpr)
        if tile_w <= 0 or tile_h <= 0:
            return
        cr.save()
        cr.translate(rx, ry)
        cr.scale(tile_w * scale / pixbuf.get_width(), tile_h * scale / pixbuf.get_height())
        Gdk.cairo_set_source_pixbuf(cr, pixbuf, 0, 0)
        cr.get_source().set_extend(cairo.Extend.REPEAT)
        cr.get_source().set_filter(cairo.Filter.GOOD)
        cr.paint()
        cr.restore()

    def _draw_label(
        self,
        cr: cairo.Context,
        output: MonitorState,
        source: Source | None,
        x: float,
        y: float,
        width: float,
        fg: Gdk.RGBA,
        selected: bool,
    ) -> None:
        """Two lines: which display and what it draws, then what it has to cover.

        The resolution is the display's real one -- the pixels a wallpaper has
        to fill. It is not the size the rectangle is drawn at, which is the
        logical size, because that is what makes the arrangement above truthful.
        """
        if self._config.span is not None:
            doing = "Span"
        elif source is None:
            doing = "Theme"
        elif source.kind == Kind.COLOR:
            doing = source.color
        else:
            doing = source.fit.label

        # Name and fit read together on the first line; the resolution is
        # reference material and sits under it. Putting all three on one line
        # runs past 240px, which is wider than most of the rectangles.
        px_w, px_h = output.pixel_size_rotated
        headline = f"{output.name} · {doing}"
        detail = f"{px_w}×{px_h}"
        if output.rotated:
            detail += " ↻"

        # A narrow display gets more room than its own rectangle, otherwise the
        # resolution would not fit under a portrait panel. Neighbours are far
        # enough apart in practice, and the ellipsis is the backstop.
        box = max(width, 160.0)
        left = x + (width - box) / 2
        line_height = self._line_height()
        for line, alpha, offset in (
            (headline, 1.0 if selected else 0.75, 0.0),
            (detail, 0.85 if selected else 0.45, float(line_height)),
        ):
            layout = self.create_pango_layout(line)
            layout.set_width(int(box * Pango.SCALE))
            layout.set_alignment(Pango.Alignment.CENTER)
            layout.set_ellipsize(Pango.EllipsizeMode.END)
            cr.save()
            cr.set_source_rgba(fg.red, fg.green, fg.blue, alpha)
            cr.move_to(left, y + offset)
            PangoCairo.show_layout(cr, layout)
            cr.restore()
