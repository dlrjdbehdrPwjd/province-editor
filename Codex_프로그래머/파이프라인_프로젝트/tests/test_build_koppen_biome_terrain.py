from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_koppen_biome_terrain as kbt


class KoppenBiomeTerrainUnitTests(unittest.TestCase):
    def test_scale_hydro_computes_aridity_and_soil_moisture(self) -> None:
        params = kbt.DEFAULT_PARAMS
        et, rb, aridity, soil = kbt.scale_hydro(0.8, 0.4, 0.1, 0.0, False, params)
        self.assertEqual(et, 0.4)
        self.assertEqual(rb, 0.1)
        self.assertAlmostEqual(aridity, 2.0)
        self.assertAlmostEqual(soil, 0.75)

    def test_koppen_dry_priority_before_temperature_groups(self) -> None:
        params = kbt.DEFAULT_PARAMS
        values = {
            "final_rainfall": 0.1,
            "final_summer_rainfall": 0.05,
            "final_winter_rainfall": 0.05,
            "final_dry_season_rainfall": 0.05,
            "dry_season_strength": 0.0,
            "mean_temperature": 25.0,
            "summer_temperature": 30.0,
            "winter_temperature": 20.0,
        }
        self.assertEqual(kbt.classify_koppen(values, 0.1, params), "BWh")

    def test_koppen_tropical_subtypes(self) -> None:
        params = kbt.DEFAULT_PARAMS
        base = {
            "final_rainfall": 1.0,
            "final_summer_rainfall": 0.5,
            "final_winter_rainfall": 0.5,
            "final_dry_season_rainfall": 0.2,
            "mean_temperature": 25.0,
            "summer_temperature": 28.0,
            "winter_temperature": 20.0,
        }
        values = {**base, "dry_season_strength": 0.1}
        self.assertEqual(kbt.classify_koppen(values, 2.0, params), "Af")
        values = {**base, "dry_season_strength": 0.8}
        self.assertEqual(kbt.classify_koppen(values, 2.0, params), "Am")
        values = {**base, "dry_season_strength": 0.8, "final_dry_season_rainfall": 0.01}
        self.assertEqual(kbt.classify_koppen(values, 2.0, params), "Aw")

    def test_terrain_lookup_priority_and_ambiguity(self) -> None:
        rows = [
            {"priority": 10, "koppen_class": "*", "biome_physical": "*", "elevation_class": "*", "soil_moisture_min": 0.0, "soil_moisture_max": 1.5, "vic3_terrain": "plains", "line_no": 1},
            {"priority": 20, "koppen_class": "Af", "biome_physical": "rainforest", "elevation_class": "*", "soil_moisture_min": 0.0, "soil_moisture_max": 1.5, "vic3_terrain": "jungle", "line_no": 2},
        ]
        terrain, priority = kbt.match_terrain(rows, "Af", "rainforest", "lowland", 0.5)
        self.assertEqual((terrain, priority), ("jungle", 20))
        rows.append({"priority": 20, "koppen_class": "Af", "biome_physical": "rainforest", "elevation_class": "*", "soil_moisture_min": 0.0, "soil_moisture_max": 1.5, "vic3_terrain": "forest", "line_no": 3})
        with self.assertRaisesRegex(ValueError, "multiple"):
            kbt.match_terrain(rows, "Af", "rainforest", "lowland", 0.5)

    def test_hydrology_overlay_desert_river_corridor_only(self) -> None:
        params = kbt.DEFAULT_PARAMS
        biome, overlay = kbt.physical_biome(
            "hot_desert",
            {"is_lake": False, "is_salt_flat": False, "is_wetland": False, "is_river": True},
            0.5,
            params,
        )
        self.assertEqual((biome, overlay), ("river_corridor", "river_corridor"))
        biome, overlay = kbt.physical_biome(
            "temperate_forest",
            {"is_lake": False, "is_salt_flat": False, "is_wetland": False, "is_river": True},
            0.5,
            params,
        )
        self.assertEqual((biome, overlay), ("temperate_forest", "river_corridor"))


if __name__ == "__main__":
    unittest.main()
