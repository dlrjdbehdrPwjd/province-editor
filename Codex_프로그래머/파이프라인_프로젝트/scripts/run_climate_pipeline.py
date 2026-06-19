from __future__ import annotations

import argparse
import ast
import csv
import heapq
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from build_bootstrap_fields import (
    atomic_write_json,
    canonical_hash,
    display_path,
    normalize_color,
)


SCHEMA_VERSION = "seasonal_climate.v0.4.1"
GRAPH_SCHEMA_VERSION = "province_graph.v0.2"
BOOTSTRAP_SCHEMA_VERSION = "bootstrap_fields.v0.1"
REPORT_SCHEMA_VERSION = "seasonal_climate_build_report.v0.1"

DEFAULT_MOISTURE_PARAMS: dict[str, Any] = {
    "coastal_source_factor": 0.161,
    "wetland_moisture_bonus": 0.15,
    "leakage_min": 0.05,
    "transport_length_px": 500.0,
    "overflow_to_rainfall_factor": 1.0,
    "improvement_epsilon": 0.000001,
    "max_transport_iterations": 2000,
    "base_capacity": 1.0,
    "k_clausius": 0.07,
    "T_ref": 15.0,
    "capacity_min": 0.35,
    "capacity_max": 2.25,
    "median_area_px": 90.0,
    "numeric_epsilon": 0.000001,
    "wind_bands": {
        "transition_width_deg": 4.0,
        "bands": [
            {"name": "itcz", "lat_min": 0.0, "lat_max": 10.0, "direction": [0.0, 1.0], "directionality": 0.20},
            {"name": "trade_winds", "lat_min": 10.0, "lat_max": 30.0, "direction": [-1.0, 0.25], "directionality": 0.85},
            {"name": "westerlies", "lat_min": 30.0, "lat_max": 60.0, "direction": [1.0, -0.15], "directionality": 0.75},
            {"name": "polar_easterlies", "lat_min": 60.0, "lat_max": 90.0, "direction": [-1.0, 0.0], "directionality": 0.65},
        ],
    },
}
DEFAULT_BARRIER_PARAMS: dict[str, Any] = {
    "barrier_scale": 3.0,
    "ridge_bonus": 0.5,
    "windward_efficiency": 0.7,
    "barrier_factor_max": 0.95,
}
DEFAULT_SEASONAL_PARAMS: dict[str, Any] = {
    "itcz_sigma": 5.0,
    "itcz_scale": 1.0,
    "subtropical_center": 25.0,
    "subtropical_width": 10.0,
    "subtropical_scale": 1.0,
    "drain_strength": 0.06,
    "suppression_factor": 0.20,
    "itcz_conversion_rate": 0.30,
    "northern_summer_itcz_offset": 5.0,
    "summer_coastal_factor_multiplier": 1.1,
    "winter_coastal_factor_multiplier": 0.9,
    "base_seasonal_amplitude": 15.0,
    "foehn_warming_factor": 0.5,
    "foehn_mtn_threshold": 0.3,
    "pet_coefficient": 0.1,
    "bare_soil_coeff": 0.3,
    "transpiration_coeff": 0.7,
    "storage_capacity": 10.0,
    "soil_storage_time_years": 5.0,
    "recycling_fraction": 0.018,
    "max_recycling_share": 0.1,
    "relaxation_alpha": 0.5,
    "max_spinup_years": 50,
    "climate_moisture_epsilon": 0.005,
    "climate_recycling_epsilon": 0.005,
    "soil_storage_epsilon": 0.001,
    "numeric_epsilon": 0.000001,
}


def strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    for index, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index]
    return line


def parse_yaml_scalar(value: str) -> Any:
    value = value.strip()
    lowered = value.lower()
    if value == "{}":
        return {}
    if value == "[]":
        return []
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if value.startswith(("[", "{")) and value.endswith(("]", "}")):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            pass
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1]
    try:
        return float(value) if any(marker in value for marker in (".", "e", "E")) else int(value)
    except ValueError:
        return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw in text.splitlines():
        clean = strip_yaml_comment(raw).rstrip()
        if clean.strip():
            lines.append((len(clean) - len(clean.lstrip(" ")), clean.strip()))

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines) or lines[index][0] < indent:
            return {}, index
        if lines[index][1].startswith("- "):
            result_list: list[Any] = []
            while index < len(lines):
                line_indent, content = lines[index]
                if line_indent != indent or not content.startswith("- "):
                    break
                item_text = content[2:].strip()
                index += 1
                if not item_text:
                    item, index = parse_block(index, indent + 2)
                    result_list.append(item)
                    continue
                if ":" not in item_text:
                    result_list.append(parse_yaml_scalar(item_text))
                    continue
                key, value = item_text.split(":", 1)
                item_dict: dict[str, Any] = {key.strip(): parse_yaml_scalar(value)} if value.strip() else {}
                if not value.strip():
                    nested, index = parse_block(index, indent + 2)
                    item_dict[key.strip()] = nested
                while index < len(lines) and lines[index][0] > indent:
                    child_indent, child_content = lines[index]
                    if ":" not in child_content:
                        break
                    child_key, child_value = child_content.split(":", 1)
                    index += 1
                    if child_value.strip():
                        item_dict[child_key.strip()] = parse_yaml_scalar(child_value)
                    else:
                        nested, index = parse_block(index, child_indent + 2)
                        item_dict[child_key.strip()] = nested
                result_list.append(item_dict)
            return result_list, index

        result_dict: dict[str, Any] = {}
        while index < len(lines):
            line_indent, content = lines[index]
            if line_indent < indent or line_indent > indent or content.startswith("- "):
                break
            if ":" not in content:
                raise ValueError(f"invalid YAML line: {content}")
            key, value = content.split(":", 1)
            index += 1
            if value.strip():
                result_dict[key.strip()] = parse_yaml_scalar(value)
            else:
                child_indent = lines[index][0] if index < len(lines) and lines[index][0] > line_indent else line_indent + 2
                nested, index = parse_block(index, child_indent)
                result_dict[key.strip()] = nested
        return result_dict, index

    parsed, _ = parse_block(0, 0)
    if not isinstance(parsed, dict):
        raise ValueError("top-level YAML must be a mapping")
    return parsed


def load_yaml(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
    except ModuleNotFoundError:
        loaded = parse_simple_yaml(text)
    except Exception as error:
        raise ValueError(f"failed to parse {label}: {error}") from error
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{label} top level must be a mapping")
    return loaded


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def compute_transport_survival(area_px: float, transport_length_px: float) -> float:
    if area_px < 1.0:
        raise ValueError("area_px must be at least 1")
    if transport_length_px <= 0.0:
        raise ValueError("transport_length_px must be positive")
    return math.exp(-math.sqrt(area_px) / transport_length_px)


def compute_itcz_weight(latitude: float, center_latitude: float, sigma: float) -> float:
    if sigma <= 0.0:
        raise ValueError("itcz sigma must be positive")
    return math.exp(-((latitude - center_latitude) ** 2) / (2.0 * sigma ** 2))


def compute_analytical_storage(
    annual_rainfall: float, annual_et: float, storage_years: float, storage_capacity: float
) -> float:
    if storage_years < 0.0 or storage_capacity < 0.0:
        raise ValueError("storage_years/storage_capacity must be non-negative")
    net_input = max(0.0, annual_rainfall - annual_et)
    return clamp(net_input * storage_years, 0.0, storage_capacity)


def finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be a number") from error
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def deep_merge(defaults: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in defaults.items():
        if isinstance(value, dict):
            child = supplied.get(key, {})
            if not isinstance(child, dict):
                raise ValueError(f"parameter {key} must be a mapping")
            result[key] = deep_merge(value, child)
        else:
            result[key] = supplied.get(key, value)
    for key, value in supplied.items():
        if key not in result:
            result[key] = value
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"failed to parse {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{label} top level must be an object")
    return value


def validate_upstream(
    graph: dict[str, Any], bootstrap: dict[str, Any]
) -> tuple[list[str], str]:
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise ValueError(f"province_graph schema_version must be {GRAPH_SCHEMA_VERSION}")
    if bootstrap.get("schema_version") != BOOTSTRAP_SCHEMA_VERSION:
        raise ValueError(f"bootstrap_fields schema_version must be {BOOTSTRAP_SCHEMA_VERSION}")
    provinces = graph.get("provinces")
    adjacency = graph.get("adjacency")
    bootstrap_provinces = bootstrap.get("provinces")
    if not isinstance(provinces, dict) or not isinstance(adjacency, dict):
        raise ValueError("province_graph provinces/adjacency must be objects")
    if not isinstance(bootstrap_provinces, dict):
        raise ValueError("bootstrap_fields.provinces must be an object")
    graph_hash = graph.get("metadata", {}).get("hash", {}).get("topology_hash")
    if not isinstance(graph_hash, str) or not graph_hash.startswith("sha256:"):
        raise ValueError("province_graph topology_hash is missing")
    if bootstrap.get("graph_hash") != graph_hash:
        raise ValueError("bootstrap_fields graph_hash does not match province_graph")
    land = sorted(
        color for color, province in provinces.items() if not bool(province.get("is_sea", False))
    )
    if set(bootstrap_provinces) != set(land):
        raise ValueError("bootstrap_fields province coverage does not match land targets")
    for color in land:
        province = provinces[color]
        field = bootstrap_provinces[color]
        if not isinstance(adjacency.get(color), dict):
            raise ValueError(f"{color}: adjacency must be an object")
        finite_number(province.get("latitude"), f"{color}.latitude")
        finite_number(province.get("area_px"), f"{color}.area_px")
        finite_number(field.get("synthetic_elevation_m"), f"{color}.synthetic_elevation_m")
        finite_number(field.get("continentality"), f"{color}.continentality")
    if not land:
        raise ValueError("province_graph has no land targets")
    return land, graph_hash


def load_mapping_document(path: Path, label: str, root_key: str) -> dict[str, dict[str, Any]]:
    document = load_yaml(path, label)
    raw = document.get(root_key, document if root_key not in document else {})
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"{label}.{root_key} must be a mapping")
    result: dict[str, dict[str, Any]] = {}
    for raw_color, data in raw.items():
        color = normalize_color(str(raw_color))
        if not isinstance(data, dict):
            raise ValueError(f"{label} {color} must be a mapping")
        result[color] = data
    return result


def normalize_constraints(
    raw: dict[str, dict[str, Any]], land: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    land_set = set(land)
    warnings = [f"unknown constraint province ignored: {color}" for color in sorted(set(raw) - land_set)]
    normalized: dict[str, dict[str, Any]] = {}
    for color in land:
        data = raw.get(color, {})
        temperature_delta = finite_number(data.get("temperature_delta", 0.0), f"{color}.temperature_delta")
        moisture_bonus = finite_number(data.get("moisture_bonus", 0.0), f"{color}.moisture_bonus")
        mountain_strength = finite_number(data.get("mountain_strength", 0.0), f"{color}.mountain_strength")
        if not 0.0 <= mountain_strength <= 1.0:
            raise ValueError(f"mountain_strength out of range ({color}: {mountain_strength})")
        normalized[color] = {
            "temperature_delta": temperature_delta,
            "moisture_bonus": moisture_bonus,
            "wetland_seed": bool(data.get("wetland_seed", False)),
            "mountain_strength": mountain_strength,
        }
    return normalized, warnings


def normalize_overrides(
    raw: dict[str, dict[str, Any]], land: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    land_set = set(land)
    warnings = [f"unknown override province ignored: {color}" for color in sorted(set(raw) - land_set)]
    normalized: dict[str, dict[str, Any]] = {}
    for color in land:
        data = raw.get(color, {})
        climate_lock = bool(data.get("climate_lock", False))
        excluded = bool(data.get("exclude_from_sim", False))
        if climate_lock and excluded:
            raise ValueError(f"exclude_from_sim=true + climate_lock=true ({color})")
        values: dict[str, float | None] = {}
        for key in ("force_temp", "force_moisture", "force_rainfall"):
            value = data.get(key)
            values[key] = None if value is None else finite_number(value, f"{color}.{key}")
        if values["force_moisture"] is not None and values["force_moisture"] < 0.0:
            raise ValueError(f"force_moisture negative ({color})")
        if values["force_rainfall"] is not None and values["force_rainfall"] < 0.0:
            raise ValueError(f"force_rainfall negative ({color})")
        if not climate_lock and any(value is not None for value in values.values()):
            warnings.append(f"force climate values ignored because climate_lock=false: {color}")
            values = {key: None for key in values}
        normalized[color] = {
            "climate_lock": climate_lock,
            "force_temp": values["force_temp"],
            "force_moisture": values["force_moisture"],
            "force_rainfall": values["force_rainfall"],
            "exclude_from_sim": excluded,
        }
    return normalized, warnings


def load_params(path: Path) -> dict[str, dict[str, Any]]:
    document = load_yaml(path, "climate_rules.yaml")
    moisture = deep_merge(DEFAULT_MOISTURE_PARAMS, document.get("moisture_transport", {}))
    barrier = deep_merge(DEFAULT_BARRIER_PARAMS, document.get("mountain_barrier", {}))
    seasonal = deep_merge(DEFAULT_SEASONAL_PARAMS, document.get("seasonal_climate", {}))
    bands_doc = moisture.get("wind_bands", {})
    bands = bands_doc.get("bands", []) if isinstance(bands_doc, dict) else []
    if not isinstance(bands, list) or not bands:
        raise ValueError("moisture_transport.wind_bands.bands must be a non-empty list")
    normalized_bands: list[dict[str, Any]] = []
    for index, band in enumerate(bands):
        if not isinstance(band, dict):
            raise ValueError(f"wind band {index} must be a mapping")
        direction = band.get("direction")
        if not isinstance(direction, list) or len(direction) != 2:
            raise ValueError(f"wind band {index}.direction must contain two numbers")
        normalized_bands.append({
            "name": str(band.get("name", f"band_{index}")),
            "lat_min": finite_number(band.get("lat_min"), f"wind band {index}.lat_min"),
            "lat_max": finite_number(band.get("lat_max"), f"wind band {index}.lat_max"),
            "direction": [finite_number(direction[0], f"wind band {index}.direction.x"), finite_number(direction[1], f"wind band {index}.direction.y")],
            "directionality": finite_number(band.get("directionality"), f"wind band {index}.directionality"),
        })
    normalized_bands.sort(key=lambda item: item["lat_min"])
    moisture["wind_bands"] = {
        "transition_width_deg": finite_number(bands_doc.get("transition_width_deg", 4.0), "transition_width_deg"),
        "bands": normalized_bands,
    }
    validate_params(moisture, barrier, seasonal)
    return {"moisture_transport": moisture, "mountain_barrier": barrier, "seasonal_climate": seasonal}


def validate_params(moisture: dict[str, Any], barrier: dict[str, Any], seasonal: dict[str, Any]) -> None:
    numeric_keys = [
        "coastal_source_factor", "wetland_moisture_bonus", "leakage_min", "transport_length_px",
        "overflow_to_rainfall_factor", "improvement_epsilon", "max_transport_iterations",
        "base_capacity", "k_clausius", "T_ref", "capacity_min", "capacity_max", "median_area_px",
        "numeric_epsilon",
    ]
    for key in numeric_keys:
        moisture[key] = finite_number(moisture[key], f"moisture_transport.{key}")
    for key in DEFAULT_BARRIER_PARAMS:
        barrier[key] = finite_number(barrier[key], f"mountain_barrier.{key}")
    for key in DEFAULT_SEASONAL_PARAMS:
        seasonal[key] = finite_number(seasonal[key], f"seasonal_climate.{key}")
    if not 0.0 <= moisture["leakage_min"] <= 1.0:
        raise ValueError("leakage_min must be in 0..1")
    if moisture["transport_length_px"] <= 0.0 or moisture["improvement_epsilon"] <= 0.0:
        raise ValueError("transport_length_px and improvement_epsilon must be positive")
    if moisture["max_transport_iterations"] < 1.0:
        raise ValueError("max_transport_iterations must be at least 1")
    moisture["max_transport_iterations"] = int(moisture["max_transport_iterations"])
    if moisture["capacity_min"] <= 0.0 or moisture["capacity_min"] > moisture["capacity_max"]:
        raise ValueError("invalid capacity_min/capacity_max")
    if barrier["barrier_scale"] < 0.0 or barrier["ridge_bonus"] < 0.0:
        raise ValueError("barrier_scale/ridge_bonus must be non-negative")
    if not 0.0 <= barrier["windward_efficiency"] <= 1.0:
        raise ValueError("windward_efficiency must be in 0..1")
    if not 0.0 < barrier["barrier_factor_max"] <= 1.0:
        raise ValueError("barrier_factor_max must be in (0, 1]")
    if seasonal["itcz_sigma"] <= 0.0 or seasonal["subtropical_width"] <= 0.0:
        raise ValueError("gaussian widths must be positive")
    if seasonal["summer_coastal_factor_multiplier"] < 0.0 or seasonal["winter_coastal_factor_multiplier"] < 0.0:
        raise ValueError("seasonal coastal multipliers must be non-negative")
    if not 0.0 <= seasonal["relaxation_alpha"] <= 1.0:
        raise ValueError("relaxation_alpha must be in 0..1")
    if seasonal["storage_capacity"] < 0.0 or seasonal["max_spinup_years"] < 1.0:
        raise ValueError("invalid storage_capacity/max_spinup_years")
    if seasonal["soil_storage_time_years"] < 0.0:
        raise ValueError("soil_storage_time_years must be non-negative")
    for key in ("climate_moisture_epsilon", "climate_recycling_epsilon", "soil_storage_epsilon"):
        if seasonal[key] <= 0.0:
            raise ValueError(f"{key} must be positive")
    seasonal["max_spinup_years"] = int(seasonal["max_spinup_years"])


def normalized_band_vector(band: dict[str, Any], latitude: float) -> tuple[float, float]:
    raw_x, raw_y = band["direction"]
    if latitude < 0.0:
        raw_y = -raw_y
    length = math.hypot(raw_x, raw_y)
    if length <= 0.0:
        return (0.0, 0.0)
    scale = float(band["directionality"]) / length
    return (raw_x * scale, raw_y * scale)


def compute_wind_vector(latitude: float, moisture_params: dict[str, Any]) -> tuple[float, float]:
    config = moisture_params["wind_bands"]
    bands = config["bands"]
    abs_lat = abs(latitude)
    transition = float(config["transition_width_deg"])
    for lower, upper in zip(bands, bands[1:]):
        boundary = float(upper["lat_min"])
        if transition > 0.0 and boundary - transition <= abs_lat <= boundary + transition:
            t = (abs_lat - (boundary - transition)) / (2.0 * transition)
            low = normalized_band_vector(lower, latitude)
            high = normalized_band_vector(upper, latitude)
            return (low[0] * (1.0 - t) + high[0] * t, low[1] * (1.0 - t) + high[1] * t)
    for band in bands:
        if float(band["lat_min"]) <= abs_lat < float(band["lat_max"]):
            return normalized_band_vector(band, latitude)
    return normalized_band_vector(bands[-1], latitude)


def compute_vertical_motion(latitude: float, params: dict[str, Any], itcz_center_lat: float = 0.0) -> float:
    abs_lat = abs(latitude)
    itcz = math.exp(-((latitude - itcz_center_lat) ** 2) / (2.0 * float(params["itcz_sigma"]) ** 2))
    subtropical = math.exp(-((abs_lat - float(params["subtropical_center"])) ** 2) / (2.0 * float(params["subtropical_width"]) ** 2))
    return -itcz * float(params["itcz_scale"]) + subtropical * float(params["subtropical_scale"])


def compute_latitude_base_temperature(latitude: float, equator_temp: float, pole_temp: float) -> float:
    abs_lat = clamp(abs(latitude), 0.0, 90.0)
    insolation_factor = math.cos(math.radians(abs_lat))
    return pole_temp + (equator_temp - pole_temp) * insolation_factor


def compute_temperatures(
    graph: dict[str, Any], bootstrap: dict[str, Any], constraints: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]], land: list[str], seasonal: dict[str, Any],
    equator_temp: float, pole_temp: float, lapse_rate: float,
) -> tuple[dict[str, float], dict[str, float]]:
    summer: dict[str, float] = {}
    winter: dict[str, float] = {}
    for color in land:
        latitude = float(graph["provinces"][color]["latitude"])
        field = bootstrap["provinces"][color]
        base = compute_latitude_base_temperature(latitude, equator_temp, pole_temp)
        base -= lapse_rate * (float(field["synthetic_elevation_m"]) / 1000.0)
        base += float(constraints[color]["temperature_delta"])
        latitude_factor = clamp(math.sin(math.radians(abs(latitude))), 0.0, 1.0)
        amplitude = float(seasonal["base_seasonal_amplitude"]) * latitude_factor * float(field["continentality"])
        summer_value = base + amplitude
        winter_value = base - amplitude
        override = overrides[color]
        if override["climate_lock"] and override["force_temp"] is not None:
            summer_value = winter_value = float(override["force_temp"])
        if override["exclude_from_sim"]:
            summer_value = winter_value = base
        summer[color] = summer_value
        winter[color] = winter_value
    return summer, winter


def map_local_temperatures_to_passes(
    graph: dict[str, Any], land: list[str], local_summer: dict[str, float], local_winter: dict[str, float]
) -> tuple[dict[str, float], dict[str, float]]:
    july: dict[str, float] = {}
    january: dict[str, float] = {}
    for color in land:
        if float(graph["provinces"][color]["latitude"]) >= 0.0:
            july[color] = local_summer[color]
            january[color] = local_winter[color]
        else:
            july[color] = local_winter[color]
            january[color] = local_summer[color]
    return july, january


def compute_capacities(temperatures: dict[str, float], moisture: dict[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for color, temperature in temperatures.items():
        value = float(moisture["base_capacity"]) * math.exp(float(moisture["k_clausius"]) * (temperature - float(moisture["T_ref"])))
        result[color] = clamp(value, float(moisture["capacity_min"]), float(moisture["capacity_max"]))
    return result


def validate_force_moisture(overrides: dict[str, dict[str, Any]], capacities: dict[str, float]) -> None:
    for color, override in overrides.items():
        value = override["force_moisture"]
        if override["climate_lock"] and value is not None and float(value) > capacities[color]:
            raise ValueError(f"force_moisture > season capacity ({color}: {value} > {capacities[color]})")


def initialize_moisture(
    graph: dict[str, Any], constraints: dict[str, dict[str, Any]], overrides: dict[str, dict[str, Any]],
    capacities: dict[str, float], recycling: dict[str, float], land: list[str], params: dict[str, Any],
    coastal_multipliers: dict[str, float] | None = None,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for color in land:
        override = overrides[color]
        if override["exclude_from_sim"]:
            result[color] = 0.0
            continue
        province = graph["provinces"][color]
        value = 0.0
        if bool(province.get("is_coastal", False)):
            multiplier = 1.0 if coastal_multipliers is None else coastal_multipliers[color]
            value += float(province.get("coastal_ratio", 0.0)) * float(params["coastal_source_factor"]) * multiplier
        if constraints[color]["wetland_seed"]:
            value += float(params["wetland_moisture_bonus"])
        value += float(constraints[color]["moisture_bonus"])
        value += float(recycling.get(color, 0.0))
        value = clamp(value, 0.0, capacities[color])
        if override["climate_lock"] and override["force_moisture"] is not None:
            value = float(override["force_moisture"])
        result[color] = value
    return result


def build_transport_routing(
    graph: dict[str, Any], land: list[str], constraints: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]], wind_vectors: dict[str, tuple[float, float]],
    moisture_params: dict[str, Any], barrier_params: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np

    index = {color: position for position, color in enumerate(land)}
    src_list: list[int] = []
    dst_list: list[int] = []
    weight_list: list[float] = []
    barrier_list: list[float] = []
    dead_end = np.ones(len(land), dtype=bool)
    for color_a in land:
        if overrides[color_a]["exclude_from_sim"]:
            continue
        candidates: list[tuple[str, float]] = []
        wind_a = wind_vectors[color_a]
        for color_b, edge in graph["adjacency"][color_a].items():
            if color_b not in index or overrides[color_b]["exclude_from_sim"]:
                continue
            direction = edge.get("direction", {})
            dx = float(direction["x"])
            dy = float(direction["y"])
            wind_b = wind_vectors[color_b]
            wind_weight = max(
                float(moisture_params["leakage_min"]),
                min(wind_a[0] * dx + wind_a[1] * dy, wind_b[0] * dx + wind_b[1] * dy),
            )
            flow_weight = wind_weight * float(edge["border_weight"])
            if flow_weight > 0.0:
                candidates.append((color_b, flow_weight))
        flow_total = sum(weight for _, weight in candidates)
        if flow_total <= 0.0:
            continue
        dead_end[index[color_a]] = False
        for color_b, flow_weight in candidates:
            mtn_a = float(constraints[color_a]["mountain_strength"])
            mtn_b = float(constraints[color_b]["mountain_strength"])
            barrier = max(mtn_a, mtn_b) + mtn_a * mtn_b * float(barrier_params["ridge_bonus"])
            barrier_factor = clamp(
                1.0 - math.exp(-barrier * float(barrier_params["barrier_scale"])),
                0.0,
                float(barrier_params["barrier_factor_max"]),
            )
            src_list.append(index[color_a])
            dst_list.append(index[color_b])
            weight_list.append(flow_weight / flow_total)
            barrier_list.append(barrier_factor)
    return {
        "index": index,
        "src": np.asarray(src_list, dtype=np.int32),
        "dst": np.asarray(dst_list, dtype=np.int32),
        "weight": np.asarray(weight_list, dtype=np.float64),
        "barrier_factor": np.asarray(barrier_list, dtype=np.float64),
        "dead_end": dead_end,
        "survival": np.asarray([
            compute_transport_survival(
                float(graph["provinces"][color]["area_px"]),
                float(moisture_params["transport_length_px"]),
            )
            for color in land
        ], dtype=np.float64),
    }


def propagate_moisture(
    graph: dict[str, Any], land: list[str], moisture_values: dict[str, float], capacities: dict[str, float],
    constraints: dict[str, dict[str, Any]], overrides: dict[str, dict[str, Any]],
    wind_vectors: dict[str, tuple[float, float]], moisture_params: dict[str, Any], barrier_params: dict[str, Any],
    routing: dict[str, Any] | None = None,
) -> dict[str, dict[str, float] | int | float | bool]:
    import numpy as np

    if routing is None:
        routing = build_transport_routing(
            graph, land, constraints, overrides, wind_vectors,
            moisture_params, barrier_params,
        )
    src = routing["src"]
    dst = routing["dst"]
    weight = routing["weight"]
    barrier_factor = routing["barrier_factor"]
    survival = routing["survival"]
    dead_end = routing["dead_end"]
    size = len(land)
    moisture = np.asarray([moisture_values[color] for color in land], dtype=np.float64)
    capacity = np.asarray([capacities[color] for color in land], dtype=np.float64)
    pending = moisture.copy()
    rainfall = np.zeros(size, dtype=np.float64)
    transit_rainfall = np.zeros(size, dtype=np.float64)
    orographic = np.zeros(size, dtype=np.float64)
    blocked_total = np.zeros(size, dtype=np.float64)
    blocked_dissipated = np.zeros(size, dtype=np.float64)
    forced_mask = np.asarray([
        bool(overrides[color]["climate_lock"] and overrides[color]["force_moisture"] is not None)
        for color in land
    ], dtype=bool)
    forced_values = np.asarray([
        float(overrides[color]["force_moisture"] or 0.0) for color in land
    ], dtype=np.float64)
    epsilon = float(moisture_params["improvement_epsilon"])
    efficiency = float(barrier_params["windward_efficiency"])
    overflow_factor = float(moisture_params["overflow_to_rainfall_factor"])
    iterations = 0
    transport_converged = False
    residual_wave_max = 0.0
    for iterations in range(1, int(moisture_params["max_transport_iterations"]) + 1):
        pending[pending < epsilon] = 0.0
        residual_wave_max = float(pending.max(initial=0.0))
        if residual_wave_max < epsilon:
            transport_converged = True
            break
        transit = pending * (1.0 - survival)
        dead_extra = np.where(dead_end, pending * survival, 0.0)
        rainfall += transit + dead_extra
        transit_rainfall += transit + dead_extra
        edge_transfer = pending[src] * survival[src] * weight
        blocked = edge_transfer * barrier_factor
        windward = blocked * efficiency
        passed = edge_transfer - blocked
        orographic += np.bincount(dst, weights=windward, minlength=size)
        blocked_total += np.bincount(dst, weights=blocked, minlength=size)
        blocked_dissipated += np.bincount(dst, weights=blocked - windward, minlength=size)
        rainfall += np.bincount(dst, weights=windward, minlength=size)
        incoming = np.bincount(dst, weights=passed, minlength=size)
        space = np.maximum(0.0, capacity - moisture)
        absorbed = np.minimum(incoming, space)
        overflow = np.maximum(0.0, incoming - absorbed)
        rainfall += overflow * overflow_factor
        moisture += absorbed
        moisture[forced_mask] = forced_values[forced_mask]
        pending = absorbed
        pending[forced_mask] = 0.0
    else:
        pending[pending < epsilon] = 0.0
        residual_wave_max = float(pending.max(initial=0.0))
    for position, color in enumerate(land):
        moisture_values[color] = float(moisture[position])
    return {
        "rainfall": {color: float(rainfall[position]) for position, color in enumerate(land)},
        "transit_rainfall": {color: float(transit_rainfall[position]) for position, color in enumerate(land)},
        "orographic_rain": {color: float(orographic[position]) for position, color in enumerate(land)},
        "blocked_moisture": {color: float(blocked_total[position]) for position, color in enumerate(land)},
        "blocked_dissipated": {color: float(blocked_dissipated[position]) for position, color in enumerate(land)},
        "queue_operations": iterations,
        "transport_converged": transport_converged,
        "transport_iterations": iterations,
        "transport_residual_wave_max": residual_wave_max,
    }


def apply_vertical_motion(
    graph: dict[str, Any], land: list[str], moisture_values: dict[str, float], rainfall: dict[str, float],
    overrides: dict[str, dict[str, Any]], vertical_motion: dict[str, float], itcz_weights: dict[str, float],
    seasonal: dict[str, Any],
) -> None:
    for color in land:
        if overrides[color]["exclude_from_sim"]:
            moisture_values[color] = rainfall[color] = 0.0
            continue
        if vertical_motion[color] < 0.0:
            condensation = moisture_values[color] * float(seasonal["itcz_conversion_rate"]) * itcz_weights[color]
            rainfall[color] += condensation
            moisture_values[color] = max(0.0, moisture_values[color] - condensation)
        if vertical_motion[color] > 0.0:
            drain_factor = clamp(vertical_motion[color] * float(seasonal["drain_strength"]), 0.0, 1.0)
            moisture_values[color] = max(0.0, moisture_values[color] * (1.0 - drain_factor))
            rainfall[color] = max(0.0, rainfall[color] * (1.0 - float(seasonal["suppression_factor"]) * drain_factor))
        override = overrides[color]
        if override["climate_lock"] and override["force_moisture"] is not None:
            moisture_values[color] = float(override["force_moisture"])
        if override["climate_lock"] and override["force_rainfall"] is not None:
            rainfall[color] = float(override["force_rainfall"])


def water_balance(
    land: list[str], temperatures: dict[str, float], moisture_values: dict[str, float], rainfall: dict[str, float],
    capacities: dict[str, float], storage: dict[str, float], overrides: dict[str, dict[str, Any]], seasonal: dict[str, Any],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    et: dict[str, float] = {}
    runoff: dict[str, float] = {}
    next_storage: dict[str, float] = {}
    vegetation: dict[str, float] = {}
    epsilon = float(seasonal["numeric_epsilon"])
    storage_capacity = float(seasonal["storage_capacity"])
    for color in land:
        if overrides[color]["exclude_from_sim"]:
            et[color] = runoff[color] = next_storage[color] = vegetation[color] = 0.0
            continue
        pet = max(0.0, temperatures[color] + 5.0) * float(seasonal["pet_coefficient"])
        vegetation[color] = clamp(moisture_values[color] / max(capacities[color], epsilon), 0.0, 1.0)
        demand = pet * float(seasonal["bare_soil_coeff"]) * (1.0 - vegetation[color])
        demand += pet * float(seasonal["transpiration_coeff"]) * vegetation[color]
        available = rainfall[color] + storage[color]
        et[color] = min(available, demand)
        remaining = available - et[color]
        runoff[color] = max(0.0, remaining - storage_capacity)
        next_storage[color] = clamp(remaining - runoff[color], 0.0, storage_capacity)
    return et, runoff, next_storage, vegetation


def run_season(
    graph: dict[str, Any], land: list[str], constraints: dict[str, dict[str, Any]], overrides: dict[str, dict[str, Any]],
    temperatures: dict[str, float], capacities: dict[str, float], recycling: dict[str, float], storage: dict[str, float],
    wind_vectors: dict[str, tuple[float, float]], vertical_motion: dict[str, float], itcz_weights: dict[str, float],
    coastal_multipliers: dict[str, float], params: dict[str, dict[str, Any]],
    routing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    validate_force_moisture(overrides, capacities)
    moisture_values = initialize_moisture(
        graph, constraints, overrides, capacities, recycling, land,
        params["moisture_transport"], coastal_multipliers,
    )
    kernel = propagate_moisture(
        graph, land, moisture_values, capacities, constraints, overrides,
        wind_vectors, params["moisture_transport"], params["mountain_barrier"], routing,
    )
    rainfall = kernel["rainfall"]
    assert isinstance(rainfall, dict)
    apply_vertical_motion(
        graph, land, moisture_values, rainfall, overrides, vertical_motion,
        itcz_weights, params["seasonal_climate"],
    )
    et, runoff, next_storage, vegetation = water_balance(land, temperatures, moisture_values, rainfall, capacities, storage, overrides, params["seasonal_climate"])
    return {"temperature": temperatures, "capacity": capacities, "moisture": moisture_values, "rainfall": rainfall, "ET": et, "runoff": runoff, "storage": next_storage, "vegetation_proxy": vegetation, **kernel}


def reuse_season_forcing(
    previous: dict[str, Any], land: list[str], storage: dict[str, float],
    overrides: dict[str, dict[str, Any]], seasonal: dict[str, Any],
) -> dict[str, Any]:
    et, runoff, next_storage, vegetation = water_balance(
        land,
        previous["temperature"],
        previous["moisture"],
        previous["rainfall"],
        previous["capacity"],
        storage,
        overrides,
        seasonal,
    )
    return {
        **previous,
        "ET": et,
        "runoff": runoff,
        "storage": next_storage,
        "vegetation_proxy": vegetation,
        "queue_operations": 0,
    }


def run_spinup(
    graph: dict[str, Any], bootstrap: dict[str, Any], land: list[str], constraints: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]], params: dict[str, dict[str, Any]], equator_temp: float, pole_temp: float,
    lapse_rate: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    seasonal = params["seasonal_climate"]
    local_summer_temp, local_winter_temp = compute_temperatures(
        graph, bootstrap, constraints, overrides, land, seasonal,
        equator_temp, pole_temp, lapse_rate,
    )
    july_temp, january_temp = map_local_temperatures_to_passes(
        graph, land, local_summer_temp, local_winter_temp
    )
    july_capacity = compute_capacities(july_temp, params["moisture_transport"])
    january_capacity = compute_capacities(january_temp, params["moisture_transport"])
    wind_vectors = {color: compute_wind_vector(float(graph["provinces"][color]["latitude"]), params["moisture_transport"]) for color in land}
    routing = build_transport_routing(
        graph, land, constraints, overrides, wind_vectors,
        params["moisture_transport"], params["mountain_barrier"],
    )
    offset = float(seasonal["northern_summer_itcz_offset"])
    sigma = float(seasonal["itcz_sigma"])
    july_vmi = {color: compute_vertical_motion(float(graph["provinces"][color]["latitude"]), seasonal, offset) for color in land}
    january_vmi = {color: compute_vertical_motion(float(graph["provinces"][color]["latitude"]), seasonal, -offset) for color in land}
    july_itcz = {color: compute_itcz_weight(float(graph["provinces"][color]["latitude"]), offset, sigma) for color in land}
    january_itcz = {color: compute_itcz_weight(float(graph["provinces"][color]["latitude"]), -offset, sigma) for color in land}
    summer_mult = float(seasonal["summer_coastal_factor_multiplier"])
    winter_mult = float(seasonal["winter_coastal_factor_multiplier"])
    july_coastal = {color: summer_mult if float(graph["provinces"][color]["latitude"]) >= 0.0 else winter_mult for color in land}
    january_coastal = {color: winter_mult if float(graph["provinces"][color]["latitude"]) >= 0.0 else summer_mult for color in land}
    recycling = {color: 0.0 for color in land}
    history: list[dict[str, float | int]] = []
    spinup_warnings: list[str] = []
    transport_nonconverged_passes = 0
    transport_residual_wave_max = 0.0
    final_july: dict[str, Any] | None = None
    final_january: dict[str, Any] | None = None
    previous_july_moisture: dict[str, float] | None = None
    previous_january_moisture: dict[str, float] | None = None
    converged = False
    numeric_epsilon = float(seasonal["numeric_epsilon"])
    for year in range(1, int(seasonal["max_spinup_years"]) + 1):
        # Phase 1 converges climate forcing only. Long-term storage is solved
        # analytically after convergence; only July -> January carry is kept.
        storage = {color: 0.0 for color in land}
        final_july = run_season(
            graph, land, constraints, overrides, july_temp, july_capacity,
            recycling, storage, wind_vectors, july_vmi, july_itcz,
            july_coastal, params, routing,
        )
        if not bool(final_july.get("transport_converged", True)):
            transport_nonconverged_passes += 1
        transport_residual_wave_max = max(
            transport_residual_wave_max,
            float(final_july.get("transport_residual_wave_max", 0.0)),
        )
        storage = final_july["storage"]
        final_january = run_season(
            graph, land, constraints, overrides, january_temp, january_capacity,
            recycling, storage, wind_vectors, january_vmi, january_itcz,
            january_coastal, params, routing,
        )
        if not bool(final_january.get("transport_converged", True)):
            transport_nonconverged_passes += 1
        transport_residual_wave_max = max(
            transport_residual_wave_max,
            float(final_january.get("transport_residual_wave_max", 0.0)),
        )
        storage = final_january["storage"]
        previous_recycling = recycling.copy()
        for color in land:
            annual_et = final_july["ET"][color] + final_january["ET"][color]
            capped = min(annual_et * float(seasonal["recycling_fraction"]), annual_et * float(seasonal["max_recycling_share"]))
            updated = recycling[color] * (1.0 - float(seasonal["relaxation_alpha"])) + capped * float(seasonal["relaxation_alpha"])
            recycling[color] = updated
        recycling_scale = max(max(recycling.values(), default=0.0), numeric_epsilon)
        recycling_residual = max(abs(recycling[color] - previous_recycling[color]) for color in land) / recycling_scale
        if previous_july_moisture is None or previous_january_moisture is None:
            moisture_residual = 1.0
        else:
            moisture_scale = max(
                max(final_july["moisture"].values(), default=0.0),
                max(final_january["moisture"].values(), default=0.0),
                numeric_epsilon,
            )
            moisture_residual = max(
                max(abs(final_july["moisture"][color] - previous_july_moisture[color]) for color in land),
                max(abs(final_january["moisture"][color] - previous_january_moisture[color]) for color in land),
            ) / moisture_scale
        history.append({
            "year": year,
            "moisture_residual": moisture_residual,
            "recycling_residual": recycling_residual,
        })
        previous_july_moisture = final_july["moisture"].copy()
        previous_january_moisture = final_january["moisture"].copy()
        if (
            moisture_residual < float(seasonal["climate_moisture_epsilon"])
            and recycling_residual < float(seasonal["climate_recycling_epsilon"])
        ):
            converged = True
            break
    if final_july is None or final_january is None:
        raise RuntimeError(
            "climate spin-up produced no seasonal result "
            f"within {seasonal['max_spinup_years']} years"
        )
    if not converged:
        spinup_warnings.append(
            "climate spin-up did not converge; using best-effort result at "
            f"{seasonal['max_spinup_years']} years "
            f"(moisture_residual={history[-1]['moisture_residual']:.8f}, "
            f"recycling_residual={history[-1]['recycling_residual']:.8f})"
        )
    if transport_nonconverged_passes:
        spinup_warnings.append(
            "moisture transport reached max_transport_iterations in "
            f"{transport_nonconverged_passes} seasonal pass(es); "
            f"max residual_wave={transport_residual_wave_max:.8f}"
        )
    storage_capacity = float(seasonal["storage_capacity"])
    storage_years = float(seasonal["soil_storage_time_years"])
    analytical_storage = {
        color: compute_analytical_storage(
            final_july["rainfall"][color] + final_january["rainfall"][color],
            final_july["ET"][color] + final_january["ET"][color],
            storage_years,
            storage_capacity,
        )
        for color in land
    }
    return {
        "july": final_july,
        "january": final_january,
        "soil_water_storage_final": analytical_storage,
        "recycling_source_final": recycling,
        "july_vertical_motion_index": july_vmi,
        "january_vertical_motion_index": january_vmi,
        "province_latitudes": {
            color: float(graph["provinces"][color]["latitude"]) for color in land
        },
    }, {
        "converged": converged,
        "climate_converged": converged,
        "years": len(history),
        "spinup_years_used": len(history),
        "max_years": int(seasonal["max_spinup_years"]),
        "transport_converged": transport_nonconverged_passes == 0,
        "transport_nonconverged_passes": transport_nonconverged_passes,
        "transport_residual_wave_max": transport_residual_wave_max,
        "warnings": spinup_warnings,
        "history": history,
    }


def assemble_output(
    simulation: dict[str, Any], land: list[str], hashes: dict[str, str], sources: dict[str, str], spinup: dict[str, Any],
) -> dict[str, Any]:
    july = simulation["july"]
    january = simulation["january"]
    epsilon = 0.000001
    output_provinces: dict[str, dict[str, float]] = {}
    for color in land:
        latitude = float(simulation["province_latitudes"][color]) if "province_latitudes" in simulation else 0.0
        summer = july if latitude >= 0.0 else january
        winter = january if latitude >= 0.0 else july
        summer_vmi = (
            simulation["july_vertical_motion_index"][color]
            if latitude >= 0.0
            else simulation["january_vertical_motion_index"][color]
        )
        winter_vmi = (
            simulation["january_vertical_motion_index"][color]
            if latitude >= 0.0
            else simulation["july_vertical_motion_index"][color]
        )
        sr = round(float(summer["rainfall"][color]), 8)
        wr = round(float(winter["rainfall"][color]), 8)
        annual = round(sr + wr, 8)
        wet = max(sr, wr)
        dry = min(sr, wr)
        dry_strength = clamp(1.0 - dry / max(annual / 2.0, epsilon), 0.0, 1.0)
        seasonality = abs(sr - wr) / (annual + epsilon)
        st = round(float(summer["temperature"][color]), 6)
        wt = round(float(winter["temperature"][color]), 6)
        output_provinces[color] = {
            "annual_rainfall_raw": annual,
            "summer_rainfall_raw": sr,
            "winter_rainfall_raw": wr,
            "wet_season_rainfall_raw": round(wet, 8),
            "dry_season_rainfall_raw": round(dry, 8),
            "dry_season_strength": round(dry_strength, 8),
            "rainfall_seasonality": round(seasonality, 8),
            "mean_temperature": round((st + wt) / 2.0, 6),
            "summer_temperature": st,
            "winter_temperature": wt,
            "annual_ET": round(float(summer["ET"][color]) + float(winter["ET"][color]), 8),
            "annual_runoff": round(float(summer["runoff"][color]) + float(winter["runoff"][color]), 8),
            "soil_water_storage_final": round(float(simulation["soil_water_storage_final"][color]), 8),
            "annual_transit_rainfall_raw": round(float(summer["transit_rainfall"][color]) + float(winter["transit_rainfall"][color]), 8),
            "vertical_motion_index": round((float(summer_vmi) + float(winter_vmi)) / 2.0, 8),
            "summer_vertical_motion_index": round(float(summer_vmi), 8),
            "winter_vertical_motion_index": round(float(winter_vmi), 8),
        }
    return {"schema_version": SCHEMA_VERSION, "source": sources, "hash": hashes, "spinup": spinup, "provinces": output_provinces}


def validate_output(output: dict[str, Any], land: list[str]) -> None:
    if output.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("seasonal output schema_version mismatch")
    provinces = output.get("provinces")
    if not isinstance(provinces, dict) or set(provinces) != set(land):
        raise ValueError("seasonal output land coverage mismatch")
    for color, values in provinces.items():
        for key, value in values.items():
            finite_number(value, f"{color}.{key}")
        if values["summer_temperature"] + 1e-6 < values["winter_temperature"]:
            raise ValueError(f"summer_temperature < winter_temperature ({color})")
        if abs(values["annual_rainfall_raw"] - round(values["summer_rainfall_raw"] + values["winter_rainfall_raw"], 8)) > 1e-8:
            raise ValueError(f"seasonal rainfall sum mismatch ({color})")
        if values["annual_rainfall_raw"] < 0.0 or values["annual_ET"] < 0.0 or values["annual_runoff"] < 0.0:
            raise ValueError(f"negative water field ({color})")
        if not 0.0 <= values["dry_season_strength"] <= 1.0:
            raise ValueError(f"dry_season_strength out of range ({color})")


def compute_ranges(provinces: dict[str, dict[str, float]]) -> dict[str, list[float]]:
    keys = next(iter(provinces.values())).keys()
    return {key: [min(values[key] for values in provinces.values()), max(values[key] for values in provinces.values())] for key in keys}


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temp, path)


def color_to_int(color: str) -> int:
    return int(color[1:], 16)


def write_debug_images(project_root: Path, debug_dir: Path, graph: dict[str, Any], output: dict[str, Any], constraints: dict[str, dict[str, Any]], simulation: dict[str, Any]) -> list[Path]:
    import numpy as np
    from PIL import Image, ImageDraw

    source = Path(graph["metadata"]["source_files"]["provinces_png"])
    if not source.is_absolute():
        source = project_root / source
    image = Image.open(source).convert("RGB")
    preview_size = (min(2048, image.width), max(1, round(image.height * min(2048, image.width) / image.width)))
    image = image.resize(preview_size, Image.Resampling.NEAREST)
    rgb = np.asarray(image, dtype=np.uint32)
    ids = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    debug_dir.mkdir(parents=True, exist_ok=True)
    province_values = output["provinces"]
    final_july = simulation["july"]
    final_january = simulation["january"]
    annual_rainfall = {c: float(v["annual_rainfall_raw"]) for c, v in province_values.items()}
    fields: list[tuple[str, dict[str, float], str]] = [
        ("annual_rainfall_raw_map.png", annual_rainfall, "blue"),
        ("annual_rainfall_log_map.png", {c: math.log10(1.0 + value) for c, value in annual_rainfall.items()}, "blue"),
        ("mean_temperature_map.png", {c: v["mean_temperature"] for c, v in province_values.items()}, "temperature"),
        ("vertical_motion_index_map.png", {c: v["vertical_motion_index"] for c, v in province_values.items()}, "diverging"),
        ("dry_season_strength_map.png", {c: v["dry_season_strength"] for c, v in province_values.items()}, "dry"),
        ("mountain_strength_map.png", {c: float(constraints[c]["mountain_strength"]) for c in province_values}, "mountain"),
        ("orographic_rain_map.png", {c: float(final_july["orographic_rain"][c]) + float(final_january["orographic_rain"][c]) for c in province_values}, "blue"),
        ("blocked_moisture_map.png", {c: float(final_july["blocked_moisture"][c]) + float(final_january["blocked_moisture"][c]) for c in province_values}, "purple"),
    ]
    paths: list[Path] = []
    for filename, values, palette in fields:
        lookup = np.zeros((1 << 24, 3), dtype=np.uint8)
        finite_values = np.asarray(list(values.values()), dtype=np.float64)
        low = float(np.min(finite_values)) if finite_values.size else 0.0
        high = float(np.percentile(finite_values, 99.0)) if finite_values.size else 1.0
        if palette == "temperature":
            low, high = -30.0, 35.0
        elif palette in {"diverging", "dry", "mountain"}:
            low, high = (-1.0, 1.0) if palette == "diverging" else (0.0, 1.0)
        span = max(high - low, 1e-9)
        for color, value in values.items():
            t = clamp((float(value) - low) / span, 0.0, 1.0)
            if palette == "blue":
                rgb_value = (int(245 * (1.0 - t)), int(250 * (1.0 - t)), int(80 + 175 * t))
            elif palette == "temperature":
                rgb_value = (int(40 + 215 * t), int(100 + 80 * (1.0 - abs(2.0 * t - 1.0))), int(255 - 215 * t))
            elif palette == "diverging":
                rgb_value = (int(40 + 215 * t), int(230 - 170 * abs(2.0 * t - 1.0)), int(255 - 215 * t))
            elif palette == "dry":
                rgb_value = (int(80 + 175 * t), int(180 - 100 * t), int(60 - 40 * t))
            elif palette == "mountain":
                rgb_value = (int(245 - 135 * t), int(245 - 175 * t), int(235 - 195 * t))
            else:
                rgb_value = (int(230 * (1.0 - t) + 100 * t), int(230 * (1.0 - t)), int(230 * (1.0 - t) + 180 * t))
            lookup[color_to_int(color)] = rgb_value
        rendered = lookup[ids]
        path = debug_dir / filename
        Image.fromarray(rendered, mode="RGB").save(path)
        paths.append(path)
    zonal_path = debug_dir / "zonal_mean_rainfall.png"
    write_zonal_mean_rainfall_image(zonal_path, graph, annual_rainfall)
    paths.append(zonal_path)
    return paths


def write_zonal_mean_rainfall_image(path: Path, graph: dict[str, Any], annual_rainfall: dict[str, float]) -> None:
    from PIL import Image, ImageDraw

    bin_size = 5
    bins: list[dict[str, float]] = []
    for start in range(-90, 90, bin_size):
        bins.append({"start": float(start), "end": float(start + bin_size), "sum": 0.0, "count": 0.0})
    for color, rainfall in annual_rainfall.items():
        province = graph["provinces"].get(color)
        if not province:
            continue
        latitude = clamp(float(province["latitude"]), -89.999999, 89.999999)
        index = int((latitude + 90.0) // bin_size)
        index = max(0, min(len(bins) - 1, index))
        bins[index]["sum"] += float(rainfall)
        bins[index]["count"] += 1.0
    points = []
    for entry in bins:
        if entry["count"] <= 0.0:
            continue
        latitude_mid = (entry["start"] + entry["end"]) * 0.5
        mean = entry["sum"] / entry["count"]
        points.append((latitude_mid, mean, int(entry["count"])))

    width, height = 1200, 720
    margin_left, margin_right, margin_top, margin_bottom = 92, 36, 48, 84
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    image = Image.new("RGB", (width, height), (255, 255, 248))
    draw = ImageDraw.Draw(image)

    if not points:
        draw.text((margin_left, margin_top), "No rainfall data", fill=(60, 60, 60))
        image.save(path)
        return

    max_mean = max(value for _, value, _ in points)
    y_max = max(max_mean * 1.1, 1e-6)

    def x_for_lat(latitude: float) -> int:
        return int(margin_left + ((latitude + 90.0) / 180.0) * plot_w)

    def y_for_rain(rainfall: float) -> int:
        return int(margin_top + (1.0 - clamp(rainfall / y_max, 0.0, 1.0)) * plot_h)

    # Grid and axes.
    for lat in range(-90, 91, 30):
        x = x_for_lat(float(lat))
        draw.line([(x, margin_top), (x, margin_top + plot_h)], fill=(225, 225, 215))
        draw.text((x - 16, margin_top + plot_h + 10), f"{lat}", fill=(70, 70, 70))
    for step in range(0, 6):
        value = y_max * step / 5.0
        y = y_for_rain(value)
        draw.line([(margin_left, y), (margin_left + plot_w, y)], fill=(225, 225, 215))
        draw.text((12, y - 7), f"{value:.3f}", fill=(70, 70, 70))
    draw.rectangle(
        [(margin_left, margin_top), (margin_left + plot_w, margin_top + plot_h)],
        outline=(70, 70, 70),
        width=2,
    )
    draw.line(
        [(x_for_lat(0.0), margin_top), (x_for_lat(0.0), margin_top + plot_h)],
        fill=(210, 80, 80),
        width=2,
    )
    for lat in (-30, 30):
        draw.line(
            [(x_for_lat(float(lat)), margin_top), (x_for_lat(float(lat)), margin_top + plot_h)],
            fill=(230, 170, 80),
            width=2,
        )

    for previous, current in zip(points, points[1:]):
        lat_a, mean_a, count_a = previous
        lat_b, mean_b, count_b = current
        low_sample = count_a < 50 or count_b < 50
        color = (130, 130, 130) if low_sample else (30, 95, 190)
        width_px = 2 if low_sample else 4
        xy_a = (x_for_lat(lat_a), y_for_rain(mean_a))
        xy_b = (x_for_lat(lat_b), y_for_rain(mean_b))
        if low_sample:
            draw_dashed_line(draw, xy_a, xy_b, fill=color, width=width_px, dash=8, gap=6)
        else:
            draw.line([xy_a, xy_b], fill=color, width=width_px)
    for latitude, mean, count in points:
        x, y = x_for_lat(latitude), y_for_rain(mean)
        if count < 50:
            draw.ellipse([(x - 3, y - 3), (x + 3, y + 3)], fill=(130, 130, 130))
            draw.text((x + 5, max(margin_top, y - 14)), f"n={count}", fill=(105, 105, 105))
        else:
            draw.ellipse([(x - 2, y - 2), (x + 2, y + 2)], fill=(30, 95, 190))

    eq_values = [mean for latitude, mean, _ in points if abs(latitude) <= 10.0]
    mid_values = [mean for latitude, mean, _ in points if 30.0 <= abs(latitude) <= 50.0]
    eq_mean = sum(eq_values) / len(eq_values) if eq_values else 0.0
    mid_mean = sum(mid_values) / len(mid_values) if mid_values else 0.0
    ratio = eq_mean / mid_mean if mid_mean > 0.0 else float("inf")

    draw.text((margin_left, 16), "Zonal mean annual rainfall raw, 5-degree latitude bins", fill=(30, 30, 30))
    draw.text((margin_left, height - 40), "Latitude (degrees). Red=equator, orange=subtropical reference lines", fill=(70, 70, 70))
    draw.text((width - 390, 16), f"equator/midlat ratio: {ratio:.2f}", fill=(30, 30, 30))
    draw.text((width - 390, 38), f"equator mean: {eq_mean:.4f}  midlat mean: {mid_mean:.4f}", fill=(30, 30, 30))
    draw_dashed_line(draw, (width - 390, 66), (width - 330, 66), fill=(130, 130, 130), width=2, dash=8, gap=6)
    draw.text((width - 320, 58), "n<50: low-sample bin", fill=(105, 105, 105))
    image.save(path)


def draw_dashed_line(
    draw: Any,
    start: tuple[int, int],
    end: tuple[int, int],
    fill: tuple[int, int, int],
    width: int = 1,
    dash: int = 8,
    gap: int = 6,
) -> None:
    distance = math.hypot(end[0] - start[0], end[1] - start[1])
    if distance <= 0.0:
        return
    dx = (end[0] - start[0]) / distance
    dy = (end[1] - start[1]) / distance
    position = 0.0
    while position < distance:
        segment_end = min(position + dash, distance)
        a = (int(start[0] + dx * position), int(start[1] + dy * position))
        b = (int(start[0] + dx * segment_end), int(start[1] + dy * segment_end))
        draw.line([a, b], fill=fill, width=width)
        position += dash + gap


def build_seasonal_climate(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = load_json(args.province_graph, "province_graph.json")
    bootstrap = load_json(args.bootstrap_fields, "bootstrap_fields.json")
    land, graph_hash = validate_upstream(graph, bootstrap)
    raw_constraints = load_mapping_document(args.province_constraints, "province_constraints.yaml", "province_constraints")
    raw_overrides = load_mapping_document(args.province_overrides, "province_overrides.yaml", "province_overrides")
    constraints, warnings = normalize_constraints(raw_constraints, land)
    overrides, override_warnings = normalize_overrides(raw_overrides, land)
    warnings.extend(override_warnings)
    params = load_params(args.params)
    max_spinup_override = getattr(args, "max_spinup_years", None)
    if max_spinup_override is not None:
        if max_spinup_override < 1:
            raise ValueError("--max-spinup-years must be at least 1")
        configured_max = int(params["seasonal_climate"]["max_spinup_years"])
        params["seasonal_climate"]["max_spinup_years"] = int(max_spinup_override)
        warnings.append(
            f"diagnostic spin-up override: {configured_max} -> {max_spinup_override} years"
        )
    if bool(getattr(args, "allow_nonconverged", False)):
        params["seasonal_climate"]["diagnostic_allow_nonconverged"] = True
        warnings.append("diagnostic output allowed before annual spin-up convergence")
    world = load_yaml(args.world, "world.yaml")
    reference = world.get("climate_reference", {})
    equator_temp = finite_number(reference.get("equator_temp_c", 28.0), "world.climate_reference.equator_temp_c")
    pole_temp = finite_number(reference.get("pole_temp_c", -20.0), "world.climate_reference.pole_temp_c")
    lapse_rate = finite_number(reference.get("lapse_rate_c_per_km", 6.5), "world.climate_reference.lapse_rate_c_per_km")
    simulation, spinup = run_spinup(graph, bootstrap, land, constraints, overrides, params, equator_temp, pole_temp, lapse_rate)
    warnings.extend(spinup.get("warnings", []))
    hashes = {
        "graph_hash": graph_hash,
        "bootstrap_hash": canonical_hash(bootstrap),
        "constraints_hash": canonical_hash(constraints),
        "overrides_hash": canonical_hash(overrides),
        "params_hash": canonical_hash(params),
    }
    sources = {
        "province_graph": display_path(args.province_graph, args.project_root),
        "bootstrap_fields": display_path(args.bootstrap_fields, args.project_root),
        "province_constraints": display_path(args.province_constraints, args.project_root),
        "province_overrides": display_path(args.province_overrides, args.project_root),
        "climate_rules": display_path(args.params, args.project_root),
        "world": display_path(args.world, args.project_root),
    }
    output = assemble_output(simulation, land, hashes, sources, spinup)
    validate_output(output, land)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "success",
        "warnings": warnings,
        "known_biases": ["foehn warming omitted because leeward detection is not specified"],
        "counts": {"land_targets": len(land), "sea_excluded": len(graph["provinces"]) - len(land), "constraints_provided": len(set(raw_constraints) & set(land)), "overrides_provided": len(set(raw_overrides) & set(land)), "excluded_from_sim": sum(1 for value in overrides.values() if value["exclude_from_sim"]), "climate_locked": sum(1 for value in overrides.values() if value["climate_lock"])},
        "spinup": spinup,
        "hashes": hashes,
        "ranges": compute_ranges(output["provinces"]),
        "params": params,
    }
    return output, {"graph": graph, "constraints": constraints, "simulation": simulation, "warnings": warnings, "report": report}


def write_debug_outputs(args: argparse.Namespace, output: dict[str, Any], diagnostics: dict[str, Any]) -> list[Path]:
    args.report_dir.mkdir(parents=True, exist_ok=True)
    report_path = args.report_dir / "seasonal_climate_build_report.json"
    atomic_write_json(report_path, diagnostics["report"], pretty=True)
    csv_path = args.report_dir / "seasonal_climate_stats.csv"
    rows = [{"province": color, **values} for color, values in output["provinces"].items()]
    try:
        write_csv(csv_path, ["province", *next(iter(output["provinces"].values())).keys()], rows)
    except PermissionError:
        csv_path = args.report_dir / "seasonal_climate_stats.latest.csv"
        write_csv(csv_path, ["province", *next(iter(output["provinces"].values())).keys()], rows)
    paths = [report_path, csv_path]
    paths.extend(write_debug_images(args.project_root, args.debug_dir, diagnostics["graph"], output, diagnostics["constraints"], diagnostics["simulation"]))
    return paths


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    province_project = project_root.parent / "프로빈스_프로젝트"
    return {
        "project_root": project_root,
        "province_graph": project_root / "cache" / "province_graph.json",
        "bootstrap_fields": project_root / "cache" / "bootstrap_fields.json",
        "province_constraints": province_project / "config" / "province_constraints.yaml",
        "province_overrides": province_project / "config" / "province_overrides.yaml",
        "params": project_root / "config" / "climate_rules.yaml",
        "world": project_root / "config" / "world.yaml",
        "output": project_root / "cache" / "seasonal_climate.json",
        "debug_dir": project_root / "outputs" / "debug",
        "report_dir": project_root / "cache" / "debug",
    }


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Build seasonal_climate.v0.4 cache")
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--province-graph", type=Path, default=defaults["province_graph"])
    parser.add_argument("--bootstrap-fields", type=Path, default=defaults["bootstrap_fields"])
    parser.add_argument("--province-constraints", type=Path, default=defaults["province_constraints"])
    parser.add_argument("--province-overrides", type=Path, default=defaults["province_overrides"])
    parser.add_argument("--params", type=Path, default=defaults["params"])
    parser.add_argument("--world", type=Path, default=defaults["world"])
    parser.add_argument("--output", type=Path, default=defaults["output"])
    parser.add_argument("--debug-dir", type=Path, default=defaults["debug_dir"])
    parser.add_argument("--report-dir", type=Path, default=defaults["report_dir"])
    parser.add_argument(
        "--max-spinup-years",
        type=int,
        default=None,
        help="diagnostic override; included in params_hash",
    )
    parser.add_argument(
        "--allow-nonconverged",
        action="store_true",
        help="diagnostic only; write a test output at the spin-up limit",
    )
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output, diagnostics = build_seasonal_climate(args)
        warnings = diagnostics["warnings"]
        if warnings and args.fail_on_warning:
            for warning in warnings:
                print(f"WARNING: {warning}")
            return 2
        atomic_write_json(args.output, output, pretty=args.pretty)
        artifacts = write_debug_outputs(args, output, diagnostics) if args.debug else []
        print(f"wrote: {args.output}")
        print(f"schema_version: {output['schema_version']}")
        print(f"land_province_count: {len(output['provinces'])}")
        print(f"spinup_years: {output['spinup']['years']}")
        print(f"graph_hash: {output['hash']['graph_hash']}")
        print(f"params_hash: {output['hash']['params_hash']}")
        print(f"warnings: {len(warnings)}")
        for warning in warnings[:20]:
            print(f"WARNING: {warning}")
        print(f"debug_artifacts: {len(artifacts)}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
