"""GTK application shell."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, Gtk

from . import APP_ID
from .window import MainWindow

CSS = b"""
window.hyprlayout frame {
  border-radius: 12px;
}
"""


class HyprlayoutApp(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)

        display = Gdk.Display.get_default()
        if display is not None:
            provider = Gtk.CssProvider()
            provider.load_from_data(CSS)
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Control>q", "<Control>w"])

    def do_activate(self) -> None:
        window = self.props.active_window
        if window is None:
            window = MainWindow(self)
            window.add_css_class("hyprlayout")
        window.present()


def run(argv: list[str] | None = None) -> int:
    return HyprlayoutApp().run(argv or [])
