from __future__ import annotations

import argparse
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import run_climate_pipeline as climate


def params() -> dict[str, dict]:
    return {
        "moisture_transport": copy.deepcopy(climate.DEFAULT_MOISTURE_PARAMS),
        "mountain_barrier": copy.deepcopy(climate.DEFAULT_BARRIER_PARAMS),
        "seasonal_climate": copy.deepcopy(climate.DEFAULT_SEASONAL_PARAMS),
    }


def graph_fixture() -> dict:
    return {
        "schema_version": climate.GRAPH_SCHEMA_VERSION,
        "metadata": {"hash": {"topology_hash": "sha256:" + "a" * 64}},
        "provinces": {
            "x111111": {"is_sea": False, "latitude": 20.0, "area_px": 90, "is_coastal": True, "coastal_ratio": 1.0},
            "x222222": {"is_sea": False, "latitude": 20.0, "area_px": 90, "is_coastal": False, "coastal_ratio": 0.0},
            "x333333": {"is_sea": True, "latitude": 20.0, "area_px": 90, "is_coastal": False, "coastal_ratio": 0.0},
        },
        "adjacency": {
            "x111111": {"x222222": {"border_weight": 1.0, "distance_px": 10.0, "direction": {"x": 1.0, "y": 0.0}}},
            "x222222": {"x111111": {"border_weight": 1.0, "distance_px": 10.0, "direction": {"x": -1.0, "y": 0.0}}},
            "x333333": {},
        },
    }


def bootstrap_fixture() -> dict:
    return {
        "schema_version": climate.BOOTSTRAP_SCHEMA_VERSION,
        "graph_hash": "sha256:" + "a" * 64,
        "constraints_hash": "sha256:" + "b" * 64,
        "params_hash": "sha256:" + "c" * 64,
        "provinces": {
            "x111111": {"synthetic_elevation_m": 0.0, "continentality": 0.0, "coast_distance_normalized": 0.0, "synthetic_flow_potential": 0.0, "is_flow_sink": False},
            "x222222": {"synthetic_elevation_m": 0.0, "continentality": 1.0, "coast_distance_normalized": 1.0, "synthetic_flow_potential": 1.0, "is_flow_sink": False},
        },
    }


class SeasonalClimateUnitTests(unittest.TestCase):
    def test_transport_survival_uses_physical_crossing_distance(self) -> None:
        survival = climate.compute_transport_survival(90.0, 500.0)
        self.assertAlmostEqual(survival, 0.981206, places=5)
        self.assertGreater(survival ** 35, 0.50)

    def test_transport_survival_is_stable_when_path_is_split(self) -> None:
        coarse = climate.compute_transport_survival(400.0, 500.0)
        split = climate.compute_transport_survival(100.0, 500.0) ** 2
        self.assertAlmostEqual(coarse, split, places=12)

    def test_dead_end_transport_conserves_flux_as_rainfall(self) -> None:
        graph = graph_fixture()
        graph["adjacency"]["x222222"] = {}
        land = ["x111111", "x222222"]
        overrides = {color: {"climate_lock": False, "force_temp": None, "force_moisture": None, "force_rainfall": None, "exclude_from_sim": False} for color in land}
        constraints = {color: {"temperature_delta": 0.0, "moisture_bonus": 0.0, "wetland_seed": False, "mountain_strength": 0.0} for color in land}
        result = climate.propagate_moisture(
            graph, land, {"x111111": 1.0, "x222222": 0.0},
            {color: 2.25 for color in land}, constraints, overrides,
            {color: (1.0, 0.0) for color in land},
            climate.DEFAULT_MOISTURE_PARAMS, climate.DEFAULT_BARRIER_PARAMS,
        )
        self.assertAlmostEqual(sum(result["rainfall"].values()), 1.0, places=8)
        self.assertTrue(result["transport_converged"])

    def test_transport_iteration_limit_is_warning_state_not_exception(self) -> None:
        graph = graph_fixture()
        land = ["x111111", "x222222"]
        overrides = {color: {"climate_lock": False, "force_temp": None, "force_moisture": None, "force_rainfall": None, "exclude_from_sim": False} for color in land}
        constraints = {color: {"temperature_delta": 0.0, "moisture_bonus": 0.0, "wetland_seed": False, "mountain_strength": 0.0} for color in land}
        moisture_cfg = copy.deepcopy(climate.DEFAULT_MOISTURE_PARAMS)
        moisture_cfg["max_transport_iterations"] = 1
        result = climate.propagate_moisture(
            graph, land, {"x111111": 1.0, "x222222": 0.0},
            {color: 2.25 for color in land}, constraints, overrides,
            {color: (1.0, 0.0) for color in land},
            moisture_cfg, climate.DEFAULT_BARRIER_PARAMS,
        )
        self.assertFalse(result["transport_converged"])
        self.assertEqual(result["transport_iterations"], 1)
        self.assertGreaterEqual(result["transport_residual_wave_max"], 0.0)

    def test_itcz_center_moves_between_global_seasons(self) -> None:
        july = climate.compute_itcz_weight(5.0, 5.0, 5.0)
        january = climate.compute_itcz_weight(5.0, -5.0, 5.0)
        self.assertGreater(july, january)

    def test_latitude_base_temperature_uses_cosine_insolation_curve(self) -> None:
        self.assertAlmostEqual(climate.compute_latitude_base_temperature(0.0, 24.0, -26.0), 24.0)
        self.assertAlmostEqual(climate.compute_latitude_base_temperature(90.0, 24.0, -26.0), -26.0)
        self.assertAlmostEqual(climate.compute_latitude_base_temperature(60.0, 24.0, -26.0), -1.0)
        self.assertAlmostEqual(climate.compute_latitude_base_temperature(45.0, 28.0, -20.0), 13.941125, places=5)

    def test_local_season_mapping_is_hemisphere_aware(self) -> None:
        graph = graph_fixture()
        graph["provinces"]["x222222"]["latitude"] = -20.0
        july, january = climate.map_local_temperatures_to_passes(
            graph, ["x111111", "x222222"],
            {"x111111": 30.0, "x222222": 30.0},
            {"x111111": 10.0, "x222222": 10.0},
        )
        self.assertEqual((july["x111111"], january["x111111"]), (30.0, 10.0))
        self.assertEqual((july["x222222"], january["x222222"]), (10.0, 30.0))

    def test_analytical_storage_uses_rainfall_scale(self) -> None:
        self.assertEqual(climate.compute_analytical_storage(1.0, 0.5, 5.0, 10.0), 2.5)
        self.assertEqual(climate.compute_analytical_storage(5.0, 0.0, 5.0, 10.0), 10.0)

    def test_vertical_motion_expected_latitude_signs(self) -> None:
        cfg = climate.DEFAULT_SEASONAL_PARAMS
        self.assertLess(climate.compute_vertical_motion(0.0, cfg), 0.0)
        self.assertGreater(climate.compute_vertical_motion(25.0, cfg), 0.0)
        self.assertLess(abs(climate.compute_vertical_motion(50.0, cfg)), 0.05)

    def test_wind_vector_flips_meridional_component_by_hemisphere(self) -> None:
        cfg = climate.DEFAULT_MOISTURE_PARAMS
        north = climate.compute_wind_vector(20.0, cfg)
        south = climate.compute_wind_vector(-20.0, cfg)
        self.assertAlmostEqual(north[0], south[0])
        self.assertAlmostEqual(north[1], -south[1])
        at_boundary = climate.compute_wind_vector(30.0, cfg)
        self.assertGreater(at_boundary[0], north[0])

    def test_fallback_yaml_supports_list_of_wind_band_mappings(self) -> None:
        parsed = climate.parse_simple_yaml(
            "moisture_transport:\n"
            "  wind_bands:\n"
            "    bands:\n"
            "      - name: test\n"
            "        lat_min: 0\n"
            "        lat_max: 90\n"
            "        direction: [1.0, 0.0]\n"
            "        directionality: 0.5\n"
        )
        band = parsed["moisture_transport"]["wind_bands"]["bands"][0]
        self.assertEqual(band["name"], "test")
        self.assertEqual(band["direction"], [1.0, 0.0])

    def test_barrier_creates_orographic_rain_and_reduces_passed_moisture(self) -> None:
        graph = graph_fixture()
        land = ["x111111", "x222222"]
        overrides = {color: {"climate_lock": False, "force_temp": None, "force_moisture": None, "force_rainfall": None, "exclude_from_sim": False} for color in land}
        flat = {color: {"temperature_delta": 0.0, "moisture_bonus": 0.0, "wetland_seed": False, "mountain_strength": 0.0} for color in land}
        mountain = copy.deepcopy(flat)
        mountain["x222222"]["mountain_strength"] = 1.0
        capacities = {color: 2.25 for color in land}
        winds = {color: (1.0, 0.0) for color in land}
        moisture_cfg = copy.deepcopy(climate.DEFAULT_MOISTURE_PARAMS)
        flat_result = climate.propagate_moisture(graph, land, {"x111111": 1.0, "x222222": 0.0}, capacities, flat, overrides, winds, moisture_cfg, climate.DEFAULT_BARRIER_PARAMS)
        mountain_result = climate.propagate_moisture(graph, land, {"x111111": 1.0, "x222222": 0.0}, capacities, mountain, overrides, winds, moisture_cfg, climate.DEFAULT_BARRIER_PARAMS)
        self.assertGreater(mountain_result["orographic_rain"]["x222222"], 0.0)
        self.assertLess(mountain_result["rainfall"]["x222222"] - mountain_result["orographic_rain"]["x222222"], flat_result["rainfall"]["x222222"] + 1e-9)

    def test_force_moisture_above_season_capacity_is_error(self) -> None:
        overrides = {"x111111": {"climate_lock": True, "force_moisture": 2.0}}
        with self.assertRaisesRegex(ValueError, "season capacity"):
            climate.validate_force_moisture(overrides, {"x111111": 1.0})

    def test_final_force_values_survive_itcz_and_drain(self) -> None:
        graph = graph_fixture()
        land = ["x111111", "x222222"]
        moisture = {color: 1.0 for color in land}
        rainfall = {color: 1.0 for color in land}
        overrides = {
            "x111111": {"climate_lock": True, "force_moisture": 0.4, "force_rainfall": 0.7, "exclude_from_sim": False},
            "x222222": {"climate_lock": False, "force_moisture": None, "force_rainfall": None, "exclude_from_sim": False},
        }
        climate.apply_vertical_motion(
            graph, land, moisture, rainfall, overrides,
            {"x111111": 1.0, "x222222": -1.0},
            {"x111111": 0.5, "x222222": 0.5},
            climate.DEFAULT_SEASONAL_PARAMS,
        )
        self.assertEqual(moisture["x111111"], 0.4)
        self.assertEqual(rainfall["x111111"], 0.7)

    def test_exclude_and_climate_lock_conflict_is_error(self) -> None:
        raw = {"x111111": {"exclude_from_sim": True, "climate_lock": True}}
        with self.assertRaisesRegex(ValueError, "exclude_from_sim"):
            climate.normalize_overrides(raw, ["x111111"])

    def test_load_mapping_document_accepts_schema_version_provinces_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "province_constraints.yaml"
            path.write_text(
                'schema_version: "province_constraints.v0.1"\n'
                "provinces:\n"
                "  x111111:\n"
                "    moisture_bonus: 0.2\n",
                encoding="utf-8",
            )
            loaded = climate.load_mapping_document(path, "province_constraints.yaml", "province_constraints")
        self.assertEqual(loaded, {"x111111": {"moisture_bonus": 0.2}})

    def test_load_mapping_document_accepts_empty_schema_version_provinces_wrapper(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "province_constraints.yaml"
            path.write_text(
                'schema_version: "province_constraints.v0.1"\n'
                "provinces: {}\n",
                encoding="utf-8",
            )
            loaded = climate.load_mapping_document(path, "province_constraints.yaml", "province_constraints")
        self.assertEqual(loaded, {})

    def test_water_balance_conserves_available_water(self) -> None:
        land = ["x111111"]
        overrides = {"x111111": {"exclude_from_sim": False}}
        et, runoff, storage, _ = climate.water_balance(land, {"x111111": 20.0}, {"x111111": 0.5}, {"x111111": 3.0}, {"x111111": 1.0}, {"x111111": 2.0}, overrides, climate.DEFAULT_SEASONAL_PARAMS)
        self.assertLessEqual(et["x111111"], 5.0)
        self.assertAlmostEqual(et["x111111"] + runoff["x111111"] + storage["x111111"], 5.0)

    def test_end_to_end_output_is_land_only_and_seasonal_sums_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            graph_path = root / "graph.json"
            bootstrap_path = root / "bootstrap.json"
            constraints_path = root / "constraints.yaml"
            overrides_path = root / "overrides.yaml"
            params_path = root / "rules.yaml"
            world_path = root / "world.yaml"
            graph_path.write_text(json.dumps(graph_fixture()), encoding="utf-8")
            bootstrap_path.write_text(json.dumps(bootstrap_fixture()), encoding="utf-8")
            constraints_path.write_text('schema_version: "province_constraints.v0.1"\nprovinces: {}\n', encoding="utf-8")
            overrides_path.write_text('schema_version: "province_overrides.v0.1"\nprovinces: {}\n', encoding="utf-8")
            params_path.write_text('seasonal_climate:\n  max_spinup_years: 3\n', encoding="utf-8")
            world_path.write_text('climate_reference:\n  equator_temp_c: 28\n  pole_temp_c: -20\n  lapse_rate_c_per_km: 6.5\n', encoding="utf-8")
            args = argparse.Namespace(project_root=root, province_graph=graph_path, bootstrap_fields=bootstrap_path, province_constraints=constraints_path, province_overrides=overrides_path, params=params_path, world=world_path, max_spinup_years=50, allow_nonconverged=False)
            output, _ = climate.build_seasonal_climate(args)
            self.assertEqual(output["schema_version"], "seasonal_climate.v0.4.1")
            self.assertEqual(set(output["provinces"]), {"x111111", "x222222"})
            self.assertEqual(output["spinup"]["max_years"], 50)
            self.assertIn("climate_converged", output["spinup"])
            self.assertIn("transport_converged", output["spinup"])
            for values in output["provinces"].values():
                self.assertAlmostEqual(values["annual_rainfall_raw"], values["summer_rainfall_raw"] + values["winter_rainfall_raw"], places=8)
                self.assertGreaterEqual(values["summer_temperature"], values["winter_temperature"])
            self.assertTrue(any(values["rainfall_seasonality"] > 0.0 for values in output["provinces"].values()))


if __name__ == "__main__":
    unittest.main()
