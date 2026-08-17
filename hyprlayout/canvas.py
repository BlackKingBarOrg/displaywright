"""The draggable display canvas.

A single :class:`Gtk.DrawingArea` renders every output as a rounded rectangle in
a zoomed-out view of the logical desktop.  Dragging a rectangle rewrites the
corresponding :class:`~hyprlayout.model.MonitorState` position, snapped to its
neighbours' edges.
"""

from __future__ import annotations

import math
from typing import Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Gdk, GObject, Gtk, Pango, PangoCairo  # noqa: E402

from .model import MonitorState, Rect, bounding_box
from .snapping import snap_and_resolve

PADDING = 28.0  # device px of breathing room around the layout
MAX_ZOOM = 0.34  # never draw a monitor larger than a third of its logical size
NUDGE = 10  # logical px per arrow key press


class Palette:
    """Flat colour set, swapped wholesale for dark mode."""

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


class LayoutCanvas(Gtk.DrawingArea):
    __gtype_name__ = "HyprlayoutCanvas"

    __gsignals__ = {
        # a different monitor became the selection
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # geometry changed and is still being dragged
        "layout-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # drag finished / keyboard nudge done -- good moment to persist or apply
        "layout-committed": (GObject.SignalFlags.RUN_FIRST, None, ()),
    }

    def __init__(self) -> None:
        super().__init__()
        self.states: list[MonitorState] = []
        self.selected: str | None = None

        self._zoom = 0.1
        self._origin = (0.0, 0.0)  # device px offset of logical (0,0)
        self._drag_name: str | None = None
        self._drag_start: tuple[int, int] = (0, 0)
        self._guides: list[tuple[str, float]] = []
        self._dark = False

        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_size_request(420, 280)
        self.set_focusable(True)
        self.set_draw_func(self._draw)

        drag = Gtk.GestureDrag()
        drag.connect("drag-begin", self._on_drag_begin)
        drag.connect("drag-update", self._on_drag_update)
        drag.connect("drag-end", self._on_drag_end)
        self.add_controller(drag)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._on_motion)
        self.add_controller(motion)

    # ------------------------------------------------------------------- public

    def set_states(self, states: Sequence[MonitorState]) -> None:
        self.states = list(states)
        if self.selected not in {s.name for s in self.states}:
            self.selected = self.states[0].name if self.states else None
            self.emit("selection-changed")
        self.queue_draw()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.queue_draw()

    def selected_state(self) -> MonitorState | None:
        return next((s for s in self.states if s.name == self.selected), None)

    def select(self, name: str | None) -> None:
        if name != self.selected:
            self.selected = name
            self.emit("selection-changed")
            self.queue_draw()

    # ------------------------------------------------------------------ view math

    def _update_view(self, width: float, height: float) -> None:
        rects = [s.rect for s in self.states] or [Rect(0, 0, 1920, 1080)]
        box = bounding_box(rects)
        usable_w = max(width - 2 * PADDING, 40.0)
        usable_h = max(height - 2 * PADDING, 40.0)
        zoom = min(usable_w / max(box.w, 1.0), usable_h / max(box.h, 1.0))
        self._zoom = min(zoom, MAX_ZOOM)
        self._origin = (
            (width - box.w * self._zoom) / 2 - box.x * self._zoom,
            (height - box.h * self._zoom) / 2 - box.y * self._zoom,
        )

    def _to_device(self, x: float, y: float) -> tuple[float, float]:
        return self._origin[0] + x * self._zoom, self._origin[1] + y * self._zoom

    def _to_logical(self, x: float, y: float) -> tuple[float, float]:
        return (x - self._origin[0]) / self._zoom, (y - self._origin[1]) / self._zoom

    def _hit(self, dx: float, dy: float) -> MonitorState | None:
        lx, ly = self._to_logical(dx, dy)
        # topmost first: the selected tile is drawn last, so it wins ties
        for state in reversed(self._draw_order()):
            if state.rect.contains(lx, ly):
                return state
        return None

    def _draw_order(self) -> list[MonitorState]:
        return sorted(self.states, key=lambda s: s.name == self.selected)

    # -------------------------------------------------------------------- input

    def _on_pressed(self, _gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        self.grab_focus()
        hit = self._hit(x, y)
        self.select(hit.name if hit else self.selected)

    def _on_drag_begin(self, _gesture: Gtk.GestureDrag, x: float, y: float) -> None:
        hit = self._hit(x, y)
        if hit is None:
            self._drag_name = None
            return
        self.select(hit.name)
        self._drag_name = hit.name
        self._drag_start = (hit.x, hit.y)

    def _on_drag_update(self, _gesture: Gtk.GestureDrag, ox: float, oy: float) -> None:
        state = next((s for s in self.states if s.name == self._drag_name), None)
        if state is None:
            return
        wanted = state.rect.moved(
            self._drag_start[0] + ox / self._zoom,
            self._drag_start[1] + oy / self._zoom,
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
        cursor = "grab" if self._hit(x, y) else "default"
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

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        palette = Palette(self._dark)
        cr.set_source_rgb(*palette.bg)
        cr.paint()

        if not self.states:
            self._draw_centered(cr, width, height, palette, "No outputs reported by Hyprland")
            return

        self._update_view(float(width), float(height))
        self._draw_grid(cr, width, height, palette)

        for state in self._draw_order():
            self._draw_monitor(cr, state, palette)

        for axis, coord in self._guides:
            self._draw_guide(cr, axis, coord, width, height, palette)

    def _draw_grid(self, cr, width: int, height: int, palette: Palette) -> None:
        step = 250.0 * self._zoom  # ~logical px, keeps a sense of scale
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

    def _draw_monitor(self, cr, state: MonitorState, palette: Palette) -> None:
        rect = state.rect
        x, y = self._to_device(rect.x, rect.y)
        w, h = rect.w * self._zoom, rect.h * self._zoom
        selected = state.name == self.selected

        radius = min(10.0, w / 6, h / 6)
        _rounded_rect(cr, x, y, w, h, radius)
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

    def _draw_guide(self, cr, axis: str, coord: float, width: int, height: int, palette: Palette) -> None:
        cr.set_source_rgb(*palette.guide)
        cr.set_line_width(1.0)
        cr.set_dash([4.0, 4.0])
        if axis == "v":
            dx, _ = self._to_device(coord, 0)
            cr.move_to(dx, 0)
            cr.line_to(dx, height)
        else:
            _, dy = self._to_device(0, coord)
            cr.move_to(0, dy)
            cr.line_to(width, dy)
        cr.stroke()
        cr.set_dash([])

    def _draw_centered(self, cr, width: int, height: int, palette: Palette, text: str) -> None:
        layout = PangoCairo.create_layout(cr)
        layout.set_font_description(Pango.FontDescription("Sans 11"))
        layout.set_text(text, -1)
        ink = layout.get_pixel_extents()[1]
        cr.set_source_rgb(*palette.text_dim)
        cr.move_to((width - ink.width) / 2, (height - ink.height) / 2)
        PangoCairo.show_layout(cr, layout)


def _rounded_rect(cr, x: float, y: float, w: float, h: float, r: float) -> None:
    r = max(0.0, min(r, w / 2, h / 2))
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 1.5 * math.pi)
    cr.close_path()
