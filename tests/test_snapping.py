import unittest

from hyprlayout.model import Mode, MonitorState, Rect
from hyprlayout.snapping import (
    SNAP_THRESHOLD,
    auto_arrange,
    normalize,
    push_out,
    snap_and_resolve,
    snap_position,
    validate,
)


def monitor(name, w, h, x=0, y=0, scale=1.0, enabled=True):
    return MonitorState(
        name=name,
        mode=Mode(w, h, 60.0),
        x=x,
        y=y,
        scale=scale,
        enabled=enabled,
        available_modes=[Mode(w, h, 60.0)],
    )


class SnapTests(unittest.TestCase):
    def setUp(self):
        self.anchor = Rect(0, 0, 1600, 1000)

    def test_snaps_to_right_edge_and_top(self):
        dropped = Rect(1650, 40, 3440, 1440)
        result = snap_position(dropped, [self.anchor])
        self.assertEqual((result.x, result.y), (1600, 0))
        self.assertIn(("v", 1600.0), result.guides)

    def test_snaps_to_left_side(self):
        dropped = Rect(-3400, 10, 3440, 1440)
        result = snap_position(dropped, [self.anchor])
        self.assertEqual(result.x, -3440)

    def test_centre_alignment_is_available(self):
        dropped = Rect(500, 1030, 600, 400)  # below, roughly centred
        result = snap_position(dropped, [self.anchor])
        self.assertEqual((result.x, result.y), (500, 1000))

    def test_far_away_is_left_alone(self):
        dropped = Rect(9000, 9000, 800, 600)
        result = snap_position(dropped, [self.anchor])
        self.assertEqual((result.x, result.y), (9000, 9000))
        self.assertEqual(result.guides, [])

    def test_threshold_boundary(self):
        dropped = Rect(1600 + SNAP_THRESHOLD + 1, 0, 800, 600)
        self.assertNotEqual(snap_position(dropped, [self.anchor]).x, 1600)

    def test_no_neighbours_means_no_snap(self):
        result = snap_position(Rect(37, 42, 800, 600), [])
        self.assertEqual((result.x, result.y), (37, 42))


class PushOutTests(unittest.TestCase):
    def test_overlap_resolves_along_shortest_axis(self):
        other = Rect(0, 0, 1600, 1000)
        moving = Rect(1500, 0, 800, 600)  # 100px into the anchor on the left
        self.assertEqual(push_out(moving, [other]), (1600, 0))

    def test_snap_and_resolve_never_overlaps(self):
        a = Rect(0, 0, 1600, 1000)
        b = Rect(1600, 0, 800, 600)
        result = snap_and_resolve(Rect(1580, 20, 800, 600), [a, b])
        placed = Rect(result.x, result.y, 800, 600)
        self.assertFalse(placed.overlaps(a))
        self.assertFalse(placed.overlaps(b))

    def test_touching_edges_do_not_count_as_overlap(self):
        self.assertFalse(Rect(0, 0, 100, 100).overlaps(Rect(100, 0, 100, 100)))


class LayoutOpTests(unittest.TestCase):
    def test_normalize_moves_bounding_box_to_origin(self):
        states = [monitor("A", 1920, 1080, x=-500, y=-200), monitor("B", 1920, 1080, x=1420, y=-200)]
        self.assertTrue(normalize(states))
        self.assertEqual((states[0].x, states[0].y), (0, 0))
        self.assertEqual((states[1].x, states[1].y), (1920, 0))
        self.assertFalse(normalize(states))

    def test_normalize_ignores_disabled_outputs(self):
        states = [monitor("A", 1920, 1080, x=0), monitor("B", 1920, 1080, x=-9000, enabled=False)]
        self.assertFalse(normalize(states))

    def test_auto_arrange_packs_left_to_right_and_centres(self):
        states = [
            monitor("A", 3200, 2000, x=0, scale=2.0),   # logical 1600x1000
            monitor("B", 3440, 1440, x=5000),
        ]
        auto_arrange(states)
        self.assertEqual((states[0].x, states[0].y), (0, 220))
        self.assertEqual((states[1].x, states[1].y), (1600, 0))


class ValidateTests(unittest.TestCase):
    def test_clean_layout_has_no_problems(self):
        states = [monitor("A", 1600, 1000), monitor("B", 3440, 1440, x=1600)]
        self.assertEqual(validate(states), [])

    def test_overlap_reported(self):
        states = [monitor("A", 1600, 1000), monitor("B", 1600, 1000, x=800)]
        self.assertTrue(any("overlap" in p for p in validate(states)))

    def test_gap_reported_as_unreachable(self):
        states = [monitor("A", 1600, 1000), monitor("B", 1600, 1000, x=4000)]
        self.assertTrue(any("cannot reach" in p for p in validate(states)))

    def test_all_disabled_reported(self):
        states = [monitor("A", 1600, 1000, enabled=False)]
        problems = validate(states)
        self.assertEqual(len(problems), 1)
        self.assertIn("disabled", problems[0])

    def test_bad_mirror_target_reported(self):
        states = [monitor("A", 1600, 1000)]
        states[0].mirror_of = "DP-9"
        self.assertTrue(any("unknown output" in p for p in validate(states)))

    def test_vertical_stack_is_connected(self):
        states = [monitor("A", 1920, 1080), monitor("B", 1920, 1080, y=1080)]
        self.assertEqual(validate(states), [])

    def test_diagonal_corner_touch_is_not_connected(self):
        states = [monitor("A", 1920, 1080), monitor("B", 1920, 1080, x=1920, y=1080)]
        self.assertTrue(any("cannot reach" in p for p in validate(states)))


if __name__ == "__main__":
    unittest.main()
