import tempfile
import unittest
from pathlib import Path

from displaywright.displays.profiles import Profile, ProfileStore, fingerprint
from displaywright.model import Mode, MonitorState


def states():
    return [
        MonitorState(
            name="eDP-1",
            description="LG Display 0x07C5",
            mode=Mode(3200, 2000, 120.0),
            scale=2.0,
            available_modes=[Mode(3200, 2000, 120.0)],
        ),
        MonitorState(
            name="DP-1",
            description="CSF CS3421",
            mode=Mode(3440, 1440, 50.0),
            x=1600,
            available_modes=[Mode(3440, 1440, 50.0), Mode(2560, 1440, 120.0)],
        ),
    ]


class FingerprintTests(unittest.TestCase):
    def test_order_independent(self):
        a, b = states(), list(reversed(states()))
        self.assertEqual(fingerprint(a), fingerprint(b))

    def test_changes_when_an_output_disappears(self):
        self.assertNotEqual(fingerprint(states()), fingerprint(states()[:1]))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "profiles.json"
        self.store = ProfileStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_roundtrip_through_disk(self):
        self.store.put("dock", states())
        reloaded = ProfileStore(self.path)
        self.assertEqual(reloaded.names(), ["dock"])
        self.assertEqual(len(reloaded.get("dock").monitors), 2)

    def test_match_by_connected_outputs(self):
        self.store.put("dock", states())
        self.assertEqual(self.store.match(states()).name, "dock")
        self.assertIsNone(self.store.match(states()[:1]))

    def test_delete(self):
        self.store.put("dock", states())
        self.assertTrue(self.store.delete("dock"))
        self.assertFalse(self.store.delete("dock"))
        self.assertEqual(ProfileStore(self.path).names(), [])

    def test_corrupt_file_is_ignored(self):
        self.path.write_text("{not json")
        self.assertEqual(ProfileStore(self.path).names(), [])


class ApplyTests(unittest.TestCase):
    def test_applies_saved_geometry(self):
        saved = states()
        saved[1].x, saved[1].y, saved[1].scale = 0, 1000, 1.0
        saved[0].x, saved[0].y = 0, 0
        profile = Profile.from_states("stacked", saved)

        live = states()
        skipped = profile.apply_to(live)
        self.assertEqual(skipped, [])
        self.assertEqual((live[1].x, live[1].y), (0, 1000))

    def test_missing_output_is_reported(self):
        profile = Profile.from_states("dock", states())
        live = states()[:1]
        self.assertEqual(profile.apply_to(live), ["DP-1"])

    def test_unavailable_mode_falls_back_to_preferred(self):
        saved = states()
        saved[1].mode = Mode(1920, 1080, 240.0)  # link no longer offers this
        profile = Profile.from_states("dock", saved)

        live = states()
        profile.apply_to(live)
        self.assertIsNone(live[1].mode)

    def test_matches_by_description_when_the_connector_moves(self):
        profile = Profile.from_states("dock", states())
        live = states()
        live[1].name = "DP-2"  # same panel, different port
        skipped = profile.apply_to(live)
        self.assertEqual(skipped, [])
        self.assertEqual(live[1].x, 1600)


if __name__ == "__main__":
    unittest.main()
