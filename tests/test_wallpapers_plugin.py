"""Installing edits shell.json, which also holds the user's whole bar layout.

These tests are mostly about what installing must *not* touch.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from displaywright.wallpapers import plugin

OTHER_PLUGIN = {"id": "acme.weather", "city": "Oslo"}


class InstallBase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.config_home = Path(self._dir.name)
        patcher = mock.patch.object(plugin, "config_home", return_value=self.config_home)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._dir.cleanup)
        self.shell_json = self.config_home / "omarchy" / "shell.json"
        self.shell_json.parent.mkdir(parents=True)
        self.write_shell({
            "version": 1,
            "bar": {"layout": {"left": [{"id": "omarchy.menu"}]}},
            "plugins": [OTHER_PLUGIN],
        })

    def write_shell(self, data):
        self.shell_json.write_text(json.dumps(data))

    def read_shell(self):
        return json.loads(self.shell_json.read_text())


class Install(InstallBase):
    def test_nothing_is_installed_to_begin_with(self):
        state = plugin.status()
        self.assertFalse(state.installed)
        self.assertFalse(state.ready)

    def test_install_links_and_enables_without_touching_the_stock_renderer(self):
        plugin.install(link=True)
        state = plugin.status()
        self.assertTrue(state.installed)
        self.assertTrue(state.linked)
        self.assertTrue(state.ready)

        data = self.read_shell()
        self.assertIn({"id": plugin.PLUGIN_ID}, data["plugins"])
        # The renderer draws on top of omarchy.background rather than in place
        # of it, so installing must leave it alone. Switching it off would blank
        # every display this plugin has no wallpaper for.
        self.assertNotIn(plugin.STOCK_PLUGIN, data.get("disabledPlugins", []))

    def test_install_repairs_an_install_that_switched_the_stock_renderer_off(self):
        # Every displaywright before this one disabled omarchy.background, and
        # so did wallwright. Upgrading has to undo that.
        self.write_shell({
            "version": 1,
            "plugins": [OTHER_PLUGIN],
            "disabledPlugins": [plugin.STOCK_PLUGIN],
        })
        changed = plugin.install(link=True)
        self.assertNotIn(plugin.STOCK_PLUGIN, self.read_shell().get("disabledPlugins", []))
        self.assertTrue(any(plugin.STOCK_PLUGIN in line for line in changed))
        self.assertTrue(plugin.status().ready)

    def test_a_stock_renderer_left_switched_off_is_reported(self):
        plugin.install(link=True)
        data = self.read_shell()
        data["disabledPlugins"] = [plugin.STOCK_PLUGIN]
        self.write_shell(data)
        state = plugin.status()
        self.assertTrue(state.stock_off)
        self.assertFalse(state.ready)
        self.assertIn("draw nothing", state.describe())

    def test_install_copies_when_asked(self):
        plugin.install(link=False)
        target = plugin.install_dir()
        self.assertFalse(target.is_symlink())
        self.assertTrue((target / "Wallpaper.qml").is_file())
        self.assertTrue((target / "renderers" / "ImageLayer.qml").is_file())

    def test_installing_twice_changes_nothing_the_second_time(self):
        plugin.install(link=True)
        first = self.read_shell()
        self.assertEqual(plugin.install(link=True), [])
        self.assertEqual(self.read_shell(), first)

    def test_the_rest_of_shell_json_is_left_alone(self):
        plugin.install(link=True)
        data = self.read_shell()
        self.assertIn(OTHER_PLUGIN, data["plugins"])
        self.assertEqual(data["bar"]["layout"]["left"], [{"id": "omarchy.menu"}])

    def test_switching_from_a_link_to_a_copy_replaces_it(self):
        plugin.install(link=True)
        self.assertTrue(plugin.install_dir().is_symlink())
        plugin.install(link=False)
        self.assertFalse(plugin.install_dir().is_symlink())
        self.assertTrue((plugin.install_dir() / "manifest.json").is_file())

    def test_a_disabled_but_uninstalled_renderer_is_reported_as_such(self):
        plugin.install(link=True)
        data = self.read_shell()
        data["plugins"] = [OTHER_PLUGIN]
        self.write_shell(data)
        state = plugin.status()
        self.assertTrue(state.installed)
        self.assertFalse(state.enabled)
        self.assertFalse(state.ready)
        self.assertIn("not enabled", state.describe())


class SourceDirTests(unittest.TestCase):
    """Finding the QML, in a checkout and in a distribution package.

    A wheel puts the Python package under site-packages and leaves `plugin/`
    behind, because it is a sibling of the package rather than a child. A
    distribution has to put it under share/ instead, and the lookup has to find
    it there or `renderer install` fails on every packaged install.
    """

    def test_a_checkout_is_found_beside_the_package(self):
        # The real repository, which is what the developer is running from.
        self.assertTrue((plugin.source_dir() / "manifest.json").is_file())
        self.assertEqual(plugin.source_dir().name, "plugin")

    def test_a_packaged_install_is_found_under_share(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            shipped = root / "displaywright" / "plugin"
            shipped.mkdir(parents=True)
            (shipped / "manifest.json").write_text("{}")
            # No checkout beside the module, which is the packaged situation.
            with mock.patch.object(plugin, "__file__", str(root / "site-packages"
                                                           / "displaywright" / "wallpapers"
                                                           / "plugin.py")), \
                 mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root)}):
                self.assertEqual(plugin.source_dir(), shipped)

    def test_the_checkout_wins_over_a_system_copy(self):
        # A developer running from a clone must not pick up a stale install.
        with mock.patch.dict(os.environ, {"XDG_DATA_HOME": "/nonexistent"}):
            self.assertTrue(str(plugin.source_dir()).startswith(str(Path.cwd())))


class Uninstall(InstallBase):
    def test_uninstall_reverses_install_completely(self):
        before = self.read_shell()
        plugin.install(link=True)
        plugin.uninstall()
        self.assertEqual(self.read_shell(), before)
        self.assertFalse(plugin.install_dir().exists())

    def test_uninstall_keeps_other_disabled_plugins(self):
        data = self.read_shell()
        data["disabledPlugins"] = ["omarchy.weather"]
        self.write_shell(data)
        plugin.install(link=True)
        plugin.uninstall()
        self.assertEqual(self.read_shell()["disabledPlugins"], ["omarchy.weather"])

    def test_uninstall_keeps_other_plugins(self):
        plugin.install(link=True)
        plugin.uninstall()
        self.assertEqual(self.read_shell()["plugins"], [OTHER_PLUGIN])

    def test_uninstalling_what_was_never_installed_is_a_no_op(self):
        self.assertEqual(plugin.uninstall(), [])

    def test_files_can_be_kept_while_the_takeover_is_undone(self):
        plugin.install(link=True)
        plugin.uninstall(remove_files=False)
        self.assertTrue(plugin.install_dir().exists())
        self.assertFalse(plugin.status().enabled)


class Manifest(unittest.TestCase):
    def test_every_renderer_the_surface_dispatches_to_exists(self):
        surface = (plugin.source_dir() / "Surface.qml").read_text()
        for name in ("ColorLayer", "VideoLayer", "ImageLayer"):
            self.assertIn(f"renderers/{name}.qml", surface)
            self.assertTrue((plugin.source_dir() / "renderers" / f"{name}.qml").is_file())
