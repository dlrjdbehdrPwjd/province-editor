from __future__ import annotations

import sys
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import build_rainfall_normalization as rainfall


class RainfallNormalizationUnitTests(unittest.TestCase):
    def test_percentile_uses_average_rank_for_ties(self) -> None:
        result = rainfall.compute_percentiles({
            "x111111": 1.0,
            "x222222": 1.0,
            "x333333": 3.0,
        })
        self.assertAlmostEqual(result["x111111"], 0.25)
        self.assertAlmostEqual(result["x222222"], 0.25)
        self.assertAlmostEqual(result["x333333"], 1.0)

    def test_single_percentile_is_midpoint(self) -> None:
        self.assertEqual(rainfall.compute_percentiles({"x111111": 7.0}), {"x111111": 0.5})

    def test_final_rainfall_mixes_absolute_and_relative(self) -> None:
        params = rainfall.DEFAULT_PARAMS.copy()
        params["relative_weight"] = 0.7
        absolute, relative, final = rainfall.normalize_one(0.5, 0.8, params)
        self.assertAlmostEqual(absolute, 0.5)
        self.assertAlmostEqual(relative, 0.8)
        self.assertAlmostEqual(final, 0.71)

    def test_final_rainfall_clamps_absolute_and_final(self) -> None:
        params = rainfall.DEFAULT_PARAMS.copy()
        params["relative_weight"] = 0.0
        params["absolute_clamp_max"] = 1.5
        params["final_max"] = 1.0
        absolute, _, final = rainfall.normalize_one(100.0, 1.0, params)
        self.assertEqual(absolute, 1.5)
        self.assertEqual(final, 1.0)

    def test_zero_raw_percentile_can_be_zeroed_by_caller(self) -> None:
        params = rainfall.DEFAULT_PARAMS.copy()
        absolute, relative, final = rainfall.normalize_one(0.0, 0.5, params)
        self.assertGreater(final, 0.0)
        # Build step intentionally zeroes this case so normalization does not
        # invent rain for truly zero-rainfall provinces.

    def test_seasonal_sum_validation_accepts_rounding(self) -> None:
        output = {
            "provinces": {
                "x111111": {
                    "final_rainfall": 1.0,
                    "final_summer_rainfall": 0.33333333,
                    "final_winter_rainfall": 0.66666667,
                    "rainfall_percentile": 0.5,
                    "lake_fraction": 0.0,
                    "final_wet_season_rainfall": 0.66666667,
                    "final_dry_season_rainfall": 0.33333333,
                    "rainfall_absolute_scaled": 0.5,
                    "rainfall_relative_scaled": 0.5,
                    "dry_season_strength": 0.0,
                    "rainfall_seasonality": 0.0,
                    "corrected_ET": 0.0,
                    "river_bonus": 0.0,
                }
            }
        }
        rainfall.validate_output(output, ["x111111"], rainfall.DEFAULT_PARAMS.copy())


if __name__ == "__main__":
    unittest.main()
