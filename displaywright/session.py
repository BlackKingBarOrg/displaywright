"""What both pages are looking at.

The point of merging the two tools was that they were describing the same desk
from two windows. This is the object that makes them describe it once: one list
of outputs, one selected display, one wallpaper config, one connection to
Hyprland's event socket.

Two lists of outputs, strictly speaking, and the difference matters:

* :attr:`Session.states` is the *desired* arrangement -- what the canvas has
  been dragged into and the sidebar has been edited to. Both pages draw this,
  so switching tabs never jumps the displays around.
* :attr:`Session.live_states` is the last thing Hyprland actually reported. It
  is what :attr:`Session.dirty` is measured against and what a revert goes back
  to.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Sequence
from typing import ClassVar

from gi.repository import GLib, GObject

from . import hypr
from .model import MonitorState
from .wallpapers import store
from .wallpapers.model import Config


def run_async(work: Callable[[], object], done: Callable[[object, Exception | None], None]) -> None:
    """Run a blocking call off the UI thread.

    A modeset can keep hyprctl busy for a while -- longer still if the
    compositor is fighting the hardware -- and doing that on the main loop
    freezes the window until it finishes. ``done`` is called back on the UI
    thread with ``(result, error)``.
    """

    def deliver(result, error):
        done(result, error)
        return False  # one-shot idle callback

    def runner():
        try:
            result, error = work(), None
        except Exception as exc:
            result, error = None, exc
        GLib.idle_add(deliver, result, error)

    threading.Thread(target=runner, name="displaywright-worker", daemon=True).start()


class Session(GObject.Object):
    """Shared state, plus the signals that keep two pages in step."""

    __gsignals__: ClassVar[dict] = {
        # the output list was replaced wholesale, from Hyprland or a revert
        "layout-reloaded": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # the states were mutated in place: dragged, nudged, or edited
        "layout-edited": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # a different display is selected
        "selection-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # the wallpaper config changed, here or in another process
        "wallpapers-changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        # something worth saying out loud; the window turns these into toasts
        "notice": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self) -> None:
        super().__init__()
        self.states: list[MonitorState] = []
        self.live_states: list[MonitorState] = []
        self.wallpapers: Config = store.load()
        self._selected: str | None = None

    # ---------------------------------------------------------------- outputs

    @property
    def selected(self) -> str | None:
        return self._selected

    @selected.setter
    def selected(self, name: str | None) -> None:
        if name == self._selected:
            return
        self._selected = name
        self.emit("selection-changed")

    def selected_state(self) -> MonitorState | None:
        return next((s for s in self.states if s.name == self._selected), None)

    def enabled_states(self) -> list[MonitorState]:
        """Only the lit displays: a disabled one cannot show a wallpaper."""
        return [s for s in self.states if s.enabled]

    @property
    def dirty(self) -> bool:
        """True when the arrangement differs from what Hyprland is running."""
        live = {s.name: s for s in self.live_states}
        if set(live) != {s.name for s in self.states}:
            return True
        return any(not s.config_equals(live[s.name]) for s in self.states)

    def adopt(self, states: Sequence[MonitorState]) -> None:
        """Take a freshly read layout as both the desired and the live one."""
        self.live_states = [s.copy() for s in states]
        self.states = list(states)
        names = {s.name for s in self.states}
        if self._selected not in names:
            focused = next((s.name for s in self.states if s.focused), None)
            self._selected = focused or (self.states[0].name if self.states else None)
        self.emit("layout-reloaded")
        self.emit("selection-changed")

    def note_edit(self) -> None:
        self.emit("layout-edited")

    def notice(self, message: str) -> None:
        self.emit("notice", message)

    # ------------------------------------------------------------- wallpapers

    def set_wallpapers(self, config: Config) -> None:
        self.wallpapers = config
        self.emit("wallpapers-changed")

    def reload_wallpapers(self) -> None:
        self.set_wallpapers(store.load())

    # ------------------------------------------------------------------- hypr

    def read_layout(self) -> list[MonitorState]:
        """Blocking read. Call through :func:`run_async` from the UI."""
        return hypr.read_monitors()
