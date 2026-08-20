"""Spanning one picture across the desk.

The geometry is the arrangement half's -- logical rectangles in Hyprland's
coordinate space -- which is the whole reason the two halves can agree about
where a display is.
"""

import unittest

from displaywright.model import Mode, MonitorState
from displaywright.wallpapers.span import coverage, offsets, span_box


def output(name, x, y, w, h, enabled=True):
    return MonitorState(name=name, mode=Mode(w, h, 60.0), x=x, y=y, enabled=enabled)


class BoundingBox(unittest.TestCase):
    def test_no_outputs_has_no_box(self):
        self.assertIsNone(span_box([]))

    def test_a_single_output_is_its_own_box(self):
        box = span_box([output("DP-1", 0, 0, 2560, 1440)])
        self.assertEqual((box.x, box.y, box.w, box.h), (0, 0, 2560, 1440))

    def test_negative_origins_are_included(self):
        box = span_box([output("eDP-1", 0, 56, 1600, 1000),
                        output("DP-1", 1600, -826, 2560, 1440)])
        self.assertEqual((box.x, box.y, box.w, box.h), (0, -826, 4160, 1882))

    def test_a_disabled_output_is_not_part_of_the_span(self):
        box = span_box([output("DP-1", 0, 0, 2560, 1440),
                        output("DP-2", 2560, 0, 1920, 1080, enabled=False)])
        self.assertEqual((box.x, box.y, box.w, box.h), (0, 0, 2560, 1440))


class Offsets(unittest.TestCase):
    def test_offsets_are_relative_to_the_box_origin(self):
        got = offsets([output("eDP-1", 0, 56, 1600, 1000),
                       output("DP-1", 1600, -826, 2560, 1440)])
        self.assertEqual(got, {"eDP-1": (0, 882), "DP-1": (1600, 0)})


class Coverage(unittest.TestCase):
    def test_a_flush_row_wastes_nothing(self):
        row = [output("A", 0, 0, 1920, 1080), output("B", 1920, 0, 1920, 1080)]
        self.assertAlmostEqual(coverage(row), 1.0)

    def test_a_staggered_pair_leaves_gaps(self):
        pair = [output("eDP-1", 0, 56, 1600, 1000), output("DP-1", 1600, -826, 2560, 1440)]
        # 1600*1000 + 2560*1440 = 5_286_400 of a 4160*1882 = 7_829_120 box.
        self.assertAlmostEqual(coverage(pair), 5_286_400 / 7_829_120)

    def test_overlapping_outputs_are_not_counted_twice(self):
        mirrored = [output("A", 0, 0, 1920, 1080), output("B", 0, 0, 1920, 1080)]
        self.assertAlmostEqual(coverage(mirrored), 1.0)

    def test_no_outputs_covers_nothing(self):
        self.assertEqual(coverage([]), 0.0)


if __name__ == "__main__":
    unittest.main()
