"""The GTK modules have to import cleanly wherever PyGObject exists.

They are skipped rather than failed where it does not, so the logic suites stay
runnable on a machine with no desktop stack at all -- which is how CI runs them.
"""

import importlib
import unittest

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Gdk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gdk, Gtk  # noqa: F401

    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False

# Gtk.init_check() is not a display probe: it returns True even with no display
# at all, and then constructing *any* widget -- a bare Gtk.DrawingArea will do
# it -- takes the interpreter down with SIGSEGV rather than an exception.
# Gdk.Display.get_default() is the honest signal.
HAVE_DISPLAY = HAVE_GTK and Gtk.init_check() and Gdk.Display.get_default() is not None

GUI_MODULES = (
    "displaywright.drawing",
    "displaywright.canvas",
    "displaywright.session",
    "displaywright.window",
    "displaywright.app",
    "displaywright.displays.canvas",
    "displaywright.displays.page",
    "displaywright.wallpapers.canvas",
    "displaywright.wallpapers.page",
)


@unittest.skipUnless(HAVE_GTK, "PyGObject with GTK 4 and libadwaita is not installed")
class GuiImports(unittest.TestCase):
    def test_every_gui_module_imports(self):
        for name in GUI_MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_the_application_id_matches_the_desktop_entry(self):
        from pathlib import Path

        from displaywright import APP_ID

        desktop = Path(__file__).resolve().parent.parent / "data" / "displaywright.desktop"
        self.assertIn(f"StartupWMClass={APP_ID}", desktop.read_text())

    def test_the_application_id_matches_the_shell_plugin(self):
        import json
        from pathlib import Path

        from displaywright.wallpapers import plugin

        manifest = Path(__file__).resolve().parent.parent / "plugin" / "manifest.json"
        self.assertEqual(json.loads(manifest.read_text())["id"], plugin.PLUGIN_ID)

    @unittest.skipUnless(HAVE_DISPLAY, "needs a Wayland or X11 display")
    def test_both_canvases_survive_an_empty_state(self):
        """Two canvases share one base; neither may trip over having no outputs.

        This needs a display. GTK 4 segfaults on the first widget it builds
        without one, so a suite that constructs widgets to prove they *can* be
        constructed headlessly proves nothing and crashes the runner -- which
        is exactly what it did. Signal and property mistakes surface at class
        registration time, which happens on import, so
        test_every_gui_module_imports already covers that ground with no
        display at all.
        """
        from displaywright.displays.canvas import ArrangeCanvas
        from displaywright.wallpapers.canvas import WallpaperCanvas
        from displaywright.wallpapers.model import Config

        arrange = ArrangeCanvas()
        arrange.set_states([])
        self.assertIsNone(arrange.selected)

        wallpapers = WallpaperCanvas()
        wallpapers.set_config([], Config(), None)
        self.assertIsNone(wallpapers.selected)


if __name__ == "__main__":
    unittest.main()
