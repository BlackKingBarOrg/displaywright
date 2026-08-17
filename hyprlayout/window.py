"""Main window: canvas on the left, per-display settings on the right."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from . import __version__, hypr, luawriter
from .canvas import LayoutCanvas
from .model import TRANSFORMS, Mode, MonitorState, bounding_box, scale_warning, suggest_scale
from .profiles import ProfileStore, fingerprint
from .snapping import auto_arrange, normalize, validate

CONFIRM_SECONDS = 15

VRR_CHOICES: list[tuple[str, int | None]] = [
    ("Inherit global", None),
    ("Off", 0),
    ("On", 1),
    ("Fullscreen only", 2),
]

SCALE_PRESETS = (1.0, 1.25, 1.5, 1.75, 2.0)


class MainWindow(Adw.ApplicationWindow):
    __gtype_name__ = "HyprlayoutWindow"

    def __init__(self, application: Adw.Application) -> None:
        super().__init__(application=application, title="Display Layout")
        self.set_default_size(1080, 680)

        self.store = ProfileStore()
        self.states: list[MonitorState] = []
        self.live_states: list[MonitorState] = []
        self._updating = False
        self._confirm_source: int | None = None

        self._build_ui()
        self._install_actions()
        self.reload_from_hyprland(announce=False)

        self._listener = hypr.EventListener(
            lambda name: GLib.idle_add(self._on_hypr_event, name)
        )
        self._listener.start()
        self.connect("close-request", self._on_close)

    # --------------------------------------------------------------------- UI

    def _build_ui(self) -> None:
        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        header = Adw.HeaderBar()
        self.window_title = Adw.WindowTitle(title="Display Layout", subtitle="")
        header.set_title_widget(self.window_title)

        reload_button = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Reload from Hyprland")
        reload_button.connect("clicked", lambda *_: self.reload_from_hyprland())
        header.pack_start(reload_button)

        self.profile_button = Gtk.MenuButton(
            icon_name="view-list-symbolic", tooltip_text="Layout profiles"
        )
        self.profile_button.set_popover(self._build_profile_popover())
        header.pack_start(self.profile_button)

        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self.apply_layout())
        header.pack_end(self.apply_button)

        menu = Gio.Menu()
        section = Gio.Menu()
        section.append("Save to monitors.lua…", "win.save-config")
        section.append("Copy Lua block", "win.copy-lua")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Auto arrange left to right", "win.auto-arrange")
        section.append("Move layout to origin", "win.normalize")
        section.append("Discard changes", "win.discard")
        menu.append_section(None, section)
        section = Gio.Menu()
        section.append("Locate selected display", "win.locate")
        section.append("About hyprlayout", "win.about")
        menu.append_section(None, section)
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu))

        toolbar.add_top_bar(header)

        self.banner = Adw.Banner(revealed=False)
        toolbar.add_top_bar(self.banner)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        self.canvas = LayoutCanvas()
        self.canvas.connect("selection-changed", lambda *_: self._sync_sidebar())
        self.canvas.connect("layout-changed", lambda *_: self._on_layout_changed())
        self.canvas.connect("layout-committed", lambda *_: self._on_layout_changed())

        canvas_frame = Gtk.Frame()
        canvas_frame.set_margin_start(12)
        canvas_frame.set_margin_end(6)
        canvas_frame.set_margin_top(12)
        canvas_frame.set_margin_bottom(12)
        canvas_frame.set_child(self.canvas)
        canvas_frame.set_hexpand(True)
        content.append(canvas_frame)

        content.append(Gtk.Separator(orientation=Gtk.Orientation.VERTICAL))
        content.append(self._build_sidebar())
        toolbar.set_content(content)

        # StyleManager is a process-wide singleton, so this handler outlives the
        # window unless we disconnect it: keep the id for teardown.
        self._style_manager = Adw.StyleManager.get_default()
        self._style_handler = self._style_manager.connect(
            "notify::dark", lambda *_: self.canvas.set_dark(self._style_manager.get_dark())
        )
        self.canvas.set_dark(self._style_manager.get_dark())

        shortcuts = Gtk.ShortcutController()
        shortcuts.set_scope(Gtk.ShortcutScope.GLOBAL)
        for accel, action in (
            ("<Control>Return", "win.apply"),
            ("<Control>s", "win.save-config"),
            ("<Control>r", "win.reload"),
            ("<Control>z", "win.discard"),
        ):
            shortcuts.add_shortcut(
                Gtk.Shortcut(
                    trigger=Gtk.ShortcutTrigger.parse_string(accel),
                    action=Gtk.NamedAction.new(action),
                )
            )
        self.add_controller(shortcuts)

    def _build_sidebar(self) -> Gtk.Widget:
        scroller = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        scroller.set_size_request(400, -1)
        page = Adw.PreferencesPage()
        scroller.set_child(page)

        display_group = Adw.PreferencesGroup(title="Display")
        page.add(display_group)

        self.output_row = Adw.ComboRow(title="Output")
        self.output_row.connect("notify::selected", self._on_output_selected)
        display_group.add(self.output_row)

        self.enabled_row = Adw.SwitchRow(title="Enabled", subtitle="Turn the output off entirely")
        self.enabled_row.connect("notify::active", self._on_enabled_changed)
        display_group.add(self.enabled_row)

        self.resolution_row = Adw.ComboRow(title="Resolution")
        self.resolution_row.connect("notify::selected", self._on_resolution_changed)
        display_group.add(self.resolution_row)

        self.refresh_row = Adw.ComboRow(title="Refresh rate")
        self.refresh_row.connect("notify::selected", self._on_refresh_changed)
        display_group.add(self.refresh_row)

        self.scale_row = Adw.SpinRow(
            title="Scale",
            adjustment=Gtk.Adjustment(lower=0.5, upper=4.0, step_increment=0.05, page_increment=0.25),
            digits=2,
        )
        self.scale_row.connect("notify::value", self._on_scale_changed)
        suggest = Gtk.Button(label="Auto", valign=Gtk.Align.CENTER)
        suggest.set_tooltip_text("Pick a scale that keeps text a readable size")
        suggest.connect("clicked", self._on_suggest_scale)
        self.scale_row.add_suffix(suggest)
        display_group.add(self.scale_row)

        # A plain box rather than an ActionRow: a row title next to five buttons
        # gets squeezed until it wraps one character per line.
        preset_box = Gtk.Box(homogeneous=True, halign=Gtk.Align.FILL, margin_top=6)
        preset_box.add_css_class("linked")
        for preset in SCALE_PRESETS:
            button = Gtk.Button(label=f"{preset:g}×", tooltip_text=f"Set scale to {preset:g}")
            button.connect("clicked", self._on_scale_preset, preset)
            preset_box.append(button)
        display_group.add(preset_box)

        self.rotation_row = Adw.ComboRow(
            title="Rotation",
            model=Gtk.StringList.new([label for label, _ in TRANSFORMS.values()]),
        )
        self.rotation_row.connect("notify::selected", self._on_rotation_changed)
        display_group.add(self.rotation_row)

        self.vrr_row = Adw.ComboRow(
            title="Variable refresh rate",
            model=Gtk.StringList.new([label for label, _ in VRR_CHOICES]),
        )
        self.vrr_row.connect("notify::selected", self._on_vrr_changed)
        display_group.add(self.vrr_row)

        self.mirror_row = Adw.ComboRow(title="Mirror of")
        self.mirror_row.connect("notify::selected", self._on_mirror_changed)
        display_group.add(self.mirror_row)

        position_group = Adw.PreferencesGroup(
            title="Position",
            description="Logical pixels. Drag on the canvas, or fine-tune here.",
        )
        page.add(position_group)
        self.x_row = Adw.SpinRow(
            title="X",
            adjustment=Gtk.Adjustment(lower=-32768, upper=32768, step_increment=10, page_increment=100),
        )
        self.x_row.connect("notify::value", self._on_position_changed)
        position_group.add(self.x_row)
        self.y_row = Adw.SpinRow(
            title="Y",
            adjustment=Gtk.Adjustment(lower=-32768, upper=32768, step_increment=10, page_increment=100),
        )
        self.y_row.connect("notify::value", self._on_position_changed)
        position_group.add(self.y_row)

        info_group = Adw.PreferencesGroup(title="Details")
        page.add(info_group)
        self.detail_row = Adw.ActionRow(title="—", subtitle="")
        self.detail_row.set_subtitle_lines(4)
        info_group.add(self.detail_row)

        return scroller

    def _build_profile_popover(self) -> Gtk.Popover:
        popover = Gtk.Popover()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=8,
                      margin_bottom=8, margin_start=8, margin_end=8)
        box.set_size_request(280, -1)

        label = Gtk.Label(label="Layout profiles", xalign=0.0)
        label.add_css_class("heading")
        box.append(label)

        self.profile_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.profile_list.add_css_class("boxed-list")
        box.append(self.profile_list)

        entry_box = Gtk.Box(spacing=6)
        self.profile_entry = Gtk.Entry(placeholder_text="New profile name", hexpand=True)
        self.profile_entry.connect("activate", lambda *_: self._save_profile())
        entry_box.append(self.profile_entry)
        save = Gtk.Button(icon_name="document-save-symbolic", tooltip_text="Save current layout")
        save.connect("clicked", lambda *_: self._save_profile())
        entry_box.append(save)
        box.append(entry_box)

        popover.set_child(box)
        popover.connect("show", lambda *_: self._refresh_profile_list())
        return popover

    def _install_actions(self) -> None:
        for name, handler in (
            ("apply", lambda *_: self.apply_layout()),
            ("reload", lambda *_: self.reload_from_hyprland()),
            ("save-config", lambda *_: self._save_config_dialog()),
            ("copy-lua", lambda *_: self._copy_lua()),
            ("auto-arrange", lambda *_: self._auto_arrange()),
            ("normalize", lambda *_: self._normalize()),
            ("discard", lambda *_: self.reload_from_hyprland()),
            ("locate", lambda *_: self._locate()),
            ("about", lambda *_: self._about()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)

    # ------------------------------------------------------------------- state

    def reload_from_hyprland(self, announce: bool = True) -> None:
        try:
            states = hypr.read_monitors()
        except hypr.HyprError as exc:
            self._toast(f"Could not read monitors: {exc}")
            return
        self.live_states = [s.copy() for s in states]
        self.states = states
        self.canvas.set_states(self.states)
        self._refresh_output_model()
        self._sync_sidebar()
        self._refresh_status()
        if announce:
            self._toast("Reloaded from Hyprland")

    @property
    def dirty(self) -> bool:
        live = {s.name: s for s in self.live_states}
        if set(live) != {s.name for s in self.states}:
            return True
        return any(not s.config_equals(live[s.name]) for s in self.states)

    def _on_layout_changed(self) -> None:
        self._sync_sidebar()
        self._refresh_status()

    def _refresh_status(self) -> None:
        enabled = [s for s in self.states if s.enabled]
        box = bounding_box([s.rect for s in enabled])
        count = f"{len(enabled)} display{'s' if len(enabled) != 1 else ''}"
        size = f"{round(box.w)}×{round(box.h)}" if enabled else "nothing enabled"
        suffix = " · unapplied changes" if self.dirty else ""
        self.window_title.set_subtitle(f"{count} · {size}{suffix}")
        self.apply_button.set_sensitive(self.dirty)

        problems = validate(self.states)
        warning = None
        selected = self.canvas.selected_state()
        if selected is not None:
            warning = scale_warning(selected)
        messages = problems + ([warning] if warning else [])
        if messages:
            self.banner.set_title(messages[0])
            self.banner.set_revealed(True)
        else:
            self.banner.set_revealed(False)

    # ----------------------------------------------------------------- sidebar

    def _refresh_output_model(self) -> None:
        self._updating = True
        try:
            labels = [f"{s.name} — {s.pretty_name}" if s.pretty_name != s.name else s.name
                      for s in self.states]
            _set_string_model(self.output_row, labels)
        finally:
            self._updating = False

    def _sync_sidebar(self) -> None:
        state = self.canvas.selected_state()
        rows = (
            self.enabled_row, self.resolution_row, self.refresh_row, self.scale_row,
            self.rotation_row, self.vrr_row, self.mirror_row, self.x_row, self.y_row,
        )
        if state is None:
            for row in rows:
                row.set_sensitive(False)
            return

        self._updating = True
        try:
            names = [s.name for s in self.states]
            if state.name in names:
                self.output_row.set_selected(names.index(state.name))

            self.enabled_row.set_active(state.enabled)
            for row in rows:
                row.set_sensitive(True)
            for row in rows[1:]:
                row.set_sensitive(state.enabled)

            # Resolution / refresh split so long mode lists stay usable.
            resolutions = _resolutions(state)
            _set_string_model(self.resolution_row, ["Preferred", *resolutions])
            if state.mode is None:
                self.resolution_row.set_selected(0)
            else:
                res = state.mode.resolution
                self.resolution_row.set_selected(
                    resolutions.index(res) + 1 if res in resolutions else 0
                )

            refreshes = _refresh_rates(state, state.mode)
            _set_string_model(self.refresh_row, [f"{r:g} Hz" for r in refreshes])
            self.refresh_row.set_sensitive(state.enabled and bool(refreshes) and state.mode is not None)
            if state.mode is not None and state.mode.refresh in refreshes:
                self.refresh_row.set_selected(refreshes.index(state.mode.refresh))

            self.scale_row.set_value(state.scale)
            self.rotation_row.set_selected(state.transform if state.transform in TRANSFORMS else 0)
            self.vrr_row.set_selected(
                next(i for i, (_, v) in enumerate(VRR_CHOICES) if v == state.vrr)
            )

            others = [s.name for s in self.states if s.name != state.name]
            _set_string_model(self.mirror_row, ["None", *others])
            self.mirror_row.set_selected(
                others.index(state.mirror_of) + 1
                if state.mirror_of in others else 0
            )

            self.x_row.set_value(state.x)
            self.y_row.set_value(state.y)

            px_w, px_h = state.pixel_size
            lw, lh = state.logical_size
            panel = state.description or state.pretty_name
            if state.diagonal_inches:
                panel += f" · {state.diagonal_inches:.1f}\" · {state.dpi:.0f} dpi"
            details = [
                panel,
                f"native {px_w}×{px_h} · logical {round(lw)}×{round(lh)}",
                f"rule: monitor = {state.rule_args()}",
            ]
            self.detail_row.set_title(state.name)
            self.detail_row.set_subtitle("\n".join(details))
        finally:
            self._updating = False

    # --------------------------------------------------------- sidebar handlers

    def _selected(self) -> MonitorState | None:
        if self._updating:
            return None
        return self.canvas.selected_state()

    def _after_edit(self) -> None:
        self.canvas.queue_draw()
        self._sync_sidebar()
        self._refresh_status()

    def _on_output_selected(self, row: Adw.ComboRow, _param) -> None:
        if self._updating:
            return
        index = row.get_selected()
        if 0 <= index < len(self.states):
            self.canvas.select(self.states[index].name)

    def _on_enabled_changed(self, row: Adw.SwitchRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        if row.get_active() == state.enabled:
            return
        state.enabled = row.get_active()
        if state.enabled and state.mode is None and state.available_modes:
            state.mode = state.preferred_mode()
        self._after_edit()

    def _on_resolution_changed(self, row: Adw.ComboRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        index = row.get_selected()
        if index <= 0:
            wanted = None
        else:
            resolutions = _resolutions(state)
            if index - 1 >= len(resolutions):
                return
            width, height = (int(v) for v in resolutions[index - 1].split("x"))
            candidates = [
                m for m in state.available_modes if m.width == width and m.height == height
            ]
            keep = state.mode.refresh if state.mode else 0.0
            wanted = min(candidates, key=lambda m: abs(m.refresh - keep)) if candidates \
                else Mode(width, height)
        if wanted == state.mode:
            return
        state.mode = wanted
        self._after_edit()

    def _on_refresh_changed(self, row: Adw.ComboRow, _param) -> None:
        state = self._selected()
        if state is None or state.mode is None:
            return
        rates = _refresh_rates(state, state.mode)
        index = row.get_selected()
        if not (0 <= index < len(rates)):
            return
        wanted = Mode(state.mode.width, state.mode.height, rates[index])
        if wanted == state.mode:
            return
        state.mode = wanted
        self._after_edit()

    def _on_scale_changed(self, row: Adw.SpinRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        scale = round(row.get_value(), 4)
        if abs(scale - state.scale) < 1e-9:
            return
        state.scale = scale
        self._after_edit()

    def _on_scale_preset(self, _button: Gtk.Button, preset: float) -> None:
        state = self.canvas.selected_state()
        if state is None:
            return
        state.scale = preset
        self._after_edit()

    def _on_suggest_scale(self, _button: Gtk.Button) -> None:
        state = self.canvas.selected_state()
        if state is None:
            return
        state.scale = suggest_scale(state)
        self._after_edit()

    def _on_rotation_changed(self, row: Adw.ComboRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        transform = int(row.get_selected())
        if transform == state.transform:
            return
        state.transform = transform
        self._after_edit()

    def _on_vrr_changed(self, row: Adw.ComboRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        vrr = VRR_CHOICES[int(row.get_selected())][1]
        if vrr == state.vrr:
            return
        state.vrr = vrr
        self._after_edit()

    def _on_mirror_changed(self, row: Adw.ComboRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        index = int(row.get_selected())
        others = [s.name for s in self.states if s.name != state.name]
        mirror = others[index - 1] if 0 < index <= len(others) else None
        if mirror == state.mirror_of:
            return
        state.mirror_of = mirror
        self._after_edit()

    def _on_position_changed(self, _row: Adw.SpinRow, _param) -> None:
        state = self._selected()
        if state is None:
            return
        x, y = int(self.x_row.get_value()), int(self.y_row.get_value())
        if (x, y) == (state.x, state.y):
            return
        state.x, state.y = x, y
        self._after_edit()

    # ------------------------------------------------------------ layout tools

    def _auto_arrange(self) -> None:
        auto_arrange(self.states)
        self._after_edit()
        self._toast("Arranged left to right")

    def _normalize(self) -> None:
        if normalize(self.states):
            self._after_edit()
            self._toast("Layout moved to origin")
        else:
            self._toast("Already at the origin")

    def _locate(self) -> None:
        """Send focus (and the pointer) to a display so the user can spot it."""
        state = self.canvas.selected_state()
        if state is None:
            return
        if not state.enabled:
            self._toast(f"{state.name} is disabled — nothing to look at")
            return
        try:
            hypr.focus_monitor(state.name)
            # Aim at where the display *currently* is, not where the pending
            # layout would put it.
            live = next((s for s in self.live_states if s.name == state.name), None)
            if live is not None and live.enabled:
                hypr.move_cursor(int(live.rect.cx), int(live.rect.cy))
        except hypr.HyprError as exc:
            self._toast(f"Could not focus {state.name}: {exc}")
            return
        hypr.notify(f"This is {state.name} — {state.pretty_name}", ms=2500)
        self._toast(f"Moved focus to {state.name}")

    # ------------------------------------------------------------------- apply

    def apply_layout(self) -> None:
        problems = validate(self.states)
        blocking = [p for p in problems if "overlap" in p or "disabled" in p]
        if blocking:
            dialog = Adw.AlertDialog(
                heading="Apply anyway?",
                body="\n".join(problems),
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("apply", "Apply")
            dialog.set_response_appearance("apply", Adw.ResponseAppearance.DESTRUCTIVE)
            dialog.set_default_response("cancel")
            dialog.set_close_response("cancel")
            dialog.connect(
                "response",
                lambda _d, response: self._push_layout() if response == "apply" else None,
            )
            dialog.present(self)
            return
        self._push_layout()

    def _push_layout(self) -> None:
        try:
            snapshot = hypr.read_monitors()
        except hypr.HyprError:
            snapshot = [s.copy() for s in self.live_states]
        try:
            hypr.apply_states(self.states)
        except hypr.HyprError as exc:
            self._toast(f"Apply failed: {exc}")
            return
        self._confirm_layout(snapshot)

    def _confirm_layout(self, snapshot: Sequence[MonitorState]) -> None:
        """Keep-or-revert prompt, defaulting to revert if nobody answers."""
        dialog = Adw.AlertDialog(heading="Keep this arrangement?")
        dialog.add_response("revert", "Revert")
        dialog.add_response("keep", "Keep changes")
        dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("keep")
        dialog.set_close_response("revert")

        checkbox = Gtk.CheckButton(
            label=f"Also write {_display_path(luawriter.default_config_path())}",
            active=True,
        )
        dialog.set_extra_child(checkbox)

        remaining = CONFIRM_SECONDS

        def render() -> None:
            dialog.set_body(
                f"Reverting in {remaining}s if you do not confirm — "
                "so a display that went black cannot lock you out."
            )

        def tick() -> bool:
            nonlocal remaining
            remaining -= 1
            if remaining <= 0:
                self._confirm_source = None
                dialog.close()
                return False
            render()
            return True

        render()
        self._confirm_source = GLib.timeout_add_seconds(1, tick)
        dialog.connect("response", self._on_confirm_response, snapshot, checkbox)
        dialog.present(self)

    def _on_confirm_response(
        self,
        _dialog: Adw.AlertDialog,
        response: str,
        snapshot: Sequence[MonitorState],
        checkbox: Gtk.CheckButton,
    ) -> None:
        if self._confirm_source is not None:
            GLib.source_remove(self._confirm_source)
            self._confirm_source = None

        if response == "keep":
            write_config = checkbox.get_active()
            try:
                self.live_states = [s.copy() for s in hypr.read_monitors()]
            except hypr.HyprError:
                self.live_states = [s.copy() for s in self.states]
            self._refresh_status()
            if write_config:
                self._write_config()
            else:
                self._toast("Applied — not saved, Hyprland will forget it on reload")
            return

        try:
            hypr.apply_states(snapshot)
        except hypr.HyprError as exc:
            self._toast(f"Revert failed: {exc}")
            return
        self.reload_from_hyprland(announce=False)
        self._toast("Reverted to the previous arrangement")

    # ------------------------------------------------------------------ persist

    def _write_config(self) -> None:
        path = luawriter.default_config_path()
        try:
            backup = luawriter.save(path, self.states)
        except OSError as exc:
            self._toast(f"Could not write {path}: {exc}")
            return
        message = f"Saved to {_display_path(path)}"
        if backup is not None:
            message += f" (backup: {backup.name})"
        self._toast(message)

    def _save_config_dialog(self) -> None:
        path = luawriter.default_config_path()
        try:
            _, patch = luawriter.preview(path, self.states)
        except OSError as exc:
            self._toast(f"Could not read {path}: {exc}")
            return
        if not patch:
            self._toast(f"{_display_path(path)} is already up to date")
            return

        dialog = Adw.AlertDialog(
            heading="Save display layout",
            body=f"These changes will be written to {_display_path(path)}. "
                 "The current file is backed up first.",
        )
        dialog.set_content_width(760)
        dialog.set_content_height(520)

        view = Gtk.TextView(editable=False, monospace=True, top_margin=8, bottom_margin=8,
                            left_margin=8, right_margin=8)
        view.get_buffer().set_text(patch)
        scroller = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        scroller.set_child(view)
        scroller.set_size_request(-1, 360)
        frame = Gtk.Frame()
        frame.set_child(scroller)
        dialog.set_extra_child(frame)

        dialog.add_response("cancel", "Cancel")
        dialog.add_response("write", "Write file")
        dialog.set_response_appearance("write", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("write")
        dialog.set_close_response("cancel")
        dialog.connect(
            "response",
            lambda _d, response: self._write_config() if response == "write" else None,
        )
        dialog.present(self)

    def _copy_lua(self) -> None:
        text = luawriter.render_block(self.states)
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        self._toast("Lua block copied to the clipboard")

    # ----------------------------------------------------------------- profiles

    def _refresh_profile_list(self) -> None:
        while (child := self.profile_list.get_first_child()) is not None:
            self.profile_list.remove(child)

        names = self.store.names()
        current = self.store.match(self.states)
        if not names:
            row = Adw.ActionRow(title="No profiles yet",
                                subtitle="Save the current arrangement below")
            row.set_activatable(False)
            self.profile_list.append(row)
            return

        for name in names:
            profile = self.store.get(name)
            row = Adw.ActionRow(title=name, subtitle=profile.fingerprint if profile else "")
            row.set_subtitle_lines(2)
            if current is not None and current.name == name:
                row.add_css_class("accent")
            load = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="Load this profile")
            load.add_css_class("flat")
            load.connect("clicked", self._on_load_profile, name)
            row.add_suffix(load)
            delete = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER,
                                tooltip_text="Delete this profile")
            delete.add_css_class("flat")
            delete.connect("clicked", self._on_delete_profile, name)
            row.add_suffix(delete)
            self.profile_list.append(row)

    def _save_profile(self) -> None:
        name = self.profile_entry.get_text().strip()
        if not name:
            self._toast("Give the profile a name first")
            return
        self.store.put(name, self.states)
        self.profile_entry.set_text("")
        self._refresh_profile_list()
        self._toast(f"Saved profile “{name}”")

    def _on_load_profile(self, _button: Gtk.Button, name: str) -> None:
        profile = self.store.get(name)
        if profile is None:
            return
        skipped = profile.apply_to(self.states)
        self._after_edit()
        self.profile_button.get_popover().popdown()
        if skipped:
            self._toast(f"Loaded “{name}” — not connected: {', '.join(skipped)}")
        else:
            self._toast(f"Loaded “{name}” — press Apply to use it")

    def _on_delete_profile(self, _button: Gtk.Button, name: str) -> None:
        self.store.delete(name)
        self._refresh_profile_list()
        self._toast(f"Deleted profile “{name}”")

    # -------------------------------------------------------------- misc / glue

    def _on_hypr_event(self, name: str) -> bool:
        if self.dirty:
            self._toast("Displays changed in Hyprland — reload to discard your edits")
            return False
        self.reload_from_hyprland(announce=False)
        if name.startswith("monitor"):
            self._toast("Display setup changed — refreshed")
        return False

    def _about(self) -> None:
        about = Adw.AboutDialog(
            application_name="hyprlayout",
            application_icon="video-display-symbolic",
            version=__version__,
            developer_name="bkblab",
            comments=(
                "Drag-and-drop display arrangement for Hyprland.\n\n"
                "Changes are applied live with hyprctl and can be written back to "
                "your Omarchy monitors.lua."
            ),
            license_type=Gtk.License.MIT_X11,
            website="https://wiki.hypr.land/Configuring/Basics/Monitors/",
        )
        about.present(self)

    def _toast(self, message: str) -> None:
        self.toasts.add_toast(Adw.Toast(title=message))

    def shutdown(self) -> None:
        """Release everything that outlives the window."""
        self._listener.stop()
        if self._confirm_source is not None:
            GLib.source_remove(self._confirm_source)
            self._confirm_source = None
        if self._style_handler:
            self._style_manager.disconnect(self._style_handler)
            self._style_handler = 0

    def _on_close(self, *_args) -> bool:
        self.shutdown()
        return False


def _set_string_model(row: Adw.ComboRow, items: Sequence[str]) -> None:
    """Replace a combo row's model only when its contents actually change.

    Setting a model re-emits notify::selected, so a handler that reacts by
    rebuilding the model loops forever and the window stops responding. Skipping
    identical updates cuts that at the source.
    """
    model = row.get_model()
    items = list(items)
    unchanged = (
        model is not None
        and model.get_n_items() == len(items)
        and all(model.get_string(i) == items[i] for i in range(len(items)))
    )
    if unchanged:
        return
    row.set_model(Gtk.StringList.new(items))


def _resolutions(state: MonitorState) -> list[str]:
    seen: list[str] = []
    for mode in state.available_modes:
        if mode.resolution not in seen:
            seen.append(mode.resolution)
    if state.mode is not None and state.mode.resolution not in seen:
        seen.insert(0, state.mode.resolution)
    return seen


def _refresh_rates(state: MonitorState, mode: Mode | None) -> list[float]:
    if mode is None:
        return []
    rates = sorted(
        {
            m.refresh
            for m in state.available_modes
            if m.width == mode.width and m.height == mode.height and m.refresh
        },
        reverse=True,
    )
    if mode.refresh and mode.refresh not in rates:
        rates.insert(0, mode.refresh)
    return rates


def _display_path(path: Path) -> str:
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def summary_line(states: Sequence[MonitorState]) -> str:
    """Short text describing a layout, used by the CLI."""
    enabled = [s for s in states if s.enabled]
    box = bounding_box([s.rect for s in enabled])
    return (
        f"{len(enabled)}/{len(states)} enabled · desktop {round(box.w)}×{round(box.h)} · "
        f"outputs {fingerprint(states)}"
    )
