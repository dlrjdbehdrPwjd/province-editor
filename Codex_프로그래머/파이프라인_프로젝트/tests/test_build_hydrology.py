from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_hydrology as hydrology


def graph_fixture() -> dict:
    return {
        "schema_version": hydrology.GRAPH_SCHEMA_VERSION,
        "metadata": {"source_files": {"provinces_png": "missing.png"}},
        "provinces": {
            "x111111": {"is_sea": False, "area_px": 10},
            "x222222": {"is_sea": False, "area_px": 10},
            "x333333": {"is_sea": False, "area_px": 10},
            "x444444": {"is_sea": True, "area_px": 10},
        },
        "adjacency": {
            "x111111": {
                "x222222": {"distance_px": 1.0, "shared_border_px": 5},
                "x444444": {"distance_px": 1.0, "shared_border_px": 5},
            },
            "x222222": {
                "x111111": {"distance_px": 1.0, "shared_border_px": 5},
                "x333333": {"distance_px": 1.0, "shared_border_px": 5},
            },
            "x333333": {
                "x222222": {"distance_px": 1.0, "shared_border_px": 5},
            },
            "x444444": {},
        },
    }


def bootstrap_fixture() -> dict:
    return {
        "schema_version": hydrology.BOOTSTRAP_SCHEMA_VERSION,
        "provinces": {
            "x111111": {"synthetic_flow_potential": 0.3, "is_flow_sink": False},
            "x222222": {"synthetic_flow_potential": 0.2, "is_flow_sink": False},
            "x333333": {"synthetic_flow_potential": 0.1, "is_flow_sink": False},
        },
    }


class HydrologyUnitTests(unittest.TestCase):
    def test_flow_prefers_lower_land_before_sea_outlet(self) -> None:
        land = ["x111111", "x222222", "x333333"]
        constraints = {color: {"lake_seed": False} for color in land}
        flow, sinks, warnings = hydrology.build_flow_direction(graph_fixture(), bootstrap_fixture(), land, constraints)
        self.assertEqual(flow["x111111"], "x222222")
        self.assertEqual(flow["x222222"], "x333333")
        self.assertTrue(sinks["x333333"])
        self.assertIn("natural pit detected: x333333", warnings)

    def test_river_path_cycle_is_error(self) -> None:
        flow = {"x111111": "x222222", "x222222": "x111111"}
        with self.assertRaisesRegex(ValueError, "cycle"):
            hydrology.topological_sort_flow(flow, ["x111111", "x222222"])

    def test_zero_threshold_does_not_mark_everything_river(self) -> None:
        land = ["x111111", "x222222"]
        graph = graph_fixture()
        bootstrap = bootstrap_fixture()
        seasonal = {
            "provinces": {
                "x111111": {
                    "annual_rainfall_raw": 0.0,
                    "annual_runoff": 0.0,
                    "soil_water_storage_final": 0.0,
                    "annual_ET": 0.0,
                    "summer_temperature": 10.0,
                    "winter_temperature": 0.0,
                },
                "x222222": {
                    "annual_rainfall_raw": 0.0,
                    "annual_runoff": 0.0,
                    "soil_water_storage_final": 0.0,
                    "annual_ET": 0.0,
                    "summer_temperature": 10.0,
                    "winter_temperature": 0.0,
                },
            }
        }
        constraints = {
            "x111111": {"river_seed": False, "river_major": False, "lake_seed": False, "wetland_seed": False},
            "x222222": {"river_seed": True, "river_major": False, "lake_seed": False, "wetland_seed": False},
        }
        overrides = {color: {"exclude_from_sim": False} for color in land}
        classified, _ = hydrology.classify_hydrology(
            graph, bootstrap, seasonal, land, constraints, overrides,
            hydrology.DEFAULT_HYDROLOGY_PARAMS, {"pet_coefficient": 0.1},
            {"x111111": "x222222", "x222222": None},
            {"x111111": False, "x222222": True},
            {"x111111": 0.0, "x222222": 0.0},
            set(),
        )
        self.assertFalse(classified["is_river"]["x111111"])
        self.assertTrue(classified["is_river"]["x222222"])

    def test_effective_runoff_uses_surplus_saturation_and_dryness(self) -> None:
        seasonal = {
            "provinces": {
                "x111111": {
                    "annual_rainfall_raw": 2.0,
                    "annual_ET": 1.0,
                    "soil_water_storage_final": 5.0,
                    "dry_season_strength": 0.5,
                }
            }
        }
        value = hydrology.compute_effective_runoff(
            "x111111",
            seasonal,
            hydrology.DEFAULT_HYDROLOGY_PARAMS,
            {"storage_capacity": 10.0},
        )
        self.assertAlmostEqual(value, 0.275)

    def test_zero_annual_runoff_falls_back_to_effective_runoff_not_rainfall(self) -> None:
        seasonal = {
            "provinces": {
                "x111111": {
                    "annual_runoff": 0.0,
                    "annual_rainfall_raw": 2.0,
                    "annual_ET": 1.0,
                    "soil_water_storage_final": 0.0,
                    "dry_season_strength": 0.0,
                }
            }
        }
        water, source = hydrology.build_local_water(
            seasonal,
            ["x111111"],
            hydrology.DEFAULT_HYDROLOGY_PARAMS,
            {"storage_capacity": 10.0},
        )
        self.assertEqual(source, "effective_runoff_proxy")
        self.assertAlmostEqual(water["x111111"], 0.1)


if __name__ == "__main__":
    unittest.main()
