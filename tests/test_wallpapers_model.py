import unittest

from displaywright.wallpapers.model import Config, Fit, Kind, Source, is_color, kind_for_path


class Kinds(unittest.TestCase):
    def test_pictures_and_videos_are_recognised_case_insensitively(self):
        self.assertIs(kind_for_path("/a/b.JPG"), Kind.IMAGE)
        self.assertIs(kind_for_path("/a/b.webp"), Kind.IMAGE)
        self.assertIs(kind_for_path("/a/b.MP4"), Kind.VIDEO)

    def test_anything_else_is_not_a_wallpaper(self):
        self.assertIsNone(kind_for_path("/a/notes.txt"))
        self.assertIsNone(kind_for_path("/a/no-suffix"))


class Colors(unittest.TestCase):
    def test_accepts_the_three_hex_lengths(self):
        for value in ("#abc", "#AABBCC", "#aabbccdd"):
            self.assertTrue(is_color(value), value)

    def test_rejects_everything_else(self):
        for value in ("abc", "#ab", "#gggggg", "", "rgb(0,0,0)"):
            self.assertFalse(is_color(value), value)


class SourceJson(unittest.TestCase):
    def test_round_trips_an_image(self):
        source = Source(kind=Kind.IMAGE, path="/w/a.png", fit=Fit.CENTER, backdrop="#112233")
        back = Source.from_json(source.to_json())
        self.assertEqual((back.kind, back.path, back.fit, back.backdrop),
                         (Kind.IMAGE, "/w/a.png", Fit.CENTER, "#112233"))

    def test_a_default_backdrop_is_not_written_out(self):
        source = Source(kind=Kind.IMAGE, path="/w/a.png", fit=Fit.FIT)
        self.assertNotIn("backdrop", source.to_json())

    def test_a_backdrop_is_only_written_for_fits_that_show_it(self):
        source = Source(kind=Kind.IMAGE, path="/w/a.png", fit=Fit.FILL, backdrop="#112233")
        self.assertNotIn("backdrop", source.to_json())

    def test_a_colour_needs_no_path(self):
        source = Source(kind=Kind.COLOR, color="#ff0000")
        back = Source.from_json(source.to_json())
        self.assertEqual((back.kind, back.color), (Kind.COLOR, "#ff0000"))

    def test_video_settings_survive(self):
        source = Source(kind=Kind.VIDEO, path="/w/a.mp4", mute=False, volume=0.4,
                        pause_when_covered=False)
        back = Source.from_json(source.to_json())
        self.assertEqual((back.mute, back.volume, back.pause_when_covered), (False, 0.4, False))

    def test_a_bad_entry_is_dropped_rather_than_raised_on(self):
        for entry in (None, 42, {}, {"kind": "hologram"}, {"kind": "image"},
                      {"kind": "color", "color": "puce"}):
            self.assertIsNone(Source.from_json(entry), entry)

    def test_an_unreadable_fit_falls_back_to_fill(self):
        source = Source.from_json({"kind": "image", "path": "/w/a.png", "fit": "diagonal"})
        self.assertIs(source.fit, Fit.FILL)

    def test_a_bad_backdrop_falls_back_to_black(self):
        source = Source.from_json({"kind": "image", "path": "/w/a.png", "backdrop": "puce"})
        self.assertEqual(source.backdrop, "#000000")


class ConfigResolution(unittest.TestCase):
    def setUp(self):
        self.pinned = Source(kind=Kind.IMAGE, path="/w/pinned.png")
        self.spanned = Source(kind=Kind.IMAGE, path="/w/spanned.png")

    def test_an_unclaimed_output_follows_the_theme(self):
        self.assertIsNone(Config().source_for("DP-1"))
        self.assertFalse(Config().is_pinned("DP-1"))

    def test_a_pinned_output_uses_its_own_source(self):
        cfg = Config(monitors={"DP-1": self.pinned})
        self.assertIs(cfg.source_for("DP-1"), self.pinned)
        self.assertIsNone(cfg.source_for("eDP-1"))

    def test_span_wins_over_every_pin(self):
        cfg = Config(monitors={"DP-1": self.pinned}, span=self.spanned)
        self.assertIs(cfg.source_for("DP-1"), self.spanned)
        # Even an output with no pin of its own is claimed by the span.
        self.assertIs(cfg.source_for("eDP-1"), self.spanned)

    def test_unpin_reports_whether_it_did_anything(self):
        cfg = Config(monitors={"DP-1": self.pinned})
        self.assertTrue(cfg.unpin("DP-1"))
        self.assertFalse(cfg.unpin("DP-1"))

    def test_copy_does_not_share_sources(self):
        cfg = Config(monitors={"DP-1": self.pinned}, span=self.spanned, folders=["/w"])
        clone = cfg.copy()
        clone.monitors["DP-1"].fit = Fit.TILE
        clone.span.path = "/w/other.png"
        clone.folders.append("/x")
        self.assertIs(cfg.monitors["DP-1"].fit, Fit.FILL)
        self.assertEqual(cfg.span.path, "/w/spanned.png")
        self.assertEqual(cfg.folders, ["/w"])

    def test_round_trips_through_json(self):
        cfg = Config(monitors={"DP-1": self.pinned}, span=self.spanned, folders=["/w"])
        back = Config.from_json(cfg.to_json())
        self.assertEqual(back.monitors["DP-1"].path, "/w/pinned.png")
        self.assertEqual(back.span.path, "/w/spanned.png")
        self.assertEqual(back.folders, ["/w"])

    def test_junk_in_the_monitors_table_is_skipped_not_fatal(self):
        cfg = Config.from_json(
            {"monitors": {"DP-1": {"kind": "image", "path": "/w/a.png"}, "eDP-1": "nonsense"}}
        )
        self.assertEqual(list(cfg.monitors), ["DP-1"])

    def test_a_non_object_config_is_empty_rather_than_an_error(self):
        self.assertEqual(Config.from_json(["not", "a", "config"]).monitors, {})
