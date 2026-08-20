import unittest

from displaywright.model import (
    Mode,
    MonitorState,
    scale_warning,
    suggest_scale,
    unmet_requests,
)

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

    def test_a_rotated_output_keeps_the_mode_hyprctl_reported(self):
        # hyprctl reports the *mode*, not what the panel shows: a display turned
        # on its side is still "3440x1440", and that is the string every entry
        # in availableModes uses. Rotating it here would invent a mode the
        # display does not have, and applying that mode would fail.
        rotated = dict(HYPRCTL_SAMPLE[1], transform=1)
        state = MonitorState.from_hyprctl(rotated)
        self.assertEqual(state.mode, Mode(3440, 1440, 50.0))
        self.assertIn(state.mode.resolution, [m.resolution for m in state.available_modes])
        self.assertEqual(state.logical_size, (1440.0, 3440.0))

    def test_focus_is_read_back(self):
        state = MonitorState.from_hyprctl(dict(HYPRCTL_SAMPLE[1], focused=True))
        self.assertTrue(state.focused)
        self.assertFalse(MonitorState.from_hyprctl(HYPRCTL_SAMPLE[1]).focused)


class PanelGeometryTests(unittest.TestCase):
    """What a wallpaper has to cover, which is not what a monitor rule says.

    The wallpaper half of the app reads these; getting a rotation or a scale
    wrong here draws the picture on its side or at the wrong size.
    """

    def entry(self, **over):
        base = dict(HYPRCTL_SAMPLE[1], width=2560, height=1440, scale=1,
                    availableModes=["2560x1440@60.00Hz"], refreshRate=60.0)
        base.update(over)
        return MonitorState.from_hyprctl(base)

    def test_an_unscaled_landscape_display_is_itself(self):
        state = self.entry()
        self.assertEqual(state.pixel_size_rotated, (2560, 1440))
        self.assertEqual(state.logical_size, (2560.0, 1440.0))
        self.assertFalse(state.rotated)
        self.assertFalse(state.portrait)

    def test_scaling_shrinks_the_footprint_but_not_the_pixels(self):
        state = self.entry(width=3200, height=2000, scale=2,
                           availableModes=["3200x2000@60.00Hz"])
        self.assertEqual(state.pixel_size_rotated, (3200, 2000))
        self.assertEqual(state.logical_size, (1600.0, 1000.0))

    def test_a_quarter_turn_swaps_width_and_height(self):
        for transform in (1, 3, 5, 7):
            with self.subTest(transform=transform):
                state = self.entry(transform=transform)
                self.assertEqual(state.pixel_size_rotated, (1440, 2560))
                self.assertEqual(state.logical_size, (1440.0, 2560.0))
                self.assertTrue(state.rotated)
                self.assertTrue(state.portrait)

    def test_a_half_turn_or_flip_does_not(self):
        for transform in (0, 2, 4, 6):
            with self.subTest(transform=transform):
                state = self.entry(transform=transform)
                self.assertEqual(state.pixel_size_rotated, (2560, 1440))
                self.assertFalse(state.rotated)

    def test_rotation_is_applied_before_the_scale(self):
        state = self.entry(width=2880, height=1800, scale=1.5, transform=1,
                           availableModes=["2880x1800@60.00Hz"])
        self.assertEqual(state.pixel_size_rotated, (1800, 2880))
        self.assertEqual(state.logical_size, (1200.0, 1920.0))

    def test_a_zero_scale_is_treated_as_one(self):
        self.assertEqual(self.entry(scale=0).logical_size, (2560.0, 1440.0))

    def test_edges_follow_from_position_and_logical_size(self):
        state = self.entry(x=1600, y=-826)
        self.assertEqual((state.rect.right, state.rect.bottom), (1600 + 2560, -826 + 1440))

    def test_an_unscaled_display_summarises_as_just_its_resolution(self):
        self.assertEqual(self.entry().panel_summary(), "2560\u00d71440")

    def test_a_scaled_display_says_what_the_desktop_makes_of_it(self):
        state = self.entry(width=3200, height=2000, scale=2,
                           availableModes=["3200x2000@60.00Hz"])
        self.assertEqual(state.panel_summary(), "3200\u00d72000 \u00b7 scale 2 \u2192 1600\u00d71000")

    def test_a_rotated_display_says_so(self):
        self.assertEqual(self.entry(transform=1).panel_summary(), "1440\u00d72560 \u00b7 rotated")


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


class BuiltinDetectionTests(unittest.TestCase):
    def test_laptop_panels_are_recognised(self):
        for name in ("eDP-1", "eDP-2", "LVDS-1", "DSI-1", "edp-1"):
            self.assertTrue(MonitorState(name=name).is_builtin, name)

    def test_external_outputs_are_not(self):
        for name in ("DP-1", "HDMI-A-1", "DVI-D-1", "HEADLESS-2", ""):
            self.assertFalse(MonitorState(name=name).is_builtin, name)


class UnmetRequestTests(unittest.TestCase):
    """What Hyprland actually delivered versus what was asked for."""

    def want(self, **kwargs):
        base = {"name": "DP-1", "mode": Mode(3440, 1440, 60.0), "scale": 1.0}
        base.update(kwargs)
        return MonitorState(**base)

    def test_exact_match_is_silent(self):
        self.assertEqual(unmet_requests([self.want()], [self.want()]), [])

    def test_refresh_rate_that_did_not_stick_is_reported(self):
        got = self.want(mode=Mode(3440, 1440, 50.0))
        problems = unmet_requests([self.want()], [got])
        self.assertEqual(len(problems), 1)
        self.assertIn("50 Hz", problems[0])
        self.assertIn("60 Hz", problems[0])

    def test_nudged_scale_is_reported(self):
        problems = unmet_requests([self.want(scale=1.3)], [self.want(scale=1.25)])
        self.assertEqual(len(problems), 1)
        self.assertIn("1.25", problems[0])

    def test_rounding_noise_in_scale_is_not_reported(self):
        self.assertEqual(unmet_requests([self.want(scale=1.25)], [self.want(scale=1.2500001)]), [])

    def test_disabled_outputs_are_skipped(self):
        want = self.want(enabled=False)
        got = self.want(enabled=False, mode=Mode(800, 600, 60.0))
        self.assertEqual(unmet_requests([want], [got]), [])

    def test_missing_output_is_skipped(self):
        self.assertEqual(unmet_requests([self.want()], []), [])

    def test_preferred_mode_makes_no_claim(self):
        want = self.want(mode=None)
        got = self.want(mode=Mode(1920, 1080, 60.0))
        self.assertEqual(unmet_requests([want], [got]), [])

    def test_several_outputs_each_reported(self):
        wants = [self.want(), self.want(name="eDP-1", mode=Mode(3200, 2000, 120.0), scale=2.0)]
        gots = [
            self.want(mode=Mode(3440, 1440, 50.0)),
            self.want(name="eDP-1", mode=Mode(3200, 2000, 60.0), scale=2.0),
        ]
        self.assertEqual(len(unmet_requests(wants, gots)), 2)


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
