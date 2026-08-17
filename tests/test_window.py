"""Main-window integration tests against the running compositor.

These need both a display and a live Hyprland instance -- they read the real
monitor list -- but they never apply or write anything.
"""

import unittest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from hyprlayout import hypr, luawriter

HAVE_DISPLAY = Gtk.init_check()
HAVE_HYPRLAND = hypr.is_running()


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
        self.assertFalse(self.window.dirty)

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


if __name__ == "__main__":
    unittest.main()
