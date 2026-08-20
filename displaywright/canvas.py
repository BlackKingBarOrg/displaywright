"""The desktop, drawn small: one rectangle per output, to scale.

Both halves of the app show the same picture of your desk. The arrangement page
lets you drag the rectangles around; the wallpaper page paints what each one is
showing. Everything they agree on lives here -- how the logical desktop is
fitted into the widget, which rectangle a click landed in, and which output is
selected -- so the two views cannot drift apart, and a display selected on one
page is still selected on the other.

Subclasses supply the parts that genuinely differ, through four hooks:
:meth:`~DisplayCanvas.draw_background`, :meth:`~DisplayCanvas.draw_tile`,
:meth:`~DisplayCanvas.draw_overlay` and :meth:`~DisplayCanvas.caption_band`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import ClassVar

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import GObject, Gtk

from .model import MonitorState, Rect, bounding_box

#: Device px of breathing room around the layout.
PADDING = 24.0
#: Never draw a monitor larger than a third of its logical size. Without a cap,
#: a single small display fills the widget and the view stops reading as a
#: scaled-down desk.
MAX_ZOOM = 0.34


class DisplayCanvas(Gtk.DrawingArea):
    """Base class: view maths, hit testing and selection. Draws nothing itself."""

    __gsignals__: ClassVar[dict] = {
        # a different output became the selection
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # a rectangle was clicked, selected or not -- the wallpaper page treats
        # this as "act on that display", the arrangement page ignores it
        "output-activated": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    padding = PADDING
    max_zoom = MAX_ZOOM

    def __init__(self) -> None:
        super().__init__()
        self.states: list[MonitorState] = []
        self.selected: str | None = None

        self._zoom = 0.1
        self._origin = (0.0, 0.0)  # device px offset of logical (0, 0)

        self.set_hexpand(True)
        self.set_draw_func(self._draw)

        click = Gtk.GestureClick()
        click.connect("pressed", self._on_pressed)
        self.add_controller(click)

    # ------------------------------------------------------------------ public

    def set_states(self, states: Sequence[MonitorState]) -> None:
        """Replace what is drawn, keeping the selection if it is still there."""
        self.states = list(states)
        if self.selected not in {s.name for s in self.states}:
            self.selected = self.states[0].name if self.states else None
            self.emit("selection-changed")
        self.queue_draw()

    def select(self, name: str | None) -> None:
        if name != self.selected:
            self.selected = name
            self.emit("selection-changed")
            self.queue_draw()

    def selected_state(self) -> MonitorState | None:
        return next((s for s in self.states if s.name == self.selected), None)

    # --------------------------------------------------------------- view math

    def caption_band(self) -> float:
        """Device px reserved below the tiles. Zero unless a subclass wants it."""
        return 0.0

    def _update_view(self, width: float, height: float) -> None:
        rects = [s.rect for s in self.states] or [Rect(0, 0, 1920, 1080)]
        box = bounding_box(rects)
        usable_w = max(width - 2 * self.padding, 40.0)
        usable_h = max(height - 2 * self.padding - self.caption_band(), 40.0)
        zoom = min(usable_w / max(box.w, 1.0), usable_h / max(box.h, 1.0))
        self._zoom = min(zoom, self.max_zoom)
        self._origin = (
            (width - box.w * self._zoom) / 2 - box.x * self._zoom,
            self.padding + (usable_h - box.h * self._zoom) / 2 - box.y * self._zoom,
        )

    def to_device(self, x: float, y: float) -> tuple[float, float]:
        return self._origin[0] + x * self._zoom, self._origin[1] + y * self._zoom

    def to_logical(self, x: float, y: float) -> tuple[float, float]:
        return (x - self._origin[0]) / self._zoom, (y - self._origin[1]) / self._zoom

    @property
    def zoom(self) -> float:
        return self._zoom

    def device_rect(self, state: MonitorState) -> tuple[float, float, float, float]:
        rect = state.rect
        x, y = self.to_device(rect.x, rect.y)
        return x, y, rect.w * self._zoom, rect.h * self._zoom

    def hit(self, dx: float, dy: float) -> MonitorState | None:
        """The output under a device-space point, topmost first.

        Tested in logical space rather than against the rectangles the last
        frame drew, so a click lands correctly before the first draw and after
        a resize that has not been painted yet.
        """
        lx, ly = self.to_logical(dx, dy)
        for state in reversed(self.draw_order()):
            if state.rect.contains(lx, ly):
                return state
        return None

    def draw_order(self) -> list[MonitorState]:
        """Back to front: the selection is drawn last so it wins overlaps."""
        return sorted(self.states, key=lambda s: s.name == self.selected)

    # -------------------------------------------------------------------- input

    def _on_pressed(self, _gesture: Gtk.GestureClick, _n: int, x: float, y: float) -> None:
        self.grab_focus()
        found = self.hit(x, y)
        if found is None:
            return
        self.select(found.name)
        self.emit("output-activated", found.name)

    # ------------------------------------------------------------------ drawing

    def _draw(self, _area: Gtk.DrawingArea, cr, width: int, height: int) -> None:
        self.draw_background(cr, width, height)
        if not self.states:
            self.draw_empty(cr, width, height)
            return
        self._update_view(float(width), float(height))
        # The grid and anything else keyed to the view has to wait until the
        # view is known, so background painting happens in two passes.
        self.draw_underlay(cr, width, height)
        for state in self.draw_order():
            self.draw_tile(cr, state, self.device_rect(state))
        self.draw_overlay(cr, width, height)

    # Hooks. The base class draws nothing, so a subclass that overrides none of
    # these produces an empty widget rather than a half-finished one.

    def draw_background(self, cr, width: int, height: int) -> None:
        """Painted before the view is computed, e.g. a flat backdrop."""

    def draw_underlay(self, cr, width: int, height: int) -> None:
        """Painted after the view is known but under the tiles, e.g. a grid."""

    def draw_tile(self, cr, state: MonitorState, rect: tuple[float, float, float, float]) -> None:
        """One output."""

    def draw_overlay(self, cr, width: int, height: int) -> None:
        """Painted over everything, e.g. alignment guides."""

    def draw_empty(self, cr, width: int, height: int) -> None:
        """Shown when Hyprland reports no outputs at all."""
