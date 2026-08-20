"""One window, two pages, one desk.

The header carries a view switcher and whatever the visible page wants beside
it; everything else -- the toast overlay, the connection to Hyprland's event
socket, and the single path by which the layout is re-read -- is owned here so
that neither page can get a different answer from the other.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk

from . import __version__, hypr
from .displays.page import DisplaysPage
from .session import Session, run_async
from .wallpapers.page import WallpapersPage


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "DisplaywrightWindow"

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="displaywright")
        self.set_default_size(1120, 800)

        self.session = Session()
        self.session.connect("notice", lambda _s, message: self.toast(message))

        self._build()
        self._install_actions()

        # Startup needs the layout before the window is useful, so read inline.
        self.reload_layout(announce=False, background=False)

        self._listener = hypr.EventListener(
            lambda name: GLib.idle_add(self._on_hypr_event, name)
        )
        self._listener.start()
        self.connect("close-request", self._on_close)

    # --------------------------------------------------------------------- UI

    def _build(self) -> None:
        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self.stack = Adw.ViewStack()
        self.displays = DisplaysPage(self.session, self, self.reload_layout)
        self.wallpapers = WallpapersPage(self.session, self)
        self.stack.add_titled_with_icon(
            self.displays, "displays", DisplaysPage.TITLE, DisplaysPage.ICON
        )
        self.stack.add_titled_with_icon(
            self.wallpapers, "wallpapers", WallpapersPage.TITLE, WallpapersPage.ICON
        )
        self._pages = {"displays": self.displays, "wallpapers": self.wallpapers}

        header = Adw.HeaderBar()
        header.set_title_widget(Adw.ViewSwitcher(
            stack=self.stack, policy=Adw.ViewSwitcherPolicy.WIDE
        ))

        reload_button = Gtk.Button(
            icon_name="view-refresh-symbolic", tooltip_text="Re-read displays from Hyprland"
        )
        reload_button.connect("clicked", lambda *_: self.reload_layout())
        header.pack_start(reload_button)

        # One stack per header side, so switching pages swaps the controls
        # without either page needing to know the other exists.
        self._start_slot = Gtk.Stack()
        self._end_slot = Gtk.Stack()
        for name, page in self._pages.items():
            self._start_slot.add_named(page.header_start(), name)
            self._end_slot.add_named(page.header_end(), name)
        header.pack_start(self._start_slot)

        self._menu_button = Gtk.MenuButton(icon_name="open-menu-symbolic",
                                           tooltip_text="Main menu")
        header.pack_end(self._menu_button)
        header.pack_end(self._end_slot)

        toolbar.add_top_bar(header)
        toolbar.set_content(self.stack)
        # A narrow window loses the header switcher; this is where it lands.
        switcher_bar = Adw.ViewSwitcherBar(stack=self.stack)
        toolbar.add_bottom_bar(switcher_bar)
        self.stack.connect("notify::visible-child-name", lambda *_: self._sync_page())

        shortcuts = Gtk.ShortcutController()
        shortcuts.set_scope(Gtk.ShortcutScope.GLOBAL)
        pairs = [("<Control>r", "win.reload")]
        for page in self._pages.values():
            pairs += list(page.shortcuts())
        for accel, action in pairs:
            shortcuts.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(accel),
                    action=Gtk.NamedAction.new(action),
                )
            )
        self.add_controller(shortcuts)

        self._sync_page()

    def _sync_page(self) -> None:
        name = self.stack.get_visible_child_name() or "displays"
        self._start_slot.set_visible_child_name(name)
        self._end_slot.set_visible_child_name(name)

        menu = self._pages[name].menu_model()
        shared = Gio.Menu()
        shared.append("About displaywright", "win.about")
        menu.append_section(None, shared)
        self._menu_button.set_menu_model(menu)

    def _install_actions(self) -> None:
        for name, handler in (
            ("reload", lambda *_: self.reload_layout()),
            ("discard", lambda *_: self.reload_layout()),
            ("about", lambda *_: self._about()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    # ------------------------------------------------------------------ state

    def reload_layout(self, announce: bool = True, background: bool = True) -> None:
        """Re-read the layout. Reads go off-thread unless we need them now."""

        def deliver(states) -> None:
            self.session.adopt(states)
            if announce:
                self.toast("Reloaded from Hyprland")

        if not background:
            try:
                deliver(self.session.read_layout())
            except hypr.HyprError as exc:
                self.toast(f"Could not read monitors: {exc}")
            return

        def done(states, error) -> None:
            if error is not None:
                self.toast(f"Could not read monitors: {error}")
                return
            deliver(states)

        # Reads are quick, so they get no progress banner of their own.
        run_async(self.session.read_layout, done)

    def _on_hypr_event(self, name: str) -> bool:
        if self.session.dirty:
            self.toast("Displays changed in Hyprland — reload to discard your edits")
            return False
        self.reload_layout(announce=False)
        if name.startswith("monitor"):
            self.toast("Display setup changed — refreshed")
        return False

    # ------------------------------------------------------------------- misc

    def toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message))

    def _about(self) -> None:
        about = Adw.AboutDialog(
            application_name="displaywright",
            application_icon="video-display-symbolic",
            version=__version__,
            developer_name="bkblab.ai",
            comments=(
                "Display arrangement and per-display wallpapers for Hyprland "
                "and Omarchy.\n\n"
                "Arrangements are applied live with hyprctl and written back to "
                "your monitors.lua. Wallpapers are drawn by an omarchy-shell "
                "plugin that replaces the built-in background renderer."
            ),
            license_type=Gtk.License.MIT_X11,
            website="https://github.com/BlackKingBarOrg/displaywright",
        )
        about.present(self)

    def shutdown(self) -> None:
        """Release everything that outlives the window."""
        self._listener.stop()
        for page in self._pages.values():
            page.shutdown()

    def _on_close(self, *_args) -> bool:
        self.shutdown()
        return False
