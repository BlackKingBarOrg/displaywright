"""The draggable arrangement view.

Dragging a rectangle rewrites the corresponding
:class:`~displaywright.model.MonitorState` position, snapped to its neighbours'
edges. Everything about *where* the rectangles go is inherited from
:class:`~displaywright.canvas.DisplayCanvas`; this class is the interaction and
the flat, high-contrast look that makes an arrangement legible.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")

from typing import ClassVar

from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo

from ..canvas import DisplayCanvas
from ..drawing import Palette, draw_centered, rounded_rect
from ..model import MonitorState
from .snapping import snap_and_resolve

PADDING = 28.0
NUDGE = 10  # logical px per arrow key press


class ArrangeCanvas(DisplayCanvas):
    __gtype_name__ = "DisplaywrightArrangeCanvas"

    __gsignals__: ClassVar[dict] = {
        # geometry changed and is still being dragged
        "layout-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # drag finished / keyboard nudge done -- good moment to persist or apply
        "layout-committed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    padding = PADDING

    def __init__(self) -> None:
        super().__init__()
        self._drag_name: str | None = None
        self._drag_start: tuple[int, int] = (0, 0)
        self._guides: list[tuple[str, float]] = []
        self._dark = False

        self.set_vexpand(True)
        self.set_size_request(420, 280)
        self.set_focusable(True)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.queue_draw()

    # -------------------------------------------------------------------- input

    def _on_drag_begin(self, _gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        found = self.hit(x, y)
        if found is None:
            self._drag_name = None
            return
        self.select(found.name)
        self._drag_name = found.name
        self._drag_start = (found.x, found.y)

    def _on_drag_update(self, _gesture: Gtk.GestureDrag, ox: float, oy: float) -> None:
        state = next((s for s in self.states if s.name == self._drag_name), None)
        if state is None:
            return
        wanted = state.rect.moved(
            self._drag_start[0] + ox / self.zoom,
            self._drag_start[1] + oy / self.zoom,
        )
        others = [s.rect for s in self.states if s.name != state.name]
        result = snap_and_resolve(wanted, others)
        state.x, state.y = result.x, result.y
        self._guides = result.guides
        self.queue_draw()
        self.emit("layout-changed")

    def _on_drag_end(self, _gesture: Gtk.GestureDrag, _ox: float, _oy: float) -> None:
        if self._drag_name is not None:
            self._drag_name = None
            self._guides = []
            self.queue_draw()
            self.emit("layout-committed")

    def _on_motion(self, _c: Gtk.EventControllerMotion, x: float, y: float) -> None:
        cursor = "grab" if self.hit(x, y) else "default"
        self.set_cursor(Gdk.Cursor.new_from_name(cursor, None))

    def _on_key(self, _c: Gtk.EventControllerKey, keyval: int, _code: int, mods: Gdk.ModifierType) -> bool:
        state = self.selected_state()
        if state is None:
            return False
        step = NUDGE * (10 if mods & Gdk.ModifierType.SHIFT_MASK else 1)
        deltas = {
            Gdk.KEY_Left: (-step, 0),
            Gdk.KEY_Right: (step, 0),
            Gdk.KEY_Up: (0, -step),
            Gdk.KEY_Down: (0, step),
        }
        if keyval == Gdk.KEY_Tab and self.states:
            names = [s.name for s in self.states]
            idx = names.index(state.name)
            self.select(names[(idx + 1) % len(names)])
            return True
        if keyval not in deltas:
            return False
        dx, dy = deltas[keyval]
        others = [s.rect for s in self.states if s.name != state.name]
        # Half a step of snapping: enough to land exactly on an edge, not enough
        # to swallow the nudge and leave the monitor where it was.
        result = snap_and_resolve(
            state.rect.moved(state.x + dx, state.y + dy), others, threshold=step / 2
        )
        state.x, state.y = result.x, result.y
        self.queue_draw()
        self.emit("layout-changed")
        self.emit("layout-committed")
        return True

    # ------------------------------------------------------------------ drawing

    def draw_background(self, cr, width: int, height: int) -> None:
        cr.set_source_rgb(*Palette(self._dark).bg)
        cr.paint()

    def draw_empty(self, cr, width: int, height: int) -> None:
        draw_centered(cr, width, height, "No outputs reported by Hyprland",
                      Palette(self._dark).text_dim)

    def draw_underlay(self, cr, width: int, height: int) -> None:
        palette = Palette(self._dark)
        step = 250.0 * self.zoom  # ~logical px, keeps a sense of scale
        if step < 8:
            return
        cr.set_source_rgb(*palette.grid)
        cr.set_line_width(1.0)
        x = self._origin[0] % step
        while x < width:
            cr.move_to(x, 0)
            cr.line_to(x, height)
            x += step
        y = self._origin[1] % step
        while y < height:
            cr.move_to(0, y)
            cr.line_to(width, y)
            y += step
        cr.stroke()

    def draw_tile(self, cr, state: MonitorState, rect: tuple[float, float, float, float]) -> None:
        palette = Palette(self._dark)
        x, y, w, h = rect
        selected = state.name == self.selected

        radius = min(10.0, w / 6, h / 6)
        rounded_rect(cr, x, y, w, h, radius)
        if not state.enabled:
            cr.set_source_rgb(*palette.tile_disabled)
        elif selected:
            cr.set_source_rgb(*palette.tile_selected)
        else:
            cr.set_source_rgb(*palette.tile)
        cr.fill_preserve()

        cr.set_source_rgb(*(palette.border_selected if selected else palette.border))
        cr.set_line_width(3.0 if selected else 1.5)
        if not state.enabled:
            cr.set_dash([6.0, 4.0])
        cr.stroke()
        cr.set_dash([])

        self._draw_labels(cr, state, palette, x, y, w, h)

    def draw_overlay(self, cr, width: int, height: int) -> None:
        palette = Palette(self._dark)
        for axis, coord in self._guides:
            cr.set_source_rgb(*palette.guide)
            cr.set_line_width(1.0)
            cr.set_dash([4.0, 4.0])
            if axis == "v":
                dx, _ = self.to_device(coord, 0)
                cr.move_to(dx, 0)
                cr.line_to(dx, height)
            else:
                _, dy = self.to_device(0, coord)
                cr.move_to(0, dy)
                cr.line_to(width, dy)
            cr.stroke()
            cr.set_dash([])

    def _draw_labels(self, cr, state: MonitorState, palette: Palette, x, y, w, h) -> None:
        px_w, px_h = state.pixel_size
        lw, lh = state.logical_size

        # Each entry lists progressively shorter alternatives; the first one that
        # fits the tile wins, so a small tile degrades instead of going blank.
        lines: list[tuple[str, list[str]]] = [("bold", [state.name])]
        if h > 46 and w > 96:
            if state.enabled:
                refresh = f" @ {state.mode.refresh:g}Hz" if state.mode and state.mode.refresh else ""
                lines.append(("dim", [f"{px_w}×{px_h}{refresh}", f"{px_w}×{px_h}"]))
                if abs(state.scale - 1.0) > 1e-6:
                    lines.append(
                        ("dim", [f"×{state.scale:g} → {round(lw)}×{round(lh)}", f"×{state.scale:g}"])
                    )
                if state.transform:
                    lines.append(("dim", [f"rotated {90 * (state.transform % 4)}°", "rotated"]))
                if state.mirror_of:
                    lines.append(("dim", [f"mirrors {state.mirror_of}", "mirrored"]))
            else:
                lines.append(("dim", ["disabled"]))
        if h > 92 and w > 130 and state.pretty_name != state.name:
            lines.append(("dim", [state.pretty_name]))

        available = w - 8
        chosen: list[tuple[str, object, float, float]] = []
        total = 0.0
        for kind, variants in lines:
            for text in variants:
                layout = PangoCairo.create_layout(cr)
                layout.set_font_description(
                    Pango.FontDescription("Sans Bold 11" if kind == "bold" else "Sans 9")
                )
                layout.set_text(text, -1)
                ink = layout.get_pixel_extents()[1]
                if ink.width <= available or text is variants[-1]:
                    if ink.width > available:
                        break  # even the shortest form does not fit
                    chosen.append((kind, layout, ink.width, ink.height))
                    total += ink.height + 2
                    break

        cursor = y + (h - total) / 2
        for kind, layout, text_w, text_h in chosen:
            cr.set_source_rgb(*(palette.text if kind == "bold" else palette.text_dim))
            cr.move_to(x + (w - text_w) / 2, cursor)
            PangoCairo.show_layout(cr, layout)
            cursor += text_h + 2
