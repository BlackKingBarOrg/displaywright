"""Main-window integration tests against the running compositor.

These need both a display and a live Hyprland instance -- they read the real
monitor list -- but they never apply a layout or write a file: the suite that
exercises the apply path mocks hyprctl out.
"""

import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, GLib, Gtk

    HAVE_GTK = True
except (ImportError, ValueError):  # PyGObject, GTK4 or libadwaita is missing
    HAVE_GTK = False

from displaywright import hypr
from displaywright.displays import luawriter

# Gtk.init_check() is not a display probe: it returns True even with no display
# at all, and then constructing a widget segfaults. Gdk.Display.get_default() is
# the honest signal.
HAVE_DISPLAY = HAVE_GTK and Gtk.init_check() and Gdk.Display.get_default() is not None
HAVE_HYPRLAND = hypr.is_running()


def pump(predicate, timeout=5.0):
    """Run the main loop until predicate() holds; hyprctl work is off-thread now."""
    context = GLib.MainContext.default()
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        while context.pending():
            context.iteration(False)
        time.sleep(0.005)
    return predicate()


class WindowFixture(unittest.TestCase):
    """Builds a window against the live compositor, but never against real state.

    The window owns both pages now, and the wallpaper page creates directories
    and reads a config the moment it is built, so every XDG root is redirected
    into a temporary one first. Nothing here may touch the user's own files.
    """

    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from displaywright.window import MainWindow

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "XDG_PICTURES_DIR": str(self.root / "pictures"),
            },
        )
        env.start()
        self.addCleanup(env.stop)

        # No GtkApplication on purpose: attaching a never-presented window to one
        # and then destroying it segfaults inside GTK's window-removed handling
        # (gtk_window_destroy -> ::window-removed). Nothing under test needs it.
        self.window = MainWindow(None)
        self.session = self.window.session
        self.page = self.window.displays
        # Toasts need a realised surface, which a never-presented window has not
        # got; record them instead so the assertions can check them.
        self.toasts: list[str] = []
        self.window.toast = self.toasts.append

    def tearDown(self):
        self.window.shutdown()
        self.window = None


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class WindowTests(WindowFixture):

    def test_loads_the_live_layout(self):
        self.assertTrue(self.session.states)
        self.assertEqual(
            [s.name for s in self.session.states],
            [s.name for s in self.page.canvas.states],
        )

    def test_starts_clean_with_apply_disabled(self):
        self.assertFalse(self.session.dirty)
        self.assertFalse(self.page.apply_button.get_sensitive())
        self.assertIn("display", self.page.status.get_label())
        self.assertNotIn("unapplied", self.page.status.get_label())

    def test_moving_a_display_marks_the_window_dirty(self):
        state = self.page.canvas.selected_state()
        state.x += 500
        self.page._on_layout_changed()
        self.assertTrue(self.session.dirty)
        self.assertTrue(self.page.apply_button.get_sensitive())
        self.assertIn("unapplied", self.page.status.get_label())

    def test_reload_discards_local_edits(self):
        state = self.page.canvas.selected_state()
        state.x += 500
        self.window.reload_layout(announce=False)
        self.assertTrue(pump(lambda: not self.session.dirty), "reload never settled")

    def test_edited_layout_shows_up_in_the_config_preview(self):
        state = self.page.canvas.selected_state()
        state.x += 500
        _, patch = luawriter.preview(luawriter.default_config_path(), self.session.states)
        self.assertIn(f'position = "{state.x}x{state.y}"', patch)

    def test_disabling_every_display_is_flagged(self):
        for state in self.session.states:
            state.enabled = False
        self.page._on_layout_changed()
        self.assertTrue(self.page.banner.get_revealed())
        self.assertIn("black screen", self.page.banner.get_title())

    def test_sidebar_follows_the_canvas_selection(self):
        names = [s.name for s in self.session.states]
        if len(names) < 2:
            self.skipTest("needs at least two outputs")
        self.page.canvas.select(names[1])
        self.assertEqual(self.page.output_row.get_selected(), 1)

    def test_scale_edit_flows_through_to_the_rule(self):
        state = self.page.canvas.selected_state()
        self.page.scale_row.set_value(1.5)
        self.assertEqual(state.scale, 1.5)
        self.assertIn(",1.5", state.rule_args())

    def test_auto_arrange_leaves_a_valid_layout(self):
        from displaywright.displays.snapping import validate

        self.page._auto_arrange()
        self.assertEqual(validate(self.session.states), [])
        self.assertEqual(self.toasts, ["Arranged left to right"])

    def test_shutdown_releases_the_process_wide_style_handler(self):
        self.assertTrue(self.page._style_handler)
        self.window.shutdown()
        self.assertEqual(self.page._style_handler, 0)
        self.window.shutdown()  # idempotent

    def test_normalize_moves_the_layout_to_the_origin(self):
        # Do not assume the machine's live layout starts at the origin: create a
        # known offset, then check both the move and the follow-up no-op.
        from displaywright.model import bounding_box

        for state in self.session.states:
            state.y += 300
        self.page._normalize()
        self.assertEqual(self.toasts[-1], "Layout moved to origin")
        box = bounding_box([s.rect for s in self.session.states if s.enabled])
        self.assertEqual((box.x, box.y), (0.0, 0.0))

        self.toasts.clear()
        self.page._normalize()
        self.assertEqual(self.toasts, ["Already at the origin"])


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class SidebarFeedbackTests(WindowFixture):
    """Changing a sidebar row must not make the sidebar rebuild itself forever.

    Setting a model on an Adw.ComboRow re-emits notify::selected. A handler that
    reacts by rebuilding that model livelocks the window: the app freezes hard,
    burns CPU, and eventually trips `g_object_notify_by_pspec: assertion
    G_IS_OBJECT (object) failed` and dies. That is what happened when picking a
    refresh rate, and defeating the fix reproduces the crash from these tests.
    """

    RUNAWAY = 25

    def setUp(self):
        super().setUp()
        self.syncs = 0
        real_sync = self.page._sync_sidebar

        def counting_sync():
            self.syncs += 1
            if self.syncs > self.RUNAWAY:
                raise AssertionError(
                    f"_sync_sidebar ran away: {self.syncs} calls for one interaction"
                )
            return real_sync()

        # _after_edit looks the method up on the instance, so this intercepts it.
        self.page._sync_sidebar = counting_sync

    def _poke(self, description, action):
        self.syncs = 0
        action()
        self.assertLessEqual(
            self.syncs, 5, f"{description} triggered {self.syncs} sidebar rebuilds"
        )

    def test_each_row_settles_after_one_change(self):
        state = self.page.canvas.selected_state()
        others = [s.name for s in self.session.states if s.name != state.name]

        self._poke("rotation", lambda: self.page.rotation_row.set_selected(1))
        self._poke("vrr", lambda: self.page.vrr_row.set_selected(2))
        self._poke("scale", lambda: self.page.scale_row.set_value(1.5))
        self._poke("x", lambda: self.page.x_row.set_value(120))
        self._poke("y", lambda: self.page.y_row.set_value(240))
        if others:
            self._poke("mirror", lambda: self.page.mirror_row.set_selected(1))
        self._poke("enabled off", lambda: self.page.enabled_row.set_active(False))
        self._poke("enabled on", lambda: self.page.enabled_row.set_active(True))

    def test_every_resolution_and_refresh_selection_terminates(self):
        # The reported scenario: walk every mode the UI offers, on every output.
        for state in self.session.states:
            self.page.canvas.select(state.name)
            res_model = self.page.resolution_row.get_model()
            for r in range(res_model.get_n_items() if res_model else 0):
                self._poke(
                    f"{state.name} resolution[{r}]",
                    lambda r=r: self.page.resolution_row.set_selected(r),
                )
                ref_model = self.page.refresh_row.get_model()
                for f in range(ref_model.get_n_items() if ref_model else 0):
                    self._poke(
                        f"{state.name} refresh[{f}]",
                        lambda f=f: self.page.refresh_row.set_selected(f),
                    )

    def test_reselecting_the_current_value_changes_nothing(self):
        # A no-op selection must not mark the layout dirty either.
        self.assertFalse(self.session.dirty)
        row = self.page.resolution_row
        self._poke("same resolution", lambda: row.set_selected(row.get_selected()))
        rate_row = self.page.refresh_row
        self._poke("same refresh", lambda: rate_row.set_selected(rate_row.get_selected()))
        self.assertFalse(self.session.dirty, "re-selecting the current mode marked it dirty")

    def test_switching_outputs_does_not_loop(self):
        names = [s.name for s in self.session.states]
        if len(names) < 2:
            self.skipTest("needs at least two outputs")
        for name in names + names[::-1]:
            self._poke(f"select {name}", lambda name=name: self.page.canvas.select(name))


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class AsyncApplyTests(WindowFixture):
    """hyprctl must never run on the UI thread.

    A modeset can keep it busy for a while, and blocking the main loop is what
    makes Hyprland put up its "application is not responding" dialog. hyprctl is
    mocked here, so nothing is applied for real.
    """

    def setUp(self):
        super().setUp()
        self.confirmed = []
        self.page._confirm_layout = lambda snapshot, shortfalls=(): self.confirmed.append(
            (snapshot, list(shortfalls))
        )

    def test_apply_returns_immediately_even_when_hyprctl_is_slow(self):
        live = [s.copy() for s in self.session.states]

        def slow_apply(_states):
            time.sleep(1.5)
            return "ok"

        with mock.patch.object(hypr, "apply_states", side_effect=slow_apply), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            started = time.monotonic()
            self.page._push_layout()
            elapsed = time.monotonic() - started
            self.assertLess(
                elapsed, 0.3, f"_push_layout blocked the UI thread for {elapsed:.2f}s"
            )
            self.assertIsNotNone(self.page._busy, "no progress shown while applying")
            self.assertFalse(self.page.apply_button.get_sensitive())
            self.assertTrue(
                pump(lambda: self.confirmed, timeout=10), "confirmation never arrived"
            )
        self.assertIsNone(self.page._busy, "busy state was not cleared")

    def test_a_second_apply_is_ignored_while_one_is_in_flight(self):
        live = [s.copy() for s in self.session.states]
        calls = []

        def slow_apply(states):
            calls.append(states)
            time.sleep(0.6)
            return "ok"

        with mock.patch.object(hypr, "apply_states", side_effect=slow_apply), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.page._push_layout()
            self.page._push_layout()
            self.page._push_layout()
            self.assertTrue(pump(lambda: self.confirmed, timeout=10))
        self.assertEqual(len(calls), 1, "apply ran more than once")

    def test_a_mode_hyprland_could_not_deliver_is_reported(self):
        from displaywright.model import Mode

        live = [s.copy() for s in self.session.states]
        target = self.page.canvas.selected_state()
        px_w, px_h = target.pixel_size
        target.mode = Mode(px_w, px_h, 137.0)  # nothing can do 137Hz

        with mock.patch.object(hypr, "apply_states", return_value="ok"), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.page._push_layout()
            self.assertTrue(pump(lambda: self.confirmed, timeout=10))

        _snapshot, shortfalls = self.confirmed[0]
        self.assertTrue(shortfalls, "silently accepted a mode that did not apply")
        self.assertIn(target.name, shortfalls[0])

    def test_a_failure_surfaces_instead_of_hanging(self):
        messages = []
        self.window.toast = messages.append
        live = [s.copy() for s in self.session.states]

        with mock.patch.object(hypr, "apply_states", side_effect=hypr.HyprError("boom")), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.page._push_layout()
            self.assertTrue(pump(lambda: messages, timeout=10))

        self.assertIn("boom", messages[-1])
        self.assertIsNone(self.page._busy)
        self.assertEqual(self.confirmed, [], "a failed apply must not ask to keep it")


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class BuiltinPanelTests(WindowFixture):
    """Switching the laptop panel off has to land in Omarchy's toggle, not in
    monitors.lua where nothing would ever remove it again."""

    def setUp(self):
        super().setUp()
        from displaywright.displays import omarchy

        self.omarchy = omarchy
        (self.root / "config" / "hypr").mkdir(parents=True, exist_ok=True)
        self.config = self.root / "config" / "hypr" / "monitors.lua"
        self.panel = omarchy.builtin(self.session.states)
        if self.panel is None:
            self.skipTest("this machine has no built-in panel")

    def test_sidebar_explains_the_recovery_for_a_laptop_panel(self):
        self.page.canvas.select(self.panel.name)
        subtitle = self.page.enabled_row.get_subtitle()
        self.assertIn("back on", subtitle)

    def test_switching_it_off_writes_the_toggle_and_keeps_an_enabled_rule(self):
        self.panel.enabled = False
        self.page._write_config()

        self.assertTrue(self.omarchy.is_disabled(), "the toggle was not written")
        self.assertIn(self.panel.name, self.omarchy.toggle_path().read_text())

        written = self.config.read_text()
        self.assertIn(f'output = "{self.panel.name}"', written)
        self.assertNotIn(f'output = "{self.panel.name}", disabled = true', written)
        self.assertIn("internal-monitor-disable", written)

    def test_switching_it_back_on_clears_the_toggle(self):
        self.panel.enabled = False
        self.page._write_config()
        self.assertTrue(self.omarchy.is_disabled())

        self.panel.enabled = True
        self.page._write_config()
        self.assertFalse(self.omarchy.is_disabled(), "the toggle outlived the panel")

    def test_a_disabled_external_still_goes_into_monitors_lua(self):
        external = next((s for s in self.session.states if not s.is_builtin), None)
        if external is None:
            self.skipTest("needs an external output")
        external.enabled = False
        self.page._write_config()
        self.assertIn(f'output = "{external.name}", disabled = true', self.config.read_text())
        self.assertFalse(self.omarchy.is_disabled())


if __name__ == "__main__":
    unittest.main()
