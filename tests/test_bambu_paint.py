#!/usr/bin/env python3
"""Tests for bambu_paint: correct hex paint_color parsing, extruder decoding,
and filament-color mapping. These lock in the bug fix where the original tool's
decimal-only regex silently dropped every hex paint code (e.g. "0C")."""
import os
import unittest

import bambu_paint as bp

# A tiny synthetic object .model body covering the exact failure mode:
# - a pure-digit paint code ("8")  -> matched by the OLD decimal regex
# - a hex paint code ("0C")        -> SILENTLY DROPPED by the old regex
# - an unpainted triangle          -> base / object-default extruder
SYNTHETIC_MODEL = '''<mesh>
 <triangles>
  <triangle v1="0" v2="1" v3="2" paint_color="8"/>
  <triangle v1="1" v2="2" v3="3" paint_color="0C"/>
  <triangle v1="2" v2="3" v3="4" paint_color="0C"/>
  <triangle v1="3" v2="4" v3="5"/>
  <triangle v1="4" v2="5" v3="6" paint_color="8"/>
 </triangles>
</mesh>'''


class TestDecodePaintColor(unittest.TestCase):
    def test_unpainted_is_zero(self):
        self.assertEqual(bp.decode_paint_color(""), 0)
        self.assertEqual(bp.decode_paint_color(None), 0)

    def test_hex_codes_decode_to_extruder_index(self):
        # extruder = int(code, 16) >> 2  (1-based)
        self.assertEqual(bp.decode_paint_color("4"), 1)
        self.assertEqual(bp.decode_paint_color("8"), 2)
        self.assertEqual(bp.decode_paint_color("0C"), 3)   # hex letter — the old bug
        self.assertEqual(bp.decode_paint_color("C"), 3)    # leading-zero-insensitive
        self.assertEqual(bp.decode_paint_color("10"), 4)


class TestExtractGroups(unittest.TestCase):
    def test_no_triangles_dropped(self):
        groups = bp.extract_paint_groups(SYNTHETIC_MODEL)
        total = sum(len(v) for v in groups.values())
        self.assertEqual(total, 5, "every triangle must land in exactly one group")

    def test_groups_keyed_by_code_including_hex(self):
        groups = bp.extract_paint_groups(SYNTHETIC_MODEL)
        self.assertEqual(set(groups), {"8", "0C", ""})
        self.assertEqual(sorted(groups["8"]), [0, 4])
        self.assertEqual(sorted(groups["0C"]), [1, 2])
        self.assertEqual(groups[""], [3])


class TestColorAssignment(unittest.TestCase):
    BEE_FILAMENTS = ["#FFFFFF", "#FFFF00", "#000000", "#FF80C0"]

    def test_bee_codes_map_to_real_colors(self):
        groups = bp.extract_paint_groups(SYNTHETIC_MODEL)
        assigned = bp.assign_colors(groups, self.BEE_FILAMENTS, default_extruder=1)
        by_code = {g.code: g for g in assigned}
        self.assertEqual(by_code[""].color_hex.upper(), "#FFFFFF")    # base -> white
        self.assertEqual(by_code["8"].color_hex.upper(), "#FFFF00")   # yellow
        self.assertEqual(by_code["0C"].color_hex.upper(), "#000000")  # black
        self.assertEqual(by_code[""].extruder, 1)
        self.assertEqual(by_code["8"].extruder, 2)
        self.assertEqual(by_code["0C"].extruder, 3)


# Optional regression against the real 23 MB sample, if present. Skipped in CI/forks
# unless SAMPLE_3MF points at it (keeps the repo clean for forking).
SAMPLE = os.environ.get("SAMPLE_3MF")


@unittest.skipUnless(SAMPLE and os.path.exists(SAMPLE), "SAMPLE_3MF not set")
class TestRealBeeFile(unittest.TestCase):
    def test_all_triangles_accounted_and_three_groups(self):
        info = bp.analyze_3mf(SAMPLE)
        self.assertEqual(info.total_triangles, 1_498_890)
        counts = {g.code: g.face_count for g in info.groups}
        self.assertEqual(counts, {"": 317_770, "8": 544_360, "0C": 636_760})
        # nothing dropped:
        self.assertEqual(sum(counts.values()), info.total_triangles)

    def test_real_colors_resolved(self):
        info = bp.analyze_3mf(SAMPLE)
        by_code = {g.code: g for g in info.groups}
        self.assertEqual(by_code[""].color_hex.upper(), "#FFFFFF")
        self.assertEqual(by_code["8"].color_hex.upper(), "#FFFF00")
        self.assertEqual(by_code["0C"].color_hex.upper(), "#000000")
        # pink #FF80C0 is in the palette but never painted:
        self.assertIn("#FF80C0", [c.upper() for c in info.palette])
        self.assertNotIn("#FF80C0", [g.color_hex.upper() for g in info.groups])


if __name__ == "__main__":
    unittest.main(verbosity=2)
