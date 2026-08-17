"""Tests for the Omarchy internal-monitor toggle integration.

Every test redirects XDG_STATE_HOME at a temporary directory, so the developer's
real toggle state is never touched.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hyprlayout import omarchy
from hyprlayout.model import Mode, MonitorState


def monitor(name, enabled=True):
    return MonitorState(name=name, mode=Mode(1920, 1080, 60.0), enabled=enabled)


class ToggleFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_path_follows_omarchys_layout(self):
        path = omarchy.toggle_path()
        self.assertEqual(path.name, "internal-monitor-disable.lua")
        self.assertEqual(path.parent, Path(self._tmp.name) / "omarchy" / "toggles" / "hypr")

    def test_toggle_is_lua_that_disables_the_named_output(self):
        text = omarchy.render_toggle("eDP-1")
        self.assertIn('hl.monitor({ output = "eDP-1", disabled = true })', text)
        # The comment has to explain why it does not live in monitors.lua.
        self.assertIn("monitors.lua", text)

    def test_disable_creates_the_file_atomically(self):
        self.assertFalse(omarchy.is_disabled())
        path = omarchy.disable_builtin("eDP-1")
        self.assertTrue(path.exists())
        self.assertTrue(omarchy.is_disabled())
        self.assertIn("eDP-1", path.read_text())
        leftovers = [p.name for p in path.parent.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_enable_removes_it_and_reports_whether_it_had_to(self):
        omarchy.disable_builtin("eDP-1")
        self.assertTrue(omarchy.enable_builtin())
        self.assertFalse(omarchy.is_disabled())
        self.assertFalse(omarchy.enable_builtin())

    def test_disable_overwrites_an_older_toggle(self):
        omarchy.disable_builtin("eDP-1")
        omarchy.disable_builtin("LVDS-1")
        self.assertIn("LVDS-1", omarchy.toggle_path().read_text())
        self.assertNotIn("eDP-1", omarchy.toggle_path().read_text())


class SyncTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        patcher = mock.patch.dict(os.environ, {"XDG_STATE_HOME": self._tmp.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def test_switching_the_panel_off_writes_the_toggle(self):
        states = [monitor("eDP-1", enabled=False), monitor("DP-1")]
        note = omarchy.sync(states)
        self.assertTrue(omarchy.is_disabled())
        self.assertIn("eDP-1", note)
        self.assertIn("comes back", note)

    def test_sync_is_idempotent(self):
        states = [monitor("eDP-1", enabled=False), monitor("DP-1")]
        omarchy.sync(states)
        self.assertIsNone(omarchy.sync(states))

    def test_switching_the_panel_on_clears_the_toggle(self):
        omarchy.disable_builtin("eDP-1")
        note = omarchy.sync([monitor("eDP-1"), monitor("DP-1")])
        self.assertFalse(omarchy.is_disabled())
        self.assertIn("back on", note)

    def test_nothing_to_do_without_a_builtin_panel(self):
        self.assertIsNone(omarchy.sync([monitor("DP-1"), monitor("HDMI-A-1")]))
        self.assertFalse(omarchy.is_disabled())

    def test_an_external_being_off_does_not_touch_the_toggle(self):
        omarchy.sync([monitor("eDP-1"), monitor("DP-1", enabled=False)])
        self.assertFalse(omarchy.is_disabled())

    def test_builtin_is_found_the_way_omarchy_finds_it(self):
        states = [monitor("DP-1"), monitor("eDP-1"), monitor("HDMI-A-1")]
        self.assertEqual(omarchy.builtin(states).name, "eDP-1")
        self.assertIsNone(omarchy.builtin([monitor("DP-1")]))


class AvailabilityTests(unittest.TestCase):
    def test_available_when_the_toggles_directory_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp})
            which = mock.patch("shutil.which", return_value=None)
            with env, which:
                self.assertFalse(omarchy.available())
                omarchy.toggles_dir().mkdir(parents=True)
                self.assertTrue(omarchy.available())

    def test_available_when_the_omarchy_command_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = mock.patch.dict(os.environ, {"XDG_STATE_HOME": tmp})
            which = mock.patch("shutil.which", return_value="/usr/bin/omarchy")
            with env, which:
                self.assertTrue(omarchy.available())

    def test_safety_net_needs_both_recovery_helpers(self):
        with mock.patch("shutil.which", side_effect=lambda name: "/usr/bin/" + name):
            self.assertTrue(omarchy.has_safety_net())
        with mock.patch("shutil.which", return_value=None):
            self.assertFalse(omarchy.has_safety_net())

    def test_safety_net_is_false_when_only_one_helper_exists(self):
        def which(name):
            return "/usr/bin/x" if name == "omarchy-hyprland-monitor-clamshell" else None

        with mock.patch("shutil.which", side_effect=which):
            self.assertFalse(omarchy.has_safety_net())


if __name__ == "__main__":
    unittest.main()
