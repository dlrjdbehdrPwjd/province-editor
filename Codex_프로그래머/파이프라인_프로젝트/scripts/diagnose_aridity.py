from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


PROJECT_ROOT = Path(__file__).resolve().parents[1]
KOPPEN_PATH = PROJECT_ROOT / "cache" / "koppen_biome_terrain.json"
RAINFALL_PATH = PROJECT_ROOT / "cache" / "rainfall_normalized.json"
HYDROLOGY_PATH = PROJECT_ROOT / "cache" / "hydrology.json"
GRAPH_PATH = PROJECT_ROOT / "cache" / "province_graph.json"
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
    koppen = load_json(KOPPEN_PATH)
    rainfall = load_json(RAINFALL_PATH)
    hydrology = load_json(HYDROLOGY_PATH)
    graph = load_json(GRAPH_PATH)
    rows: list[dict] = []
    for color, province in graph["provinces"].items():
        if province.get("is_sea"):
            continue
        latitude = float(province["latitude"])
        kbt = koppen["provinces"][color]
        rn = rainfall["provinces"][color]
        rows.append({
            "province": color,
            "latitude": latitude,
            "band": band_for(latitude),
            "final_rainfall": float(rn["final_rainfall"]),
            "corrected_ET": float(hydrology["corrected_ET"][color]),
            "aridity_index": float(kbt["aridity_index"]),
            "koppen_class": str(kbt["koppen_class"]),
        })

    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        DEBUG_DIR / "aridity_diagnostic.csv",
        ["province", "latitude", "band", "final_rainfall", "corrected_ET", "aridity_index", "koppen_class"],
        rows,
    )

    aridity = [row["aridity_index"] for row in rows]
    print("overall aridity_index distribution:")
    print(
        f"  min={min(aridity):.8f} "
        f"p10={percentile(aridity, 10):.8f} "
        f"p25={percentile(aridity, 25):.8f} "
        f"p50={percentile(aridity, 50):.8f} "
        f"p75={percentile(aridity, 75):.8f} "
        f"p90={percentile(aridity, 90):.8f} "
        f"max={max(aridity):.8f}"
    )
    b_candidates = [row for row in rows if row["aridity_index"] < 0.5]
    print(f"aridity_index < 0.50 candidates: {len(b_candidates)} ({len(b_candidates) / len(rows):.2%})")

    by_band: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_band[row["band"]].append(row)
    print("mean aridity_index by latitude band:")
    for name, _, _ in BANDS:
        band_rows = by_band[name]
        if not band_rows:
            print(f"  {name}: n=0")
            continue
        print(f"  {name}: n={len(band_rows)} mean={mean(row['aridity_index'] for row in band_rows):.8f}")

    subtropical = by_band["subtropical"]
    if subtropical:
        sub_b = [row for row in subtropical if row["aridity_index"] < 0.5]
        print("subtropical band diagnostic:")
        print(f"  n={len(subtropical)}")
        print(f"  final_rainfall_mean={mean(row['final_rainfall'] for row in subtropical):.8f}")
        print(f"  corrected_ET_mean={mean(row['corrected_ET'] for row in subtropical):.8f}")
        print(f"  aridity_index_mean={mean(row['aridity_index'] for row in subtropical):.8f}")
        print(f"  aridity_index<0.5={len(sub_b)} ({len(sub_b) / len(subtropical):.2%})")

    not_b = [row for row in b_candidates if not row["koppen_class"].startswith("B")]
    print(f"aridity_index < 0.5 but not B: {len(not_b)}")
    if not_b:
        print("  koppen distribution:", dict(sorted(Counter(row["koppen_class"] for row in not_b).items())))
    print(f"wrote: {DEBUG_DIR / 'aridity_diagnostic.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
