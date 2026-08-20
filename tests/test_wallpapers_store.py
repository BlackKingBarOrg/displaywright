import json
import tempfile
import unittest
from pathlib import Path

from displaywright.wallpapers import store as config
from displaywright.wallpapers.model import Config, Fit, Kind, Source


class SaveAndLoad(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.path = Path(self._dir.name) / "nested" / "config.json"

    def tearDown(self):
        self._dir.cleanup()

    def test_a_missing_file_reads_as_empty(self):
        self.assertEqual(config.load(self.path).monitors, {})

    def test_save_creates_the_directory(self):
        config.save(Config(), self.path)
        self.assertTrue(self.path.is_file())

    def test_round_trip(self):
        cfg = Config(monitors={"DP-1": Source(kind=Kind.IMAGE, path="/w/a.png", fit=Fit.TILE)})
        config.save(cfg, self.path)
        self.assertEqual(config.load(self.path).monitors["DP-1"].fit, Fit.TILE)

    def test_corrupt_json_reads_as_empty_instead_of_raising(self):
        # The renderer treats an empty config as "every output follows the
        # theme", which is a working desktop; refusing to load would not be.
        self.path.parent.mkdir(parents=True)
        self.path.write_text("{ this is not json")
        self.assertEqual(config.load(self.path).monitors, {})

    def test_no_temporary_file_is_left_behind(self):
        config.save(Config(), self.path)
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name != "config.json"]
        self.assertEqual(leftovers, [])

    def test_the_written_file_is_valid_json_with_a_version(self):
        config.save(Config(monitors={"DP-1": Source(path="/w/a.png")}), self.path)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["version"], 1)
        self.assertIn("DP-1", data["monitors"])

    def test_saving_over_an_existing_file_replaces_it_wholesale(self):
        config.save(Config(monitors={"DP-1": Source(path="/w/a.png")}), self.path)
        config.save(Config(), self.path)
        self.assertEqual(json.loads(self.path.read_text())["monitors"], {})


class TempSibling(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.target = Path(self._dir.name) / "thing.png"
        self.addCleanup(self._dir.cleanup)

    def test_it_lands_next_to_the_target(self):
        # Same directory means the same filesystem, which is what makes the
        # rename that replaces the target atomic.
        self.assertEqual(config.temp_sibling(self.target).parent, self.target.parent)

    def test_it_is_hidden_and_mentions_the_target(self):
        name = config.temp_sibling(self.target).name
        self.assertTrue(name.startswith("."))
        self.assertIn("thing.png", name)

    def test_every_call_gets_its_own_name(self):
        # Two callers writing the same target -- the thumbnail worker and a
        # canvas repaint -- must not share one scratch file, or the first to
        # finish deletes the other's.
        names = {config.temp_sibling(self.target) for _ in range(200)}
        self.assertEqual(len(names), 200)
