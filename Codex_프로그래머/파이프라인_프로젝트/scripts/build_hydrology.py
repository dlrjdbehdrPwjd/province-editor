from __future__ import annotations

import argparse
import math
import os
import sys
from collections import deque
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_climate_pipeline as climate


SCHEMA_VERSION = "hydrology.v0.5"
SEASONAL_SCHEMA_VERSION = "seasonal_climate.v0.4.1"
BOOTSTRAP_SCHEMA_VERSION = "bootstrap_fields.v0.1"
GRAPH_SCHEMA_VERSION = "province_graph.v0.2"


DEFAULT_HYDROLOGY_PARAMS = {
    "river_threshold_percentile": 87.0,
    "lake_threshold": 50.0,
    "lake_full_threshold": 200.0,
    "salt_flat_runoff_threshold": 5.0,
    "wetland_rainfall_threshold": 30.0,
    "wetland_storage_threshold": 20.0,
    "river_bonus_factor": 0.05,
    "river_bonus_decay": 50.0,
    "open_water_factor": 1.0,
    "runoff_base_coeff": 0.10,
    "runoff_saturation_weight": 0.20,
    "runoff_dry_season_weight": 0.15,
    "runoff_coeff_min": 0.02,
    "runoff_coeff_max": 0.45,
}


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    province_project = project_root.parent / "프로빈스_프로젝트"
    return {
        "project_root": project_root,
        "province_graph": project_root / "cache" / "province_graph.json",
        "bootstrap_fields": project_root / "cache" / "bootstrap_fields.json",
        "seasonal_climate": project_root / "cache" / "seasonal_climate.json",
        "province_constraints": province_project / "config" / "province_constraints.yaml",
        "province_overrides": province_project / "config" / "province_overrides.yaml",
        "params": project_root / "config" / "climate_rules.yaml",
        "output": project_root / "cache" / "hydrology.json",
        "draft_rivers": project_root / "outputs" / "draft_rivers.png",
    }


def atomic_write_json(path: Path, data: Any, pretty: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    climate.atomic_write_json(temp, data, pretty=pretty)
    os.replace(temp, path)


def load_optional_mapping_document(path: Path, label: str, root_key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        return climate.load_mapping_document(path, label, root_key)
    except ValueError:
        document = climate.load_yaml(path, label)
        raw = document.get(root_key, {})
        if raw is None:
            return {}
        if not isinstance(raw, dict):
            raise
        result: dict[str, dict[str, Any]] = {}
        for raw_color, data in raw.items():
            if not isinstance(raw_color, str) or not raw_color.lower().startswith("x"):
                continue
            color = climate.normalize_color(raw_color)
            if not isinstance(data, dict):
                raise ValueError(f"{label} {color} must be a mapping")
            result[color] = data
        return result


def load_hydrology_params(path: Path) -> tuple[dict[str, float], dict[str, float]]:
    document = climate.load_yaml(path, "climate_rules.yaml")
    hydro = {**DEFAULT_HYDROLOGY_PARAMS, **document.get("hydrology", {})}
    for key, value in list(hydro.items()):
        hydro[key] = climate.finite_number(value, f"hydrology.{key}")
    if not 0.0 <= hydro["river_threshold_percentile"] <= 100.0:
        raise ValueError("hydrology.river_threshold_percentile must be in 0..100")
    for key in (
        "lake_threshold", "lake_full_threshold", "salt_flat_runoff_threshold",
        "wetland_rainfall_threshold", "wetland_storage_threshold",
        "river_bonus_factor", "river_bonus_decay", "open_water_factor",
        "runoff_base_coeff", "runoff_saturation_weight", "runoff_dry_season_weight",
        "runoff_coeff_min", "runoff_coeff_max",
    ):
        if hydro[key] < 0.0:
            raise ValueError(f"hydrology.{key} must be non-negative")
    if hydro["river_bonus_decay"] <= 0.0:
        raise ValueError("hydrology.river_bonus_decay must be positive")
    if hydro["runoff_coeff_min"] > hydro["runoff_coeff_max"]:
        raise ValueError("hydrology.runoff_coeff_min must be <= runoff_coeff_max")
    seasonal = document.get("seasonal_climate", {})
    pet_coefficient = climate.finite_number(seasonal.get("pet_coefficient", 0.1), "seasonal_climate.pet_coefficient")
    storage_capacity = climate.finite_number(seasonal.get("storage_capacity", 10.0), "seasonal_climate.storage_capacity")
    if storage_capacity < 0.0:
        raise ValueError("seasonal_climate.storage_capacity must be non-negative")
    return hydro, {"pet_coefficient": pet_coefficient, "storage_capacity": storage_capacity}


def validate_inputs(graph: dict[str, Any], bootstrap: dict[str, Any], seasonal: dict[str, Any]) -> list[str]:
    if graph.get("schema_version") != GRAPH_SCHEMA_VERSION:
        raise ValueError(f"expected {GRAPH_SCHEMA_VERSION}, got {graph.get('schema_version')}")
    if bootstrap.get("schema_version") != BOOTSTRAP_SCHEMA_VERSION:
        raise ValueError(f"expected {BOOTSTRAP_SCHEMA_VERSION}, got {bootstrap.get('schema_version')}")
    if seasonal.get("schema_version") != SEASONAL_SCHEMA_VERSION:
        raise ValueError(f"expected {SEASONAL_SCHEMA_VERSION}, got {seasonal.get('schema_version')}")
    land = [
        color for color, province in graph["provinces"].items()
        if not bool(province.get("is_sea", False)) and color in seasonal["provinces"]
    ]
    missing_bootstrap = [color for color in land if color not in bootstrap["provinces"]]
    if missing_bootstrap:
        raise ValueError(f"bootstrap_fields missing provinces: {missing_bootstrap[:5]}")
    return sorted(land)


def normalize_constraints(raw: dict[str, dict[str, Any]], land: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    land_set = set(land)
    warnings = [f"unknown hydrology constraint province ignored: {color}" for color in sorted(set(raw) - land_set)]
    result: dict[str, dict[str, Any]] = {}
    for color in land:
        data = raw.get(color, {})
        river_path_raw = data.get("river_path", [])
        if river_path_raw in (None, False):
            river_path: list[str] = []
        elif isinstance(river_path_raw, list):
            river_path = [climate.normalize_color(str(item)) for item in river_path_raw]
        else:
            raise ValueError(f"{color}.river_path must be a list")
        if river_path and river_path[0] != color:
            river_path = [color, *river_path]
        result[color] = {
            "river_seed": bool(data.get("river_seed", False)),
            "river_major": bool(data.get("river_major", False)),
            "river_path": river_path,
            "lake_seed": bool(data.get("lake_seed", False)),
            "wetland_seed": bool(data.get("wetland_seed", False)),
        }
    return result, warnings


def normalize_overrides(raw: dict[str, dict[str, Any]], land: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    land_set = set(land)
    warnings = [f"unknown hydrology override province ignored: {color}" for color in sorted(set(raw) - land_set)]
    result: dict[str, dict[str, Any]] = {}
    for color in land:
        data = raw.get(color, {})
        result[color] = {
            "exclude_from_sim": bool(data.get("exclude_from_sim", False)),
            "force_terrain": data.get("force_terrain"),
            "locked": bool(data.get("locked", False)),
        }
    return result, warnings


def color_id(color: str) -> int:
    return int(color[1:], 16)


def choose_sea_outlet(graph: dict[str, Any], color: str, sea_neighbors: list[str]) -> str:
    adjacency = graph["adjacency"][color]
    return min(
        sea_neighbors,
        key=lambda neighbor: (
            -float(adjacency[neighbor].get("shared_border_px", 0.0)),
            float(adjacency[neighbor].get("distance_px", 0.0)),
            color_id(neighbor),
        ),
    )


def build_flow_direction(
    graph: dict[str, Any],
    bootstrap: dict[str, Any],
    land: list[str],
    constraints: dict[str, dict[str, Any]],
) -> tuple[dict[str, str | None], dict[str, bool], list[str]]:
    land_set = set(land)
    warnings: list[str] = []
    is_flow_sink = {
        color: bool(bootstrap["provinces"][color].get("is_flow_sink", False)) or bool(constraints[color]["lake_seed"])
        for color in land
    }
    flow_direction: dict[str, str | None] = {color: None for color in land}
    potential = {color: float(bootstrap["provinces"][color]["synthetic_flow_potential"]) for color in land}
    tie_break_count = 0
    for color in land:
        if is_flow_sink[color]:
            flow_direction[color] = None
            continue
        adjacency = graph["adjacency"].get(color, {})
        valid_neighbors = [neighbor for neighbor in adjacency if neighbor in land_set]
        sea_neighbors = [
            neighbor for neighbor in adjacency
            if neighbor in graph["provinces"] and bool(graph["provinces"][neighbor].get("is_sea", False))
        ]
        lower = [neighbor for neighbor in valid_neighbors if potential[neighbor] < potential[color]]
        if lower:
            best = min(
                lower,
                key=lambda neighbor: (
                    potential[neighbor],
                    float(adjacency[neighbor].get("distance_px", 0.0)),
                    color_id(neighbor),
                ),
            )
            tied = [
                neighbor for neighbor in lower
                if abs(potential[neighbor] - potential[best]) < 1e-12
            ]
            if len(tied) > 1:
                tie_break_count += 1
            flow_direction[color] = best
            continue
        if sea_neighbors:
            flow_direction[color] = choose_sea_outlet(graph, color, sea_neighbors)
            continue
        is_flow_sink[color] = True
        flow_direction[color] = None
        warnings.append(f"natural pit detected: {color}")
    if tie_break_count:
        warnings.append(f"flow direction tie-break applied in {tie_break_count} province(s)")
    return flow_direction, is_flow_sink, warnings


def apply_river_paths(
    flow_direction: dict[str, str | None],
    constraints: dict[str, dict[str, Any]],
    land: list[str],
    graph: dict[str, Any],
) -> tuple[set[str], list[str]]:
    land_set = set(land)
    path_nodes: set[str] = set()
    warnings: list[str] = []
    for color in land:
        path = constraints[color]["river_path"]
        if not path:
            continue
        for item in path:
            if item not in graph["provinces"]:
                raise ValueError(f"river_path references unknown province: {item}")
        path_nodes.update(item for item in path if item in land_set)
        for upstream, downstream in zip(path, path[1:]):
            if upstream not in land_set:
                raise ValueError(f"river_path upstream is not land: {upstream}")
            if downstream not in graph["provinces"]:
                raise ValueError(f"river_path downstream unknown: {downstream}")
            flow_direction[upstream] = downstream
    return path_nodes, warnings


def topological_sort_flow(flow_direction: dict[str, str | None], land: list[str]) -> list[str]:
    land_set = set(land)
    indegree = {color: 0 for color in land}
    children = {color: [] for color in land}
    for color, downstream in flow_direction.items():
        if downstream in land_set:
            indegree[downstream] += 1
            children[color].append(downstream)
    queue = deque([color for color in land if indegree[color] == 0])
    order: list[str] = []
    while queue:
        color = queue.popleft()
        order.append(color)
        for downstream in children[color]:
            indegree[downstream] -= 1
            if indegree[downstream] == 0:
                queue.append(downstream)
    if len(order) != len(land):
        cycle_nodes = [color for color, degree in indegree.items() if degree > 0]
        raise ValueError(f"river_path cycle detected: {cycle_nodes[:12]}")
    return order


def accumulate_flow(
    flow_direction: dict[str, str | None],
    land: list[str],
    order: list[str],
    local_water: dict[str, float],
    overrides: dict[str, dict[str, Any]],
) -> tuple[dict[str, float], float]:
    land_set = set(land)
    accumulated = {color: 0.0 for color in land}
    sea_discharge = 0.0
    for color in order:
        local = 0.0 if overrides[color]["exclude_from_sim"] else local_water[color]
        accumulated[color] += local
        downstream = flow_direction[color]
        if downstream in land_set:
            accumulated[downstream] += accumulated[color]
        elif downstream is not None:
            sea_discharge += accumulated[color]
    return accumulated, sea_discharge


def compute_effective_runoff(
    color: str,
    seasonal: dict[str, Any],
    params: dict[str, float],
    seasonal_params: dict[str, float],
) -> float:
    values = seasonal["provinces"][color]
    rainfall = float(values["annual_rainfall_raw"])
    et = float(values["annual_ET"])
    surplus = max(0.0, rainfall - et)
    storage_capacity = max(float(seasonal_params["storage_capacity"]), 1e-12)
    storage = float(values["soil_water_storage_final"])
    saturation = climate.clamp(storage / storage_capacity, 0.0, 1.0)
    dry_strength = climate.clamp(float(values["dry_season_strength"]), 0.0, 1.0)
    coeff = (
        float(params["runoff_base_coeff"])
        + float(params["runoff_saturation_weight"]) * saturation
        + float(params["runoff_dry_season_weight"]) * dry_strength
    )
    coeff = climate.clamp(coeff, float(params["runoff_coeff_min"]), float(params["runoff_coeff_max"]))
    return surplus * coeff


def build_local_water(
    seasonal: dict[str, Any],
    land: list[str],
    params: dict[str, float],
    seasonal_params: dict[str, float],
) -> tuple[dict[str, float], str]:
    runoff = {color: float(seasonal["provinces"][color]["annual_runoff"]) for color in land}
    if any(value > 0.0 for value in runoff.values()):
        return runoff, "annual_runoff"
    effective = {
        color: compute_effective_runoff(color, seasonal, params, seasonal_params)
        for color in land
    }
    return effective, "effective_runoff_proxy"


def percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q / 100.0
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[int(position)]
    fraction = position - lower
    return ordered[lower] * (1.0 - fraction) + ordered[upper] * fraction


def classify_hydrology(
    graph: dict[str, Any],
    bootstrap: dict[str, Any],
    seasonal: dict[str, Any],
    land: list[str],
    constraints: dict[str, dict[str, Any]],
    overrides: dict[str, dict[str, Any]],
    params: dict[str, float],
    seasonal_params: dict[str, float],
    flow_direction: dict[str, str | None],
    is_flow_sink: dict[str, bool],
    accumulated: dict[str, float],
    path_nodes: set[str],
) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    positive_accumulated = [value for value in accumulated.values() if value > 1e-12]
    threshold = percentile(positive_accumulated, float(params["river_threshold_percentile"])) if positive_accumulated else 0.0
    is_river: dict[str, bool] = {}
    is_lake: dict[str, bool] = {}
    is_salt_flat: dict[str, bool] = {}
    is_wetland: dict[str, bool] = {}
    lake_fraction: dict[str, float] = {}
    river_bonus = {color: 0.0 for color in land}
    corrected_et: dict[str, float] = {}
    land_set = set(land)
    for color in land:
        seeded = bool(constraints[color]["river_seed"])
        major = bool(constraints[color]["river_major"])
        path_member = color in path_nodes
        river = path_member or seeded or (threshold > 0.0 and accumulated[color] >= threshold)
        if seeded and is_flow_sink[color]:
            warnings.append(f"river_seed set on pit province: {color}")
        if major and not (seeded or path_member):
            warnings.append(f"river_major requires river_seed or river_path: {color}")
        is_river[color] = bool(river)
        lake = bool(is_flow_sink[color] and accumulated[color] >= float(params["lake_threshold"]))
        is_lake[color] = lake
        is_salt_flat[color] = bool(
            is_flow_sink[color]
            and not lake
            and float(seasonal["provinces"][color]["annual_runoff"]) < float(params["salt_flat_runoff_threshold"])
        )
        if lake:
            lake_fraction[color] = climate.clamp(
                accumulated[color] / max(float(params["lake_full_threshold"]), 1e-12),
                0.0,
                1.0,
            )
        else:
            lake_fraction[color] = 0.0
        is_wetland[color] = bool(
            constraints[color]["wetland_seed"]
            or (
                is_river[color]
                and float(seasonal["provinces"][color]["annual_rainfall_raw"]) >= float(params["wetland_rainfall_threshold"])
                and float(seasonal["provinces"][color]["soil_water_storage_final"]) >= float(params["wetland_storage_threshold"])
            )
        )

    bonus_factor = float(params["river_bonus_factor"])
    bonus_decay = float(params["river_bonus_decay"])
    for color in land:
        if not is_river[color]:
            continue
        for neighbor, edge in graph["adjacency"].get(color, {}).items():
            if neighbor not in land_set:
                continue
            distance = float(edge.get("distance_px", 0.0))
            river_bonus[neighbor] += accumulated[color] * bonus_factor * math.exp(-distance / bonus_decay)

    pet_coefficient = float(seasonal_params["pet_coefficient"])
    open_water_factor = float(params["open_water_factor"])
    for color in land:
        values = seasonal["provinces"][color]
        annual_et = float(values["annual_ET"])
        if is_lake[color]:
            summer_pet = max(0.0, float(values["summer_temperature"]) + 5.0) * pet_coefficient
            winter_pet = max(0.0, float(values["winter_temperature"]) + 5.0) * pet_coefficient
            open_water_correction = ((summer_pet + winter_pet) * 0.5) * open_water_factor * lake_fraction[color]
            corrected_et[color] = annual_et + open_water_correction
        else:
            corrected_et[color] = annual_et

    return {
        "river_threshold": threshold,
        "river_threshold_sample_count": len(positive_accumulated),
        "discharge": accumulated,
        "is_river": is_river,
        "is_lake": is_lake,
        "is_salt_flat": is_salt_flat,
        "is_wetland": is_wetland,
        "lake_fraction": lake_fraction,
        "river_bonus": river_bonus,
        "corrected_ET": corrected_et,
    }, warnings


def validate_output(output: dict[str, Any], land: list[str]) -> None:
    land_set = set(land)
    for key in ("discharge", "is_river", "is_lake", "is_salt_flat", "is_wetland", "lake_fraction", "river_bonus", "corrected_ET"):
        if set(output[key]) != land_set:
            raise ValueError(f"{key} province set mismatch")
    for color in land:
        for key in ("discharge", "lake_fraction", "river_bonus", "corrected_ET"):
            value = climate.finite_number(output[key][color], f"{key}.{color}")
            if value < -1e-9:
                raise ValueError(f"negative {key}: {color}")
        if not 0.0 <= output["lake_fraction"][color] <= 1.0:
            raise ValueError(f"lake_fraction out of range: {color}")
        if output["is_lake"][color] and output["is_salt_flat"][color]:
            raise ValueError(f"lake and salt_flat both true: {color}")


def build_output(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    graph = climate.load_json(args.province_graph, "province_graph.json")
    bootstrap = climate.load_json(args.bootstrap_fields, "bootstrap_fields.json")
    seasonal = climate.load_json(args.seasonal_climate, "seasonal_climate.json")
    land = validate_inputs(graph, bootstrap, seasonal)
    raw_constraints = load_optional_mapping_document(args.province_constraints, "province_constraints.yaml", "province_constraints")
    raw_overrides = load_optional_mapping_document(args.province_overrides, "province_overrides.yaml", "province_overrides")
    constraints, warnings = normalize_constraints(raw_constraints, land)
    overrides, override_warnings = normalize_overrides(raw_overrides, land)
    warnings.extend(override_warnings)
    params, seasonal_params = load_hydrology_params(args.params)
    flow_direction, is_flow_sink, flow_warnings = build_flow_direction(graph, bootstrap, land, constraints)
    warnings.extend(flow_warnings)
    path_nodes, path_warnings = apply_river_paths(flow_direction, constraints, land, graph)
    warnings.extend(path_warnings)
    order = topological_sort_flow(flow_direction, land)
    local_water, local_water_source = build_local_water(seasonal, land, params, seasonal_params)
    if local_water_source != "annual_runoff":
        warnings.append("annual_runoff is zero for all provinces; using effective_runoff proxy for hydrology accumulation")
    accumulated, sea_discharge = accumulate_flow(flow_direction, land, order, local_water, overrides)
    classified, class_warnings = classify_hydrology(
        graph, bootstrap, seasonal, land, constraints, overrides,
        params, seasonal_params, flow_direction, is_flow_sink,
        accumulated, path_nodes,
    )
    warnings.extend(class_warnings)
    output = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "seasonal_climate": climate.display_path(args.seasonal_climate, args.project_root),
            "bootstrap_fields": climate.display_path(args.bootstrap_fields, args.project_root),
            "province_graph": climate.display_path(args.province_graph, args.project_root),
            "province_constraints": climate.display_path(args.province_constraints, args.project_root),
            "province_overrides": climate.display_path(args.province_overrides, args.project_root),
            "climate_rules": climate.display_path(args.params, args.project_root),
        },
        "metadata": {
            "land_province_count": len(land),
            "river_threshold_percentile": params["river_threshold_percentile"],
            "river_threshold": classified["river_threshold"],
            "river_threshold_sample_count": classified["river_threshold_sample_count"],
            "sea_discharge": sea_discharge,
            "topological_order_count": len(order),
            "local_water_source": local_water_source,
        },
        "warnings": warnings,
        "flow_direction": flow_direction,
        "is_flow_sink": is_flow_sink,
        **classified,
    }
    validate_output(output, land)
    diagnostics = {
        "graph": graph,
        "land": land,
        "constraints": constraints,
        "params": params,
    }
    return output, diagnostics


def write_draft_rivers(path: Path, project_root: Path, graph: dict[str, Any], output: dict[str, Any]) -> Path:
    import numpy as np
    from PIL import Image

    source = Path(graph["metadata"]["source_files"]["provinces_png"])
    if not source.is_absolute():
        source = project_root / source
    image = Image.open(source).convert("RGB")
    preview_size = (min(2048, image.width), max(1, round(image.height * min(2048, image.width) / image.width)))
    image = image.resize(preview_size, Image.Resampling.NEAREST)
    rgb = np.asarray(image, dtype=np.uint32)
    ids = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    lookup = np.zeros((1 << 24, 3), dtype=np.uint8)
    lookup[:, :] = (185, 210, 235)
    for color in output["discharge"]:
        if output["is_lake"][color]:
            rgb_value = (60, 120, 220)
        elif output["is_salt_flat"][color]:
            rgb_value = (230, 220, 190)
        elif output["is_river"][color]:
            rgb_value = (20, 80, 210)
        elif output["is_wetland"][color]:
            rgb_value = (70, 150, 95)
        else:
            rgb_value = (238, 238, 220)
        lookup[int(color[1:], 16)] = rgb_value
    rendered = lookup[ids]
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rendered, mode="RGB").save(path)
    return path


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Build hydrology.v0.5 cache")
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--province-graph", type=Path, default=defaults["province_graph"])
    parser.add_argument("--bootstrap-fields", type=Path, default=defaults["bootstrap_fields"])
    parser.add_argument("--seasonal-climate", type=Path, default=defaults["seasonal_climate"])
    parser.add_argument("--province-constraints", type=Path, default=defaults["province_constraints"])
    parser.add_argument("--province-overrides", type=Path, default=defaults["province_overrides"])
    parser.add_argument("--params", type=Path, default=defaults["params"])
    parser.add_argument("--output", type=Path, default=defaults["output"])
    parser.add_argument("--draft-rivers", type=Path, default=defaults["draft_rivers"])
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
        draft_path = write_draft_rivers(args.draft_rivers, args.project_root, diagnostics["graph"], output) if args.debug else None
        print(f"wrote: {args.output}")
        print(f"schema_version: {output['schema_version']}")
        print(f"land_province_count: {output['metadata']['land_province_count']}")
        print(f"river_count: {sum(1 for value in output['is_river'].values() if value)}")
        print(f"lake_count: {sum(1 for value in output['is_lake'].values() if value)}")
        print(f"salt_flat_count: {sum(1 for value in output['is_salt_flat'].values() if value)}")
        print(f"wetland_count: {sum(1 for value in output['is_wetland'].values() if value)}")
        print(f"river_threshold: {output['metadata']['river_threshold']:.8f}")
        print(f"sea_discharge: {output['metadata']['sea_discharge']:.8f}")
        print(f"warnings: {len(output['warnings'])}")
        for warning in output["warnings"][:20]:
            print(f"WARNING: {warning}")
        if draft_path:
            print(f"draft_rivers: {draft_path}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
