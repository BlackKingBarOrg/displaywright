"""Moving a wallwright / hyprlayout installation over.

Every path here writes into a temporary XDG root. Nothing in this suite may
touch the real one -- a migration that got loose would move the developer's own
wallpapers out from under their desktop.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from displaywright import migrate
from displaywright.wallpapers import store


class MigrateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.pictures = self.root / "pictures"
        env = mock.patch.dict(
            os.environ,
            {
                "XDG_CONFIG_HOME": str(self.root / "config"),
                "XDG_CACHE_HOME": str(self.root / "cache"),
                "XDG_STATE_HOME": str(self.root / "state"),
                "XDG_PICTURES_DIR": str(self.pictures),
            },
        )
        env.start()
        self.addCleanup(env.stop)

    def seed_wallwright(self) -> Path:
        old_pictures = self.pictures / "Wallwright"
        old_pictures.mkdir(parents=True)
        picture = old_pictures / "a.jpg"
        picture.write_bytes(b"not really a jpeg")

        old_config = self.root / "config" / "wallwright"
        old_config.mkdir(parents=True)
        (old_config / "config.json").write_text(json.dumps({
            "version": 1,
            "monitors": {"DP-1": {"kind": "image", "path": str(picture), "fit": "fill"}},
            "folders": [str(old_pictures)],
        }))
        (self.root / "cache" / "wallwright" / "thumbnails").mkdir(parents=True)
        return picture

    def test_nothing_to_do_on_a_clean_machine(self):
        self.assertFalse(migrate.pending())
        self.assertEqual(migrate.run(install_renderer=False), [])

    def test_a_wallwright_install_is_detected(self):
        self.seed_wallwright()
        self.assertTrue(migrate.pending())

    def test_the_wallpaper_folder_and_the_paths_into_it_move_together(self):
        self.seed_wallwright()
        migrate.run(install_renderer=False)

        moved = self.pictures / "Displaywright" / "a.jpg"
        self.assertTrue(moved.is_file(), "the picture did not come across")
        self.assertFalse((self.pictures / "Wallwright").exists())

        config = store.load()
        self.assertEqual(config.monitors["DP-1"].path, str(moved))
        self.assertEqual(config.folders, [str(self.pictures / "Displaywright")])

    def test_the_config_lands_under_the_new_name(self):
        self.seed_wallwright()
        migrate.run(install_renderer=False)
        self.assertTrue(store.config_path().is_file())
        self.assertFalse(store.legacy_config_path().exists())
        self.assertFalse((self.root / "config" / "wallwright").exists())

    def test_layout_profiles_come_across(self):
        old = self.root / "config" / "hyprlayout"
        old.mkdir(parents=True)
        (old / "profiles.json").write_text('{"schema": 1, "profiles": {}}')
        migrate.run(install_renderer=False)
        self.assertTrue((self.root / "config" / "displaywright" / "profiles.json").is_file())
        self.assertFalse(old.exists())

    def test_the_thumbnail_cache_moves(self):
        self.seed_wallwright()
        migrate.run(install_renderer=False)
        self.assertTrue((self.root / "cache" / "displaywright" / "thumbnails").is_dir())
        self.assertFalse((self.root / "cache" / "wallwright").exists())

    def test_running_twice_is_harmless(self):
        self.seed_wallwright()
        migrate.run(install_renderer=False)
        self.assertEqual(migrate.run(install_renderer=False), [])
        self.assertFalse(migrate.pending())

    def test_an_existing_config_is_never_overwritten(self):
        self.seed_wallwright()
        store.config_path().parent.mkdir(parents=True, exist_ok=True)
        store.config_path().write_text('{"version": 1, "monitors": {}}')
        changed = migrate.run(install_renderer=False)
        self.assertTrue(any("already exists" in line for line in changed))
        self.assertEqual(store.load().monitors, {})


class LegacyFallbackTests(unittest.TestCase):
    """An unmigrated machine still shows its wallpapers rather than nothing."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(self.root / "config")})
        env.start()
        self.addCleanup(env.stop)

    def test_the_wallwright_config_is_read_when_there_is_no_current_one(self):
        legacy = store.legacy_config_path()
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({
            "version": 1,
            "monitors": {"DP-1": {"kind": "color", "color": "#101010"}},
        }))
        self.assertIn("DP-1", store.load().monitors)

    def test_a_current_config_wins(self):
        legacy = store.legacy_config_path()
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({
            "version": 1,
            "monitors": {"DP-1": {"kind": "color", "color": "#101010"}},
        }))
        store.config_path().parent.mkdir(parents=True)
        store.config_path().write_text('{"version": 1, "monitors": {}}')
        self.assertEqual(store.load().monitors, {})


if __name__ == "__main__":
    unittest.main()
