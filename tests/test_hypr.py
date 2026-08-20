import json
import unittest
from unittest import mock

from displaywright import hypr
from displaywright.model import Mode, MonitorState

MONITORS_JSON = json.dumps(
    [
        {
            "name": "DP-1",
            "description": "CSF CS3421",
            "width": 3440,
            "height": 1440,
            "refreshRate": 50.0,
            "x": 1600,
            "y": 0,
            "scale": 1,
            "transform": 0,
            "disabled": False,
            "mirrorOf": "none",
            "availableModes": ["3440x1440@60.00Hz"],
        },
        {
            "name": "HDMI-A-1",
            "description": "Some Panel",
            "width": 0,
            "height": 0,
            "x": 0,
            "y": 0,
            "scale": 1,
            "transform": 0,
            "disabled": True,
            "mirrorOf": "none",
            "availableModes": [],
        },
        {
            "name": "eDP-1",
            "description": "LG Display",
            "width": 3200,
            "height": 2000,
            "refreshRate": 120.0,
            "x": 0,
            "y": 0,
            "scale": 2,
            "transform": 0,
            "disabled": False,
            "mirrorOf": "none",
            "availableModes": ["3200x2000@120.00Hz"],
        },
    ]
)


class ReadMonitorsTests(unittest.TestCase):
    def test_sorts_left_to_right_with_disabled_last(self):
        with mock.patch.object(hypr, "_run", return_value=MONITORS_JSON):
            states = hypr.read_monitors()
        self.assertEqual([s.name for s in states], ["eDP-1", "DP-1", "HDMI-A-1"])
        self.assertFalse(states[-1].enabled)

    def test_bad_json_raises_hypr_error(self):
        with mock.patch.object(hypr, "_run", return_value="not json"), \
                self.assertRaises(hypr.HyprError):
            hypr.read_monitors()


def sample_states():
    return [
        MonitorState(name="eDP-1", mode=Mode(3200, 2000, 120.0), scale=2.0),
        MonitorState(name="DP-1", mode=Mode(3440, 1440, 50.0), x=1600),
        MonitorState(name="HDMI-A-1", enabled=False),
    ]


class ApplyTests(unittest.TestCase):
    def test_prefers_eval_with_lua(self):
        with mock.patch.object(hypr, "_run", return_value="ok") as run:
            hypr.apply_states(sample_states())
        self.assertEqual(run.call_count, 1)
        args = run.call_args[0][0]
        self.assertEqual(args[0], "eval")
        self.assertEqual(
            args[1],
            'hl.monitor({ output = "eDP-1", mode = "3200x2000@120", position = "0x0", scale = 2 }); '
            'hl.monitor({ output = "DP-1", mode = "3440x1440@50", position = "1600x0", scale = 1 }); '
            'hl.monitor({ output = "HDMI-A-1", disabled = true })',
        )

    def test_falls_back_to_keyword_on_hyprlang_builds(self):
        replies = ["error: unknown request eval", "ok"]
        with mock.patch.object(hypr, "_run", side_effect=replies) as run:
            hypr.apply_states(sample_states())
        self.assertEqual(run.call_count, 2)
        args = run.call_args[0][0]
        self.assertEqual(args[0], "--batch")
        self.assertEqual(
            args[1],
            "keyword monitor eDP-1,3200x2000@120,0x0,2 ; "
            "keyword monitor DP-1,3440x1440@50,1600x0,1 ; "
            "keyword monitor HDMI-A-1,disable",
        )

    def test_lua_config_rejects_keyword_and_that_is_reported(self):
        # Real reply from Hyprland 0.56 with a Lua config.
        reply = "keyword can't work with non-legacy parsers. Use eval."
        with mock.patch.object(hypr, "_run", return_value=reply), \
                self.assertRaises(hypr.HyprError) as caught:
            hypr.apply_states(sample_states())
        self.assertIn("can't work", str(caught.exception))

    def test_no_monitors_is_a_no_op(self):
        with mock.patch.object(hypr, "_run") as run:
            self.assertEqual(hypr.apply_states([]), "")
        run.assert_not_called()


class DispatchTests(unittest.TestCase):
    """hyprctl exits 0 even for a rejected dispatcher, so text decides."""

    def test_first_accepted_form_wins(self):
        with mock.patch.object(hypr, "_run", return_value="ok") as run:
            hypr.dispatch("new-form", "old-form")
        self.assertEqual(run.call_count, 1)

    def test_falls_back_when_the_new_form_is_rejected(self):
        replies = ["error: hl.dispatch: expected a dispatcher", "ok"]
        with mock.patch.object(hypr, "_run", side_effect=replies) as run:
            hypr.dispatch("new-form", "old-form")
        self.assertEqual(run.call_count, 2)

    def test_raises_when_nothing_is_accepted(self):
        with mock.patch.object(hypr, "_run", return_value="error: nope"), \
                self.assertRaises(hypr.HyprError) as caught:
            hypr.dispatch("a", "b")
        self.assertIn("nope", str(caught.exception))

    def test_focus_monitor_prefers_the_lua_form(self):
        with mock.patch.object(hypr, "_run", return_value="ok") as run:
            hypr.focus_monitor("DP-1")
        self.assertEqual(run.call_args[0][0], ["dispatch", 'hl.dsp.focus{monitor="DP-1"}'])

    def test_move_cursor_prefers_the_lua_form(self):
        with mock.patch.object(hypr, "_run", return_value="ok") as run:
            hypr.move_cursor(3320, 720)
        self.assertEqual(run.call_args[0][0], ["dispatch", "hl.dsp.cursor.move{x=3320, y=720}"])


class MiscTests(unittest.TestCase):
    def test_notify_never_raises(self):
        with mock.patch.object(hypr, "_run", side_effect=hypr.HyprError("boom")):
            hypr.notify("hello")  # must not propagate

    def test_config_errors_normalises_the_clean_case(self):
        with mock.patch.object(hypr, "_run", return_value="no errors\n"):
            self.assertEqual(hypr.config_errors(), "")
        with mock.patch.object(hypr, "_run", return_value="Config error: bad line\n"):
            self.assertIn("bad line", hypr.config_errors())

    def test_failed_hyprctl_becomes_hypr_error(self):
        completed = mock.Mock(returncode=1, stdout="", stderr="boom")
        with mock.patch("subprocess.run", return_value=completed), \
                self.assertRaises(hypr.HyprError):
            hypr._run(["monitors"])


@unittest.skipUnless(hypr.is_running(), "needs a running Hyprland")
class LiveTests(unittest.TestCase):
    """Read-only checks against the real compositor."""

    def test_reads_at_least_one_monitor(self):
        states = hypr.read_monitors()
        self.assertTrue(states)
        self.assertTrue(all(s.name for s in states))

    def test_runtime_socket_exists(self):
        self.assertTrue((hypr.runtime_dir() / ".socket2.sock").exists())

    def test_identity_apply_is_accepted_and_changes_nothing(self):
        """Proves the live-apply dialect this Hyprland speaks is the one we send."""
        before = hypr.read_monitors()
        hypr.apply_states(before)  # raises HyprError if the compositor refuses
        after = hypr.read_monitors()
        self.assertEqual(len(before), len(after))
        for a, b in zip(before, after, strict=False):
            self.assertTrue(a.config_equals(b), f"{a.name} changed unexpectedly")

    def test_event_listener_connects_and_stops(self):
        listener = hypr.EventListener(lambda _name: None)
        self.assertTrue(listener.start())
        listener.stop()


if __name__ == "__main__":
    unittest.main()
