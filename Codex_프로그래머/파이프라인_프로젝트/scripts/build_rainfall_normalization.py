from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Iterable


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_climate_pipeline as climate


SCHEMA_VERSION = "rainfall_normalization.v0.6"
SEASONAL_SCHEMA_VERSION = "seasonal_climate.v0.4.1"
HYDROLOGY_SCHEMA_VERSION = "hydrology.v0.5"
GRAPH_SCHEMA_VERSION = "province_graph.v0.2"


DEFAULT_PARAMS = {
    "world_scale": 1.0,
    "relative_weight": 0.7,
    "relative_curve_gamma": 1.0,
    "absolute_clamp_min": 0.0,
    "absolute_clamp_max": 1.5,
    "final_min": 0.0,
    "final_max": 1.5,
    "numeric_epsilon": 0.000001,
}


RAINFALL_RAW_FIELDS = (
    "annual_rainfall_raw",
    "summer_rainfall_raw",
    "winter_rainfall_raw",
    "wet_season_rainfall_raw",
    "dry_season_rainfall_raw",
)


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    return {
        "project_root": project_root,
        "seasonal": project_root / "cache" / "seasonal_climate.json",
        "hydrology": project_root / "cache" / "hydrology.json",
        "province_graph": project_root / "cache" / "province_graph.json",
        "params": project_root / "config" / "climate_rules.yaml",
        "output": project_root / "cache" / "rainfall_normalized.json",
        "debug_dir": project_root / "cache" / "debug",
    }


def canonical_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_write_json(path: Path, data: Any, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8", newline="\n") as handle:
        if pretty:
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        else:
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    os.replace(temp, path)


def load_params(path: Path) -> dict[str, float]:
    document = climate.load_yaml(path, "climate_rules.yaml")
    params = {**DEFAULT_PARAMS, **document.get("rainfall_normalization", {})}
    for key, value in list(params.items()):
        params[key] = climate.finite_number(value, f"rainfall_normalization.{key}")
    if not 0.0 <= params["relative_weight"] <= 1.0:
        raise ValueError("rainfall_normalization.relative_weight must be in 0..1")
    if params["relative_curve_gamma"] <= 0.0:
        raise ValueError("rainfall_normalization.relative_curve_gamma must be positive")
    if params["absolute_clamp_min"] > params["absolute_clamp_max"]:
        raise ValueError("absolute_clamp_min must be <= absolute_clamp_max")
    if params["final_min"] > params["final_max"]:
        raise ValueError("final_min must be <= final_max")
    if params["numeric_epsilon"] <= 0.0:
        raise ValueError("numeric_epsilon must be positive")
    return params


def validate_inputs(seasonal: dict[str, Any], hydrology: dict[str, Any], graph: dict[str, Any]) -> list[str]:
    if seasonal.get("schema_version") != SEASONAL_SCHEMA_VERSION:
        raise ValueError(f"expected {SEASONAL_SCHEMA_VERSION}, got {seasonal.get('schema_version')}")
    if hydrology.get("schema_version") != HYDROLOGY_SCHEMA_VERSION:
        raise ValueError(f"expected {HYDROLOGY_SCHEMA_VERSION}, got {hydrology.get('schema_version')}")
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise ValueError(f"expected {GRAPH_SCHEMA_VERSION}, got {graph.get('schema_version')}")
    topology_hash = graph.get("metadata", {}).get("hash", {}).get("topology_hash")
    if not topology_hash:
        raise ValueError("province_graph.metadata.hash.topology_hash missing")
    land = [
        color for color, province in graph["provinces"].items()
        if not bool(province.get("is_sea", False))
    ]
    seasonal_set = set(seasonal.get("provinces", {}))
    missing_seasonal = [color for color in land if color not in seasonal_set]
    if missing_seasonal:
        raise ValueError(f"seasonal_climate missing land province: {missing_seasonal[:5]}")
    for field in ("corrected_ET", "river_bonus", "lake_fraction"):
        if field not in hydrology:
            raise ValueError(f"hydrology.{field} missing")
        missing = [color for color in land if color not in hydrology[field]]
        if missing:
            raise ValueError(f"hydrology.{field} missing province: {missing[:5]}")
    return sorted(land)


def sanitize_raw_rainfall(seasonal: dict[str, Any], land: list[str]) -> dict[str, dict[str, float]]:
    sanitized: dict[str, dict[str, float]] = {}
    for color in land:
        values = seasonal["provinces"][color]
        row: dict[str, float] = {}
        for field in RAINFALL_RAW_FIELDS:
            if field not in values:
                raise ValueError(f"{color}.{field} missing")
            value = climate.finite_number(values[field], f"{color}.{field}")
            row[field] = max(0.0, value)
        for passthrough in ("dry_season_strength", "rainfall_seasonality", "annual_ET"):
            if passthrough not in values:
                raise ValueError(f"{color}.{passthrough} missing")
            row[passthrough] = climate.finite_number(values[passthrough], f"{color}.{passthrough}")
        sanitized[color] = row
    return sanitized


def compute_percentiles(values: dict[str, float]) -> dict[str, float]:
    colors = list(values)
    if len(colors) == 1:
        return {colors[0]: 0.5}
    sorted_values = sorted((value, color) for color, value in values.items())
    result: dict[str, float] = {}
    index = 0
    while index < len(sorted_values):
        value = sorted_values[index][0]
        end = index + 1
        while end < len(sorted_values) and sorted_values[end][0] == value:
            end += 1
        average_rank = (index + end - 1) / 2.0
        percentile = average_rank / (len(sorted_values) - 1)
        for _, color in sorted_values[index:end]:
            result[color] = percentile
        index = end
    return result


def normalize_one(raw: float, percentile: float, params: dict[str, float]) -> tuple[float, float, float]:
    absolute = climate.clamp(
        raw * float(params["world_scale"]),
        float(params["absolute_clamp_min"]),
        float(params["absolute_clamp_max"]),
    )
    relative = math.pow(climate.clamp(percentile, 0.0, 1.0), float(params["relative_curve_gamma"]))
    weight = float(params["relative_weight"])
    final = absolute * (1.0 - weight) + relative * weight
    final = climate.clamp(final, float(params["final_min"]), float(params["final_max"]))
    return absolute, relative, final


def build_output(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    seasonal = climate.load_json(args.seasonal, "seasonal_climate.json")
    hydrology = climate.load_json(args.hydrology, "hydrology.json")
    graph = climate.load_json(args.province_graph, "province_graph.json")
    params = load_params(args.params)
    land = validate_inputs(seasonal, hydrology, graph)
    raw = sanitize_raw_rainfall(seasonal, land)
    annual_raw = {color: raw[color]["annual_rainfall_raw"] for color in land}
    percentiles = compute_percentiles(annual_raw)
    output_provinces: dict[str, dict[str, float]] = {}
    clamped_absolute_count = 0
    zero_final_count = 0
    max_final_count = 0
    epsilon = float(params["numeric_epsilon"])
    for color in land:
        absolute, relative, final = normalize_one(annual_raw[color], percentiles[color], params)
        if annual_raw[color] <= epsilon:
            absolute = 0.0
            relative = 0.0
            final = 0.0
        if absolute in (float(params["absolute_clamp_min"]), float(params["absolute_clamp_max"])):
            raw_scaled = annual_raw[color] * float(params["world_scale"])
            if raw_scaled < float(params["absolute_clamp_min"]) or raw_scaled > float(params["absolute_clamp_max"]):
                clamped_absolute_count += 1
        if abs(final - float(params["final_min"])) <= epsilon:
            zero_final_count += 1
        if abs(final - float(params["final_max"])) <= epsilon:
            max_final_count += 1
        summer_raw = raw[color]["summer_rainfall_raw"]
        winter_raw = raw[color]["winter_rainfall_raw"]
        season_total = summer_raw + winter_raw
        if season_total > 0.0:
            final_summer = final * summer_raw / season_total
            final_winter = final * winter_raw / season_total
        else:
            final_summer = 0.0
            final_winter = 0.0
        final_wet = max(final_summer, final_winter)
        final_dry = min(final_summer, final_winter)
        output_provinces[color] = {
            "final_rainfall": round(final, 8),
            "final_summer_rainfall": round(final_summer, 8),
            "final_winter_rainfall": round(final_winter, 8),
            "final_wet_season_rainfall": round(final_wet, 8),
            "final_dry_season_rainfall": round(final_dry, 8),
            "rainfall_percentile": round(percentiles[color], 8),
            "rainfall_absolute_scaled": round(absolute, 8),
            "rainfall_relative_scaled": round(relative, 8),
            "dry_season_strength": round(raw[color]["dry_season_strength"], 8),
            "rainfall_seasonality": round(raw[color]["rainfall_seasonality"], 8),
            "corrected_ET": round(float(hydrology["corrected_ET"][color]), 8),
            "river_bonus": round(float(hydrology["river_bonus"][color]), 8),
            "lake_fraction": round(float(hydrology["lake_fraction"][color]), 8),
        }
    warnings: list[str] = []
    if all(value <= epsilon for value in annual_raw.values()):
        warnings.append("annual_rainfall_raw is zero for all land provinces")
    if zero_final_count / max(len(land), 1) > 0.5:
        warnings.append(f"final_rainfall at final_min for {zero_final_count} province(s)")
    if max_final_count / max(len(land), 1) > 0.2:
        warnings.append(f"final_rainfall at final_max for {max_final_count} province(s)")
    topology_hash = graph["metadata"]["hash"]["topology_hash"]
    params_hash = canonical_hash(params)
    output = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "seasonal_climate": climate.display_path(args.seasonal, args.project_root),
            "hydrology": climate.display_path(args.hydrology, args.project_root),
            "province_graph": climate.display_path(args.province_graph, args.project_root),
            "climate_rules": climate.display_path(args.params, args.project_root),
        },
        "hash": {
            "seasonal_hash": file_hash(args.seasonal),
            "hydrology_hash": file_hash(args.hydrology),
            "graph_hash": topology_hash,
            "params_hash": params_hash,
        },
        "metadata": {
            "land_province_count": len(land),
            "absolute_clamped_count": clamped_absolute_count,
            "final_min_count": zero_final_count,
            "final_max_count": max_final_count,
        },
        "warnings": warnings,
        "provinces": output_provinces,
    }
    validate_output(output, land, params)
    diagnostics = {
        "annual_raw": annual_raw,
        "percentiles": percentiles,
        "params": params,
    }
    return output, diagnostics


def validate_output(output: dict[str, Any], land: list[str], params: dict[str, float]) -> None:
    if set(output["provinces"]) != set(land):
        raise ValueError("output province set mismatch")
    epsilon = float(params["numeric_epsilon"])
    for color, values in output["provinces"].items():
        for key, value in values.items():
            climate.finite_number(value, f"{color}.{key}")
        if not float(params["final_min"]) - epsilon <= values["final_rainfall"] <= float(params["final_max"]) + epsilon:
            raise ValueError(f"final_rainfall out of range: {color}")
        if abs(values["final_summer_rainfall"] + values["final_winter_rainfall"] - values["final_rainfall"]) > max(2e-8, epsilon):
            raise ValueError(f"seasonal rainfall sum mismatch: {color}")
        if not 0.0 <= values["rainfall_percentile"] <= 1.0:
            raise ValueError(f"rainfall_percentile out of range: {color}")
        if not 0.0 <= values["lake_fraction"] <= 1.0:
            raise ValueError(f"lake_fraction out of range: {color}")


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    climate.write_csv(path, fieldnames, rows)


def write_debug_outputs(args: argparse.Namespace, output: dict[str, Any], diagnostics: dict[str, Any]) -> list[Path]:
    args.debug_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.debug_dir / "rainfall_normalization_report.json"
    report = {
        "schema_version": output["schema_version"],
        "metadata": output["metadata"],
        "warnings": output["warnings"],
        "params": diagnostics["params"],
    }
    atomic_write_json(report_path, report, pretty=True)
    distribution_path = args.debug_dir / "rainfall_distribution.csv"
    rows = [
        {
            "province": color,
            "annual_rainfall_raw": diagnostics["annual_raw"][color],
            "rainfall_percentile": diagnostics["percentiles"][color],
            "final_rainfall": values["final_rainfall"],
            "rainfall_absolute_scaled": values["rainfall_absolute_scaled"],
            "rainfall_relative_scaled": values["rainfall_relative_scaled"],
        }
        for color, values in output["provinces"].items()
    ]
    write_csv(
        distribution_path,
        ["province", "annual_rainfall_raw", "rainfall_percentile", "final_rainfall", "rainfall_absolute_scaled", "rainfall_relative_scaled"],
        rows,
    )
    clamped_path = args.debug_dir / "rainfall_clamped.csv"
    clamped_rows = [
        row for row in rows
        if row["rainfall_absolute_scaled"] in (
            diagnostics["params"]["absolute_clamp_min"],
            diagnostics["params"]["absolute_clamp_max"],
        )
    ]
    write_csv(
        clamped_path,
        ["province", "annual_rainfall_raw", "rainfall_percentile", "final_rainfall", "rainfall_absolute_scaled", "rainfall_relative_scaled"],
        clamped_rows,
    )
    return [report_path, distribution_path, clamped_path]


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Build rainfall_normalization.v0.6 cache")
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--seasonal", type=Path, default=defaults["seasonal"])
    parser.add_argument("--hydrology", type=Path, default=defaults["hydrology"])
    parser.add_argument("--province-graph", type=Path, default=defaults["province_graph"])
    parser.add_argument("--params", type=Path, default=defaults["params"])
    parser.add_argument("--output", type=Path, default=defaults["output"])
    parser.add_argument("--debug-dir", type=Path, default=defaults["debug_dir"])
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output, diagnostics = build_output(args)
        if output["warnings"] and args.fail_on_warning:
            for warning in output["warnings"]:
                print(f"WARNING: {warning}")
            return 2
        atomic_write_json(args.output, output, pretty=args.pretty)
        artifacts = write_debug_outputs(args, output, diagnostics) if args.debug else []
        values = [row["final_rainfall"] for row in output["provinces"].values()]
        print(f"wrote: {args.output}")
        print(f"schema_version: {output['schema_version']}")
        print(f"land_province_count: {len(output['provinces'])}")
        print(f"final_rainfall_min: {min(values):.8f}")
        print(f"final_rainfall_max: {max(values):.8f}")
        print(f"final_rainfall_mean: {sum(values) / len(values):.8f}")
        print(f"absolute_clamped_count: {output['metadata']['absolute_clamped_count']}")
        print(f"warnings: {len(output['warnings'])}")
        for warning in output["warnings"][:20]:
            print(f"WARNING: {warning}")
        print(f"debug_artifacts: {len(artifacts)}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
