#!/usr/bin/env python3
"""Tests for the pure helpers in bambu_solid: label smoothing + plate layout.
Needs numpy + scipy, so run inside the container image (not host stdlib)."""
import unittest
import numpy as np

import bambu_solid as bs


class TestSmoothLabels(unittest.TestCase):
    def test_lone_interior_voxel_flips_to_majority(self):
        filled = np.ones((5, 5, 5), bool)
        lab = np.ones((5, 5, 5), np.int32)
        lab[2, 2, 2] = 2  # a single stray label-2 voxel surrounded by label-1
        out = bs.smooth_labels(lab, filled, n_labels=2, iters=1)
        self.assertEqual(out[2, 2, 2], 1, "lone voxel should take the surrounding majority")
        self.assertTrue(np.all(out[filled] >= 1))

    def test_labels_zero_outside_filled(self):
        filled = np.zeros((4, 4, 4), bool)
        filled[1:3, 1:3, 1:3] = True
        lab = np.where(filled, 1, 0).astype(np.int32)
        out = bs.smooth_labels(lab, filled, n_labels=1, iters=2)
        self.assertTrue(np.all(out[~filled] == 0))
        self.assertTrue(np.all(out[filled] == 1))


def _placed_aabbs(footprints, trans):
    out = []
    for (mnx, mny, mxx, mxy), (dx, dy) in zip(footprints, trans):
        out.append((mnx + dx, mny + dy, mxx + dx, mxy + dy))
    return out


def _overlap(a, b, eps=1e-6):
    return (a[0] < b[2] - eps and b[0] < a[2] - eps and
            a[1] < b[3] - eps and b[1] < a[3] - eps)


class TestGridPositions(unittest.TestCase):
    def test_translations_make_non_overlapping_grid(self):
        # four 10x10 footprints at arbitrary original positions
        footprints = [(0, 0, 10, 10), (100, 0, 110, 10),
                      (0, 50, 10, 60), (-30, -30, -20, -20)]
        trans = bs.grid_positions(footprints, gap=2.0)
        self.assertEqual(len(trans), 4)
        placed = _placed_aabbs(footprints, trans)
        for i in range(len(placed)):
            for j in range(i + 1, len(placed)):
                self.assertFalse(_overlap(placed[i], placed[j]),
                                 f"items {i},{j} overlap after layout")

    def test_single_item_centered_at_origin_cell(self):
        trans = bs.grid_positions([(5, 5, 15, 15)], gap=1.0)
        dx, dy = trans[0]
        # footprint center (10,10) -> cell center (0,0)
        self.assertAlmostEqual(dx, -10.0)
        self.assertAlmostEqual(dy, -10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
