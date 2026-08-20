import unittest

from displaywright.wallpapers.model import Fit
from displaywright.wallpapers.preview import fitted_rect, natural_size, span_rect


class FittedRect(unittest.TestCase):
    box = (1600.0, 1000.0)

    def test_stretch_takes_the_whole_box(self):
        self.assertEqual(fitted_rect(Fit.STRETCH, (400, 300), self.box), (0, 0, 1600, 1000))

    def test_fill_covers_and_crops_the_overflow(self):
        x, y, w, h = fitted_rect(Fit.FILL, (1000, 1000), self.box)
        self.assertEqual((w, h), (1600, 1600))
        self.assertEqual(x, 0)
        # Square picture on a 16:10 box: the top and bottom are cut off evenly.
        self.assertEqual(y, -300)

    def test_fit_contains_and_letterboxes(self):
        x, y, w, h = fitted_rect(Fit.FIT, (1000, 1000), self.box)
        self.assertEqual((w, h), (1000, 1000))
        self.assertEqual((x, y), (300, 0))

    def test_fill_and_fit_agree_when_the_aspect_matches(self):
        image = (3200, 2000)
        self.assertEqual(
            fitted_rect(Fit.FILL, image, self.box), fitted_rect(Fit.FIT, image, self.box)
        )

    def test_centre_is_device_pixel_exact(self):
        # A 3200x2000 file on a 200%-scaled 1600x1000 panel covers it exactly,
        # because 3200 device pixels *are* the panel.
        self.assertEqual(fitted_rect(Fit.CENTER, (3200, 2000), self.box, dpr=2), (0, 0, 1600, 1000))

    def test_centre_at_dpr_one_leaves_a_margin(self):
        x, y, w, h = fitted_rect(Fit.CENTER, (800, 600), self.box, dpr=1)
        self.assertEqual((w, h), (800, 600))
        self.assertEqual((x, y), (400, 200))

    def test_tile_reports_one_tile_from_the_origin(self):
        self.assertEqual(fitted_rect(Fit.TILE, (256, 256), self.box, dpr=2), (0, 0, 128, 128))

    def test_degenerate_sizes_do_not_divide_by_zero(self):
        self.assertEqual(fitted_rect(Fit.FILL, (0, 0), self.box), (0, 0, 1600, 1000))


class NaturalSize(unittest.TestCase):
    def test_scales_down_by_the_device_pixel_ratio(self):
        self.assertEqual(natural_size((3200, 2000), 2), (1600, 1000))

    def test_a_zero_ratio_is_treated_as_one(self):
        self.assertEqual(natural_size((800, 600), 0), (800, 600))


class SpanRect(unittest.TestCase):
    # The layout this was written on: a 200%-scaled laptop panel at 0,56 and a
    # 2560x1440 display at 1600,-826. Bounding box 4160x1882.
    box = (4160.0, 1882.0)

    def test_each_output_shifts_the_same_picture(self):
        image = (4160.0, 1882.0)
        laptop = span_rect(image, self.box, (0, 882))
        external = span_rect(image, self.box, (1600, 0))
        self.assertEqual(laptop, (0, -882, 4160, 1882))
        self.assertEqual(external, (-1600, 0, 4160, 1882))

    def test_the_picture_covers_the_whole_bounding_box(self):
        _, _, w, h = span_rect((1000, 1000), self.box, (0, 0))
        self.assertGreaterEqual(w, self.box[0])
        self.assertGreaterEqual(h, self.box[1])
