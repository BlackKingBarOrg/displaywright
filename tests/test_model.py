import unittest

from hyprlayout.model import Mode, MonitorState, scale_warning, suggest_scale

# Trimmed from `hyprctl monitors all -j` on a real laptop + ultrawide setup.
HYPRCTL_SAMPLE = [
    {
        "name": "eDP-1",
        "description": "LG Display 0x07C5",
        "make": "LG Display",
        "model": "0x07C5",
        "physicalWidth": 340,
        "physicalHeight": 220,
        "width": 3200,
        "height": 2000,
        "refreshRate": 120.0,
        "x": 0,
        "y": 0,
        "scale": 2,
        "transform": 0,
        "disabled": False,
        "mirrorOf": "none",
        "availableModes": ["3200x2000@120.00Hz", "3200x2000@60.00Hz"],
    },
    {
        "name": "DP-1",
        "description": "CSF CS3421",
        "make": "CSF",
        "model": "CS3421",
        "physicalWidth": 810,
        "physicalHeight": 350,
        "width": 3440,
        "height": 1440,
        "refreshRate": 50.0,
        "x": 1600,
        "y": 0,
        "scale": 1,
        "transform": 0,
        "disabled": False,
        "mirrorOf": "none",
        "availableModes": ["3440x1440@60.00Hz", "3440x1440@99.99Hz", "2560x1440@120.00Hz"],
    },
]


class ModeTests(unittest.TestCase):
    def test_parses_hyprctl_form(self):
        self.assertEqual(Mode.parse("3440x1440@99.99Hz"), Mode(3440, 1440, 99.99))
        self.assertEqual(Mode.parse("1920x1080"), Mode(1920, 1080, 0.0))
        self.assertIsNone(Mode.parse("garbage"))

    def test_renders_compact_hypr_form(self):
        self.assertEqual(Mode(3200, 2000, 120.0).hypr(), "3200x2000@120")
        self.assertEqual(Mode(3440, 1440, 99.99).hypr(), "3440x1440@99.99")
        self.assertEqual(Mode(1920, 1080).hypr(), "1920x1080")

    def test_label_is_human_readable(self):
        self.assertEqual(Mode(2560, 1440, 120.0).label(), "2560×1440 @ 120 Hz")


class FromHyprctlTests(unittest.TestCase):
    def setUp(self):
        self.laptop = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[0])
        self.ultrawide = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[1])

    def test_reads_geometry(self):
        self.assertEqual(self.laptop.mode, Mode(3200, 2000, 120.0))
        self.assertEqual(self.laptop.scale, 2.0)
        self.assertEqual(self.laptop.logical_size, (1600.0, 1000.0))
        self.assertEqual(self.ultrawide.x, 1600)

    def test_modes_sorted_by_area_then_refresh(self):
        self.assertEqual(self.ultrawide.available_modes[0], Mode(3440, 1440, 99.99))

    def test_off_list_refresh_rate_is_preserved(self):
        # This ultrawide runs 3440x1440@50 because of a link bandwidth limit, and
        # 50Hz is not advertised. Rewriting it to the nearest listed rate (60)
        # would silently change the user's mode on the next Apply.
        self.assertEqual(self.ultrawide.mode, Mode(3440, 1440, 50.0))
        self.assertNotIn(self.ultrawide.mode, self.ultrawide.available_modes)

    def test_near_miss_refresh_snaps_to_advertised_mode(self):
        # 99.988 reported vs 99.99 advertised is rounding, not a different mode.
        entry = dict(HYPRCTL_SAMPLE[1], refreshRate=99.988)
        state = MonitorState.from_hyprctl(entry)
        self.assertEqual(state.mode, Mode(3440, 1440, 99.99))
        self.assertIn(state.mode, state.available_modes)

    def test_pretty_name_skips_hex_model_ids(self):
        self.assertEqual(self.laptop.pretty_name, "LG Display")
        self.assertEqual(self.ultrawide.pretty_name, "CSF CS3421")

    def test_rotation_undone_when_reading_back(self):
        rotated = dict(HYPRCTL_SAMPLE[1], transform=1, width=1440, height=3440)
        state = MonitorState.from_hyprctl(rotated)
        self.assertEqual(state.mode, Mode(3440, 1440, 50.0))
        self.assertEqual(state.logical_size, (1440.0, 3440.0))


class RuleArgsTests(unittest.TestCase):
    def base(self, **kwargs):
        return MonitorState(name="DP-1", mode=Mode(2560, 1440, 60.0), **kwargs)

    def test_plain(self):
        self.assertEqual(self.base(x=100, y=50).rule_args(), "DP-1,2560x1440@60,100x50,1")

    def test_preferred_mode(self):
        state = MonitorState(name="DP-1", scale=1.5)
        self.assertEqual(state.rule_args(), "DP-1,preferred,0x0,1.5")

    def test_extras(self):
        state = self.base(transform=3, mirror_of="eDP-1", vrr=1, scale=1.25)
        self.assertEqual(
            state.rule_args(),
            "DP-1,2560x1440@60,0x0,1.25,transform,3,mirror,eDP-1,vrr,1",
        )

    def test_disabled(self):
        self.assertEqual(self.base(enabled=False).rule_args(), "DP-1,disable")


class ScaleTests(unittest.TestCase):
    def test_integer_logical_size_is_silent(self):
        state = MonitorState(name="eDP-1", mode=Mode(3200, 2000, 120.0), scale=2.0)
        self.assertIsNone(scale_warning(state))

    def test_fractional_logical_size_warns(self):
        state = MonitorState(name="eDP-1", mode=Mode(3200, 2000, 120.0), scale=1.3)
        warning = scale_warning(state)
        self.assertIsNotNone(warning)
        self.assertIn("fractional", warning)

    def test_disabled_never_warns(self):
        state = MonitorState(name="eDP-1", mode=Mode(3200, 2000), scale=1.3, enabled=False)
        self.assertIsNone(scale_warning(state))

    def test_suggestion_uses_physical_density(self):
        # 3200x2000 across 340mm is ~239 dpi: 2x lands at a comfortable ~120.
        laptop = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[0])
        self.assertAlmostEqual(laptop.dpi, 239.06, places=1)
        self.assertEqual(suggest_scale(laptop), 2.0)

        # 3440x1440 across 810mm is ~108 dpi: already right at 1x.
        ultrawide = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[1])
        self.assertEqual(suggest_scale(ultrawide), 1.0)

    def test_suggestion_prefers_integer_logical_sizes(self):
        state = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[0])
        scale = suggest_scale(state)
        w, h = state.pixel_size
        self.assertEqual(w / scale, round(w / scale))
        self.assertEqual(h / scale, round(h / scale))

    def test_suggestion_falls_back_without_edid_size(self):
        hidpi = MonitorState(name="eDP-1", mode=Mode(3200, 2000, 120.0))
        fhd = MonitorState(name="DP-1", mode=Mode(1920, 1080, 60.0))
        self.assertEqual(hidpi.dpi, 0.0)
        self.assertEqual(suggest_scale(hidpi), 2.0)
        self.assertEqual(suggest_scale(fhd), 1.0)

    def test_diagonal_inches(self):
        laptop = MonitorState.from_hyprctl(HYPRCTL_SAMPLE[0])
        self.assertAlmostEqual(laptop.diagonal_inches, 15.9, places=1)
        self.assertEqual(MonitorState(name="X").diagonal_inches, 0.0)


class ComparisonTests(unittest.TestCase):
    def test_config_equals_ignores_metadata(self):
        a = MonitorState(name="DP-1", mode=Mode(1920, 1080, 60.0), description="A")
        b = MonitorState(name="DP-1", mode=Mode(1920, 1080, 60.0), description="B")
        self.assertTrue(a.config_equals(b))
        b.x = 10
        self.assertFalse(a.config_equals(b))

    def test_copy_is_independent(self):
        a = MonitorState(name="DP-1", available_modes=[Mode(800, 600)])
        b = a.copy()
        b.x = 99
        b.available_modes.append(Mode(640, 480))
        self.assertEqual(a.x, 0)
        self.assertEqual(len(a.available_modes), 1)


if __name__ == "__main__":
    unittest.main()
