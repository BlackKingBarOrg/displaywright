import tempfile
import unittest
from pathlib import Path

from hyprlayout import luawriter
from hyprlayout.model import Mode, MonitorState

# Shaped like a stock Omarchy ~/.config/hypr/monitors.lua.
EXISTING = """\
-- See https://wiki.hypr.land/Configuring/Basics/Monitors/

local omarchy_monitor_scale = 2

hl.env("GDK_SCALE", "2")
hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 2 })

-- Laptop panel pinned at origin.
hl.monitor({ output = "eDP-1", mode = "3200x2000@120", position = "0x0", scale = 2 })
"""


def laptop():
    return MonitorState(
        name="eDP-1",
        make="LG Display",
        model="0x07C5",
        mode=Mode(3200, 2000, 120.0),
        scale=2.0,
        x=0,
        y=0,
        available_modes=[Mode(3200, 2000, 120.0)],
    )


def ultrawide(**kwargs):
    defaults = {
        "name": "DP-1",
        "make": "CSF",
        "model": "CS3421",
        "mode": Mode(3440, 1440, 50.0),
        "scale": 1.0,
        "x": 1600,
        "y": 0,
        "available_modes": [Mode(3440, 1440, 50.0)],
    }
    defaults.update(kwargs)
    return MonitorState(**defaults)


class RenderTests(unittest.TestCase):
    def test_basic_call(self):
        self.assertEqual(
            luawriter.render_call(laptop()),
            'hl.monitor({ output = "eDP-1", mode = "3200x2000@120", position = "0x0", scale = 2 })',
        )

    def test_extras_use_hl_monitorspec_field_names(self):
        state = ultrawide(transform=1, mirror_of="eDP-1", vrr=1, scale=1.25)
        rendered = luawriter.render_call(state)
        self.assertIn("transform = 1", rendered)
        self.assertIn('mirror = "eDP-1"', rendered)
        self.assertIn("vrr = 1", rendered)
        self.assertIn("scale = 1.25", rendered)

    def test_disabled_output(self):
        self.assertEqual(
            luawriter.render_call(ultrawide(enabled=False)),
            'hl.monitor({ output = "DP-1", disabled = true })',
        )

    def test_quotes_are_escaped(self):
        state = MonitorState(name='we"ird', mode=Mode(800, 600))
        self.assertIn('output = "we\\"ird"', luawriter.render_call(state))

    def test_block_has_markers_and_comments(self):
        block = luawriter.render_block([laptop(), ultrawide()])
        self.assertTrue(block.startswith(luawriter.BEGIN))
        self.assertTrue(block.rstrip().endswith(luawriter.END))
        self.assertIn("-- eDP-1: LG Display", block)
        self.assertEqual(block.count("hl.monitor("), 2)

    def test_block_orders_left_to_right(self):
        block = luawriter.render_block([ultrawide(), laptop()])
        self.assertLess(block.index('"eDP-1"'), block.index('"DP-1"'))


class BuiltinToggleTests(unittest.TestCase):
    """A switched-off laptop panel must not be written as disabled = true.

    Nothing removes that line again, so unplugging the external display would
    leave a black machine. The "off" belongs in Omarchy's toggle instead.
    """

    def panel(self, enabled=False):
        return MonitorState(
            name="eDP-1",
            make="LG Display",
            mode=Mode(3200, 2000, 120.0),
            scale=2.0,
            enabled=enabled,
            available_modes=[Mode(3200, 2000, 120.0)],
        )

    def test_disabled_panel_is_written_as_an_enabled_rule(self):
        block = luawriter.render_block([self.panel(), ultrawide()], toggle_builtin=True)
        self.assertIn('hl.monitor({ output = "eDP-1", mode = "3200x2000@120"', block)
        self.assertNotIn('output = "eDP-1", disabled = true', block)
        self.assertIn("internal-monitor-disable", block)

    def test_without_the_toggle_it_is_written_as_disabled(self):
        block = luawriter.render_block([self.panel(), ultrawide()], toggle_builtin=False)
        self.assertIn('hl.monitor({ output = "eDP-1", disabled = true })', block)
        self.assertNotIn("internal-monitor-disable", block)

    def test_an_enabled_panel_is_unaffected(self):
        with_toggle = luawriter.render_block([self.panel(enabled=True)], toggle_builtin=True)
        without = luawriter.render_block([self.panel(enabled=True)], toggle_builtin=False)
        self.assertEqual(with_toggle, without)

    def test_a_disabled_external_is_still_written_as_disabled(self):
        block = luawriter.render_block(
            [self.panel(enabled=True), ultrawide(enabled=False)], toggle_builtin=True
        )
        self.assertIn('hl.monitor({ output = "DP-1", disabled = true })', block)

    def test_the_geometry_omarchy_restores_from_is_preserved(self):
        # omarchy-hyprland-monitor-clamshell reads scale and position back out of
        # monitors.lua when it switches the panel on again.
        block = luawriter.render_block([self.panel()], toggle_builtin=True)
        self.assertIn('position = "0x0"', block)
        self.assertIn("scale = 2", block)


class MergeTests(unittest.TestCase):
    def test_first_save_preserves_user_lines_and_comments_out_monitors(self):
        merged = luawriter.render_file(EXISTING, [laptop(), ultrawide()])
        self.assertIn('hl.env("GDK_SCALE", "2")', merged)
        self.assertIn("local omarchy_monitor_scale = 2", merged)
        self.assertIn(
            '-- [hyprlayout] replaced: hl.monitor({ output = "eDP-1"', merged
        )
        self.assertIn("commented out 1 earlier hl.monitor call(s)", merged)
        self.assertIn(luawriter.BEGIN, merged)

    def test_catch_all_rule_is_never_touched(self):
        # `output = ""` configures displays we have not seen yet -- deleting it
        # would leave a freshly plugged monitor unconfigured.
        merged = luawriter.render_file(EXISTING, [laptop(), ultrawide()])
        self.assertIn(
            'hl.monitor({ output = "", mode = "preferred", position = "auto", scale = 2 })',
            merged,
        )

    def test_rules_for_absent_outputs_are_kept(self):
        source = EXISTING + 'hl.monitor({ output = "HDMI-A-1", mode = "preferred" })\n'
        merged = luawriter.render_file(source, [laptop(), ultrawide()])
        self.assertIn('hl.monitor({ output = "HDMI-A-1", mode = "preferred" })', merged)

    def test_second_save_replaces_block_only(self):
        once = luawriter.render_file(EXISTING, [laptop(), ultrawide()])
        twice = luawriter.render_file(once, [laptop(), ultrawide()])
        self.assertEqual(once, twice)

    def test_block_updates_in_place_without_duplicating(self):
        once = luawriter.render_file(EXISTING, [laptop(), ultrawide()])
        moved = luawriter.render_file(once, [laptop(), ultrawide(x=1600, y=200)])
        self.assertEqual(moved.count(luawriter.BEGIN), 1)
        self.assertIn('position = "1600x200"', moved)
        self.assertNotIn('position = "1600x0"', moved)

    def test_text_after_the_block_survives(self):
        once = luawriter.render_file(EXISTING, [laptop()])
        with_tail = once + '\nhl.env("MY_VAR", "1")\n'
        again = luawriter.render_file(with_tail, [laptop(), ultrawide()])
        self.assertIn('hl.env("MY_VAR", "1")', again)

    def test_multiline_calls_are_fully_commented(self):
        source = (
            "hl.monitor({\n"
            '  output = "eDP-1",\n'
            '  mode = "preferred",\n'
            "})\n"
            'hl.env("KEEP", "1")\n'
        )
        merged = luawriter.render_file(source, [laptop()])
        self.assertIn('-- [hyprlayout] replaced:   mode = "preferred",', merged)
        self.assertIn('-- [hyprlayout] replaced: })', merged)
        self.assertIn('hl.env("KEEP", "1")', merged)
        self.assertIn("commented out 1 earlier hl.monitor call(s)", merged)

    def test_empty_file(self):
        merged = luawriter.render_file("", [laptop()])
        self.assertTrue(merged.startswith(luawriter.BEGIN))


class SaveTests(unittest.TestCase):
    def test_save_creates_backup_and_writes_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitors.lua"
            path.write_text(EXISTING)

            backup = luawriter.save(path, [laptop(), ultrawide()])
            self.assertIsNotNone(backup)
            self.assertEqual(backup.read_text(), EXISTING)
            self.assertIn(luawriter.BEGIN, path.read_text())
            # No temp file left behind.
            self.assertEqual(
                [p.name for p in Path(tmp).iterdir() if p.name.startswith(".")], []
            )

    def test_save_to_new_path_makes_no_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nested" / "monitors.lua"
            self.assertIsNone(luawriter.save(path, [laptop()]))
            self.assertIn("hl.monitor(", path.read_text())

    def test_preview_matches_what_save_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitors.lua"
            path.write_text(EXISTING)
            expected, patch = luawriter.preview(path, [laptop()])
            self.assertIn("+", patch)
            luawriter.save(path, [laptop()], backup=False)
            self.assertEqual(path.read_text(), expected)

    def test_diff_is_empty_when_nothing_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "monitors.lua"
            path.write_text(EXISTING)
            luawriter.save(path, [laptop()], backup=False)
            _, patch = luawriter.preview(path, [laptop()])
            self.assertEqual(patch, "")


if __name__ == "__main__":
    unittest.main()
