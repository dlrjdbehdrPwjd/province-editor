from __future__ import annotations

import argparse
import ast
import heapq
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None


WARM_CURRENTS = {"warm", "warm_current"}
COLD_CURRENTS = {"cold", "cold_current"}


def find_workspace_root(start: Path) -> Path:
    for path in [start, *start.parents]:
        if (path / "map_data").is_dir():
            return path
    return start.parents[1]


def strip_comment(line: str) -> str:
    in_single = False
    in_double = False
    for idx, char in enumerate(line):
        if char == "'" and not in_double:
            in_single = not in_single
        elif char == '"' and not in_single:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:idx]
    return line


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == "":
        return ""
    if value == "{}":
        return {}
    if value == "[]":
        return []
    if value in ("true", "True"):
        return True
    if value in ("false", "False"):
        return False
    if value in ("null", "None", "~"):
        return None
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return value
    try:
        if any(char in value for char in (".", "e", "E")):
            return float(value)
        return int(value)
    except ValueError:
        return value


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        clean = strip_comment(raw_line).rstrip()
        if not clean.strip():
            continue
        indent = len(clean) - len(clean.lstrip(" "))
        lines.append((indent, clean.strip()))

    def next_is_list(index: int, indent: int) -> bool:
        if index >= len(lines):
            return False
        next_indent, next_content = lines[index]
        return next_indent > indent and next_content.startswith("- ")

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(lines):
            return {}, index
        if lines[index][0] < indent:
            return {}, index
        if lines[index][1].startswith("- "):
            result: list[Any] = []
            while index < len(lines):
                line_indent, content = lines[index]
                if line_indent != indent or not content.startswith("- "):
                    break
                item_text = content[2:].strip()
                index += 1
                if item_text == "":
                    item, index = parse_block(index, indent + 2)
                    result.append(item)
                    continue
                if ":" in item_text and not item_text.startswith(("http://", "https://")):
                    key, value = item_text.split(":", 1)
                    item_dict: dict[str, Any] = {}
                    if value.strip():
                        item_dict[key.strip()] = parse_scalar(value.strip())
                    else:
                        nested, index = parse_block(index, indent + 2)
                        item_dict[key.strip()] = nested
                    while index < len(lines) and lines[index][0] > indent:
                        child_indent, child_content = lines[index]
                        if child_indent < indent + 2:
                            break
                        if ":" not in child_content:
                            break
                        child_key, child_value = child_content.split(":", 1)
                        index += 1
                        if child_value.strip():
                            item_dict[child_key.strip()] = parse_scalar(child_value.strip())
                        else:
                            nested, index = parse_block(index, child_indent + 2)
                            item_dict[child_key.strip()] = nested
                    result.append(item_dict)
                else:
                    result.append(parse_scalar(item_text))
            return result, index

        result: dict[str, Any] = {}
        while index < len(lines):
            line_indent, content = lines[index]
            if line_indent < indent:
                break
            if line_indent > indent:
                break
            if content.startswith("- "):
                break
            if ":" not in content:
                index += 1
                continue
            key, value = content.split(":", 1)
            key = key.strip()
            value = value.strip()
            index += 1
            if value:
                result[key] = parse_scalar(value)
            else:
                nested_indent = line_indent + 2
                if next_is_list(index, line_indent):
                    nested_indent = lines[index][0]
                nested, index = parse_block(index, nested_indent)
                result[key] = nested
        return result, index

    parsed, _ = parse_block(0, 0)
    return parsed if isinstance(parsed, dict) else {}


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        return yaml.safe_load(text) or {}
    except ModuleNotFoundError:
        return parse_simple_yaml(text)


def normalize_color(value: str) -> str:
    value = value.strip().strip('"')
    if value.startswith(("x", "X")):
        return "x" + value[1:].upper()
    return value


def int_to_hex(color_int: int) -> str:
    return f"x{(color_int >> 16) & 0xFF:02X}{(color_int >> 8) & 0xFF:02X}{color_int & 0xFF:02X}"


def load_constraints(province_project_root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    config = province_project_root / "config"
    raw_constraints = load_yaml(config / "province_constraints.yaml").get("province_constraints", {})
    raw_overrides = load_yaml(config / "province_overrides.yaml").get("province_overrides", {})
    constraints = {normalize_color(str(color)): data for color, data in raw_constraints.items() if isinstance(data, dict)}
    overrides = {normalize_color(str(color)): data for color, data in raw_overrides.items() if isinstance(data, dict)}
    return constraints, overrides


def load_locked(overrides: dict[str, dict[str, Any]]) -> set[str]:
    return {color for color, data in overrides.items() if data.get("locked", False)}


def compute_temperature(province: dict[str, Any], climate_rules: dict[str, Any], constraints: dict[str, dict[str, Any]]) -> float:
    lat = float(province["latitude"])
    heightmap_usage = climate_rules.get("heightmap_usage", {})
    if heightmap_usage.get("use_for_temperature", False):
        elev_m = float(province["elevation_m"])
    else:
        elev_m = 0.0
    temp_cfg = climate_rules["temperature"]
    eq_t = float(temp_cfg["equator_temperature_c"])
    pole_t = float(temp_cfg["pole_temperature_c"])
    temp = eq_t + (pole_t - eq_t) * (abs(lat) / 90.0)
    temp -= float(temp_cfg["lapse_rate_c_per_1000m"]) * (elev_m / 1000.0)

    constraint = constraints.get(province["color"], {})
    current = str(constraint.get("current", "")).strip()
    if province["is_coastal"] and current:
        current_cfg = climate_rules.get("currents", {})
        if current in WARM_CURRENTS:
            temp += float(current_cfg.get("warm_current_temperature_bonus_c", 0.0))
        elif current in COLD_CURRENTS:
            temp += float(current_cfg.get("cold_current_temperature_penalty_c", 0.0))
    return temp


def compute_capacity(temperature: float, climate_rules: dict[str, Any]) -> float:
    cfg = climate_rules["moisture_capacity"]
    capacity = float(cfg["base"]) * math.exp(float(cfg["temperature_coefficient"]) * (temperature - float(cfg["reference_temperature_c"])))
    return max(float(cfg["min"]), min(float(cfg["max"]), capacity))


def compute_mountain_strengths(
    graph: dict[str, Any],
    constraints: dict[str, dict[str, Any]],
    climate_rules: dict[str, Any],
) -> dict[str, float]:
    cfg = climate_rules.get("mountain_barrier", {})
    heightmap_usage = climate_rules.get("heightmap_usage", {})
    use_auto_heightmap = bool(heightmap_usage.get("use_for_mountain_auto", False))
    threshold = float(cfg.get("mountain_threshold_m", 1200.0))
    high_threshold = float(cfg.get("high_mountain_threshold_m", 2500.0))
    span = max(high_threshold - threshold, 1.0)
    strengths: dict[str, float] = {}
    for color, province in graph["provinces"].items():
        if province["is_sea"]:
            strengths[color] = 0.0
            continue
        if use_auto_heightmap:
            elevation_max = float(province.get("elevation_max_m", province.get("elevation_m", 0.0)))
            auto_strength = clamp01((elevation_max - threshold) / span)
        else:
            auto_strength = 0.0
        user_strength = float(constraints.get(color, {}).get("mountain_strength", 0.0))
        strengths[color] = clamp01(max(auto_strength, user_strength))
    return strengths


def wind_vector_for_band(name: str, directionality: float, is_north: bool) -> tuple[float, float]:
    if name == "itcz":
        raw = (0.0, 1.0 if is_north else -1.0)
    elif name == "trade_winds":
        raw = (-1.0, 0.25 if is_north else -0.25)
    elif name == "westerlies":
        raw = (1.0, -0.15 if is_north else 0.15)
    elif name == "polar_easterlies":
        raw = (-1.0, -0.1 if is_north else 0.1)
    else:
        raw = (0.0, 0.0)
    length = math.hypot(raw[0], raw[1])
    if length <= 0:
        return (0.0, 0.0)
    return (raw[0] / length * directionality, raw[1] / length * directionality)


def compute_wind_vector(latitude: float, climate_rules: dict[str, Any]) -> tuple[float, float]:
    abs_lat = abs(latitude)
    is_north = latitude >= 0
    bands = sorted(climate_rules["wind_bands"], key=lambda item: float(item["abs_lat_min"]))
    transition_width = float(climate_rules.get("wind_transition_width_deg", 0.0))

    if transition_width > 0.0:
        for lower, upper in zip(bands, bands[1:]):
            boundary = float(upper["abs_lat_min"])
            if boundary - transition_width <= abs_lat <= boundary + transition_width:
                t = (abs_lat - (boundary - transition_width)) / (transition_width * 2.0)
                low_vec = wind_vector_for_band(str(lower["name"]), float(lower["directionality"]), is_north)
                high_vec = wind_vector_for_band(str(upper["name"]), float(upper["directionality"]), is_north)
                return (
                    low_vec[0] * (1.0 - t) + high_vec[0] * t,
                    low_vec[1] * (1.0 - t) + high_vec[1] * t,
                )

    for band in bands:
        if float(band["abs_lat_min"]) <= abs_lat < float(band["abs_lat_max"]):
            return wind_vector_for_band(str(band["name"]), float(band["directionality"]), is_north)
    return (0.0, 0.0)


def initialize_moisture(
    graph: dict[str, Any],
    constraints: dict[str, dict[str, Any]],
    climate_rules: dict[str, Any],
    capacity: dict[str, float],
    locked: set[str],
) -> tuple[dict[str, float], dict[str, float]]:
    moisture: dict[str, float] = {}
    rainfall: dict[str, float] = {}
    source_cfg = climate_rules["moisture_source"]

    for color, province in graph["provinces"].items():
        moisture[color] = 0.0
        rainfall[color] = 0.0
        if color in locked:
            continue
        if province["is_sea"]:
            moisture[color] = 1.0
        elif province["is_coastal"]:
            moisture[color] = min(float(province["coastal_ratio"]) * float(source_cfg["coastal_base"]), capacity[color])

        constraint = constraints.get(color, {})
        if constraint.get("wetland_seed"):
            moisture[color] = min(moisture[color] + float(source_cfg["wetland_seed_bonus"]), capacity[color])
        if "moisture_bonus" in constraint:
            moisture[color] = min(moisture[color] + float(constraint["moisture_bonus"]), capacity[color])

    return moisture, rainfall


def propagate_moisture(
    graph: dict[str, Any],
    moisture: dict[str, float],
    rainfall: dict[str, float],
    capacity: dict[str, float],
    wind_vectors: dict[str, tuple[float, float]],
    mountain_strength: dict[str, float],
    climate_rules: dict[str, Any],
    locked: set[str],
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    median_area = max(float(graph["metadata"]["median_area_px"]), 1.0)
    cfg = climate_rules["propagation"]
    base_loss = float(cfg["base_loss"])
    decay_scale = float(cfg["distance_decay_px"])
    epsilon = float(cfg["improvement_epsilon"])
    overflow_rf = float(cfg.get("overflow_rainfall_factor", 0.5))
    export_fraction = float(cfg.get("export_fraction", 0.85))
    wind_leakage_min = float(cfg.get("wind_leakage_min", 0.0))
    barrier_cfg = climate_rules.get("mountain_barrier", {})
    barrier_scale = float(barrier_cfg.get("barrier_scale", 3.0))
    ridge_bonus = float(barrier_cfg.get("ridge_bonus", 0.5))
    windward_efficiency = float(barrier_cfg.get("windward_efficiency", 0.7))

    propagated = {color: 0.0 for color in graph["provinces"]}
    orographic_rain = {color: 0.0 for color in graph["provinces"]}
    rain_shadow = {color: 0.0 for color in graph["provinces"]}
    queue: list[tuple[float, str]] = []
    for color, value in moisture.items():
        if value > 0.0:
            queue.append((-value, color))
    heapq.heapify(queue)

    while queue:
        _, color_a = heapq.heappop(queue)
        if color_a in locked:
            continue
        delta_a = moisture[color_a] - propagated[color_a]
        if delta_a <= epsilon:
            continue
        propagated[color_a] = moisture[color_a]

        province_a = graph["provinces"][color_a]
        wind_a = wind_vectors[color_a]
        candidates: list[tuple[str, dict[str, Any], float]] = []
        for color_b, edge in province_a["neighbors"].items():
            if color_b in locked:
                continue
            province_b = graph["provinces"][color_b]
            if province_b["is_sea"]:
                continue

            direction = edge["direction"]
            wind_b = wind_vectors[color_b]
            dot_a = wind_a[0] * direction[0] + wind_a[1] * direction[1]
            dot_b = wind_b[0] * direction[0] + wind_b[1] * direction[1]
            wind_weight = max(wind_leakage_min, min(dot_a, dot_b))
            if wind_weight <= 0.0:
                continue

            distance_decay = math.exp(-float(edge["distance_px"]) / decay_scale)
            flow_weight = wind_weight * float(edge["border_weight"]) * distance_decay
            if flow_weight <= 0.0:
                continue
            candidates.append((color_b, edge, flow_weight))

        flow_total = sum(weight for _, _, weight in candidates)
        if flow_total <= 0.0:
            continue

        export_delta = delta_a * export_fraction
        for color_b, edge, flow_weight in candidates:
            province_b = graph["provinces"][color_b]
            area_factor = math.sqrt(float(province_b["area_px"]) / median_area)
            transfer = export_delta * (flow_weight / flow_total)
            mtn_a = mountain_strength.get(color_a, 0.0)
            mtn_b = mountain_strength.get(color_b, 0.0)
            crossing_barrier = max(mtn_a, mtn_b)
            ridge_continuity = mtn_a * mtn_b * ridge_bonus
            barrier = crossing_barrier + ridge_continuity
            barrier_factor = 1.0 - math.exp(-barrier * barrier_scale)
            blocked = transfer * barrier_factor
            passed = max(0.0, transfer - blocked)
            windward_rain = blocked * windward_efficiency
            rainfall[color_b] += windward_rain
            orographic_rain[color_b] += windward_rain
            rain_shadow[color_b] += blocked

            loss = min(passed, passed * base_loss * area_factor)
            net = max(0.0, passed - loss)

            space = capacity[color_b] - moisture[color_b]
            absorbed = max(0.0, min(net, space))
            overflow = max(0.0, net - absorbed)
            rainfall[color_b] += loss + overflow * overflow_rf

            if absorbed > epsilon:
                moisture[color_b] += absorbed
                heapq.heappush(queue, (-moisture[color_b], color_b))

    return moisture, rainfall, orographic_rain, rain_shadow


def apply_itcz_correction(
    moisture: dict[str, float],
    rainfall: dict[str, float],
    graph: dict[str, Any],
    climate_rules: dict[str, Any],
    locked: set[str],
) -> tuple[dict[str, float], dict[str, float]]:
    itcz = next(band for band in climate_rules["wind_bands"] if band["name"] == "itcz")
    lat_min = float(itcz["abs_lat_min"])
    lat_max = float(itcz["abs_lat_max"])
    efficiency = float(itcz["itcz_rainfall_efficiency"])
    for color, province in graph["provinces"].items():
        if color in locked or province["is_sea"]:
            continue
        if lat_min <= abs(float(province["latitude"])) < lat_max:
            condensation = min(moisture[color] * (efficiency - 1.0) * 0.3, moisture[color])
            rainfall[color] += condensation
            moisture[color] -= condensation
    return moisture, rainfall


def encode_rgb(path: Path) -> np.ndarray:
    img = np.array(Image.open(path).convert("RGB"))
    return (
        img[:, :, 0].astype(np.int32) * 65536
        + img[:, :, 1].astype(np.int32) * 256
        + img[:, :, 2].astype(np.int32)
    )


def render_debug_map(
    inverse: np.ndarray,
    shape: tuple[int, int],
    unique_values: np.ndarray,
    values_by_int: dict[int, float],
    color_fn: Callable[[float], tuple[int, int, int]],
    output_path: Path,
) -> None:
    palette = np.zeros((len(unique_values), 3), dtype=np.uint8)
    for idx, color_int in enumerate(unique_values):
        palette[idx] = color_fn(values_by_int.get(int(color_int), 0.0))
    output = palette[inverse].reshape((shape[0], shape[1], 3))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.stem}.tmp{output_path.suffix}")
    Image.fromarray(output).save(tmp_path)
    tmp_path.replace(output_path)


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def blue_scale(value: float) -> tuple[int, int, int]:
    value = clamp01(value)
    light = int(255 * (1.0 - value))
    return (light, light, 255)


def blue_log_scale(value: float) -> tuple[int, int, int]:
    value = math.log1p(max(0.0, value) * 8.0) / math.log1p(8.0)
    return blue_scale(value)


def source_scale(value: float) -> tuple[int, int, int]:
    value = clamp01(value)
    return (int(value * 255), 0, int((1.0 - value) * 255))


def mountain_scale(value: float) -> tuple[int, int, int]:
    value = clamp01(value)
    low = np.array([245, 245, 245], dtype=np.float64)
    high = np.array([116, 82, 45], dtype=np.float64)
    color = low * (1.0 - value) + high * value
    return tuple(int(channel) for channel in color)


def wind_band_color(latitude: float) -> tuple[int, int, int]:
    abs_lat = abs(latitude)
    if abs_lat < 10:
        return (255, 50, 50)
    if abs_lat < 30:
        return (255, 165, 0)
    if abs_lat < 60:
        return (0, 200, 0)
    return (0, 100, 255)


def generate_debug_outputs(
    graph: dict[str, Any],
    moisture: dict[str, float],
    rainfall: dict[str, float],
    source_moisture: dict[str, float],
    mountain_strength: dict[str, float],
    orographic_rain: dict[str, float],
    rain_shadow: dict[str, float],
    map_data: Path,
    output_dir: Path,
) -> None:
    encoded = encode_rgb(map_data / "provinces.png")
    unique_values, inverse = np.unique(encoded.ravel(), return_inverse=True)
    int_colors = {color: int(color[1:], 16) for color in graph["provinces"]}
    moisture_int = {int_colors[color]: value for color, value in moisture.items()}
    rainfall_int = {int_colors[color]: value for color, value in rainfall.items()}
    source_int = {int_colors[color]: value for color, value in source_moisture.items()}
    mountain_int = {int_colors[color]: value for color, value in mountain_strength.items()}
    orographic_int = {int_colors[color]: value for color, value in orographic_rain.items()}
    shadow_int = {int_colors[color]: value for color, value in rain_shadow.items()}
    latitude_int = {int_colors[color]: float(province["latitude"]) for color, province in graph["provinces"].items()}

    render_debug_map(inverse, encoded.shape, unique_values, moisture_int, blue_scale, output_dir / "moisture_raw.png")
    render_debug_map(inverse, encoded.shape, unique_values, rainfall_int, blue_scale, output_dir / "rainfall_raw.png")
    render_debug_map(inverse, encoded.shape, unique_values, moisture_int, blue_log_scale, output_dir / "moisture_contrast.png")
    render_debug_map(inverse, encoded.shape, unique_values, rainfall_int, blue_log_scale, output_dir / "rainfall_contrast.png")
    render_debug_map(inverse, encoded.shape, unique_values, mountain_int, mountain_scale, output_dir / "barrier_strength.png")
    render_debug_map(inverse, encoded.shape, unique_values, orographic_int, blue_log_scale, output_dir / "orographic_rain.png")
    render_debug_map(inverse, encoded.shape, unique_values, shadow_int, blue_log_scale, output_dir / "rain_shadow.png")
    render_debug_map(inverse, encoded.shape, unique_values, source_int, source_scale, output_dir / "moisture_source.png")
    render_debug_map(inverse, encoded.shape, unique_values, latitude_int, wind_band_color, output_dir / "wind_band.png")


def write_result(
    output_path: Path,
    graph: dict[str, Any],
    temperature: dict[str, float],
    capacity: dict[str, float],
    moisture: dict[str, float],
    rainfall: dict[str, float],
    mountain_strength: dict[str, float],
    orographic_rain: dict[str, float],
    rain_shadow: dict[str, float],
    locked: set[str],
) -> None:
    data = {
        "version": "0.3",
        "source_graph": "cache/province_graph.json",
        "metadata": {
            "province_count": graph["metadata"]["province_count"],
            "land_province_count": graph["metadata"]["land_province_count"],
            "sea_province_count": graph["metadata"]["sea_province_count"],
        },
        "provinces": {
            color: {
                "temperature_c": round(temperature[color], 4),
                "moisture_capacity": round(capacity[color], 6),
                "moisture": round(moisture[color], 6),
                "rainfall": round(rainfall[color], 6),
                "mountain_strength": round(mountain_strength[color], 6),
                "orographic_rain": round(orographic_rain[color], 6),
                "rain_shadow": round(rain_shadow[color], 6),
                "locked": color in locked,
                "is_sea": graph["provinces"][color]["is_sea"],
            }
            for color in sorted(graph["provinces"])
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def print_summary(graph: dict[str, Any], moisture: dict[str, float], rainfall: dict[str, float], capacity: dict[str, float], locked: set[str]) -> None:
    land_colors = [color for color, province in graph["provinces"].items() if not province["is_sea"]]
    moisture_values = np.array([moisture[color] for color in land_colors], dtype=np.float64)
    rainfall_values = np.array([rainfall[color] for color in land_colors], dtype=np.float64)
    capacity_values = np.array([capacity[color] for color in land_colors], dtype=np.float64)
    invalid_moisture = int(np.sum((moisture_values < -1e-9) | (moisture_values > capacity_values + 1e-9)))
    invalid_rainfall = int(np.sum(rainfall_values < -1e-9))
    print(f"land provinces: {len(land_colors)}")
    print(f"locked provinces: {len(locked)}")
    print(f"moisture min/mean/max: {moisture_values.min():.4f} / {moisture_values.mean():.4f} / {moisture_values.max():.4f}")
    print(f"rainfall min/mean/max: {rainfall_values.min():.4f} / {rainfall_values.mean():.4f} / {rainfall_values.max():.4f}")
    print(f"capacity min/mean/max: {capacity_values.min():.4f} / {capacity_values.mean():.4f} / {capacity_values.max():.4f}")
    print(f"invalid moisture count: {invalid_moisture}")
    print(f"invalid rainfall count: {invalid_rainfall}")


def main() -> None:
    default_project_root = Path(__file__).resolve().parents[1]
    default_root = find_workspace_root(default_project_root)
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=default_root)
    parser.add_argument("--project-root", type=Path, default=default_project_root)
    parser.add_argument("--province-project-root", type=Path, default=default_project_root.parent / "프로빈스_프로젝트")
    parser.add_argument("--graph", type=Path, default=None)
    args = parser.parse_args()

    graph_path = args.graph or (args.project_root / "cache" / "province_graph.json")
    if not graph_path.is_file():
        raise FileNotFoundError(f"province graph not found: {graph_path}")
    graph = json.loads(graph_path.read_text(encoding="utf-8"))
    climate_rules = load_yaml(args.project_root / "config" / "climate_rules.yaml")
    constraints, overrides = load_constraints(args.province_project_root)
    locked = load_locked(overrides)
    mountain_strength = compute_mountain_strengths(graph, constraints, climate_rules)

    temperature: dict[str, float] = {}
    capacity: dict[str, float] = {}
    wind_vectors: dict[str, tuple[float, float]] = {}
    for color, province in graph["provinces"].items():
        temperature[color] = compute_temperature(province, climate_rules, constraints)
        capacity[color] = compute_capacity(temperature[color], climate_rules)
        wind_vectors[color] = compute_wind_vector(float(province["latitude"]), climate_rules)

    moisture, rainfall = initialize_moisture(graph, constraints, climate_rules, capacity, locked)
    source_moisture = dict(moisture)
    moisture, rainfall, orographic_rain, rain_shadow = propagate_moisture(
        graph,
        moisture,
        rainfall,
        capacity,
        wind_vectors,
        mountain_strength,
        climate_rules,
        locked,
    )
    moisture, rainfall = apply_itcz_correction(moisture, rainfall, graph, climate_rules, locked)

    result_path = args.project_root / "cache" / "province_moisture.json"
    debug_dir = args.project_root / "outputs" / "debug"
    write_result(result_path, graph, temperature, capacity, moisture, rainfall, mountain_strength, orographic_rain, rain_shadow, locked)
    generate_debug_outputs(
        graph,
        moisture,
        rainfall,
        source_moisture,
        mountain_strength,
        orographic_rain,
        rain_shadow,
        args.root / "map_data",
        debug_dir,
    )

    print(f"wrote {result_path}")
    print(f"wrote {debug_dir / 'moisture_raw.png'}")
    print(f"wrote {debug_dir / 'rainfall_raw.png'}")
    print(f"wrote {debug_dir / 'moisture_contrast.png'}")
    print(f"wrote {debug_dir / 'rainfall_contrast.png'}")
    print(f"wrote {debug_dir / 'barrier_strength.png'}")
    print(f"wrote {debug_dir / 'orographic_rain.png'}")
    print(f"wrote {debug_dir / 'rain_shadow.png'}")
    print(f"wrote {debug_dir / 'wind_band.png'}")
    print(f"wrote {debug_dir / 'moisture_source.png'}")
    print_summary(graph, moisture, rainfall, capacity, locked)


if __name__ == "__main__":
    main()
