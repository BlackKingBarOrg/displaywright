"""The arrangement page: canvas on the left, per-display settings on the right."""

from __future__ import annotations

from collections.abc import Callable, Sequence

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .. import hypr
from ..model import (
    TRANSFORMS,
    Mode,
    MonitorState,
    bounding_box,
    scale_warning,
    suggest_scale,
    unmet_requests,
)
from ..paths import display_path
from ..session import Session, run_async
from . import luawriter, omarchy
from .canvas import ArrangeCanvas
from .luawriter import default_config_path
from .profiles import ProfileStore
from .snapping import auto_arrange, normalize, validate

CONFIRM_SECONDS = 15

VRR_CHOICES: list[tuple[str, int | None]] = [
    ("Inherit global", None),
    ("Off", 0),
    ("On", 1),
    ("Fullscreen only", 2),
]

SCALE_PRESETS = (1.0, 1.25, 1.5, 1.75, 2.0)


class DisplaysPage(Gtk.Box):
    """Drag displays into place, tune each one, apply, then keep or revert."""

    __gtype_name__ = "DisplaywrightDisplaysPage"

    #: What the view switcher calls this page.
    TITLE = "Displays"
    ICON = "video-display-symbolic"

    def __init__(
        self, session: Session, actions: Gio.ActionMap, reload_layout: Callable[[], None]
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.session = session
        #: Asked for rather than done here, so a revert brings both pages back
        #: in step through the window's one reload path.
        self.reload_layout = reload_layout
        self.store = ProfileStore()
        self._updating = False
        self._confirm_source: int | None = None
        self._busy: str | None = None

        self._build()
        self._install_actions(actions)

        session.connect("layout-reloaded", lambda *_: self._on_layout_reloaded())
        session.connect("selection-changed", lambda *_: self._on_selection_changed())

    # ----------------------------------------------------------------- header

    def header_start(self) -> Gtk.Widget:
        """Controls this page contributes to the left of the header bar."""
        return self._header_start

    def header_end(self) -> Gtk.Widget:
        return self._header_end

    def _build_header(self) -> None:
        """Built with the rest of the page, not when the window asks for it.

        refresh_status() reaches for the Apply button, and it can run before the
        window has collected these.
        """
        self._header_start = Gtk.Box(spacing=6)
        self.profile_button = Gtk.MenuButton(
            icon_name="view-list-symbolic", tooltip_text="Layout profiles"
        )
        self.profile_button.set_popover(self._build_profile_popover())
        self._header_start.append(self.profile_button)

        self._header_end = Gtk.Box(spacing=6)
        self.apply_button = Gtk.Button(label="Apply")
        self.apply_button.add_css_class("suggested-action")
        self.apply_button.connect("clicked", lambda *_: self.apply_layout())
        self._header_end.append(self.apply_button)

    def menu_model(self) -> Gio.Menu:
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
        menu.append_section(None, section)
        return menu

    def shortcuts(self) -> tuple[tuple[str, str], ...]:
        return (
            ("<Control>Return", "win.apply"),
            ("<Control>s", "win.save-config"),
            ("<Control>z", "win.discard"),
        )

    # --------------------------------------------------------------------- UI

    def _build(self) -> None:
        self._build_header()

        self.banner = Adw.Banner(revealed=False)
        self.append(self.banner)

        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, vexpand=True)
        self.canvas = ArrangeCanvas()
        self.canvas.connect("selection-changed", self._on_canvas_selection)
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
        self.append(content)

        self.status = Gtk.Label(xalign=0.0, margin_start=14, margin_end=14,
                                margin_top=4, margin_bottom=6, ellipsize=3)
        self.status.add_css_class("caption")
        self.status.add_css_class("dim-label")
        self.append(self.status)

        # StyleManager is a process-wide singleton, so this handler outlives the
        # page unless we disconnect it: keep the id for teardown.
        self._style_manager = Adw.StyleManager.get_default()
        self._style_handler = self._style_manager.connect(
            "notify::dark", lambda *_: self.canvas.set_dark(self._style_manager.get_dark())
        )
        self.canvas.set_dark(self._style_manager.get_dark())

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

    def _install_actions(self, actions: Gio.ActionMap) -> None:
        for name, handler in (
            ("apply", lambda *_: self.apply_layout()),
            ("save-config", lambda *_: self._save_config_dialog()),
            ("copy-lua", lambda *_: self._copy_lua()),
            ("auto-arrange", lambda *_: self._auto_arrange()),
            ("normalize", lambda *_: self._normalize()),
            ("locate", lambda *_: self._locate()),
        ):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            actions.add_action(action)

    # ---------------------------------------------------------------- session

    @property
    def states(self) -> list[MonitorState]:
        return self.session.states

    def _on_layout_reloaded(self) -> None:
        self.canvas.set_states(self.states)
        self._refresh_output_model()
        self._sync_sidebar()
        self.refresh_status()

    def _on_selection_changed(self) -> None:
        if self.canvas.selected != self.session.selected:
            self.canvas.select(self.session.selected)
        self._sync_sidebar()
        self.refresh_status()

    def _on_canvas_selection(self, *_args) -> None:
        self.session.selected = self.canvas.selected

    def _set_busy(self, message: str | None) -> None:
        self._busy = message
        if message:
            self.banner.set_title(message)
            self.banner.set_revealed(True)
            self.apply_button.set_sensitive(False)
        else:
            self.refresh_status()

    def _on_layout_changed(self) -> None:
        self.session.note_edit()
        self._sync_sidebar()
        self.refresh_status()

    def refresh_status(self) -> None:
        enabled = [s for s in self.states if s.enabled]
        box = bounding_box([s.rect for s in enabled])
        count = f"{len(enabled)} display{'s' if len(enabled) != 1 else ''}"
        size = f"{round(box.w)}×{round(box.h)}" if enabled else "nothing enabled"
        suffix = " · unapplied changes" if self.session.dirty else ""
        self.status.set_label(f"{count} · {size}{suffix}")
        self.apply_button.set_sensitive(self.session.dirty and self._busy is None)

        problems = validate(self.states)
        warning = None
        selected = self.session.selected_state()
        if selected is not None:
            warning = scale_warning(selected)
        messages = problems + ([warning] if warning else [])
        if messages:
            self.banner.set_title(messages[0])
            self.banner.set_revealed(True)
        elif self._busy is None:
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
        state = self.session.selected_state()
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
            if state.is_builtin and omarchy.has_safety_net():
                self.enabled_row.set_subtitle(
                    "Off while an external display is connected; Omarchy switches "
                    "it back on when none is left"
                )
            elif state.is_builtin:
                self.enabled_row.set_subtitle(
                    "Turn the panel off — nothing on this system switches it back on "
                    "automatically"
                )
            else:
                self.enabled_row.set_subtitle("Turn the output off entirely")
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
        return self.session.selected_state()

    def _after_edit(self) -> None:
        self.canvas.queue_draw()
        self.session.note_edit()
        self._sync_sidebar()
        self.refresh_status()

    def _on_output_selected(self, row: Adw.ComboRow, _param) -> None:
        if self._updating:
            return
        index = row.get_selected()
        if 0 <= index < len(self.states):
            self.session.selected = self.states[index].name

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
        state = self.session.selected_state()
        if state is None:
            return
        state.scale = preset
        self._after_edit()

    def _on_suggest_scale(self, _button: Gtk.Button) -> None:
        state = self.session.selected_state()
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
        self.session.notice("Arranged left to right")

    def _normalize(self) -> None:
        if normalize(self.states):
            self._after_edit()
            self.session.notice("Layout moved to origin")
        else:
            self.session.notice("Already at the origin")

    def _locate(self) -> None:
        """Send focus (and the pointer) to a display so the user can spot it."""
        state = self.session.selected_state()
        if state is None:
            return
        if not state.enabled:
            self.session.notice(f"{state.name} is disabled — nothing to look at")
            return
        # Aim at where the display *currently* is, not where the pending layout
        # would put it.
        live = next((s for s in self.session.live_states if s.name == state.name), None)
        target = (int(live.rect.cx), int(live.rect.cy)) if live and live.enabled else None
        name, pretty = state.name, state.pretty_name

        def work():
            hypr.focus_monitor(name)
            if target is not None:
                hypr.move_cursor(*target)
            hypr.notify(f"This is {name} — {pretty}", ms=2500)

        def done(_result, error) -> None:
            if error is not None:
                self.session.notice(f"Could not focus {name}: {error}")
            else:
                self.session.notice(f"Moved focus to {name}")

        run_async(work, done)

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
        if self._busy is not None:
            return
        wanted = [s.copy() for s in self.states]
        fallback = [s.copy() for s in self.session.live_states]

        def work():
            try:
                snapshot = hypr.read_monitors()
            except hypr.HyprError:
                snapshot = fallback
            hypr.apply_states(wanted)
            # Read back: an advertised mode can still be unreachable, and a
            # fractional scale gets nudged. The user deserves to hear about it.
            try:
                achieved = hypr.read_monitors()
            except hypr.HyprError:
                achieved = []
            return snapshot, achieved

        def done(result, error) -> None:
            self._set_busy(None)
            if error is not None:
                self.session.notice(f"Apply failed: {error}")
                return
            snapshot, achieved = result
            self._confirm_layout(snapshot, unmet_requests(wanted, achieved))

        self._set_busy("Applying — waiting for Hyprland…")
        run_async(work, done)

    def _confirm_layout(
        self, snapshot: Sequence[MonitorState], shortfalls: Sequence[str] = ()
    ) -> None:
        """Keep-or-revert prompt, defaulting to revert if nobody answers."""
        heading = "Keep this arrangement?"
        if shortfalls:
            heading = "Applied, but not exactly as asked"
        dialog = Adw.AlertDialog(heading=heading)
        dialog.add_response("revert", "Revert")
        dialog.add_response("keep", "Keep changes")
        dialog.set_response_appearance("keep", Adw.ResponseAppearance.SUGGESTED)
        dialog.set_default_response("keep")
        dialog.set_close_response("revert")

        checkbox = Gtk.CheckButton(
            label=f"Also write {display_path(default_config_path())}",
            active=True,
        )
        dialog.set_extra_child(checkbox)

        remaining = CONFIRM_SECONDS

        preamble = ("\n".join(shortfalls) + "\n\n") if shortfalls else ""

        def render() -> None:
            dialog.set_body(
                f"{preamble}Reverting in {remaining}s if you do not confirm — "
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

            def kept(states, error) -> None:
                self._set_busy(None)
                self.session.live_states = [
                    s.copy() for s in (self.states if error is not None else states)
                ]
                self.refresh_status()
                if write_config:
                    self._write_config()
                else:
                    self.session.notice(
                        "Applied — not saved, Hyprland will forget it on reload"
                    )

            self._set_busy("Confirming with Hyprland…")
            run_async(hypr.read_monitors, kept)
            return

        def reverted(_result, error) -> None:
            self._set_busy(None)
            if error is not None:
                self.session.notice(f"Revert failed: {error}")
                return
            self.reload_layout()
            self.session.notice("Reverted to the previous arrangement")

        self._set_busy("Reverting…")
        run_async(lambda: hypr.apply_states(snapshot), reverted)

    # ------------------------------------------------------------------ persist

    def _write_config(self) -> None:
        path = default_config_path()
        use_toggle = omarchy.available()
        try:
            backup = luawriter.save(path, self.states, toggle_builtin=use_toggle)
        except OSError as exc:
            self.session.notice(f"Could not write {path}: {exc}")
            return

        note = None
        if use_toggle:
            try:
                note = omarchy.sync(self.states)
            except OSError as exc:
                self.session.notice(f"Could not update the built-in display toggle: {exc}")

        message = f"Saved to {display_path(path)}"
        if backup is not None:
            message += f" (backup: {backup.name})"
        if note:
            message += f" — {note}"
        self.session.notice(message)

    def _save_config_dialog(self) -> None:
        path = default_config_path()
        try:
            _, patch = luawriter.preview(path, self.states, toggle_builtin=omarchy.available())
        except OSError as exc:
            self.session.notice(f"Could not read {path}: {exc}")
            return
        if not patch:
            self.session.notice(f"{display_path(path)} is already up to date")
            return

        dialog = Adw.AlertDialog(
            heading="Save display layout",
            body=f"These changes will be written to {display_path(path)}. "
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
        text = luawriter.render_block(self.states, toggle_builtin=omarchy.available())
        clipboard = Gdk.Display.get_default().get_clipboard()
        clipboard.set(text)
        self.session.notice("Lua block copied to the clipboard")

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
            self.session.notice("Give the profile a name first")
            return
        self.store.put(name, self.states)
        self.profile_entry.set_text("")
        self._refresh_profile_list()
        self.session.notice(f"Saved profile “{name}”")

    def _on_load_profile(self, _button: Gtk.Button, name: str) -> None:
        profile = self.store.get(name)
        if profile is None:
            return
        skipped = profile.apply_to(self.states)
        self._after_edit()
        self.profile_button.get_popover().popdown()
        if skipped:
            self.session.notice(f"Loaded “{name}” — not connected: {', '.join(skipped)}")
        else:
            self.session.notice(f"Loaded “{name}” — press Apply to use it")

    def _on_delete_profile(self, _button: Gtk.Button, name: str) -> None:
        self.store.delete(name)
        self._refresh_profile_list()
        self.session.notice(f"Deleted profile “{name}”")

    # -------------------------------------------------------------- teardown

    def shutdown(self) -> None:
        """Release everything that outlives the page."""
        if self._confirm_source is not None:
            GLib.source_remove(self._confirm_source)
            self._confirm_source = None
        if self._style_handler:
            self._style_manager.disconnect(self._style_handler)
            self._style_handler = 0


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
