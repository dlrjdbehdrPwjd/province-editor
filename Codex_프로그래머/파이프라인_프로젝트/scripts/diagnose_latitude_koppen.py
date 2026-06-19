from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GRAPH_PATH = PROJECT_ROOT / "cache" / "province_graph.json"
SEASONAL_PATH = PROJECT_ROOT / "cache" / "seasonal_climate.json"
KOPPEN_PATH = PROJECT_ROOT / "cache" / "koppen_biome_terrain.json"
DEBUG_DIR = PROJECT_ROOT / "cache" / "debug"


BANDS = [
    ("tropical", 0.0, 23.5),
    ("subtropical", 23.5, 35.0),
    ("temperate", 35.0, 55.0),
    ("subpolar", 55.0, 66.5),
    ("polar", 66.5, float("inf")),
]


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


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


def main() -> int:
    graph = load_json(GRAPH_PATH)
    seasonal = load_json(SEASONAL_PATH)
    koppen = load_json(KOPPEN_PATH)
    rows = []
    for color, province in graph["provinces"].items():
        if province.get("is_sea"):
            continue
        if color not in seasonal["provinces"] or color not in koppen["provinces"]:
            raise ValueError(f"missing province in cache: {color}")
        sc = seasonal["provinces"][color]
        kb = koppen["provinces"][color]
        latitude = float(province["latitude"])
        rows.append({
            "color": color,
            "band": band_for(latitude),
            "latitude": latitude,
            "mean_temperature": float(sc["mean_temperature"]),
            "summer_temperature": float(sc["summer_temperature"]),
            "winter_temperature": float(sc["winter_temperature"]),
            "koppen_class": str(kb["koppen_class"]),
            "koppen_group": str(kb["koppen_class"])[0],
        })
    total = len(rows)
    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)

    band_summary = []
    for name, _, _ in BANDS:
        band_rows = by_band[name]
        if band_rows:
            band_summary.append({
                "band": name,
                "province_count": len(band_rows),
                "land_percent": len(band_rows) / total,
                "mean_temp_avg": mean(row["mean_temperature"] for row in band_rows),
                "summer_temp_avg": mean(row["summer_temperature"] for row in band_rows),
                "winter_temp_avg": mean(row["winter_temperature"] for row in band_rows),
                "winter_temp_min": min(row["winter_temperature"] for row in band_rows),
            })
        else:
            band_summary.append({
                "band": name,
                "province_count": 0,
                "land_percent": 0.0,
                "mean_temp_avg": 0.0,
                "summer_temp_avg": 0.0,
                "winter_temp_avg": 0.0,
                "winter_temp_min": 0.0,
            })

    crosstab = []
    for name, _, _ in BANDS:
        band_rows = by_band[name]
        counts = Counter(row["koppen_class"] for row in band_rows)
        denom = max(len(band_rows), 1)
        for klass, count in sorted(counts.items()):
            crosstab.append({
                "band": name,
                "koppen_class": klass,
                "count": count,
                "pct_within_band": count / denom,
            })

    temp_summary = []
    for name, _, _ in BANDS:
        winters = [row["winter_temperature"] for row in by_band[name]]
        temp_summary.append({
            "band": name,
            "winter_temp_p10": percentile(winters, 10.0),
            "winter_temp_p50": percentile(winters, 50.0),
            "winter_temp_p90": percentile(winters, 90.0),
        })

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        DEBUG_DIR / "latitude_band_summary.csv",
        ["band", "province_count", "land_percent", "mean_temp_avg", "summer_temp_avg", "winter_temp_avg", "winter_temp_min"],
        band_summary,
    )
    write_csv(
        DEBUG_DIR / "latitude_koppen_crosstab.csv",
        ["band", "koppen_class", "count", "pct_within_band"],
        crosstab,
    )
    write_csv(
        DEBUG_DIR / "temperature_band_summary.csv",
        ["band", "winter_temp_p10", "winter_temp_p50", "winter_temp_p90"],
        temp_summary,
    )

    print("latitude band land percent:")
    for item in band_summary:
        print(f"  {item['band']}: {item['province_count']} ({item['land_percent']:.2%})")
    print("koppen group ratio by band:")
    for name, _, _ in BANDS:
        band_rows = by_band[name]
        denom = max(len(band_rows), 1)
        groups = Counter(row["koppen_group"] for row in band_rows)
        group_text = ", ".join(f"{group}={groups[group] / denom:.2%}" for group in ["A", "B", "C", "D", "E", "H"])
        print(f"  {name}: {group_text}")
    temperate_rows = by_band["temperate"]
    temperate_a = sum(1 for row in temperate_rows if row["koppen_group"] == "A") / max(len(temperate_rows), 1)
    high_lat_rows = by_band["subpolar"] + by_band["polar"]
    high_lat_d = sum(1 for row in high_lat_rows if row["koppen_group"] == "D") / max(len(high_lat_rows), 1)
    coldest = min(rows, key=lambda row: row["winter_temperature"])
    print(f"temperate band A ratio: {temperate_a:.2%}")
    print(f"subpolar/polar D ratio: {high_lat_d:.2%}")
    if high_lat_d == 0.0:
        print("subpolar/polar D ratio is 0%")
    print(
        "coldest winter_temperature: "
        f"{coldest['winter_temperature']:.6f} at {coldest['color']} "
        f"lat={coldest['latitude']:.6f} koppen={coldest['koppen_class']}"
    )
    print(f"wrote: {DEBUG_DIR / 'latitude_band_summary.csv'}")
    print(f"wrote: {DEBUG_DIR / 'latitude_koppen_crosstab.csv'}")
    print(f"wrote: {DEBUG_DIR / 'temperature_band_summary.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
