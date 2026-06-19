from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import build_koppen_biome_terrain as kbt


SCALES = [5.0, 8.0, 10.0, 12.0, 15.0]
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


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    frac = position - lower
    return ordered[lower] * (1.0 - frac) + ordered[upper] * frac


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


def summarize_output(output: dict, graph: dict, scale: float) -> dict:
    rows = []
    for color, values in output["provinces"].items():
        latitude = float(graph["provinces"][color]["latitude"])
        rows.append({
            "band": band_for(latitude),
            "aridity_index": float(values["aridity_index"]),
            "koppen_group": str(values["koppen_class"])[0],
        })
    aridity = [row["aridity_index"] for row in rows]
    group_counts = Counter(row["koppen_group"] for row in rows)
    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)
    subtropical = by_band["subtropical"]
    tropical = by_band["tropical"]
    total = len(rows)
    return {
        "et_world_scale": scale,
        "aridity_p10": percentile(aridity, 10.0),
        "aridity_p25": percentile(aridity, 25.0),
        "aridity_p50": percentile(aridity, 50.0),
        "aridity_p75": percentile(aridity, 75.0),
        "aridity_p90": percentile(aridity, 90.0),
        "b_count": group_counts["B"],
        "b_ratio": group_counts["B"] / total,
        "subtropical_b_count": sum(1 for row in subtropical if row["koppen_group"] == "B"),
        "subtropical_b_ratio": sum(1 for row in subtropical if row["koppen_group"] == "B") / max(len(subtropical), 1),
        "tropical_aridity_mean": mean(row["aridity_index"] for row in tropical) if tropical else 0.0,
        "subtropical_aridity_mean": mean(row["aridity_index"] for row in subtropical) if subtropical else 0.0,
        "group_A_ratio": group_counts["A"] / total,
        "group_B_ratio": group_counts["B"] / total,
        "group_C_ratio": group_counts["C"] / total,
        "group_D_ratio": group_counts["D"] / total,
        "group_E_ratio": group_counts["E"] / total,
        "group_H_ratio": group_counts["H"] / total,
    }


def main() -> int:
    defaults = kbt.default_paths()
    base_args = make_args(defaults)
    graph = kbt.climate.load_json(defaults["province_graph"], "province_graph.json")
    base_load_params = kbt.load_params
    summaries = []
    try:
        for scale in SCALES:
            def patched_load_params(path: Path, scale: float = scale) -> dict:
                params = base_load_params(path)
                params["soil_moisture"]["et_world_scale"] = scale
                return params
            kbt.load_params = patched_load_params
            output, _ = kbt.build_output(base_args)
            summaries.append(summarize_output(output, graph, scale))
    finally:
        kbt.load_params = base_load_params
    out_path = defaults["debug_dir"] / "et_world_scale_grid.csv"
    fieldnames = [
        "et_world_scale",
        "aridity_p10", "aridity_p25", "aridity_p50", "aridity_p75", "aridity_p90",
        "b_count", "b_ratio",
        "subtropical_b_count", "subtropical_b_ratio",
        "tropical_aridity_mean", "subtropical_aridity_mean",
        "group_A_ratio", "group_B_ratio", "group_C_ratio", "group_D_ratio", "group_E_ratio", "group_H_ratio",
    ]
    write_csv(out_path, fieldnames, summaries)
    print("et_world_scale grid summary:")
    print(",".join(fieldnames))
    for row in summaries:
        print(",".join(str(row[field]) for field in fieldnames))
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
