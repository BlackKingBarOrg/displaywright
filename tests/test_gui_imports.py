"""The GTK modules have to import cleanly wherever PyGObject exists.

They are skipped rather than failed where it does not, so the logic suites stay
runnable on a machine with no desktop stack at all -- which is how CI runs them.
"""

import importlib
import unittest

try:
    import gi

    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gtk  # noqa: F401

    HAVE_GTK = True
except (ImportError, ValueError):
    HAVE_GTK = False

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

    def test_both_canvases_can_be_constructed_without_a_display(self):
        # Constructing a widget needs no display; realising one does. This
        # catches signal and property mistakes that only surface at class
        # registration time -- and there are two canvases sharing one base now,
        # so both registrations have to hold.
        from displaywright.displays.canvas import ArrangeCanvas
        from displaywright.wallpapers.canvas import WallpaperCanvas
        from displaywright.wallpapers.model import Config

        arrange = ArrangeCanvas()
        arrange.set_states([])

        wallpapers = WallpaperCanvas()
        wallpapers.set_config([], Config(), None)


if __name__ == "__main__":
    unittest.main()
