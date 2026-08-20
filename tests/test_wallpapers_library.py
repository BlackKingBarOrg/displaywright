"""Where pictures come from, and what happens to one you pick."""

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from displaywright.wallpapers import library


class PicturesDir(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_the_environment_wins(self):
        with mock.patch.dict(os.environ, {"XDG_PICTURES_DIR": str(self.root / "Snaps")}):
            self.assertEqual(library.pictures_dir(), self.root / "Snaps")

    def test_user_dirs_dirs_is_parsed_with_home_expanded(self):
        (self.root / "user-dirs.dirs").write_text(
            'XDG_DOWNLOAD_DIR="$HOME/Downloads"\nXDG_PICTURES_DIR="$HOME/Bilder"\n'
        )
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_PICTURES_DIR", None)
            with mock.patch.object(library, "config_home", return_value=self.root):
                self.assertEqual(library.pictures_dir(), Path.home() / "Bilder")

    def test_it_falls_back_to_pictures(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("XDG_PICTURES_DIR", None)
            with mock.patch.object(library, "config_home", return_value=self.root):
                self.assertEqual(library.pictures_dir(), Path.home() / "Pictures")

    def test_the_wallpaper_folder_sits_under_it(self):
        with mock.patch.dict(os.environ, {"XDG_PICTURES_DIR": str(self.root)}):
            self.assertEqual(library.wallpaper_dir(), self.root / "Displaywright")


class Adopt(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        self.pictures = self.root / "Pictures"
        self.pictures.mkdir()
        self.elsewhere = self.root / "Downloads"
        self.elsewhere.mkdir()
        patcher = mock.patch.dict(os.environ, {"XDG_PICTURES_DIR": str(self.pictures)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, folder: Path, name: str, content: bytes = b"picture") -> Path:
        path = folder / name
        path.write_bytes(content)
        return path

    def test_a_file_from_outside_is_copied_in(self):
        source = self.make(self.elsewhere, "a.png")
        adoption = library.adopt(source, folders=[])
        adopted = adoption.path
        self.assertTrue(adoption.copied)
        self.assertEqual(adopted, library.wallpaper_dir() / "a.png")
        self.assertTrue(adopted.is_file())
        self.assertEqual(adopted.read_bytes(), b"picture")
        # The original is left alone.
        self.assertTrue(source.is_file())

    def test_the_folder_is_created_on_demand(self):
        self.assertFalse(library.wallpaper_dir().exists())
        library.adopt(self.make(self.elsewhere, "a.png"), folders=[])
        self.assertTrue(library.wallpaper_dir().is_dir())

    def test_a_file_the_picker_already_sees_is_left_where_it_is(self):
        source = self.make(self.pictures, "a.png")
        self.assertEqual(library.adopt(source, folders=[self.pictures]).path, source)
        self.assertFalse((library.wallpaper_dir() / "a.png").exists())

    def test_a_file_already_in_the_wallpaper_folder_is_left_alone(self):
        library.ensure_wallpaper_dir()
        source = self.make(library.wallpaper_dir(), "a.png")
        self.assertEqual(library.adopt(source, folders=[]).path, source)

    def test_picking_the_same_file_twice_does_not_duplicate_it(self):
        source = self.make(self.elsewhere, "a.png")
        first = library.adopt(source, folders=[])
        second = library.adopt(source, folders=[])
        self.assertEqual(first.path, second.path)
        self.assertTrue(first.copied)
        # The second time nothing is written; it resolves to the first copy.
        self.assertFalse(second.copied)
        self.assertTrue(second.reused)
        self.assertEqual(len(list(library.wallpaper_dir().iterdir())), 1)

    def test_identical_contents_under_a_different_name_resolve_to_the_first_copy(self):
        first = library.adopt(self.make(self.elsewhere, "a.png"), folders=[])
        twin = library.adopt(self.make(self.elsewhere, "renamed.png"), folders=[])
        self.assertEqual(twin.path, first.path)
        self.assertTrue(twin.reused)

    def test_a_name_clash_with_different_contents_gets_a_suffix(self):
        library.adopt(self.make(self.elsewhere, "a.png", b"one"), folders=[])
        other = self.root / "other"
        other.mkdir()
        second = library.adopt(self.make(other, "a.png", b"two"), folders=[])
        self.assertEqual(second.path.name, "a-2.png")
        self.assertEqual(second.path.read_bytes(), b"two")
        self.assertTrue(second.copied)

    def test_no_partial_file_is_left_in_a_folder_the_picker_scans(self):
        library.adopt(self.make(self.elsewhere, "a.png"), folders=[])
        names = [p.name for p in library.wallpaper_dir().iterdir()]
        self.assertEqual(names, ["a.png"])

    def test_a_missing_source_is_returned_unchanged(self):
        missing = self.elsewhere / "gone.png"
        result = library.adopt(missing, folders=[])
        self.assertEqual(result.path, missing)
        self.assertFalse(result.copied)
        self.assertFalse(library.wallpaper_dir().exists())

    def test_the_wallpaper_folder_is_the_only_default(self):
        library.ensure_wallpaper_dir()
        self.assertEqual(library.default_folders(), [library.wallpaper_dir()])

    def test_pictures_itself_is_not_offered(self):
        # It is full of screenshots; the whole point of the wallpaper folder is
        # that the grid shows what was chosen, not what happens to be lying about.
        (self.pictures / "screenshot.png").write_bytes(b"x")
        library.ensure_wallpaper_dir()
        self.assertNotIn(self.pictures, library.default_folders())

    def test_there_are_no_defaults_before_the_folder_exists(self):
        self.assertEqual(library.default_folders(), [])


class Inside(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)

    def test_a_nested_file_is_inside(self):
        nested = self.root / "a" / "b"
        nested.mkdir(parents=True)
        target = nested / "c.png"
        target.write_bytes(b"x")
        self.assertTrue(library.is_inside(target, self.root))

    def test_a_sibling_is_not(self):
        (self.root / "a").mkdir()
        (self.root / "b").mkdir()
        target = self.root / "b" / "c.png"
        target.write_bytes(b"x")
        self.assertFalse(library.is_inside(target, self.root / "a"))


try:
    import gi

    gi.require_version("GdkPixbuf", "2.0")
    from gi.repository import GdkPixbuf

    HAVE_PIXBUF = True
except (ImportError, ValueError):
    HAVE_PIXBUF = False


@unittest.skipUnless(HAVE_PIXBUF, "GdkPixbuf is not installed")
class Thumbnails(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)
        self.addCleanup(self._dir.cleanup)
        patcher = mock.patch.dict(
            os.environ, {"XDG_CACHE_HOME": str(self.root / "cache")}
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.picture = self.root / "big.png"
        pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, False, 8, 900, 600)
        pixbuf.fill(0x3366CCFF)
        pixbuf.savev(str(self.picture), "png", [], [])

    def test_a_thumbnail_is_produced_and_reused(self):
        first = library.ensure_thumbnail(self.picture)
        self.assertIsNotNone(first)
        self.assertTrue(first.is_file())
        self.assertEqual(library.ensure_thumbnail(self.picture), first)

    def test_concurrent_callers_all_get_one(self):
        # Regression: the scratch filename used to be shared by every caller in
        # a process, so a canvas repaint and the picker's worker thumbnailing
        # the same file would delete each other's temporary and one would come
        # back None -- which the canvas then cached as a grey rectangle.
        for _ in range(5):
            library.thumbnail_path(self.picture).unlink(missing_ok=True)
            self.assertEqual(len(set(self._race(4))), 1)

    def _race(self, workers: int) -> list:
        results: list = []
        lock = threading.Lock()

        def work():
            got = library.ensure_thumbnail(self.picture)
            with lock:
                results.append(got)

        threads = [threading.Thread(target=work) for _ in range(workers)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertNotIn(None, results)
        return results

    def test_nothing_is_left_behind_in_the_cache(self):
        library.ensure_thumbnail(self.picture)
        cache = library.thumbnail_path(self.picture).parent
        leftovers = [p.name for p in cache.iterdir() if p.name.startswith(".")]
        self.assertEqual(leftovers, [])

    def test_a_file_that_is_not_a_picture_yields_nothing(self):
        junk = self.root / "notes.txt"
        junk.write_text("hello")
        self.assertIsNone(library.ensure_thumbnail(junk))

    def test_a_corrupt_picture_yields_nothing_rather_than_raising(self):
        broken = self.root / "broken.png"
        broken.write_bytes(b"not really a png")
        self.assertIsNone(library.ensure_thumbnail(broken))
