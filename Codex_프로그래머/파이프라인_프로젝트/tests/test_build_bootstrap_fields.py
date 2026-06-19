from __future__ import annotations

import argparse
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "build_bootstrap_fields.py"
SPEC = importlib.util.spec_from_file_location("build_bootstrap_fields", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_graph() -> dict:
    provinces = {
        "x000001": {
            "is_sea": False,
            "is_coastal": True,
            "center": {"x": 0.0, "y": 0.0},
        },
        "x000002": {
            "is_sea": False,
            "is_coastal": False,
            "center": {"x": 1.0, "y": 0.0},
        },
        "x000003": {
            "is_sea": False,
            "is_coastal": False,
            "center": {"x": 2.0, "y": 0.0},
        },
        "x000004": {
            "is_sea": False,
            "is_coastal": False,
            "center": {"x": 4.0, "y": 0.0},
        },
        "x0000FF": {
            "is_sea": True,
            "is_coastal": False,
            "center": {"x": 0.0, "y": 1.0},
        },
    }
    adjacency = {
        "x000001": {"x000002": {}, "x0000FF": {}},
        "x000002": {"x000001": {}, "x000003": {}},
        "x000003": {"x000002": {}, "x0000FF": {}},
        "x000004": {"x0000FF": {}},
        "x0000FF": {"x000001": {}, "x000003": {}, "x000004": {}},
    }
    return {
        "schema_version": "province_graph.v0.2",
        "metadata": {
            "hash": {
                "topology_hash": "sha256:" + "1" * 64,
                "heightmap_stats_hash": None,
            },
            "heightmap": {"authoritative": False},
            "world": {"width_px": 5, "height_px": 2},
        },
        "provinces": provinces,
        "adjacency": adjacency,
    }


class BootstrapFieldsUnitTests(unittest.TestCase):
    def test_fallback_yaml_parses_inline_empty_collections(self) -> None:
        parsed = MODULE.parse_simple_yaml(
            "province_constraints: {}\nriver_path: []\n"
        )
        self.assertEqual(parsed["province_constraints"], {})
        self.assertEqual(parsed["river_path"], [])

    def test_params_loader_isolates_bootstrap_section(self) -> None:
        text = (
            "unrelated:\n"
            "  items:\n"
            "    - name: unsupported_by_fallback\n"
            "      value: 1\n"
            "bootstrap_fields:\n"
            "  mountain_average_elevation_m: 1700\n"
            "  mountain_flow_bonus: 0.4\n"
            "  max_coast_distance_hops: auto\n"
            "after_section:\n"
            "  ignored: true\n"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "climate_rules.yaml"
            path.write_text(text, encoding="utf-8")
            params = MODULE.load_bootstrap_params(path)
        self.assertEqual(params["mountain_average_elevation_m"], 1700.0)
        self.assertEqual(params["mountain_flow_bonus"], 0.4)
        self.assertEqual(params["max_coast_distance_hops"], "auto")

    def test_land_only_bfs_does_not_cross_sea(self) -> None:
        graph = make_graph()
        land = MODULE.build_land_targets(graph)
        distance, unreachable, coastal = MODULE.compute_coast_distance(graph, land)
        self.assertEqual(distance["x000001"], 0)
        self.assertEqual(distance["x000002"], 1)
        self.assertEqual(distance["x000003"], 2)
        self.assertNotIn("x000004", distance)
        self.assertEqual(unreachable, ["x000004"])
        self.assertEqual(coastal, ["x000001"])

    def test_coast_distance_normalization_auto_and_configured(self) -> None:
        land = {"x000001", "x000002", "x000003", "x000004"}
        distance = {"x000001": 0, "x000002": 1, "x000003": 2}
        automatic, auto_max = MODULE.normalize_coast_distance(
            distance, land, {"max_coast_distance_hops": "auto"}
        )
        self.assertEqual(auto_max, 2.0)
        self.assertEqual(automatic["x000001"], 0.0)
        self.assertEqual(automatic["x000002"], 0.5)
        self.assertEqual(automatic["x000003"], 1.0)
        self.assertEqual(automatic["x000004"], 1.0)

        configured, configured_max = MODULE.normalize_coast_distance(
            distance, land, {"max_coast_distance_hops": 4}
        )
        self.assertEqual(configured_max, 4.0)
        self.assertEqual(configured["x000003"], 0.5)
        self.assertEqual(configured["x000004"], 1.0)

        all_coastal, zero_max = MODULE.normalize_coast_distance(
            {"x000001": 0}, {"x000001"}, {"max_coast_distance_hops": "auto"}
        )
        self.assertEqual(zero_max, 0.0)
        self.assertEqual(all_coastal["x000001"], 0.0)

    def test_constraint_defaults_and_relevant_fields_only(self) -> None:
        graph = make_graph()
        raw = {
            "x000001": {
                "mountain_strength": 0.5,
                "elevation_hint": "highland",
                "lake_seed": True,
                "river_seed": True,
            },
            "xFFFFFF": {"mountain_strength": 0.0},
        }
        normalized, warnings, counts = MODULE.normalize_constraints(raw, graph)
        self.assertEqual(
            normalized["x000001"],
            {
                "mountain_strength": 0.5,
                "elevation_hint": "highland",
                "lake_seed": True,
            },
        )
        self.assertEqual(normalized["x000002"]["elevation_hint"], "none")
        self.assertEqual(counts, {"provided": 2, "missing": 4, "unknown": 1})
        self.assertEqual(len(warnings), 2)

    def test_invalid_mountain_strength_is_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "0.0..1.0"):
            MODULE.normalize_constraints(
                {"x000001": {"mountain_strength": 1.1}}, make_graph()
            )

    def test_synthetic_formulas_and_flow_sink(self) -> None:
        graph = make_graph()
        normalized, _, _ = MODULE.normalize_constraints(
            {
                "x000001": {
                    "mountain_strength": 0.5,
                    "elevation_hint": "highland",
                    "lake_seed": True,
                }
            },
            graph,
        )
        params = dict(MODULE.DEFAULT_PARAMS)
        land = {"x000001"}
        elevation = MODULE.compute_synthetic_elevation(normalized, params, graph, land)
        flow = MODULE.compute_synthetic_flow_potential(
            {"x000001": 0.25}, normalized, params
        )
        sinks = MODULE.compute_is_flow_sink(normalized, land)
        self.assertEqual(elevation["x000001"], 1200.0)
        self.assertEqual(flow["x000001"], 0.85)
        self.assertTrue(sinks["x000001"])

    def test_constraints_hash_ignores_non_bootstrap_fields(self) -> None:
        graph = make_graph()
        first, _, _ = MODULE.normalize_constraints(
            {"x000001": {"mountain_strength": 0.5, "river_seed": True}}, graph
        )
        second, _, _ = MODULE.normalize_constraints(
            {"x000001": {"mountain_strength": 0.5, "river_seed": False}}, graph
        )
        land = MODULE.build_land_targets(graph)
        self.assertEqual(
            MODULE.compute_constraints_hash(first, land),
            MODULE.compute_constraints_hash(second, land),
        )

    def test_end_to_end_output_excludes_sea(self) -> None:
        graph = make_graph()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            graph_path = root / "province_graph.json"
            constraints_path = root / "province_constraints.yaml"
            params_path = root / "climate_rules.yaml"
            graph_path.write_text(json.dumps(graph), encoding="utf-8")
            constraints_path.write_text(
                "schema_version: province_constraints.v0.2\n"
                "province_constraints:\n"
                "  x000001:\n"
                "    mountain_strength: 0.5\n"
                "    elevation_hint: highland\n"
                "    lake_seed: true\n",
                encoding="utf-8",
            )
            params_path.write_text(
                "bootstrap_fields:\n"
                "  mountain_average_elevation_m: 1500\n"
                "  mountain_flow_bonus: 0.5\n"
                "  max_coast_distance_hops: auto\n",
                encoding="utf-8",
            )
            args = argparse.Namespace(
                project_root=root,
                province_graph=graph_path,
                province_constraints=constraints_path,
                params=params_path,
            )
            fields, diagnostics = MODULE.build_bootstrap_fields(args)

        self.assertEqual(fields["schema_version"], "bootstrap_fields.v0.1")
        self.assertNotIn("x0000FF", fields["provinces"])
        self.assertEqual(len(fields["provinces"]), 4)
        self.assertTrue(fields["provinces"]["x000001"]["is_flow_sink"])
        self.assertEqual(
            fields["provinces"]["x000001"]["synthetic_elevation_m"], 1200.0
        )
        self.assertEqual(diagnostics["report"]["counts"]["unreachable_land"], 1)


if __name__ == "__main__":
    unittest.main()
