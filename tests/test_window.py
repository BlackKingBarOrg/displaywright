"""Main-window integration tests against the running compositor.

These need both a display and a live Hyprland instance -- they read the real
monitor list -- but they never apply a layout or write a file: the suite that
exercises the apply path mocks hyprctl out.
"""

import time
import unittest
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

from hyprlayout import hypr, luawriter

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


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class WindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from hyprlayout.window import MainWindow

        # No GtkApplication on purpose: attaching a never-presented window to one
        # and then destroying it segfaults inside GTK's window-removed handling
        # (gtk_window_destroy -> ::window-removed). Nothing under test needs it.
        self.window = MainWindow(None)
        # Toasts need a realised surface, which a never-presented window has not
        # got; record them instead so the assertions can check them.
        self.toasts: list[str] = []
        self.window._toast = self.toasts.append

    def tearDown(self):
        self.window.shutdown()
        self.window = None

    def test_loads_the_live_layout(self):
        self.assertTrue(self.window.states)
        self.assertEqual(
            [s.name for s in self.window.states],
            [s.name for s in self.window.canvas.states],
        )

    def test_starts_clean_with_apply_disabled(self):
        self.assertFalse(self.window.dirty)
        self.assertFalse(self.window.apply_button.get_sensitive())
        self.assertIn("display", self.window.window_title.get_subtitle())
        self.assertNotIn("unapplied", self.window.window_title.get_subtitle())

    def test_moving_a_display_marks_the_window_dirty(self):
        state = self.window.canvas.selected_state()
        state.x += 500
        self.window._on_layout_changed()
        self.assertTrue(self.window.dirty)
        self.assertTrue(self.window.apply_button.get_sensitive())
        self.assertIn("unapplied", self.window.window_title.get_subtitle())

    def test_reload_discards_local_edits(self):
        state = self.window.canvas.selected_state()
        state.x += 500
        self.window.reload_from_hyprland(announce=False)
        self.assertTrue(pump(lambda: not self.window.dirty), "reload never settled")

    def test_edited_layout_shows_up_in_the_config_preview(self):
        state = self.window.canvas.selected_state()
        state.x += 500
        _, patch = luawriter.preview(luawriter.default_config_path(), self.window.states)
        self.assertIn(f'position = "{state.x}x{state.y}"', patch)

    def test_disabling_every_display_is_flagged(self):
        for state in self.window.states:
            state.enabled = False
        self.window._on_layout_changed()
        self.assertTrue(self.window.banner.get_revealed())
        self.assertIn("black screen", self.window.banner.get_title())

    def test_sidebar_follows_the_canvas_selection(self):
        names = [s.name for s in self.window.states]
        if len(names) < 2:
            self.skipTest("needs at least two outputs")
        self.window.canvas.select(names[1])
        self.assertEqual(self.window.output_row.get_selected(), 1)

    def test_scale_edit_flows_through_to_the_rule(self):
        state = self.window.canvas.selected_state()
        self.window.scale_row.set_value(1.5)
        self.assertEqual(state.scale, 1.5)
        self.assertIn(",1.5", state.rule_args())

    def test_auto_arrange_leaves_a_valid_layout(self):
        from hyprlayout.snapping import validate

        self.window._auto_arrange()
        self.assertEqual(validate(self.window.states), [])
        self.assertEqual(self.toasts, ["Arranged left to right"])

    def test_shutdown_releases_the_process_wide_style_handler(self):
        self.assertTrue(self.window._style_handler)
        self.window.shutdown()
        self.assertEqual(self.window._style_handler, 0)
        self.window.shutdown()  # idempotent

    def test_normalize_moves_the_layout_to_the_origin(self):
        # Do not assume the machine's live layout starts at the origin: create a
        # known offset, then check both the move and the follow-up no-op.
        from hyprlayout.model import bounding_box

        for state in self.window.states:
            state.y += 300
        self.window._normalize()
        self.assertEqual(self.toasts[-1], "Layout moved to origin")
        box = bounding_box([s.rect for s in self.window.states if s.enabled])
        self.assertEqual((box.x, box.y), (0.0, 0.0))

        self.toasts.clear()
        self.window._normalize()
        self.assertEqual(self.toasts, ["Already at the origin"])


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class SidebarFeedbackTests(unittest.TestCase):
    """Changing a sidebar row must not make the sidebar rebuild itself forever.

    Setting a model on an Adw.ComboRow re-emits notify::selected. A handler that
    reacts by rebuilding that model livelocks the window: the app freezes hard,
    burns CPU, and eventually trips `g_object_notify_by_pspec: assertion
    G_IS_OBJECT (object) failed` and dies. That is what happened when picking a
    refresh rate, and defeating the fix reproduces the crash from these tests.
    """

    RUNAWAY = 25

    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from hyprlayout.window import MainWindow

        self.window = MainWindow(None)
        self.syncs = 0
        real_sync = self.window._sync_sidebar

        def counting_sync():
            self.syncs += 1
            if self.syncs > self.RUNAWAY:
                raise AssertionError(
                    f"_sync_sidebar ran away: {self.syncs} calls for one interaction"
                )
            return real_sync()

        # _after_edit looks the method up on the instance, so this intercepts it.
        self.window._sync_sidebar = counting_sync

    def tearDown(self):
        self.window.shutdown()
        self.window = None

    def _poke(self, description, action):
        self.syncs = 0
        action()
        self.assertLessEqual(
            self.syncs, 5, f"{description} triggered {self.syncs} sidebar rebuilds"
        )

    def test_each_row_settles_after_one_change(self):
        state = self.window.canvas.selected_state()
        others = [s.name for s in self.window.states if s.name != state.name]

        self._poke("rotation", lambda: self.window.rotation_row.set_selected(1))
        self._poke("vrr", lambda: self.window.vrr_row.set_selected(2))
        self._poke("scale", lambda: self.window.scale_row.set_value(1.5))
        self._poke("x", lambda: self.window.x_row.set_value(120))
        self._poke("y", lambda: self.window.y_row.set_value(240))
        if others:
            self._poke("mirror", lambda: self.window.mirror_row.set_selected(1))
        self._poke("enabled off", lambda: self.window.enabled_row.set_active(False))
        self._poke("enabled on", lambda: self.window.enabled_row.set_active(True))

    def test_every_resolution_and_refresh_selection_terminates(self):
        # The reported scenario: walk every mode the UI offers, on every output.
        for state in self.window.states:
            self.window.canvas.select(state.name)
            res_model = self.window.resolution_row.get_model()
            for r in range(res_model.get_n_items() if res_model else 0):
                self._poke(
                    f"{state.name} resolution[{r}]",
                    lambda r=r: self.window.resolution_row.set_selected(r),
                )
                ref_model = self.window.refresh_row.get_model()
                for f in range(ref_model.get_n_items() if ref_model else 0):
                    self._poke(
                        f"{state.name} refresh[{f}]",
                        lambda f=f: self.window.refresh_row.set_selected(f),
                    )

    def test_reselecting_the_current_value_changes_nothing(self):
        # A no-op selection must not mark the layout dirty either.
        self.assertFalse(self.window.dirty)
        row = self.window.resolution_row
        self._poke("same resolution", lambda: row.set_selected(row.get_selected()))
        rate_row = self.window.refresh_row
        self._poke("same refresh", lambda: rate_row.set_selected(rate_row.get_selected()))
        self.assertFalse(self.window.dirty, "re-selecting the current mode marked it dirty")

    def test_switching_outputs_does_not_loop(self):
        names = [s.name for s in self.window.states]
        if len(names) < 2:
            self.skipTest("needs at least two outputs")
        for name in names + names[::-1]:
            self._poke(f"select {name}", lambda name=name: self.window.canvas.select(name))


@unittest.skipUnless(HAVE_DISPLAY and HAVE_HYPRLAND, "needs a display and a running Hyprland")
class AsyncApplyTests(unittest.TestCase):
    """hyprctl must never run on the UI thread.

    A modeset can keep it busy for a while, and blocking the main loop is what
    makes Hyprland put up its "application is not responding" dialog. hyprctl is
    mocked here, so nothing is applied for real.
    """

    @classmethod
    def setUpClass(cls):
        Adw.init()

    def setUp(self):
        from hyprlayout.window import MainWindow

        self.window = MainWindow(None)
        self.window._toast = lambda *_: None
        self.confirmed = []
        self.window._confirm_layout = lambda snapshot, shortfalls=(): self.confirmed.append(
            (snapshot, list(shortfalls))
        )

    def tearDown(self):
        self.window.shutdown()
        self.window = None

    def test_apply_returns_immediately_even_when_hyprctl_is_slow(self):
        live = [s.copy() for s in self.window.states]

        def slow_apply(_states):
            time.sleep(1.5)
            return "ok"

        with mock.patch.object(hypr, "apply_states", side_effect=slow_apply), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            started = time.monotonic()
            self.window._push_layout()
            elapsed = time.monotonic() - started
            self.assertLess(
                elapsed, 0.3, f"_push_layout blocked the UI thread for {elapsed:.2f}s"
            )
            self.assertIsNotNone(self.window._busy, "no progress shown while applying")
            self.assertFalse(self.window.apply_button.get_sensitive())
            self.assertTrue(
                pump(lambda: self.confirmed, timeout=10), "confirmation never arrived"
            )
        self.assertIsNone(self.window._busy, "busy state was not cleared")

    def test_a_second_apply_is_ignored_while_one_is_in_flight(self):
        live = [s.copy() for s in self.window.states]
        calls = []

        def slow_apply(states):
            calls.append(states)
            time.sleep(0.6)
            return "ok"

        with mock.patch.object(hypr, "apply_states", side_effect=slow_apply), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.window._push_layout()
            self.window._push_layout()
            self.window._push_layout()
            self.assertTrue(pump(lambda: self.confirmed, timeout=10))
        self.assertEqual(len(calls), 1, "apply ran more than once")

    def test_a_mode_hyprland_could_not_deliver_is_reported(self):
        from hyprlayout.model import Mode

        live = [s.copy() for s in self.window.states]
        target = self.window.canvas.selected_state()
        px_w, px_h = target.pixel_size
        target.mode = Mode(px_w, px_h, 137.0)  # nothing can do 137Hz

        with mock.patch.object(hypr, "apply_states", return_value="ok"), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.window._push_layout()
            self.assertTrue(pump(lambda: self.confirmed, timeout=10))

        _snapshot, shortfalls = self.confirmed[0]
        self.assertTrue(shortfalls, "silently accepted a mode that did not apply")
        self.assertIn(target.name, shortfalls[0])

    def test_a_failure_surfaces_instead_of_hanging(self):
        messages = []
        self.window._toast = messages.append
        live = [s.copy() for s in self.window.states]

        with mock.patch.object(hypr, "apply_states", side_effect=hypr.HyprError("boom")), \
                mock.patch.object(hypr, "read_monitors", return_value=live):
            self.window._push_layout()
            self.assertTrue(pump(lambda: messages, timeout=10))

        self.assertIn("boom", messages[-1])
        self.assertIsNone(self.window._busy)
        self.assertEqual(self.confirmed, [], "a failed apply must not ask to keep it")


if __name__ == "__main__":
    unittest.main()
