from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_province_graph.py"
SPEC = importlib.util.spec_from_file_location("build_province_graph", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProvinceGraphUnitTests(unittest.TestCase):
    def test_piecewise_latitude(self) -> None:
        world = {
            "latitude": {
                "north_latitude": 70.0,
                "south_latitude": -45.0,
                "equator_y": 4,
            }
        }
        self.assertEqual(MODULE.latitude_for_y(0, world, 10), 70.0)
        self.assertEqual(MODULE.latitude_for_y(4, world, 10), 0.0)
        self.assertEqual(MODULE.latitude_for_y(9, world, 10), -45.0)

    def test_default_map_hints(self) -> None:
        text = """
        wrap_x = yes
        sea_starts = { x000001 x000002 }
        lakes = { x000003 }
        """
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "default.map"
            path.write_text(text, encoding="utf-8")
            hints = MODULE.parse_default_map(path)
        self.assertTrue(hints["wrap_x"])
        self.assertEqual(hints["sea_starts"], {"x000001", "x000002"})
        self.assertEqual(hints["lake_starts"], {"x000003"})

    def test_wrap_x_adds_seam_adjacency(self) -> None:
        encoded = np.array(
            [
                [1, 3, 2],
                [3, 3, 2],
            ],
            dtype=np.int32,
        )
        colors = np.unique(encoded)
        without_wrap, _ = MODULE.aggregate_boundaries(encoded, colors, wrap_x=False)
        with_wrap, perimeter = MODULE.aggregate_boundaries(encoded, colors, wrap_x=True)
        self.assertNotIn(2, without_wrap.get(1, {}))
        self.assertEqual(with_wrap[1][2], 1)
        self.assertTrue(np.all(perimeter > 0))

    def test_sea_resolution_never_leaves_candidates(self) -> None:
        shared = {
            1: {2: 3},
            2: {1: 3, 3: 2},
            3: {2: 2, 4: 1},
            4: {3: 1},
        }
        resolved = MODULE.resolve_sea_set({1}, {1, 2, 3}, shared)
        self.assertEqual(resolved, {1, 2, 3})
        self.assertNotIn(4, resolved)


if __name__ == "__main__":
    unittest.main()
