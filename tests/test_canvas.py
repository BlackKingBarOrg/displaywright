"""Arrangement drag pipeline. Skipped when there is no display to initialise GTK on."""

import unittest

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    from gi.repository import Gdk, Gtk

    HAVE_GTK = True
except (ImportError, ValueError):  # PyGObject or the GTK4 typelib is missing
    HAVE_GTK = False

from displaywright.model import Mode, MonitorState

# Gtk.init_check() is not a display probe: it returns True even with no display
# at all, and then constructing a widget segfaults. Gdk.Display.get_default() is
# the honest signal.
HAVE_DISPLAY = HAVE_GTK and Gtk.init_check() and Gdk.Display.get_default() is not None


def monitor(name, w, h, x=0, y=0, scale=1.0):
    return MonitorState(
        name=name,
        mode=Mode(w, h, 60.0),
        x=x,
        y=y,
        scale=scale,
        available_modes=[Mode(w, h, 60.0)],
    )


@unittest.skipUnless(HAVE_DISPLAY, "needs a Wayland or X11 display")
class CanvasDragTests(unittest.TestCase):
    def setUp(self):
        from displaywright.displays.canvas import ArrangeCanvas

        self.canvas = ArrangeCanvas()
        # eDP-1 is 1600x1000 logical, DP-1 sits flush to its right.
        self.canvas.set_states(
            [monitor("eDP-1", 3200, 2000, scale=2.0), monitor("DP-1", 3440, 1440, x=1600)]
        )
        self.canvas._update_view(900.0, 600.0)
        self.laptop, self.wide = self.canvas.states

    def _grab(self, state):
        """Start a drag from the centre of a monitor's tile."""
        cx, cy = self.canvas.to_device(state.rect.cx, state.rect.cy)
        self.canvas._on_drag_begin(None, cx, cy)

    def _move(self, dx_logical, dy_logical, finish=True):
        zoom = self.canvas.zoom
        self.canvas._on_drag_update(None, dx_logical * zoom, dy_logical * zoom)
        if finish:
            self.canvas._on_drag_end(None, dx_logical * zoom, dy_logical * zoom)

    def test_grab_selects_the_tile_under_the_pointer(self):
        self._grab(self.wide)
        self.assertEqual(self.canvas.selected, "DP-1")

    def test_drag_below_snaps_flush_under_the_other_display(self):
        self._grab(self.wide)
        self._move(-1550, 1040)  # roughly under the laptop panel
        self.assertEqual(self.wide.y, 1000)
        self.assertEqual(self.wide.x, 0)

    def test_drag_far_away_keeps_the_free_position(self):
        self._grab(self.wide)
        self._move(3000, 3000)
        self.assertEqual((self.wide.x, self.wide.y), (4600, 3000))

    def test_drag_never_leaves_an_overlap(self):
        self._grab(self.wide)
        self._move(-1500, 30)  # dropped right on top of the laptop panel
        self.assertFalse(self.wide.rect.overlaps(self.laptop.rect))

    def test_guides_appear_mid_drag_and_clear_on_release(self):
        self._grab(self.wide)
        self._move(-1550, 1040, finish=False)
        self.assertTrue(self.canvas._guides)
        self.canvas._on_drag_end(None, 0, 0)
        self.assertEqual(self.canvas._guides, [])

    def test_drag_on_empty_space_moves_nothing(self):
        before = [(s.x, s.y) for s in self.canvas.states]
        self.canvas._on_drag_begin(None, 2.0, 2.0)  # corner padding, no tile there
        self._move(500, 500)
        self.assertEqual([(s.x, s.y) for s in self.canvas.states], before)

    def test_arrow_key_nudges_by_ten_logical_pixels(self):
        self.canvas.select("DP-1")
        handled = self.canvas._on_key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0))
        self.assertTrue(handled)
        self.assertEqual(self.wide.x, 1610)

    def test_shift_arrow_nudges_further(self):
        self.canvas.select("DP-1")
        self.canvas._on_key(None, Gdk.KEY_Right, 0, Gdk.ModifierType.SHIFT_MASK)
        self.assertEqual(self.wide.x, 1700)

    def test_nudge_back_lands_exactly_on_the_shared_edge(self):
        self.canvas.select("DP-1")
        self.canvas._on_key(None, Gdk.KEY_Right, 0, Gdk.ModifierType(0))
        self.canvas._on_key(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0))
        self.assertEqual(self.wide.x, 1600)

    def test_nudge_cannot_push_into_a_neighbour(self):
        self.canvas.select("DP-1")
        self.canvas._on_key(None, Gdk.KEY_Left, 0, Gdk.ModifierType(0))
        self.assertEqual(self.wide.x, 1600)
        self.assertFalse(self.wide.rect.overlaps(self.laptop.rect))

    def test_tab_cycles_the_selection(self):
        self.canvas.select("eDP-1")
        self.canvas._on_key(None, Gdk.KEY_Tab, 0, Gdk.ModifierType(0))
        self.assertEqual(self.canvas.selected, "DP-1")

    def test_selection_survives_a_state_refresh(self):
        self.canvas.select("DP-1")
        self.canvas.set_states([monitor("eDP-1", 3200, 2000, scale=2.0), monitor("DP-1", 3440, 1440)])
        self.assertEqual(self.canvas.selected, "DP-1")

    def test_selection_resets_when_the_output_disappears(self):
        self.canvas.select("DP-1")
        self.canvas.set_states([monitor("eDP-1", 3200, 2000, scale=2.0)])
        self.assertEqual(self.canvas.selected, "eDP-1")

    def test_draw_does_not_crash_for_every_state_shape(self):
        import cairo

        states = [
            monitor("eDP-1", 3200, 2000, scale=2.0),
            monitor("DP-1", 3440, 1440, x=1600),
            monitor("HDMI-A-1", 1920, 1080, x=1600, y=1440),
        ]
        states[2].enabled = False
        states[1].transform = 1
        states[0].mirror_of = "DP-1"
        self.canvas.set_states(states)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 900, 600)
        for dark in (False, True):
            self.canvas.set_dark(dark)
            self.canvas._draw(self.canvas, cairo.Context(surface), 900, 600)
        # Also exercise the degenerate "nothing connected" branch.
        self.canvas.set_states([])
        self.canvas._draw(self.canvas, cairo.Context(surface), 900, 600)


if __name__ == "__main__":
    unittest.main()
