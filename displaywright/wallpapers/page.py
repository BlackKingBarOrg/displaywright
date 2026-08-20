"""The wallpaper page: pick a display, pick a picture, pick how it sits.

Changes are written as they are made rather than gathered behind an Apply
button. A wallpaper is visible the moment it lands and costs nothing to undo by
choosing something else, so a confirmation step would only put a dialog between
the user and the thing they are trying to look at.

That is the opposite of how the arrangement page behaves, deliberately: a bad
wallpaper is an eyesore, a bad arrangement is a black screen you cannot click
your way out of.
"""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from ..session import Session
from . import library, plugin, shell, span, store
from .canvas import WallpaperCanvas
from .model import Fit, Kind, Source, kind_for_path

#: Extra entry after the real fits. Spanning is a property of the desktop, not
#: of one output, but Windows puts it in this list and so does everyone's
#: muscle memory.
SPAN_LABEL = "Span across all displays"

THUMBNAIL_WIDTH = 200


class WallpapersPage(Gtk.Box):
    """What each display draws, previewed on the same arrangement."""

    __gtype_name__ = "DisplaywrightWallpapersPage"

    TITLE = "Wallpapers"
    ICON = "preferences-desktop-wallpaper-symbolic"

    def __init__(self, session: Session, actions: Gio.ActionMap) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        self._last_written: dict | None = None
        self._entries: list[library.Entry] = []
        self._tiles: dict[str, Gtk.Picture] = {}
        self._library_generation = 0
        self._suppress = False
        self._save_source_id = 0

        library.ensure_wallpaper_dir()

        self._build()
        self._install_actions(actions)
        self._watch_config()

        session.connect("layout-reloaded", lambda *_: self._refresh())
        session.connect("layout-edited", lambda *_: self._refresh())
        session.connect("selection-changed", lambda *_: self._refresh())
        session.connect("wallpapers-changed", lambda *_: self._refresh())

        self._reload_library()
        self._refresh()

    # ----------------------------------------------------------------- header

    def header_start(self) -> Gtk.Widget:
        return self._header_start

    def header_end(self) -> Gtk.Widget:
        return self._header_end

    def _build_header(self) -> None:
        """Built with the rest of the page, not when the window asks for it.

        The first refresh runs before the window collects these widgets, and it
        wants to grey out "Follow theme" -- so the button has to exist by then.
        """
        self._header_start = Gtk.Box(spacing=6)
        browse = Gtk.Button(label="Browse…")
        browse.set_tooltip_text("Pick a picture from anywhere on disk")
        browse.connect("clicked", self._on_browse)
        self._header_start.append(browse)

        self._header_end = Gtk.Box(spacing=6)
        self._follow = Gtk.Button(label="Follow theme")
        self._follow.set_tooltip_text("Hand this display back to the Omarchy theme background")
        self._follow.connect("clicked", self._on_follow_theme)
        self._header_end.append(self._follow)

    def menu_model(self) -> Gio.Menu:
        menu = Gio.Menu()
        picker = Gio.Menu()
        picker.append("Open wallpaper folder", "win.open-folder")
        picker.append("Add folder…", "win.add-folder")
        picker.append("Rescan folders", "win.rescan")
        menu.append_section(None, picker)

        system = Gio.Menu()
        system.append("Clear every display", "win.clear-all")
        menu.append_section(None, system)

        renderer = Gio.Menu()
        renderer.append("Install renderer", "win.install-renderer")
        renderer.append("Remove renderer", "win.uninstall-renderer")
        menu.append_section("Renderer", renderer)
        return menu

    def shortcuts(self) -> tuple[tuple[str, str], ...]:
        return (("<Control>o", "win.open-folder"),)

    def _install_actions(self, actions: Gio.ActionMap) -> None:
        for name, handler in (
            ("open-folder", self._on_open_folder),
            ("add-folder", self._on_add_folder),
            ("rescan", lambda *_: self._reload_library()),
            ("clear-all", self._on_clear_all),
            ("install-renderer", lambda *_: self._install_renderer()),
            ("uninstall-renderer", lambda *_: self._uninstall_renderer()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            actions.add_action(action)

    # --------------------------------------------------------------- building

    def _build(self) -> None:
        self._build_header()

        self._banner = Adw.Banner(revealed=False)
        self._banner.connect("button-clicked", lambda *_: self._install_renderer())
        self.append(self._banner)

        self._canvas = WallpaperCanvas()
        self._canvas.connect("output-activated", self._on_output_activated)
        self.append(self._canvas)

        self.append(self._controls())
        self.append(Gtk.Separator())
        self.append(self._library_view())

        self.status = Gtk.Label(xalign=0.0, margin_start=16, margin_end=16,
                                margin_top=4, margin_bottom=6, ellipsize=3)
        self.status.add_css_class("caption")
        self.status.add_css_class("dim-label")
        self.append(self.status)

    def _controls(self) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(10)
        box.set_margin_bottom(10)

        box.append(Gtk.Label(label="Fit", xalign=0))

        self._fit_model = Gtk.StringList()
        for fit in Fit:
            self._fit_model.append(fit.label)
        self._fit_model.append(SPAN_LABEL)
        self._fit_drop = Gtk.DropDown(model=self._fit_model)
        self._fit_drop.connect("notify::selected", self._on_fit_changed)
        box.append(self._fit_drop)

        self._backdrop = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False))
        self._backdrop.set_tooltip_text("Colour behind a Fit or a Center")
        self._backdrop.connect("notify::rgba", self._on_backdrop_changed)
        box.append(self._backdrop)

        box.append(Gtk.Box(hexpand=True))
        return box

    def _library_view(self) -> Gtk.Widget:
        self._flow = Gtk.FlowBox(
            valign=Gtk.Align.START,
            selection_mode=Gtk.SelectionMode.NONE,
            homogeneous=True,
            column_spacing=12,
            row_spacing=12,
            min_children_per_line=2,
            max_children_per_line=8,
        )
        self._flow.set_margin_start(16)
        self._flow.set_margin_end(16)
        self._flow.set_margin_top(12)
        self._flow.set_margin_bottom(16)
        self._flow.connect("child-activated", self._on_entry_activated)

        self._library_status = Adw.StatusPage(
            title="No wallpapers yet",
            description=(
                "Choose Browse… to pick one. It is copied into "
                f"{library.wallpaper_dir()} and shows up here.\n"
                "Add folder… in the menu brings in a collection you already have."
            ),
            icon_name="image-x-generic-symbolic",
        )
        self._library_status.set_vexpand(True)

        self._library_stack = Gtk.Stack()
        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(self._flow)
        self._library_stack.add_named(scroller, "grid")
        self._library_stack.add_named(self._library_status, "empty")
        self._library_stack.set_vexpand(True)
        return self._library_stack

    # -------------------------------------------------------------- watching

    def _watch_config(self) -> None:
        """The CLI writes the same file. Follow it so both stay in step."""
        path = store.config_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        self._monitor = Gio.File.new_for_path(str(path)).monitor_file(
            Gio.FileMonitorFlags.NONE, None
        )
        self._monitor.connect("changed", self._on_config_file_changed)

    def _on_config_file_changed(self, *_args) -> None:
        if self._save_source_id:
            # A write of ours is still queued; the widgets are already ahead of
            # the file and reloading would undo whatever is being edited.
            return
        loaded = store.load()
        if loaded.to_json() == self._last_written:
            # The monitor firing for our own completed write.
            return
        self.session.set_wallpapers(loaded)

    # ---------------------------------------------------------------- session

    @property
    def config(self):
        return self.session.wallpapers

    def _outputs(self):
        """Lit displays only: a disabled one has no surface to draw into."""
        return self.session.enabled_states()

    def _selected_output(self):
        return next((o for o in self._outputs() if o.name == self.session.selected), None)

    def _on_output_activated(self, _canvas: WallpaperCanvas, name: str) -> None:
        self.session.selected = name

    def _refresh(self) -> None:
        self._sync_widgets()
        self._canvas.set_config(self._outputs(), self.config, self.session.selected)
        self._sync_banner()

    def _sync_banner(self) -> None:
        state = plugin.status()
        if not state.ready:
            self._banner.set_title(
                "displaywright is not drawing any wallpaper yet — " + state.describe()
            )
            self._banner.set_button_label("Install")
            self._banner.set_revealed(True)
            return
        if self.session.dirty:
            # The preview is drawn on the arrangement being edited, which is not
            # what is on the glass yet. Saying so beats silently lying.
            self._banner.set_title(
                "Previewing your unapplied arrangement — apply it on the Displays page"
            )
            self._banner.set_button_label(None)
            self._banner.set_revealed(True)
            return
        self._banner.set_revealed(False)

    # --------------------------------------------------------------- widgets

    def _sync_widgets(self) -> None:
        self._suppress = True
        try:
            output = self._selected_output()
            source = self.config.source_for(self.session.selected or "")
            spanning = self.config.span is not None
            outputs = self._outputs()

            if output is None:
                self.status.set_label("No display selected")
            elif spanning:
                covered = span.coverage(outputs)
                self.status.set_label(
                    f"Spanned across {len(outputs)} displays · "
                    f"{covered * 100:.0f}% of the picture is on a screen"
                )
            else:
                where = source.describe() if source else "follows the theme background"
                self.status.set_label(
                    f"{output.name} · {output.panel_summary()} · {where}"
                )

            if spanning:
                self._fit_drop.set_selected(len(Fit))
            else:
                fit = source.fit if source else Fit.FILL
                self._fit_drop.set_selected(list(Fit).index(fit))

            uses_backdrop = (
                not spanning and source is not None and source.fit.uses_backdrop
            )
            self._backdrop.set_sensitive(uses_backdrop)
            rgba = Gdk.RGBA()
            rgba.parse(source.backdrop if source else "#000000")
            self._backdrop.set_rgba(rgba)

            self._follow.set_sensitive(spanning or source is not None)
            self._fit_drop.set_sensitive(output is not None)
        finally:
            self._suppress = False

    # ----------------------------------------------------------------- edits

    def _on_fit_changed(self, *_args) -> None:
        if self._suppress:
            return
        index = self._fit_drop.get_selected()
        if index == Gtk.INVALID_LIST_POSITION:
            return

        if index == len(Fit):
            self._start_span()
            return

        fit = list(Fit)[index]
        selected = self.session.selected
        if self.config.span is not None:
            # Coming back from a span: the picture stays, every display keeps
            # it, and the new fit applies to all of them. Leaving some displays
            # spanned and others not would be a state nothing can describe.
            source = self.config.span
            self.config.span = None
            for output in self._outputs():
                pinned = Source(
                    kind=source.kind,
                    path=source.path,
                    fit=fit,
                    backdrop=source.backdrop,
                    color=source.color,
                )
                self.config.pin(output.name, pinned)
            self._commit(f"Every display now shows it {fit.label.lower()}ed")
            return

        if not selected:
            return
        source = self.config.monitors.get(selected)
        if source is None:
            # Nothing pinned yet: adopt whatever the theme is showing so the
            # fit has something to act on.
            theme = library.theme_background()
            if theme is None:
                self._notice("Pick a picture first")
                self._sync_widgets()
                return
            source = Source(kind=Kind.IMAGE, path=str(theme))
            self.config.pin(selected, source)
        source.fit = fit
        self._commit()

    def _start_span(self) -> None:
        source = None
        if self.session.selected:
            source = self.config.monitors.get(self.session.selected)
        if source is None:
            source = next(iter(self.config.monitors.values()), None)
        if source is None:
            theme = library.theme_background()
            source = Source(kind=Kind.IMAGE, path=str(theme)) if theme else None
        if source is None:
            self._notice("Pick a picture first")
            self._sync_widgets()
            return

        self.config.span = Source(kind=source.kind, path=source.path, fit=Fit.FILL,
                                  color=source.color)
        covered = span.coverage(self._outputs())
        note = f"Spanned — {covered * 100:.0f}% of the picture lands on a screen"
        if covered < 0.9:
            note += ". The rest falls in the gaps between your displays."
        self._commit(note)

    def _on_backdrop_changed(self, *_args) -> None:
        if self._suppress or not self.session.selected:
            return
        source = self.config.monitors.get(self.session.selected)
        if source is None:
            return
        rgba = self._backdrop.get_rgba()
        source.backdrop = (
            f"#{round(rgba.red * 255):02x}"
            f"{round(rgba.green * 255):02x}"
            f"{round(rgba.blue * 255):02x}"
        )
        self._commit()

    def _on_follow_theme(self, *_args) -> None:
        if self.config.span is not None:
            self.config.span = None
            self._commit("Span cleared")
            return
        selected = self.session.selected
        if selected and self.config.unpin(selected):
            self._commit(f"{selected} follows the theme background again")

    def _on_clear_all(self, *_args) -> None:
        self.config.monitors.clear()
        self.config.span = None
        self._commit("Every display follows the theme background again")

    def _assign(self, path: Path) -> None:
        kind = kind_for_path(path)
        if kind is None:
            self._notice(f"Not a picture displaywright can draw: {path.name}")
            return

        try:
            adoption = library.adopt(path, self._folders())
        except OSError as exc:
            # Better a wallpaper pointing at the original than no wallpaper.
            self._notice(f"Using the original — could not copy it in: {exc}")
        else:
            path = adoption.path
            if adoption.copied or not self._grid_shows(path):
                self._reload_library()

        if self.config.span is not None:
            self.config.span.kind = kind
            self.config.span.path = str(path)
            self._commit(f"Spanned {path.name}")
            return

        selected = self.session.selected
        if not selected:
            self._notice("Select a display first")
            return
        existing = self.config.monitors.get(selected)
        fit = existing.fit if existing else Fit.FILL
        backdrop = existing.backdrop if existing else "#000000"
        self.config.pin(
            selected,
            Source(kind=kind, path=str(path), fit=fit, backdrop=backdrop),
        )
        self._commit(f"{path.name} on {selected}")

    def _commit(self, message: str = "") -> None:
        """Persist and redraw. Writes are coalesced so a drag on the colour
        button does not thrash the file the renderer is watching."""
        self._refresh()
        if message:
            self._notice(message)
        if self._save_source_id:
            GLib.source_remove(self._save_source_id)
        self._save_source_id = GLib.timeout_add(120, self._flush)

    def _flush(self) -> bool:
        self._save_source_id = 0
        payload = self.config.to_json()
        try:
            store.save(self.config)
        except OSError as exc:
            self._notice(f"Could not save: {exc}")
            return False
        self._last_written = payload
        shell.reload()
        return False

    # -------------------------------------------------------------- library

    def _grid_shows(self, path: Path) -> bool:
        return any(entry.path == path for entry in self._entries)

    def _folders(self) -> list[Path]:
        chosen = [Path(f).expanduser() for f in self.config.folders]
        return chosen or library.default_folders()

    def _reload_library(self) -> None:
        self._library_generation += 1
        generation = self._library_generation
        folders = self._folders()

        def work() -> None:
            entries = library.scan(folders)
            GLib.idle_add(self._populate_library, generation, entries)
            for entry in entries:
                if generation != self._library_generation:
                    return
                thumb = library.ensure_thumbnail(entry.path)
                if thumb is not None:
                    GLib.idle_add(self._set_thumbnail, generation, str(entry.path), str(thumb))

        threading.Thread(target=work, name="displaywright-library", daemon=True).start()

    def _populate_library(self, generation: int, entries: list[library.Entry]) -> bool:
        if generation != self._library_generation:
            return False
        self._entries = entries
        self._tiles = {}

        child = self._flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self._flow.remove(child)
            child = nxt

        for entry in entries:
            self._flow.append(self._tile(entry))
        self._library_stack.set_visible_child_name("grid" if entries else "empty")
        return False

    def _tile(self, entry: library.Entry) -> Gtk.Widget:
        picture = Gtk.Picture(content_fit=Gtk.ContentFit.COVER)
        picture.set_size_request(THUMBNAIL_WIDTH, round(THUMBNAIL_WIDTH * 9 / 16))
        picture.add_css_class("card")
        self._tiles[str(entry.path)] = picture

        label = Gtk.Label(label=entry.name, ellipsize=3, max_width_chars=18)
        label.add_css_class("caption")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(picture)
        if entry.kind == Kind.VIDEO:
            row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4,
                          halign=Gtk.Align.CENTER)
            row.append(Gtk.Image(icon_name="video-x-generic-symbolic"))
            row.append(label)
            box.append(row)
        else:
            box.append(label)

        child = Gtk.FlowBoxChild()
        child.set_child(box)
        child.set_tooltip_text(str(entry.path))
        # FlowBox with SelectionMode.NONE still activates on click, which is
        # the interaction we want: one click puts it on the display.
        child.set_focusable(True)
        return child

    def _set_thumbnail(self, generation: int, path: str, thumb: str) -> bool:
        if generation != self._library_generation:
            return False
        picture = self._tiles.get(path)
        if picture is not None:
            picture.set_filename(thumb)
        return False

    def _on_entry_activated(self, _flow: Gtk.FlowBox, child: Gtk.FlowBoxChild) -> None:
        index = child.get_index()
        if 0 <= index < len(self._entries):
            self._assign(self._entries[index].path)

    # --------------------------------------------------------------- dialogs

    def _on_browse(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Choose a wallpaper")
        filters = Gio.ListStore.new(Gtk.FileFilter)
        pictures = Gtk.FileFilter(name="Pictures and videos")
        for mime in ("image/*", "video/*"):
            pictures.add_mime_type(mime)
        filters.append(pictures)
        dialog.set_filters(filters)
        dialog.open(self.get_root(), None, self._on_browse_done)

    def _on_browse_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.open_finish(result)
        except GLib.Error:
            return
        if file is not None and file.get_path():
            self._assign(Path(file.get_path()))

    def _on_open_folder(self, *_args) -> None:
        folder = library.ensure_wallpaper_dir()
        launcher = Gtk.FileLauncher(file=Gio.File.new_for_path(str(folder)))
        launcher.launch(self.get_root(), None, None)

    def _on_add_folder(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Add a wallpaper folder")
        dialog.select_folder(self.get_root(), None, self._on_add_folder_done)

    def _on_add_folder_done(self, dialog: Gtk.FileDialog, result) -> None:
        try:
            file = dialog.select_folder_finish(result)
        except GLib.Error:
            return
        if file is None or not file.get_path():
            return
        folder = file.get_path()
        if not self.config.folders:
            # First explicit choice replaces the guessed defaults, but keeping
            # the guesses would silently re-add folders the user did not ask
            # for, so seed the list with them instead of discarding them.
            self.config.folders = [str(p) for p in library.default_folders()]
        if folder not in self.config.folders:
            self.config.folders.append(folder)
        self._commit(f"Added {folder}")
        self._reload_library()

    # ---------------------------------------------------------------- misc

    def _install_renderer(self) -> None:
        if not plugin.is_omarchy():
            self._notice("This does not look like an Omarchy system")
            return
        try:
            changed = plugin.install(link=True)
        except (OSError, FileNotFoundError) as exc:
            self._notice(str(exc))
            return
        if shell.is_running():
            shell.call("shell", "reloadConfig")
            shell.rescan_plugins()
        self._sync_banner()
        self._notice("Renderer installed" if changed else "Renderer was already installed")

    def _uninstall_renderer(self) -> None:
        plugin.uninstall()
        if shell.is_running():
            shell.call("shell", "reloadConfig")
            shell.rescan_plugins()
        self._sync_banner()
        self._notice("Background handed back to Omarchy")

    def _notice(self, message: str) -> None:
        self.session.notice(message)

    def shutdown(self) -> None:
        if self._save_source_id:
            GLib.source_remove(self._save_source_id)
            self._save_source_id = 0
            self._flush()
