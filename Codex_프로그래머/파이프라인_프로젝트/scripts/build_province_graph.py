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

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

SCHEMA_VERSION = "province_graph.v0.2"
COLOR_RE = re.compile(r"x[0-9A-Fa-f]{6}")


def parse_scalar(value: str) -> Any:
    value = value.strip()
    if not value:
        return ""
    if value in {"true", "yes"}:
        return True
    if value in {"false", "no"}:
        return False
    if value == "null":
        return None
    if value == "auto":
        return "auto"
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value.strip('"')


def parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = []
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


def load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(text)
        return loaded or {}
    except ModuleNotFoundError:
        return parse_simple_yaml(text)


def normalize_color(value: str) -> str:
    value = value.strip().strip('"')
    if not COLOR_RE.fullmatch(value):
        raise ValueError(f"invalid province color: {value}")
    return "x" + value[1:].upper()


def color_to_int(value: str) -> int:
    return int(normalize_color(value)[1:], 16)


def int_to_key(value: int) -> str:
    return f"x{value:06X}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def combined_hash(schema_version: str, inputs: Iterable[tuple[str, Path]]) -> str:
    digest = hashlib.sha256()
    digest.update(schema_version.encode("utf-8"))
    for label, path in inputs:
        digest.update(b"\0")
        digest.update(label.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def canonical_json_hash(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def display_path(path: Path | None, project_root: Path) -> str | None:
    if path is None:
        return None
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return os.path.relpath(path.resolve(), project_root.resolve()).replace("\\", "/")


def extract_block_colors(text: str, key: str) -> set[str]:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*\{{(?P<body>.*?)\}}", text, re.S)
    if not match:
        return set()
    return {normalize_color(item.group(0)) for item in COLOR_RE.finditer(match.group("body"))}


def parse_default_map(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    sea_starts = extract_block_colors(text, "sea_starts")
    lake_starts = extract_block_colors(text, "lakes") | extract_block_colors(text, "lake_starts")
    full_water = set()
    for key in ("water", "waters", "water_provinces", "sea_provinces"):
        full_water |= extract_block_colors(text, key)
    wrap_match = re.search(r"\bwrap_x\s*=\s*(yes|no|true|false)", text, re.I)
    wrap_x = bool(wrap_match and wrap_match.group(1).lower() in {"yes", "true"})
    return {
        "sea_starts": sea_starts,
        "lake_starts": lake_starts,
        "water_candidates": full_water,
        "wrap_x": wrap_x,
    }


def parse_color_file(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8-sig")
    return {normalize_color(item.group(0)) for item in COLOR_RE.finditer(text)}


def encode_provinces(path: Path) -> tuple[np.ndarray, str]:
    with Image.open(path) as image:
        mode = image.mode
        if mode not in {"RGB", "RGBA"}:
            raise ValueError(f"provinces.png must be RGB/RGBA, got {mode}")
        rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    encoded = (
        rgb[:, :, 0].astype(np.int32) << 16
        | rgb[:, :, 1].astype(np.int32) << 8
        | rgb[:, :, 2].astype(np.int32)
    )
    return encoded, mode


def compute_geometry(
    inverse: np.ndarray,
    width: int,
    height: int,
    province_count: int,
    chunk_size: int = 4_000_000,
) -> dict[str, np.ndarray]:
    area = np.bincount(inverse, minlength=province_count).astype(np.int64)
    sum_x = np.zeros(province_count, dtype=np.float64)
    sum_y = np.zeros(province_count, dtype=np.float64)
    x_min = np.full(province_count, width, dtype=np.int32)
    x_max = np.full(province_count, -1, dtype=np.int32)
    y_min = np.full(province_count, height, dtype=np.int32)
    y_max = np.full(province_count, -1, dtype=np.int32)

    total = inverse.size
    for start in range(0, total, chunk_size):
        end = min(start + chunk_size, total)
        labels = inverse[start:end]
        linear = np.arange(start, end, dtype=np.int64)
        xs = (linear % width).astype(np.int32)
        ys = (linear // width).astype(np.int32)
        sum_x += np.bincount(labels, weights=xs, minlength=province_count)
        sum_y += np.bincount(labels, weights=ys, minlength=province_count)
        np.minimum.at(x_min, labels, xs)
        np.maximum.at(x_max, labels, xs)
        np.minimum.at(y_min, labels, ys)
        np.maximum.at(y_max, labels, ys)

    denominator = np.maximum(area, 1)
    return {
        "area": area,
        "center_x": sum_x / denominator,
        "center_y": sum_y / denominator,
        "x_min": x_min,
        "x_max": x_max,
        "y_min": y_min,
        "y_max": y_max,
    }


def aggregate_boundaries(
    encoded: np.ndarray,
    unique_colors: np.ndarray,
    wrap_x: bool,
) -> tuple[dict[int, dict[int, int]], np.ndarray]:
    h_mask = encoded[:, :-1] != encoded[:, 1:]
    v_mask = encoded[:-1, :] != encoded[1:, :]

    h_a = encoded[:, :-1][h_mask].astype(np.uint64)
    h_b = encoded[:, 1:][h_mask].astype(np.uint64)
    v_a = encoded[:-1, :][v_mask].astype(np.uint64)
    v_b = encoded[1:, :][v_mask].astype(np.uint64)
    boundary_a = [h_a, v_a]
    boundary_b = [h_b, v_b]
    if wrap_x:
        seam_mask = encoded[:, -1] != encoded[:, 0]
        boundary_a.append(encoded[:, -1][seam_mask].astype(np.uint64))
        boundary_b.append(encoded[:, 0][seam_mask].astype(np.uint64))
    a = np.concatenate(boundary_a)
    b = np.concatenate(boundary_b)

    perimeter = np.zeros(len(unique_colors), dtype=np.int64)
    internal_sides = np.concatenate((a, b)).astype(np.int32, copy=False)
    internal_indices = np.searchsorted(unique_colors, internal_sides)
    perimeter += np.bincount(internal_indices, minlength=len(unique_colors))

    if wrap_x:
        outer_colors = np.concatenate((encoded[0, :], encoded[-1, :]))
    else:
        outer_colors = np.concatenate(
            (encoded[0, :], encoded[-1, :], encoded[:, 0], encoded[:, -1])
        )
    outer_indices = np.searchsorted(unique_colors, outer_colors)
    perimeter += np.bincount(outer_indices, minlength=len(unique_colors))

    low = np.minimum(a, b)
    high = np.maximum(a, b)
    pair_keys = (low << np.uint64(24)) | high
    unique_pairs, pair_counts = np.unique(pair_keys, return_counts=True)
    shared: dict[int, dict[int, int]] = {}
    for key, count in zip(unique_pairs, pair_counts):
        left = int(key >> np.uint64(24))
        right = int(key & np.uint64(0xFFFFFF))
        border = int(count)
        shared.setdefault(left, {})[right] = border
        shared.setdefault(right, {})[left] = border
    return shared, perimeter


def water_candidates_from_mask(mask_path: Path, encoded: np.ndarray) -> set[int]:
    with Image.open(mask_path) as image:
        mask_array = np.asarray(image)
    if mask_array.shape[:2] != encoded.shape:
        raise ValueError(
            f"water_mask size {mask_array.shape[:2][::-1]} does not match provinces {encoded.shape[::-1]}"
        )
    if mask_array.ndim == 2:
        water_pixels = mask_array != 0
    else:
        water_pixels = np.any(mask_array[:, :, :3] != 0, axis=2)
    return {int(value) for value in np.unique(encoded[water_pixels])}


def connected_components(candidates: set[int], shared: dict[int, dict[int, int]]) -> list[set[int]]:
    remaining = set(candidates)
    components = []
    while remaining:
        start = min(remaining)
        component = {start}
        queue = deque([start])
        remaining.remove(start)
        while queue:
            current = queue.popleft()
            for neighbor in shared.get(current, {}):
                if neighbor in remaining:
                    remaining.remove(neighbor)
                    component.add(neighbor)
                    queue.append(neighbor)
        components.append(component)
    return components


def resolve_sea_set(
    sea_starts: set[int],
    candidates: set[int],
    shared: dict[int, dict[int, int]],
) -> set[int]:
    outside = sea_starts - candidates
    if outside:
        sample = ", ".join(int_to_key(value) for value in sorted(outside)[:10])
        raise ValueError(f"sea_starts outside water candidates: {sample}")
    resolved: set[int] = set()
    queue = deque(sorted(sea_starts))
    while queue:
        current = queue.popleft()
        if current in resolved:
            continue
        resolved.add(current)
        for neighbor in shared.get(current, {}):
            if neighbor in candidates and neighbor not in resolved:
                queue.append(neighbor)
    if not resolved:
        raise ValueError("resolved_sea_set is empty")
    return resolved


def latitude_for_y(y: float, world: dict[str, Any], height: int) -> float:
    latitude = world.get("latitude", {})
    north = float(latitude["north_latitude"])
    south = float(latitude["south_latitude"])
    equator_y = float(latitude["equator_y"])
    if not 0 < equator_y < height - 1:
        raise ValueError("latitude.equator_y must be inside the map")
    if y <= equator_y:
        return north * (1.0 - y / equator_y)
    ratio = (y - equator_y) / ((height - 1) - equator_y)
    return south * ratio


def heightmap_metadata(
    path: Path | None,
    world: dict[str, Any],
    province_shape: tuple[int, int],
    warnings: list[str],
) -> tuple[dict[str, Any], np.ndarray | None, np.ndarray | None]:
    authoritative = bool(world.get("heightmap", {}).get("authoritative", False))
    source = world.get("heightmap", {}).get("source")
    if path is None or not path.exists():
        return {
            "present": False,
            "authoritative": authoritative,
            "elevation_source": source,
            "mode": None,
            "width_px": None,
            "height_px": None,
            "raw_min": None,
            "raw_max": None,
        }, None, None

    with Image.open(path) as image:
        mode = image.mode
        raw = np.asarray(image)
        width, height = image.size
    raw_min = float(np.min(raw))
    raw_max = float(np.max(raw))
    metadata = {
        "present": True,
        "authoritative": authoritative,
        "elevation_source": source,
        "mode": mode,
        "width_px": width,
        "height_px": height,
        "raw_min": raw_min,
        "raw_max": raw_max,
    }
    if raw.shape[:2] != province_shape:
        message = (
            f"heightmap size {(width, height)} does not match provinces "
            f"{province_shape[::-1]}; resampling is forbidden"
        )
        if authoritative:
            raise ValueError(message)
        warnings.append(message + "; elevation omitted")
        return metadata, None, None

    scale = world.get("heightmap", {}).get("elevation_scale", {})
    raw_low = float(scale.get("raw_min", raw_min))
    raw_high = float(scale.get("raw_max", raw_max))
    elevation_low = float(scale.get("elevation_min_m", 0.0))
    elevation_high = float(scale.get("elevation_max_m", 1.0))
    denominator = max(raw_high - raw_low, 1.0)
    relative = np.clip((raw.astype(np.float64) - raw_low) / denominator, 0.0, 1.0)
    meters = elevation_low + relative * (elevation_high - elevation_low)
    return metadata, meters, raw.astype(np.float64)


def aggregate_elevation(
    inverse: np.ndarray,
    values: np.ndarray,
    province_count: int,
) -> tuple[np.ndarray, np.ndarray]:
    flat = values.ravel()
    area = np.bincount(inverse, minlength=province_count)
    mean = np.bincount(inverse, weights=flat, minlength=province_count) / np.maximum(area, 1)
    maximum = np.full(province_count, -np.inf, dtype=np.float64)
    np.maximum.at(maximum, inverse, flat)
    return mean, maximum


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def atomic_json_write(path: Path, value: Any, pretty: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp_{os.getpid()}")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            indent=2 if pretty else None,
            separators=None if pretty else (",", ":"),
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

    # Some Windows/sandbox combinations deny replace-over-existing even when
    # neither file is read-only. Keep a recoverable backup during the swap.
    backup = path.with_name(f".{path.name}.backup_{os.getpid()}")
    os.replace(path, backup)
    try:
        os.replace(temporary, path)
    except Exception:
        os.replace(backup, path)
        raise
    else:
        backup.unlink(missing_ok=True)


def build_graph(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    warnings: list[str] = []
    info: list[str] = []
    project_root = args.project_root.resolve()
    provinces_path = args.provinces.resolve()
    default_map_path = args.default_map.resolve()
    world_path = args.world.resolve()
    heightmap_path = None if args.no_heightmap else args.heightmap.resolve()
    water_mask_path = args.water_mask.resolve() if args.water_mask and args.water_mask.exists() else None
    water_candidates_path = (
        args.water_candidates.resolve()
        if args.water_candidates and args.water_candidates.exists()
        else None
    )

    for required in (provinces_path, default_map_path, world_path):
        if not required.exists():
            raise FileNotFoundError(required)

    world = load_yaml(world_path)
    if world.get("schema_version") != "world.v0.1":
        raise ValueError("world.yaml schema_version must be world.v0.1")

    encoded, provinces_mode = encode_provinces(provinces_path)
    height, width = encoded.shape
    map_config = world.get("map", {})
    configured_width = int(map_config.get("width_px", width))
    configured_height = int(map_config.get("height_px", height))
    if (configured_width, configured_height) != (width, height):
        raise ValueError(
            f"world map size {(configured_width, configured_height)} does not match provinces {(width, height)}"
        )

    unique_colors, inverse = np.unique(encoded.ravel(), return_inverse=True)
    color_set = {int(value) for value in unique_colors}
    geometry = compute_geometry(inverse, width, height, len(unique_colors))
    hints = parse_default_map(default_map_path)
    wrap_x = bool(hints["wrap_x"])
    shared, perimeter = aggregate_boundaries(encoded, unique_colors, wrap_x=wrap_x)
    sea_starts_all = {color_to_int(value) for value in hints["sea_starts"]}
    lake_starts_all = {color_to_int(value) for value in hints["lake_starts"]}
    missing_starts = (sea_starts_all | lake_starts_all) - color_set
    if missing_starts:
        warnings.append(f"{len(missing_starts)} water starts are absent from provinces.png")
    sea_starts = sea_starts_all & color_set
    lake_starts = lake_starts_all & color_set

    candidate_source: Path | None = None
    candidate_source_type: str | None = None
    default_candidates = {color_to_int(value) for value in hints["water_candidates"]} & color_set
    if default_candidates:
        water_candidates = default_candidates
        candidate_source = default_map_path
        candidate_source_type = "default_map_full_water_list"
    elif water_candidates_path is not None:
        water_candidates = {color_to_int(value) for value in parse_color_file(water_candidates_path)}
        candidate_source = water_candidates_path
        candidate_source_type = "explicit_color_list"
    elif water_mask_path is not None:
        water_candidates = water_candidates_from_mask(water_mask_path, encoded)
        candidate_source = water_mask_path
        candidate_source_type = "water_mask"
    else:
        raise ValueError(
            "water candidates unavailable; provide --water-candidates or --water-mask"
        )

    missing_candidates = water_candidates - color_set
    if missing_candidates:
        warnings.append(f"{len(missing_candidates)} water candidates are absent from provinces.png")
    water_candidates &= color_set
    resolved_sea = resolve_sea_set(sea_starts, water_candidates, shared)
    unresolved_water = water_candidates - resolved_sea
    unresolved_components = connected_components(unresolved_water, shared)
    if unresolved_components:
        warnings.append(
            f"{len(unresolved_components)} unresolved inland-water/lake candidate components found"
        )
    if lake_starts & resolved_sea:
        warnings.append("lake_starts overlap resolved_sea_set")

    height_metadata, elevation_meters, _ = heightmap_metadata(
        heightmap_path,
        world,
        encoded.shape,
        warnings,
    )
    elevation_mean = elevation_max = None
    if elevation_meters is not None:
        elevation_mean, elevation_max = aggregate_elevation(
            inverse, elevation_meters, len(unique_colors)
        )

    color_to_index = {int(color): index for index, color in enumerate(unique_colors)}
    sea_border = np.zeros(len(unique_colors), dtype=np.int64)
    for color, neighbors in shared.items():
        if color in resolved_sea:
            continue
        index = color_to_index[color]
        sea_border[index] = sum(
            border for neighbor, border in neighbors.items() if neighbor in resolved_sea
        )

    provinces: dict[str, Any] = {}
    adjacency: dict[str, dict[str, Any]] = {}
    degenerate_edges: list[dict[str, Any]] = []
    small_provinces: list[dict[str, Any]] = []
    coastal_provinces: list[dict[str, Any]] = []
    area_values = geometry["area"]

    for color_int, index in color_to_index.items():
        key = int_to_key(color_int)
        is_sea = color_int in resolved_sea
        area_px = int(area_values[index])
        perimeter_px = int(perimeter[index])
        if perimeter_px <= 0:
            raise ValueError(f"{key}: perimeter_px must be positive")
        center_x = float(geometry["center_x"][index])
        center_y = float(geometry["center_y"][index])
        latitude = latitude_for_y(center_y, world, height)
        if not -90.0 <= latitude <= 90.0:
            raise ValueError(f"{key}: latitude outside -90..90: {latitude}")
        coastal_ratio = 0.0 if is_sea else float(sea_border[index] / perimeter_px)
        elevation = None
        if elevation_mean is not None and elevation_max is not None:
            elevation = {
                "elevation_m": round(float(elevation_mean[index]), 3),
                "elevation_max_m": round(float(elevation_max[index]), 3),
            }
        province = {
            "color_hex": f"{color_int:06X}",
            "is_sea": is_sea,
            "is_simulation_target": not is_sea,
            "center": {"x": round(center_x, 3), "y": round(center_y, 3)},
            "area_px": area_px,
            "perimeter_px": perimeter_px,
            "bbox": {
                "x_min": int(geometry["x_min"][index]),
                "x_max": int(geometry["x_max"][index]),
                "y_min": int(geometry["y_min"][index]),
                "y_max": int(geometry["y_max"][index]),
            },
            "latitude": round(latitude, 6),
            "coastal_ratio": round(coastal_ratio, 6),
            "is_coastal": (not is_sea) and coastal_ratio > 0.0,
            "elevation": elevation,
        }
        provinces[key] = province
        adjacency[key] = {}
        if area_px < 4:
            small_provinces.append({"province": key, "area_px": area_px})
        if province["is_coastal"]:
            coastal_provinces.append(
                {
                    "province": key,
                    "coastal_ratio": province["coastal_ratio"],
                    "sea_shared_border_px": int(sea_border[index]),
                }
            )

    for color_int, neighbors in shared.items():
        source_key = int_to_key(color_int)
        source = provinces[source_key]
        source_x = float(source["center"]["x"])
        source_y = float(source["center"]["y"])
        source_perimeter = int(source["perimeter_px"])
        for neighbor_int, shared_border in neighbors.items():
            target_key = int_to_key(neighbor_int)
            target = provinces[target_key]
            dx = float(target["center"]["x"]) - source_x
            dy = float(target["center"]["y"]) - source_y
            if wrap_x and abs(dx) > width / 2:
                dx -= math.copysign(width, dx)
            distance = math.hypot(dx, dy)
            if distance == 0.0:
                degenerate_edges.append(
                    {"source": source_key, "target": target_key, "reason": "distance_px=0"}
                )
                continue
            adjacency[source_key][target_key] = {
                "shared_border_px": int(shared_border),
                "border_weight": round(shared_border / source_perimeter, 8),
                "direction": {
                    "x": round(dx / distance, 8),
                    "y": round(dy / distance, 8),
                },
                "distance_px": round(distance, 4),
            }

    topology_inputs = [
        ("provinces_png", provinces_path),
        ("default_map", default_map_path),
        ("world_yaml", world_path),
    ]
    if candidate_source is not None and candidate_source.resolve() != default_map_path.resolve():
        topology_inputs.append(("water_candidates", candidate_source))
    topology_hash = combined_hash(SCHEMA_VERSION, topology_inputs)
    if heightmap_path is not None and heightmap_path.exists():
        digest = hashlib.sha256()
        digest.update(heightmap_path.read_bytes())
        digest.update(canonical_json_hash(world.get("heightmap", {})))
        heightmap_stats_hash = "sha256:" + digest.hexdigest()
    else:
        heightmap_stats_hash = None

    land_areas = [
        int(area_values[index])
        for color, index in color_to_index.items()
        if color not in resolved_sea
    ]
    median_area = float(np.median(land_areas)) if land_areas else 0.0
    metadata = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_status": "success",
        "source_files": {
            "provinces_png": display_path(provinces_path, project_root),
            "default_map": display_path(default_map_path, project_root),
            "water_candidates": display_path(candidate_source, project_root),
            "water_mask_png": display_path(water_mask_path, project_root),
            "heightmap_png": display_path(heightmap_path, project_root),
            "world_yaml": display_path(world_path, project_root),
        },
        "source_hashes": {
            "provinces_png": sha256_file(provinces_path),
            "default_map": sha256_file(default_map_path),
            "water_candidates": sha256_file(candidate_source) if candidate_source else None,
            "water_mask_png": sha256_file(water_mask_path) if water_mask_path else None,
            "heightmap_png": sha256_file(heightmap_path)
            if heightmap_path and heightmap_path.exists()
            else None,
            "world_yaml": sha256_file(world_path),
        },
        "world": {
            "width_px": width,
            "height_px": height,
            "north_latitude": float(world["latitude"]["north_latitude"]),
            "south_latitude": float(world["latitude"]["south_latitude"]),
            "equator_y": float(world["latitude"]["equator_y"]),
            "latitude_mapping": world["latitude"].get("mapping", "piecewise_equator"),
            "lon_left": float(world.get("longitude", {}).get("left", -180.0)),
            "lon_right": float(world.get("longitude", {}).get("right", 180.0)),
            "wrap_x": wrap_x,
        },
        "heightmap": height_metadata,
        "water": {
            "candidate_source_type": candidate_source_type,
            "candidate_count": len(water_candidates),
            "sea_start_count": len(sea_starts),
            "resolved_sea_count": len(resolved_sea),
            "unresolved_candidate_count": len(unresolved_water),
            "lake_start_count": len(lake_starts),
            "default_map_wrap_x": wrap_x,
        },
        "hash": {
            "topology_hash": topology_hash,
            "heightmap_stats_hash": heightmap_stats_hash,
        },
        "province_count": {
            "total": len(unique_colors),
            "land": len(unique_colors) - len(resolved_sea),
            "sea": len(resolved_sea),
        },
        "statistics": {
            "median_land_area_px": median_area,
            "adjacency_directed_edge_count": sum(len(value) for value in adjacency.values()),
            "small_province_count": len(small_provinces),
            "coastal_province_count": len(coastal_provinces),
            "degenerate_adjacency_count": len(degenerate_edges),
        },
        "provinces_image_mode": provinces_mode,
    }
    graph = {
        "schema_version": SCHEMA_VERSION,
        "metadata": metadata,
        "provinces": provinces,
        "adjacency": adjacency,
    }
    debug_context = {
        "warnings": warnings,
        "info": info,
        "small_provinces": small_provinces,
        "coastal_provinces": coastal_provinces,
        "degenerate_edges": degenerate_edges,
        "water_components": connected_components(water_candidates, shared),
        "unresolved_components": unresolved_components,
        "encoded": encoded,
        "inverse": inverse,
        "unique_colors": unique_colors,
        "resolved_sea": resolved_sea,
        "coastal_ratios": np.array(
            [provinces[int_to_key(int(color))]["coastal_ratio"] for color in unique_colors],
            dtype=np.float32,
        ),
        "degrees": np.array(
            [len(adjacency[int_to_key(int(color))]) for color in unique_colors],
            dtype=np.float32,
        ),
    }
    return graph, debug_context


def validate_graph(graph: dict[str, Any], context: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings = list(context["warnings"])
    if graph.get("schema_version") != SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    provinces = graph.get("provinces", {})
    adjacency = graph.get("adjacency", {})
    if set(provinces) != set(adjacency):
        errors.append("provinces and adjacency key sets differ")
    for key, province in provinces.items():
        if int(province["perimeter_px"]) <= 0:
            errors.append(f"{key}: perimeter_px <= 0")
        if not -90.0 <= float(province["latitude"]) <= 90.0:
            errors.append(f"{key}: latitude outside -90..90")
        expected_coastal = (not province["is_sea"]) and province["coastal_ratio"] > 0
        if province["is_coastal"] != expected_coastal:
            errors.append(f"{key}: is_coastal inconsistent with coastal_ratio")
        border_sum = sum(float(edge["border_weight"]) for edge in adjacency.get(key, {}).values())
        if border_sum > 1.01:
            warnings.append(f"{key}: border_weight sum {border_sum:.6f} exceeds 1.01")
        for target, edge in adjacency.get(key, {}).items():
            direction = edge["direction"]
            length = math.hypot(float(direction["x"]), float(direction["y"]))
            if abs(length - 1.0) > 0.01:
                errors.append(f"{key}->{target}: direction is not unit length")
    counts = graph["metadata"]["province_count"]
    if counts["land"] + counts["sea"] != counts["total"]:
        errors.append("land + sea != total province count")
    return errors, warnings


def write_debug_artifacts(
    debug_dir: Path,
    graph: dict[str, Any],
    context: dict[str, Any],
    include_images: bool,
) -> list[str]:
    debug_dir.mkdir(parents=True, exist_ok=True)
    artifact_paths: list[str] = []
    report_path = debug_dir / "province_graph_build_report.json"
    report = {
        "schema_version": "province_graph_build_report.v0.1",
        "generated_at": graph["metadata"]["generated_at"],
        "validation_status": graph["metadata"]["validation_status"],
        "warnings": context["warnings"],
        "info": context["info"],
        "metadata": graph["metadata"],
    }
    atomic_json_write(report_path, report, pretty=True)
    artifact_paths.append(str(report_path))

    land_areas = [
        province["area_px"]
        for province in graph["provinces"].values()
        if not province["is_sea"]
    ]
    histogram, edges = np.histogram(land_areas, bins=20) if land_areas else ([], [])
    histogram_rows = []
    for index, count in enumerate(histogram):
        histogram_rows.append(
            {
                "bin_min": round(float(edges[index]), 3),
                "bin_max": round(float(edges[index + 1]), 3),
                "province_count": int(count),
            }
        )
    write_csv(
        debug_dir / "province_area_histogram.csv",
        ["bin_min", "bin_max", "province_count"],
        histogram_rows,
    )
    write_csv(
        debug_dir / "small_provinces.csv",
        ["province", "area_px"],
        context["small_provinces"],
    )
    write_csv(
        debug_dir / "coastal_provinces.csv",
        ["province", "coastal_ratio", "sea_shared_border_px"],
        context["coastal_provinces"],
    )
    write_csv(
        debug_dir / "degenerate_adjacency.csv",
        ["source", "target", "reason"],
        context["degenerate_edges"],
    )
    water_rows = []
    resolved_sea = context["resolved_sea"]
    for index, component in enumerate(context["water_components"], 1):
        water_rows.append(
            {
                "component_id": index,
                "province_count": len(component),
                "resolved_as_sea": bool(component & resolved_sea),
                "sample_provinces": " ".join(int_to_key(value) for value in sorted(component)[:10]),
            }
        )
    write_csv(
        debug_dir / "water_components.csv",
        ["component_id", "province_count", "resolved_as_sea", "sample_provinces"],
        water_rows,
    )
    unresolved_rows = []
    for index, component in enumerate(context["unresolved_components"], 1):
        for province in sorted(component):
            unresolved_rows.append(
                {"component_id": index, "province": int_to_key(province)}
            )
    write_csv(
        debug_dir / "unresolved_lake_candidates.csv",
        ["component_id", "province"],
        unresolved_rows,
    )

    for name in (
        "province_area_histogram.csv",
        "small_provinces.csv",
        "coastal_provinces.csv",
        "degenerate_adjacency.csv",
        "water_components.csv",
        "unresolved_lake_candidates.csv",
    ):
        artifact_paths.append(str(debug_dir / name))

    if include_images:
        encoded = context["encoded"]
        sea_values = np.array(sorted(resolved_sea), dtype=np.int32)
        sea_mask = np.isin(encoded, sea_values)
        sea_land = np.zeros((*encoded.shape, 3), dtype=np.uint8)
        sea_land[sea_mask] = (47, 98, 166)
        sea_land[~sea_mask] = (224, 221, 190)
        Image.fromarray(sea_land, mode="RGB").save(debug_dir / "sea_land_mask.png")

        inverse = context["inverse"]
        ratios = context["coastal_ratios"][inverse].reshape(encoded.shape)
        ratio_image = np.zeros((*encoded.shape, 3), dtype=np.uint8)
        ratio_image[:, :, 0] = np.clip(ratios * 255, 0, 255).astype(np.uint8)
        ratio_image[:, :, 1] = np.clip((1.0 - ratios) * 180, 0, 255).astype(np.uint8)
        ratio_image[:, :, 2] = 80
        ratio_image[sea_mask] = (47, 98, 166)
        Image.fromarray(ratio_image, mode="RGB").save(
            debug_dir / "coastal_ratio_preview.png"
        )

        degrees = context["degrees"]
        degree_max = max(float(np.max(degrees)), 1.0)
        degree_values = degrees[inverse].reshape(encoded.shape) / degree_max
        degree_image = np.zeros((*encoded.shape, 3), dtype=np.uint8)
        degree_image[:, :, 0] = np.clip(degree_values * 255, 0, 255).astype(np.uint8)
        degree_image[:, :, 1] = 100
        degree_image[:, :, 2] = np.clip((1.0 - degree_values) * 255, 0, 255).astype(np.uint8)
        Image.fromarray(degree_image, mode="RGB").save(
            debug_dir / "adjacency_degree_preview.png"
        )
        artifact_paths.extend(
            str(debug_dir / name)
            for name in (
                "sea_land_mask.png",
                "coastal_ratio_preview.png",
                "adjacency_degree_preview.png",
            )
        )
    return artifact_paths


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    map_data = project_root.parent / "map_data"
    sea_candidates = map_data / "state_regions" / "99_pav_seas.txt"
    return {
        "project_root": project_root,
        "provinces": map_data / "provinces.png",
        "default_map": map_data / "default.map",
        "world": project_root / "config" / "world.yaml",
        "heightmap": map_data / "heightmap.png",
        "water_mask": map_data / "water_mask.png",
        "water_candidates": sea_candidates,
        "output": project_root / "cache" / "province_graph.json",
        "debug_dir": project_root / "cache" / "debug",
    }


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Build province_graph.v0.2 topology cache")
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--provinces", type=Path, default=defaults["provinces"])
    parser.add_argument("--default-map", type=Path, default=defaults["default_map"])
    parser.add_argument("--world", type=Path, default=defaults["world"])
    parser.add_argument("--heightmap", type=Path, default=defaults["heightmap"])
    parser.add_argument("--water-mask", type=Path, default=defaults["water_mask"])
    parser.add_argument(
        "--water-candidates",
        type=Path,
        default=defaults["water_candidates"],
        help="Explicit file containing all water candidate province colors",
    )
    parser.add_argument("--output", type=Path, default=defaults["output"])
    parser.add_argument("--debug-dir", type=Path, default=defaults["debug_dir"])
    parser.add_argument("--no-heightmap", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        graph, context = build_graph(args)
        errors, warnings = validate_graph(graph, context)
        context["warnings"] = warnings
        if errors:
            graph["metadata"]["validation_status"] = "failed"
            for error in errors:
                print(f"ERROR: {error}")
            return 1
        if warnings and args.fail_on_warning:
            graph["metadata"]["validation_status"] = "failed"
            for warning in warnings:
                print(f"WARNING: {warning}")
            return 2
        atomic_json_write(args.output, graph, pretty=args.pretty)
        artifacts = write_debug_artifacts(
            args.debug_dir,
            graph,
            context,
            include_images=args.debug,
        )
        print(f"wrote: {args.output}")
        print(f"schema_version: {graph['schema_version']}")
        print(f"province_count: {graph['metadata']['province_count']['total']}")
        print(f"land_count: {graph['metadata']['province_count']['land']}")
        print(f"sea_count: {graph['metadata']['province_count']['sea']}")
        print(f"topology_hash: {graph['metadata']['hash']['topology_hash']}")
        print(f"warnings: {len(warnings)}")
        for warning in warnings[:20]:
            print(f"WARNING: {warning}")
        if len(warnings) > 20:
            print(f"WARNING: ... {len(warnings) - 20} more")
        print(f"debug_artifacts: {len(artifacts)}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
