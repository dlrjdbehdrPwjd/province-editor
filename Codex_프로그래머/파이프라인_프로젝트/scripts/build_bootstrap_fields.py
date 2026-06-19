from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image, ImageDraw


SCHEMA_VERSION = "bootstrap_fields.v0.1"
GRAPH_SCHEMA_VERSION = "province_graph.v0.2"
REPORT_SCHEMA_VERSION = "bootstrap_fields_build_report.v0.1"
COLOR_RE = re.compile(r"x[0-9A-Fa-f]{6}")

DEFAULT_ELEVATION_HINT_ELEVATION_M = {
    "none": 0.0,
    "lowland": 100.0,
    "upland": 500.0,
    "highland": 1200.0,
    "mountain": 2000.0,
}
DEFAULT_ELEVATION_HINT_FLOW_BONUS = {
    "none": 0.0,
    "lowland": 0.05,
    "upland": 0.15,
    "highland": 0.35,
    "mountain": 0.60,
}
DEFAULT_PARAMS = {
    "mountain_average_elevation_m": 1500.0,
    "mountain_flow_bonus": 0.5,
    "max_coast_distance_hops": "auto",
    "elevation_hint_elevation_m": DEFAULT_ELEVATION_HINT_ELEVATION_M,
    "elevation_hint_flow_bonus": DEFAULT_ELEVATION_HINT_FLOW_BONUS,
}


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    lowered = value.lower()
    if lowered in {"true", "yes"}:
        return True
    if lowered in {"false", "no"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if lowered == "auto":
        return "auto"
    if value == "{}":
        return {}
    if value == "[]":
        return []
    try:
        return float(value) if any(marker in value for marker in (".", "e", "E")) else int(value)
    except ValueError:
        return value.strip('"').strip("'")


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if line.strip():
            lines.append(line)

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        result: dict[str, Any] | list[Any] | None = None
        while index < len(lines):
            line = lines[index]
            current_indent = len(line) - len(line.lstrip(" "))
            if current_indent < indent:
                break
            if current_indent > indent:
                raise ValueError(f"invalid YAML indentation near: {line}")
            stripped = line.strip()
            if stripped.startswith("- "):
                if result is None:
                    result = []
                if not isinstance(result, list):
                    raise ValueError("mixed YAML mapping/list block")
                result.append(parse_scalar(stripped[2:]))
                index += 1
                continue
            if ":" not in stripped:
                raise ValueError(f"invalid YAML line: {line}")
            if result is None:
                result = {}
            if not isinstance(result, dict):
                raise ValueError("mixed YAML mapping/list block")
            key, value = stripped.split(":", 1)
            if value.strip():
                result[key.strip()] = parse_scalar(value)
                index += 1
            else:
                nested, index = parse_block(index + 1, indent + 2)
                result[key.strip()] = nested
        return result if result is not None else {}, index

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


def extract_top_level_yaml_section(text: str, section: str) -> str | None:
    lines = text.splitlines()
    start: int | None = None
    for index, raw in enumerate(lines):
        stripped = raw.split("#", 1)[0].rstrip()
        if stripped == f"{section}:":
            start = index
            break
    if start is None:
        return None
    end = len(lines)
    for index in range(start + 1, len(lines)):
        raw = lines[index]
        content = raw.split("#", 1)[0].rstrip()
        if content and not raw[:1].isspace():
            end = index
            break
    return "\n".join(lines[start:end]) + "\n"


def normalize_color(value: str) -> str:
    normalized = value.strip().strip('"').strip("'")
    if not COLOR_RE.fullmatch(normalized):
        raise ValueError(f"invalid province color: {value}")
    return "x" + normalized[1:].upper()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def display_path(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return os.path.relpath(path.resolve(), project_root.resolve()).replace("\\", "/")


def load_province_graph(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"province_graph.json not found: {path}")
    try:
        graph = json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        raise ValueError(f"failed to parse province_graph.json: {error}") from error
    if not isinstance(graph, dict):
        raise ValueError("province_graph.json top level must be an object")
    return graph


def validate_province_graph_for_bootstrap(graph: dict[str, Any]) -> dict[str, Any]:
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise ValueError(f"province_graph schema_version must be {GRAPH_SCHEMA_VERSION}")
    metadata = graph.get("metadata")
    provinces = graph.get("provinces")
    adjacency = graph.get("adjacency")
    if not isinstance(metadata, dict):
        raise ValueError("province_graph.metadata must be an object")
    if not isinstance(provinces, dict) or not isinstance(adjacency, dict):
        raise ValueError("province_graph provinces/adjacency must be objects")
    topology_hash = metadata.get("hash", {}).get("topology_hash")
    if not isinstance(topology_hash, str) or not topology_hash.startswith("sha256:"):
        raise ValueError("province_graph metadata.hash.topology_hash is missing")

    heightmap = metadata.get("heightmap", {})
    authoritative = bool(heightmap.get("authoritative", False))
    heightmap_stats_hash = metadata.get("hash", {}).get("heightmap_stats_hash")
    if authoritative:
        if not isinstance(heightmap_stats_hash, str) or not heightmap_stats_hash.startswith("sha256:"):
            raise ValueError("authoritative heightmap requires heightmap_stats_hash")
        for color, province in provinces.items():
            if bool(province.get("is_sea", False)):
                continue
            elevation = province.get("elevation")
            if not isinstance(elevation, dict) or elevation.get("elevation_m") is None:
                raise ValueError(f"{color}: authoritative heightmap requires elevation.elevation_m")
            value = float(elevation["elevation_m"])
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(f"{color}: invalid authoritative elevation.elevation_m")
    return {
        "topology_hash": topology_hash,
        "heightmap_authoritative": authoritative,
        "heightmap_stats_hash": heightmap_stats_hash,
    }


def load_province_constraints(path: Path) -> dict[str, dict[str, Any]]:
    document = load_yaml(path, "province_constraints.yaml")
    if "province_constraints" in document:
        raw_constraints = document["province_constraints"]
    elif "provinces" in document:
        raw_constraints = document["provinces"]
    else:
        raw_constraints = {}
    if raw_constraints is None:
        return {}
    if not isinstance(raw_constraints, dict):
        raise ValueError("province constraints container must be a mapping")

    constraints: dict[str, dict[str, Any]] = {}
    for raw_color, raw_data in raw_constraints.items():
        color = normalize_color(str(raw_color))
        if color in constraints:
            raise ValueError(f"duplicate normalized province color: {color}")
        if raw_data is None:
            raw_data = {}
        if not isinstance(raw_data, dict):
            raise ValueError(f"{color}: province constraint must be a mapping")
        constraints[color] = raw_data
    return constraints


def _number(value: Any, label: str, minimum: float | None = None) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{label} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be >= {minimum}")
    return number


def _mapping_of_numbers(value: Any, label: str) -> dict[str, float]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a mapping")
    result: dict[str, float] = {}
    for key, item in value.items():
        result[str(key).strip().lower()] = _number(item, f"{label}.{key}", minimum=0.0)
    return result


def load_bootstrap_params(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"bootstrap params not found: {path}")
    text = path.read_text(encoding="utf-8-sig")
    try:
        import yaml  # type: ignore

        document = yaml.safe_load(text) or {}
    except ModuleNotFoundError:
        relevant_text = extract_top_level_yaml_section(text, "bootstrap_fields") or text
        document = parse_simple_yaml(relevant_text)
    except Exception as error:
        raise ValueError(f"failed to parse bootstrap params: {error}") from error
    if not isinstance(document, dict):
        raise ValueError("bootstrap params top level must be a mapping")
    raw = document.get("bootstrap_fields", document)
    if not isinstance(raw, dict):
        raise ValueError("bootstrap_fields params must be a mapping")

    params: dict[str, Any] = {
        "mountain_average_elevation_m": _number(
            raw.get("mountain_average_elevation_m", DEFAULT_PARAMS["mountain_average_elevation_m"]),
            "mountain_average_elevation_m",
            minimum=0.0,
        ),
        "mountain_flow_bonus": _number(
            raw.get("mountain_flow_bonus", DEFAULT_PARAMS["mountain_flow_bonus"]),
            "mountain_flow_bonus",
            minimum=0.0,
        ),
    }
    max_hops = raw.get("max_coast_distance_hops", "auto")
    if isinstance(max_hops, str) and max_hops.strip().lower() == "auto":
        params["max_coast_distance_hops"] = "auto"
    else:
        numeric_hops = _number(max_hops, "max_coast_distance_hops", minimum=0.0)
        if not numeric_hops.is_integer():
            raise ValueError("max_coast_distance_hops must be an integer or auto")
        params["max_coast_distance_hops"] = int(numeric_hops)

    elevation_mapping = dict(DEFAULT_ELEVATION_HINT_ELEVATION_M)
    if "elevation_hint_elevation_m" in raw:
        elevation_mapping.update(
            _mapping_of_numbers(raw["elevation_hint_elevation_m"], "elevation_hint_elevation_m")
        )
    flow_mapping = dict(DEFAULT_ELEVATION_HINT_FLOW_BONUS)
    if "elevation_hint_flow_bonus" in raw:
        flow_mapping.update(
            _mapping_of_numbers(raw["elevation_hint_flow_bonus"], "elevation_hint_flow_bonus")
        )
    if set(elevation_mapping) != set(flow_mapping):
        raise ValueError("elevation hint mappings must have identical keys")
    params["elevation_hint_elevation_m"] = dict(sorted(elevation_mapping.items()))
    params["elevation_hint_flow_bonus"] = dict(sorted(flow_mapping.items()))
    return params


def normalize_constraints(
    constraints: dict[str, dict[str, Any]],
    graph: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, int]]:
    graph_colors = set(graph["provinces"])
    unknown_colors = sorted(set(constraints) - graph_colors)
    missing_colors = sorted(graph_colors - set(constraints))
    warnings: list[str] = []
    if unknown_colors:
        sample = ", ".join(unknown_colors[:10])
        warnings.append(
            f"{len(unknown_colors)} province constraint colors are absent from graph"
            + (f": {sample}" if sample else "")
        )
    if missing_colors:
        warnings.append(
            f"{len(missing_colors)} graph provinces have no constraints; bootstrap defaults used"
        )

    allowed_hints = set(DEFAULT_ELEVATION_HINT_ELEVATION_M)
    normalized: dict[str, dict[str, Any]] = {}
    for color, raw in constraints.items():
        strength_raw = raw.get("mountain_strength", 0.0)
        strength = 0.0 if strength_raw is None else _number(
            strength_raw, f"{color}.mountain_strength"
        )
        if not 0.0 <= strength <= 1.0:
            raise ValueError(f"{color}.mountain_strength must be in 0.0..1.0")
        hint_raw = raw.get("elevation_hint", "none")
        hint = "none" if hint_raw is None else str(hint_raw).strip().lower()
        if hint not in allowed_hints:
            raise ValueError(
                f"{color}.elevation_hint must be one of {', '.join(sorted(allowed_hints))}"
            )
        lake_raw = raw.get("lake_seed", False)
        lake_seed = False if lake_raw is None else lake_raw
        if not isinstance(lake_seed, bool):
            raise ValueError(f"{color}.lake_seed must be boolean")
        normalized[color] = {
            "mountain_strength": float(strength),
            "elevation_hint": hint,
            "lake_seed": lake_seed,
        }

    default = {
        "mountain_strength": 0.0,
        "elevation_hint": "none",
        "lake_seed": False,
    }
    for color in graph_colors:
        normalized.setdefault(color, dict(default))
    return normalized, warnings, {
        "provided": len(constraints),
        "missing": len(missing_colors),
        "unknown": len(unknown_colors),
    }


def build_land_targets(graph: dict[str, Any]) -> set[str]:
    return {
        color
        for color, province in graph["provinces"].items()
        if not bool(province.get("is_sea", False))
    }


def compute_coast_distance(
    graph: dict[str, Any],
    land_targets: set[str],
) -> tuple[dict[str, int], list[str], list[str]]:
    coastal = sorted(
        color
        for color in land_targets
        if bool(graph["provinces"][color].get("is_coastal", False))
    )
    if not coastal:
        raise ValueError("coastal land province count is zero")
    distance = {color: 0 for color in coastal}
    queue = deque(coastal)
    adjacency = graph["adjacency"]
    while queue:
        current = queue.popleft()
        next_distance = distance[current] + 1
        for neighbor in adjacency.get(current, {}):
            if neighbor in land_targets and neighbor not in distance:
                distance[neighbor] = next_distance
                queue.append(neighbor)
    unreachable = sorted(land_targets - set(distance))
    return distance, unreachable, coastal


def normalize_coast_distance(
    distance: dict[str, int],
    land_targets: set[str],
    params: dict[str, Any],
) -> tuple[dict[str, float], float]:
    configured = params["max_coast_distance_hops"]
    max_hop = float(max(distance.values(), default=0) if configured == "auto" else configured)
    normalized: dict[str, float] = {}
    for color in land_targets:
        if color not in distance:
            normalized[color] = 1.0
        elif max_hop == 0.0:
            normalized[color] = 0.0
        else:
            normalized[color] = min(max(distance[color] / max_hop, 0.0), 1.0)
    return normalized, max_hop


def compute_synthetic_elevation(
    constraints: dict[str, dict[str, Any]],
    params: dict[str, Any],
    graph: dict[str, Any],
    land_targets: Iterable[str],
) -> dict[str, float]:
    authoritative = bool(graph["metadata"].get("heightmap", {}).get("authoritative", False))
    result: dict[str, float] = {}
    for color in land_targets:
        if authoritative:
            value = float(graph["provinces"][color]["elevation"]["elevation_m"])
        else:
            constraint = constraints[color]
            mountain_component = (
                constraint["mountain_strength"] * params["mountain_average_elevation_m"]
            )
            hint_component = params["elevation_hint_elevation_m"][constraint["elevation_hint"]]
            value = max(mountain_component, hint_component)
        result[color] = float(value)
    return result


def compute_synthetic_flow_potential(
    coast_distance_normalized: dict[str, float],
    constraints: dict[str, dict[str, Any]],
    params: dict[str, Any],
) -> dict[str, float]:
    return {
        color: float(
            coast_distance
            + constraints[color]["mountain_strength"] * params["mountain_flow_bonus"]
            + params["elevation_hint_flow_bonus"][constraints[color]["elevation_hint"]]
        )
        for color, coast_distance in coast_distance_normalized.items()
    }


def compute_is_flow_sink(
    constraints: dict[str, dict[str, Any]], land_targets: Iterable[str]
) -> dict[str, bool]:
    return {color: bool(constraints[color]["lake_seed"]) for color in land_targets}


def compute_continentality(
    coast_distance_normalized: dict[str, float],
) -> dict[str, float]:
    return dict(coast_distance_normalized)


def compute_graph_hash(graph_info: dict[str, Any]) -> str:
    if not graph_info["heightmap_authoritative"]:
        return str(graph_info["topology_hash"])
    return canonical_hash(
        {
            "topology_hash": graph_info["topology_hash"],
            "heightmap_stats_hash": graph_info["heightmap_stats_hash"],
        }
    )


def compute_constraints_hash(
    constraints: dict[str, dict[str, Any]], land_targets: Iterable[str]
) -> str:
    logical = {color: constraints[color] for color in sorted(land_targets)}
    return canonical_hash(logical)


def compute_params_hash(params: dict[str, Any]) -> str:
    return canonical_hash(params)


def validate_bootstrap_fields(
    fields: dict[str, Any],
    land_targets: set[str],
    expected_flow_max: float,
) -> list[str]:
    warnings: list[str] = []
    provinces = fields.get("provinces", {})
    if set(provinces) != land_targets:
        raise ValueError("bootstrap province keys do not match land_targets")
    for color, values in provinces.items():
        elevation = float(values["synthetic_elevation_m"])
        flow = float(values["synthetic_flow_potential"])
        coast = float(values["coast_distance_normalized"])
        continentality = float(values["continentality"])
        if not math.isfinite(elevation) or elevation < 0.0:
            raise ValueError(f"{color}: synthetic_elevation_m must be finite and >= 0")
        if not 0.0 <= coast <= 1.0:
            raise ValueError(f"{color}: coast_distance_normalized outside 0.0..1.0")
        if not 0.0 <= continentality <= 1.0:
            raise ValueError(f"{color}: continentality outside 0.0..1.0")
        if continentality != coast:
            raise ValueError(f"{color}: continentality must equal coast_distance_normalized")
        if not math.isfinite(flow):
            raise ValueError(f"{color}: synthetic_flow_potential must be finite")
        if flow < 0.0 or flow > expected_flow_max + 1e-9:
            warnings.append(
                f"{color}: synthetic_flow_potential {flow:.8f} outside 0.0..{expected_flow_max:.8f}"
            )
        if not isinstance(values["is_flow_sink"], bool):
            raise ValueError(f"{color}: is_flow_sink must be boolean")
    return warnings


def atomic_write_json(path: Path, value: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp_{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
            allow_nan=False,
        )
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
        return
    except PermissionError:
        if not path.exists():
            raise
    backup = path.with_name(f".{path.name}.backup_{os.getpid()}")
    os.replace(path, backup)
    try:
        os.replace(temporary, path)
    except Exception:
        os.replace(backup, path)
        raise
    else:
        backup.unlink(missing_ok=True)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _gradient(value: float, low: tuple[int, int, int], high: tuple[int, int, int]) -> tuple[int, int, int]:
    ratio = min(max(float(value), 0.0), 1.0)
    return tuple(round(a + (b - a) * ratio) for a, b in zip(low, high))


def write_debug_images(
    debug_dir: Path,
    graph: dict[str, Any],
    fields: dict[str, Any],
) -> list[Path]:
    world = graph["metadata"].get("world", {})
    source_width = max(int(world.get("width_px", 1)), 1)
    source_height = max(int(world.get("height_px", 1)), 1)
    width = min(source_width, 2048)
    height = max(1, round(source_height * width / source_width))
    scale_x = (width - 1) / max(source_width - 1, 1)
    scale_y = (height - 1) / max(source_height - 1, 1)
    province_values = fields["provinces"]
    max_elevation = max(
        (float(item["synthetic_elevation_m"]) for item in province_values.values()),
        default=0.0,
    )
    max_flow = max(
        (float(item["synthetic_flow_potential"]) for item in province_values.values()),
        default=0.0,
    )
    specs = {
        "coast_distance_preview.png": (
            "coast_distance_normalized",
            lambda value: _gradient(value, (60, 190, 220), (215, 90, 55)),
        ),
        "synthetic_elevation_preview.png": (
            "synthetic_elevation_m",
            lambda value: _gradient(value / max(max_elevation, 1.0), (75, 135, 70), (245, 245, 240)),
        ),
        "synthetic_flow_potential_preview.png": (
            "synthetic_flow_potential",
            lambda value: _gradient(value / max(max_flow, 1.0), (70, 190, 210), (150, 45, 145)),
        ),
        "continentality_preview.png": (
            "continentality",
            lambda value: _gradient(value, (80, 175, 215), (225, 155, 65)),
        ),
    }
    paths: list[Path] = []
    for filename, (field_name, color_function) in specs.items():
        image = Image.new("RGB", (width, height), (30, 65, 105))
        draw = ImageDraw.Draw(image)
        for color, values in province_values.items():
            center = graph["provinces"][color]["center"]
            x = round(float(center["x"]) * scale_x)
            y = round(float(center["y"]) * scale_y)
            draw.point((x, y), fill=color_function(float(values[field_name])))
        path = debug_dir / filename
        image.save(path)
        paths.append(path)

    sink_image = Image.new("RGB", (width, height), (30, 65, 105))
    sink_draw = ImageDraw.Draw(sink_image)
    for color, values in province_values.items():
        center = graph["provinces"][color]["center"]
        x = round(float(center["x"]) * scale_x)
        y = round(float(center["y"]) * scale_y)
        fill = (240, 60, 80) if values["is_flow_sink"] else (190, 190, 165)
        sink_draw.point((x, y), fill=fill)
    sink_path = debug_dir / "flow_sink_preview.png"
    sink_image.save(sink_path)
    paths.append(sink_path)
    return paths


def write_debug_outputs(
    debug_dir: Path,
    graph: dict[str, Any],
    fields: dict[str, Any],
    diagnostics: dict[str, Any],
) -> list[Path]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    report_path = debug_dir / "bootstrap_fields_build_report.json"
    atomic_write_json(report_path, diagnostics["report"], pretty=True)
    paths.append(report_path)

    coast_path = debug_dir / "coast_distance.csv"
    distance = diagnostics["coast_distance_hops"]
    coastal = set(diagnostics["coastal_land"])
    write_csv(
        coast_path,
        ["province", "coast_distance_hops", "coast_distance_normalized", "reachable", "is_coastal"],
        (
            {
                "province": color,
                "coast_distance_hops": distance.get(color, ""),
                "coast_distance_normalized": fields["provinces"][color]["coast_distance_normalized"],
                "reachable": color in distance,
                "is_coastal": color in coastal,
            }
            for color in sorted(fields["provinces"])
        ),
    )
    paths.append(coast_path)

    unreachable_path = debug_dir / "unreachable_land_provinces.csv"
    write_csv(
        unreachable_path,
        ["province"],
        ({"province": color} for color in diagnostics["unreachable_land"]),
    )
    paths.append(unreachable_path)

    sinks_path = debug_dir / "flow_sinks.csv"
    write_csv(
        sinks_path,
        ["province", "source"],
        (
            {"province": color, "source": "province_constraints.lake_seed"}
            for color, values in sorted(fields["provinces"].items())
            if values["is_flow_sink"]
        ),
    )
    paths.append(sinks_path)

    warnings_path = debug_dir / "bootstrap_warnings.csv"
    write_csv(
        warnings_path,
        ["severity", "message"],
        ({"severity": "WARNING", "message": warning} for warning in diagnostics["warnings"]),
    )
    paths.append(warnings_path)
    paths.extend(write_debug_images(debug_dir, graph, fields))
    return paths


def build_bootstrap_fields(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = load_province_graph(args.province_graph)
    graph_info = validate_province_graph_for_bootstrap(graph)
    raw_constraints = load_province_constraints(args.province_constraints)
    params = load_bootstrap_params(args.params)
    constraints, warnings, constraint_counts = normalize_constraints(raw_constraints, graph)
    land_targets = build_land_targets(graph)
    coast_distance, unreachable, coastal_land = compute_coast_distance(graph, land_targets)
    coast_normalized, effective_max_hop = normalize_coast_distance(
        coast_distance, land_targets, params
    )
    if unreachable:
        warnings.append(
            f"{len(unreachable)} land provinces are unreachable from coastal land; normalized distance set to 1.0"
        )
    elevation = compute_synthetic_elevation(
        constraints, params, graph, land_targets
    )
    flow = compute_synthetic_flow_potential(coast_normalized, constraints, params)
    flow_sinks = compute_is_flow_sink(constraints, land_targets)
    continentality = compute_continentality(coast_normalized)

    graph_hash = compute_graph_hash(graph_info)
    constraints_hash = compute_constraints_hash(constraints, land_targets)
    params_hash = compute_params_hash(params)
    province_fields = {
        color: {
            "synthetic_elevation_m": round(elevation[color], 3),
            "synthetic_flow_potential": round(flow[color], 8),
            "continentality": round(continentality[color], 8),
            "coast_distance_normalized": round(coast_normalized[color], 8),
            "is_flow_sink": flow_sinks[color],
        }
        for color in sorted(land_targets)
    }
    fields = {
        "schema_version": SCHEMA_VERSION,
        "graph_hash": graph_hash,
        "constraints_hash": constraints_hash,
        "params_hash": params_hash,
        "source_constraints": {
            "province_constraints": display_path(args.province_constraints, args.project_root)
        },
        "provinces": province_fields,
    }
    expected_flow_max = (
        1.0
        + float(params["mountain_flow_bonus"])
        + max(params["elevation_hint_flow_bonus"].values(), default=0.0)
    )
    warnings.extend(validate_bootstrap_fields(fields, land_targets, expected_flow_max))
    info = [
        (
            "authoritative heightmap elevation used"
            if graph_info["heightmap_authoritative"]
            else "heightmap.authoritative=false; constraints-based synthetic elevation used"
        ),
        "state_constraints.yaml not read; province_constraints only",
        "river_seed/river_major/river_path/wetland_seed not read in this stage",
        "sea provinces excluded from bootstrap_fields.provinces",
    ]
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": generated_at,
        "validation_status": "success",
        "warnings": warnings,
        "info": info,
        "source_files": {
            "province_graph": display_path(args.province_graph, args.project_root),
            "province_constraints": display_path(args.province_constraints, args.project_root),
            "params": display_path(args.params, args.project_root),
        },
        "hashes": {
            "graph_hash": graph_hash,
            "constraints_hash": constraints_hash,
            "params_hash": params_hash,
        },
        "counts": {
            "graph_provinces": len(graph["provinces"]),
            "land_targets": len(land_targets),
            "sea_excluded": len(graph["provinces"]) - len(land_targets),
            "coastal_land": len(coastal_land),
            "reachable_land": len(coast_distance),
            "unreachable_land": len(unreachable),
            "flow_sinks": sum(flow_sinks.values()),
            "constraints_provided": constraint_counts["provided"],
            "constraints_missing": constraint_counts["missing"],
            "constraints_unknown": constraint_counts["unknown"],
        },
        "coast_distance": {
            "configured_max_hops": params["max_coast_distance_hops"],
            "effective_max_hops": effective_max_hop,
            "reachable_max_hops": max(coast_distance.values(), default=0),
        },
        "ranges": {
            "synthetic_elevation_m": [min(elevation.values(), default=0.0), max(elevation.values(), default=0.0)],
            "synthetic_flow_potential": [min(flow.values(), default=0.0), max(flow.values(), default=0.0)],
            "coast_distance_normalized": [min(coast_normalized.values(), default=0.0), max(coast_normalized.values(), default=0.0)],
            "continentality": [min(continentality.values(), default=0.0), max(continentality.values(), default=0.0)],
            "expected_flow_potential": [0.0, expected_flow_max],
        },
        "params": params,
    }
    diagnostics = {
        "warnings": warnings,
        "info": info,
        "report": report,
        "coast_distance_hops": coast_distance,
        "unreachable_land": unreachable,
        "coastal_land": coastal_land,
    }
    return fields, diagnostics


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    return {
        "project_root": project_root,
        "province_graph": project_root / "cache" / "province_graph.json",
        "params": project_root / "config" / "climate_rules.yaml",
        "output": project_root / "cache" / "bootstrap_fields.json",
        "debug_dir": project_root / "cache" / "debug",
    }


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(
        description="Build bootstrap_fields.v0.1 synthetic physical fields cache"
    )
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--province-graph", type=Path, default=defaults["province_graph"])
    parser.add_argument("--province-constraints", type=Path, required=True)
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
        fields, diagnostics = build_bootstrap_fields(args)
        warnings = diagnostics["warnings"]
        if warnings and args.fail_on_warning:
            for warning in warnings:
                print(f"WARNING: {warning}")
            return 2
        atomic_write_json(args.output, fields, pretty=args.pretty)
        debug_paths: list[Path] = []
        if args.debug:
            debug_paths = write_debug_outputs(
                args.debug_dir,
                load_province_graph(args.province_graph),
                fields,
                diagnostics,
            )
        print(f"wrote: {args.output}")
        print(f"schema_version: {fields['schema_version']}")
        print(f"land_province_count: {len(fields['provinces'])}")
        print(f"graph_hash: {fields['graph_hash']}")
        print(f"constraints_hash: {fields['constraints_hash']}")
        print(f"params_hash: {fields['params_hash']}")
        print(f"warnings: {len(warnings)}")
        for warning in warnings[:20]:
            print(f"WARNING: {warning}")
        if len(warnings) > 20:
            print(f"WARNING: ... {len(warnings) - 20} more")
        print(f"debug_artifacts: {len(debug_paths)}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
