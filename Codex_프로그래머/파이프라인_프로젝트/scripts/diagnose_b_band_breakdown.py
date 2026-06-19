from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

import build_koppen_biome_terrain as kbt


SCALES = [10.0, 12.0]
BANDS = [
    ("tropical", 0.0, 23.5),
    ("subtropical", 23.5, 35.0),
    ("temperate", 35.0, 55.0),
    ("subpolar", 55.0, 66.5),
    ("polar", 66.5, float("inf")),
]


def band_for(latitude: float) -> str:
    abs_lat = abs(latitude)
    for name, low, high in BANDS:
        if low <= abs_lat < high:
            return name
    raise ValueError(f"latitude out of range: {latitude}")


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def make_args(defaults: dict[str, Path]) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=defaults["project_root"],
        rainfall_normalized=defaults["rainfall_normalized"],
        seasonal=defaults["seasonal"],
        hydrology=defaults["hydrology"],
        bootstrap=defaults["bootstrap"],
        province_graph=defaults["province_graph"],
        province_constraints=defaults["province_constraints"],
        province_overrides=defaults["province_overrides"],
        params=defaults["params"],
        terrain_lookup=defaults["terrain_lookup"],
        output=defaults["output"],
        debug_dir=defaults["debug_dir"],
        debug_image_dir=defaults["debug_image_dir"],
        pretty=False,
        debug=False,
        fail_on_warning=False,
    )


def main() -> int:
    defaults = kbt.default_paths()
    args = make_args(defaults)
    graph = kbt.climate.load_json(defaults["province_graph"], "province_graph.json")
    rainfall = kbt.climate.load_json(defaults["rainfall_normalized"], "rainfall_normalized.json")
    land_band = {
        color: band_for(float(province["latitude"]))
        for color, province in graph["provinces"].items()
        if not province.get("is_sea")
    }
    band_land_count = defaultdict(int)
    band_rainfall = defaultdict(list)
    for color, band in land_band.items():
        band_land_count[band] += 1
        band_rainfall[band].append(float(rainfall["provinces"][color]["final_rainfall"]))

    base_load_params = kbt.load_params
    rows: list[dict] = []
    try:
        for scale in SCALES:
            def patched_load_params(path: Path, scale: float = scale) -> dict:
                params = base_load_params(path)
                params["soil_moisture"]["et_world_scale"] = scale
                return params
            kbt.load_params = patched_load_params
            output, _ = kbt.build_output(args)
            b_counts = defaultdict(int)
            for color, values in output["provinces"].items():
                if str(values["koppen_class"]).startswith("B"):
                    b_counts[land_band[color]] += 1
            for band, _, _ in BANDS:
                land_count = band_land_count[band]
                rows.append({
                    "et_world_scale": scale,
                    "band": band,
                    "B_count": b_counts[band],
                    "band_land_count": land_count,
                    "B_pct_within_band": b_counts[band] / max(land_count, 1),
                })
    finally:
        kbt.load_params = base_load_params

    output_path = defaults["debug_dir"] / "b_class_band_breakdown.csv"
    write_csv(
        output_path,
        ["et_world_scale", "band", "B_count", "band_land_count", "B_pct_within_band"],
        rows,
    )

    print("B class band breakdown:")
    print("et_world_scale,band,B_count,band_land_count,B_pct_within_band")
    for row in rows:
        print(",".join(str(row[key]) for key in ["et_world_scale", "band", "B_count", "band_land_count", "B_pct_within_band"]))

    print("final_rainfall_mean by band:")
    print("band,land_count,final_rainfall_mean")
    for band, _, _ in BANDS:
        values = band_rainfall[band]
        print(f"{band},{len(values)},{mean(values) if values else 0.0}")
    print(f"wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
