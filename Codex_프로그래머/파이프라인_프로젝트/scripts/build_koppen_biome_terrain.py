from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import run_climate_pipeline as climate


SCHEMA_VERSION = "koppen_biome_terrain.v0.7"
RAINFALL_SCHEMA_VERSION = "rainfall_normalization.v0.6"
SEASONAL_SCHEMA_VERSION = "seasonal_climate.v0.4.1"
HYDROLOGY_SCHEMA_VERSION = "hydrology.v0.5"
BOOTSTRAP_SCHEMA_VERSION = "bootstrap_fields.v0.1"
GRAPH_SCHEMA_VERSION = "province_graph.v0.2"

VALID_TERRAINS = {"plains", "forest", "hills", "mountain", "jungle", "wetland", "desert", "tundra", "savanna", "snow"}


DEFAULT_PARAMS = {
    "epsilon": 0.000001,
    "aridity_cap": 3.0,
    "soil_moisture": {
        "et_world_scale": 1.0,
        "et_clamp_min": 0.0,
        "et_clamp_max": 1.5,
        "river_bonus_world_scale": 1.0,
        "river_bonus_clamp_min": 0.0,
        "river_bonus_clamp_max": 0.5,
        "lake_moisture_bonus": 0.25,
        "wetland_seed_soil_bonus": 0.20,
        "soil_moisture_min": -1.0,
        "soil_moisture_max": 1.0,
        "soil_moisture_cap": 1.5,
        "river_corridor_soil_min": 0.35,
        "dry_steppe_soil_max": 0.25,
        "grassland_soil_min": 0.45,
    },
    "elevation": {
        "upland_threshold_m": 500.0,
        "highland_threshold_m": 1200.0,
        "mountain_threshold_m": 1800.0,
        "highland_cool_summer_threshold": 18.0,
    },
    "koppen": {
        "b_base_threshold": 0.50,
        "b_summer_rain_multiplier": 1.15,
        "b_even_rain_multiplier": 1.00,
        "b_winter_rain_multiplier": 0.85,
        "summer_dominant_threshold": 0.70,
        "winter_dominant_threshold": 0.70,
        "desert_fraction": 0.50,
        "b_hot_threshold_c": 18.0,
        "ice_cap_summer_threshold": 0.0,
        "tundra_summer_threshold": 10.0,
        "tropical_coldest_threshold": 18.0,
        "tropical_af_dry_strength_max": 0.25,
        "tropical_monsoon_dry_rain_min": 0.15,
        "temperate_warmest_min": 10.0,
        "continental_winter_threshold": 0.0,
        "no_dry_season_strength_max": 0.25,
        "hot_summer_threshold": 22.0,
        "warm_summer_threshold": 10.0,
    },
}


def default_paths() -> dict[str, Path]:
    project_root = Path(__file__).resolve().parents[1]
    province_project = project_root.parent / "프로빈스_프로젝트"
    return {
        "project_root": project_root,
        "rainfall_normalized": project_root / "cache" / "rainfall_normalized.json",
        "seasonal": project_root / "cache" / "seasonal_climate.json",
        "hydrology": project_root / "cache" / "hydrology.json",
        "bootstrap": project_root / "cache" / "bootstrap_fields.json",
        "province_graph": project_root / "cache" / "province_graph.json",
        "province_constraints": province_project / "config" / "province_constraints.yaml",
        "province_overrides": province_project / "config" / "province_overrides.yaml",
        "params": project_root / "config" / "climate_rules.yaml",
        "terrain_lookup": project_root / "config" / "terrain_lookup.csv",
        "output": project_root / "cache" / "koppen_biome_terrain.json",
        "debug_dir": project_root / "cache" / "debug",
        "debug_image_dir": project_root / "outputs" / "debug",
    }


def deep_merge(default: dict[str, Any], supplied: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for key, value in default.items():
        if isinstance(value, dict):
            result[key] = deep_merge(value, supplied.get(key, {}) if isinstance(supplied.get(key, {}), dict) else {})
        else:
            result[key] = supplied.get(key, value)
    for key, value in supplied.items():
        if key not in result:
            result[key] = value
    return result


def canonical_hash(data: Any) -> str:
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    if not path.exists():
        return canonical_hash(None)
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


def load_params(path: Path) -> dict[str, Any]:
    doc = climate.load_yaml(path, "climate_rules.yaml")
    params = deep_merge(DEFAULT_PARAMS, doc.get("koppen_biome_terrain", {}))
    def walk(obj: dict[str, Any], prefix: str) -> None:
        for key, value in list(obj.items()):
            if isinstance(value, dict):
                walk(value, f"{prefix}.{key}")
            else:
                obj[key] = climate.finite_number(value, f"{prefix}.{key}")
    walk(params, "koppen_biome_terrain")
    if params["epsilon"] <= 0.0:
        raise ValueError("koppen_biome_terrain.epsilon must be positive")
    sm = params["soil_moisture"]
    if sm["soil_moisture_min"] >= sm["soil_moisture_max"]:
        raise ValueError("soil_moisture_min must be < soil_moisture_max")
    return params


def load_optional_mapping(path: Path, label: str, root_key: str) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        return climate.load_mapping_document(path, label, root_key)
    except ValueError:
        doc = climate.load_yaml(path, label)
        raw = doc.get(root_key, {})
        if not isinstance(raw, dict):
            return {}
        result = {}
        for raw_color, value in raw.items():
            if isinstance(raw_color, str) and raw_color.lower().startswith("x") and isinstance(value, dict):
                result[climate.normalize_color(raw_color)] = value
        return result


def normalize_constraints(raw: dict[str, dict[str, Any]], land: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    warnings = [f"unknown constraint province ignored: {color}" for color in sorted(set(raw) - set(land))]
    result = {}
    for color in land:
        data = raw.get(color, {})
        result[color] = {"fantasy_zone": data.get("fantasy_zone")}
    return result, warnings


def normalize_overrides(raw: dict[str, dict[str, Any]], land: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
    warnings = [f"unknown override province ignored: {color}" for color in sorted(set(raw) - set(land))]
    result = {}
    for color in land:
        data = raw.get(color, {})
        result[color] = {
            "locked": bool(data.get("locked", False)),
            "force_biome": data.get("force_biome"),
            "force_terrain": data.get("force_terrain"),
            "exclude_from_sim": bool(data.get("exclude_from_sim", False)),
        }
    return result, warnings


def validate_inputs(rainfall: dict[str, Any], seasonal: dict[str, Any], hydrology: dict[str, Any], bootstrap: dict[str, Any], graph: dict[str, Any]) -> list[str]:
    expected = [
        (rainfall, RAINFALL_SCHEMA_VERSION),
        (seasonal, SEASONAL_SCHEMA_VERSION),
        (hydrology, HYDROLOGY_SCHEMA_VERSION),
        (bootstrap, BOOTSTRAP_SCHEMA_VERSION),
        (graph, GRAPH_SCHEMA_VERSION),
    ]
    for doc, schema in expected:
        if doc.get("schema_version") != schema:
            raise ValueError(f"expected {schema}, got {doc.get('schema_version')}")
    land = sorted([color for color, province in graph["provinces"].items() if not bool(province.get("is_sea", False))])
    for name, doc, key in [
        ("rainfall_normalized", rainfall, "provinces"),
        ("seasonal_climate", seasonal, "provinces"),
        ("bootstrap_fields", bootstrap, "provinces"),
    ]:
        missing = [color for color in land if color not in doc.get(key, {})]
        if missing:
            raise ValueError(f"{name} missing land province: {missing[:5]}")
    for field in ("corrected_ET", "river_bonus", "lake_fraction", "discharge", "is_river", "is_lake", "is_salt_flat", "is_wetland"):
        if field not in hydrology:
            raise ValueError(f"hydrology.{field} missing")
        missing = [color for color in land if color not in hydrology[field]]
        if missing:
            raise ValueError(f"hydrology.{field} missing land province: {missing[:5]}")
    return land


def load_terrain_lookup(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"priority", "koppen_class", "biome_physical", "elevation_class", "soil_moisture_min", "soil_moisture_max", "vic3_terrain"}
        if set(reader.fieldnames or []) != required:
            missing = required - set(reader.fieldnames or [])
            if missing:
                raise ValueError(f"terrain_lookup.csv missing columns: {sorted(missing)}")
        for line_no, row in enumerate(reader, start=2):
            parsed = {
                "priority": int(float(row["priority"])),
                "koppen_class": row["koppen_class"].strip(),
                "biome_physical": row["biome_physical"].strip(),
                "elevation_class": row["elevation_class"].strip(),
                "soil_moisture_min": float(row["soil_moisture_min"]),
                "soil_moisture_max": float(row["soil_moisture_max"]),
                "vic3_terrain": row["vic3_terrain"].strip(),
                "line_no": line_no,
            }
            if parsed["vic3_terrain"] not in VALID_TERRAINS:
                raise ValueError(f"invalid terrain in terrain_lookup line {line_no}: {parsed['vic3_terrain']}")
            rows.append(parsed)
    if not any(row["priority"] == 0 for row in rows):
        raise ValueError("terrain_lookup.csv requires priority 0 catch-all")
    return sorted(rows, key=lambda row: row["priority"], reverse=True)


def match_terrain(rows: list[dict[str, Any]], koppen_class: str, biome_physical: str, elevation_class: str, soil_moisture: float) -> tuple[str, int]:
    matches_by_priority: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row["koppen_class"] not in ("*", koppen_class):
            continue
        if row["biome_physical"] not in ("*", biome_physical):
            continue
        if row["elevation_class"] not in ("*", elevation_class):
            continue
        if not (row["soil_moisture_min"] <= soil_moisture <= row["soil_moisture_max"]):
            continue
        matches_by_priority.setdefault(row["priority"], []).append(row)
    if not matches_by_priority:
        raise ValueError(f"no terrain lookup match: {koppen_class}/{biome_physical}/{elevation_class}/{soil_moisture}")
    priority = max(matches_by_priority)
    matches = matches_by_priority[priority]
    if len(matches) > 1:
        raise ValueError(f"multiple terrain lookup matches at priority {priority}: {[m['line_no'] for m in matches]}")
    return matches[0]["vic3_terrain"], priority


def scale_hydro(final_rainfall: float, corrected_et: float, river_bonus: float, lake_fraction: float, is_wetland: bool, params: dict[str, Any]) -> tuple[float, float, float, float]:
    sm = params["soil_moisture"]
    et_scaled = climate.clamp(corrected_et * sm["et_world_scale"], sm["et_clamp_min"], sm["et_clamp_max"])
    rb_scaled = climate.clamp(river_bonus * sm["river_bonus_world_scale"], sm["river_bonus_clamp_min"], sm["river_bonus_clamp_max"])
    if et_scaled <= params["epsilon"] and final_rainfall <= params["epsilon"]:
        aridity = 0.0
    elif et_scaled <= params["epsilon"]:
        aridity = params["aridity_cap"]
    else:
        aridity = min(params["aridity_cap"], final_rainfall / et_scaled)
    wetland_bonus = sm["wetland_seed_soil_bonus"] if is_wetland else 0.0
    raw = final_rainfall + rb_scaled + lake_fraction * sm["lake_moisture_bonus"] + wetland_bonus - et_scaled
    soil = climate.clamp((raw - sm["soil_moisture_min"]) / (sm["soil_moisture_max"] - sm["soil_moisture_min"]), 0.0, sm["soil_moisture_cap"])
    return et_scaled, rb_scaled, aridity, soil


def elevation_class(elevation_m: float, params: dict[str, Any]) -> str:
    e = params["elevation"]
    if elevation_m >= e["mountain_threshold_m"]:
        return "mountain"
    if elevation_m >= e["highland_threshold_m"]:
        return "highland"
    if elevation_m >= e["upland_threshold_m"]:
        return "upland"
    return "lowland"


def classify_koppen(values: dict[str, float], aridity: float, params: dict[str, Any]) -> str:
    k = params["koppen"]
    final = values["final_rainfall"]
    summer_share = values["final_summer_rainfall"] / max(final, params["epsilon"])
    winter_share = values["final_winter_rainfall"] / max(final, params["epsilon"])
    if summer_share >= k["summer_dominant_threshold"]:
        b_threshold = k["b_base_threshold"] * k["b_summer_rain_multiplier"]
    elif winter_share >= k["winter_dominant_threshold"]:
        b_threshold = k["b_base_threshold"] * k["b_winter_rain_multiplier"]
    else:
        b_threshold = k["b_base_threshold"] * k["b_even_rain_multiplier"]
    if aridity < b_threshold * k["desert_fraction"]:
        return "BWh" if values["mean_temperature"] >= k["b_hot_threshold_c"] else "BWk"
    if aridity < b_threshold:
        return "BSh" if values["mean_temperature"] >= k["b_hot_threshold_c"] else "BSk"
    if values["summer_temperature"] < k["ice_cap_summer_threshold"]:
        return "EF"
    if values["summer_temperature"] < k["tundra_summer_threshold"]:
        return "ET"
    if values["winter_temperature"] >= k["tropical_coldest_threshold"]:
        if values["dry_season_strength"] <= k["tropical_af_dry_strength_max"]:
            return "Af"
        if values["final_dry_season_rainfall"] >= k["tropical_monsoon_dry_rain_min"]:
            return "Am"
        return "Aw"
    if values["summer_temperature"] >= k["temperate_warmest_min"]:
        group = "C" if values["winter_temperature"] > k["continental_winter_threshold"] else "D"
        if values["dry_season_strength"] <= k["no_dry_season_strength_max"]:
            precip = "f"
        elif values["final_summer_rainfall"] < values["final_winter_rainfall"]:
            precip = "s"
        else:
            precip = "w"
        if values["summer_temperature"] >= k["hot_summer_threshold"]:
            temp = "a"
        elif values["summer_temperature"] >= k["warm_summer_threshold"]:
            temp = "b"
        else:
            temp = "c"
        return group + precip + temp
    raise ValueError("Koppen-lite class unresolved")


def apply_highland(koppen_base: str, elev_class: str, summer_temperature: float, params: dict[str, Any]) -> str:
    if elev_class == "mountain":
        return "H"
    if elev_class == "highland" and summer_temperature < params["elevation"]["highland_cool_summer_threshold"]:
        return "H"
    return koppen_base


def biome_from_koppen(koppen: str) -> str:
    exact = {
        "Af": "rainforest",
        "Am": "monsoon_forest",
        "Aw": "savanna",
        "BWh": "hot_desert",
        "BWk": "cold_desert",
        "BSh": "hot_steppe",
        "BSk": "cold_steppe",
        "ET": "tundra",
        "EF": "ice",
        "H": "highland",
    }
    if koppen in exact:
        return exact[koppen]
    if koppen.startswith("Cs"):
        return "mediterranean"
    if koppen.startswith("C"):
        return "temperate_forest"
    if koppen in {"Dfa", "Dfb", "Dwa", "Dwb"}:
        return "boreal_forest"
    if koppen.startswith("D"):
        return "taiga"
    raise ValueError(f"no biome mapping for Koppen class: {koppen}")


def physical_biome(base: str, hydrology_values: dict[str, Any], soil_moisture: float, params: dict[str, Any]) -> tuple[str, str | None]:
    sm = params["soil_moisture"]
    if hydrology_values["is_lake"]:
        return "lake", "lake"
    if hydrology_values["is_salt_flat"]:
        return "salt_flat", "salt_flat"
    if hydrology_values["is_wetland"]:
        return "wetland", "wetland"
    if hydrology_values["is_river"] and soil_moisture >= sm["river_corridor_soil_min"]:
        if base in {"hot_desert", "cold_desert", "hot_steppe", "cold_steppe"}:
            return "river_corridor", "river_corridor"
        return base, "river_corridor"
    if base in {"savanna", "hot_steppe", "cold_steppe"} and soil_moisture >= sm["grassland_soil_min"]:
        return "savanna" if base == "savanna" else base, None
    return base, None


def apply_fantasy_label(biome: str, fantasy_zone: Any) -> str:
    if fantasy_zone is None or fantasy_zone == "":
        return biome
    return f"{biome}__{fantasy_zone}"


def build_output(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    rainfall = climate.load_json(args.rainfall_normalized, "rainfall_normalized.json")
    seasonal = climate.load_json(args.seasonal, "seasonal_climate.json")
    hydrology = climate.load_json(args.hydrology, "hydrology.json")
    bootstrap = climate.load_json(args.bootstrap, "bootstrap_fields.json")
    graph = climate.load_json(args.province_graph, "province_graph.json")
    params = load_params(args.params)
    land = validate_inputs(rainfall, seasonal, hydrology, bootstrap, graph)
    raw_constraints = load_optional_mapping(args.province_constraints, "province_constraints.yaml", "province_constraints")
    raw_overrides = load_optional_mapping(args.province_overrides, "province_overrides.yaml", "province_overrides")
    constraints, warnings = normalize_constraints(raw_constraints, land)
    overrides, override_warnings = normalize_overrides(raw_overrides, land)
    warnings.extend(override_warnings)
    lookup = load_terrain_lookup(args.terrain_lookup)
    provinces: dict[str, dict[str, Any]] = {}
    fallback_priority_counts = Counter()
    for color in land:
        province_warnings: list[str] = []
        rn = rainfall["provinces"][color]
        sc = seasonal["provinces"][color]
        if abs(float(rn["corrected_ET"]) - float(hydrology["corrected_ET"][color])) > params["epsilon"]:
            raise ValueError(f"corrected_ET mismatch: {color}")
        if abs(float(rn["river_bonus"]) - float(hydrology["river_bonus"][color])) > params["epsilon"]:
            raise ValueError(f"river_bonus mismatch: {color}")
        if abs(float(rn["lake_fraction"]) - float(hydrology["lake_fraction"][color])) > params["epsilon"]:
            raise ValueError(f"lake_fraction mismatch: {color}")
        values = {
            "final_rainfall": float(rn["final_rainfall"]),
            "final_summer_rainfall": float(rn["final_summer_rainfall"]),
            "final_winter_rainfall": float(rn["final_winter_rainfall"]),
            "final_dry_season_rainfall": float(rn["final_dry_season_rainfall"]),
            "dry_season_strength": float(rn["dry_season_strength"]),
            "mean_temperature": float(sc["mean_temperature"]),
            "summer_temperature": float(sc["summer_temperature"]),
            "winter_temperature": float(sc["winter_temperature"]),
        }
        hv = {
            "is_lake": bool(hydrology["is_lake"][color]),
            "is_salt_flat": bool(hydrology["is_salt_flat"][color]),
            "is_wetland": bool(hydrology["is_wetland"][color]),
            "is_river": bool(hydrology["is_river"][color]),
        }
        et_scaled, rb_scaled, aridity, soil = scale_hydro(
            values["final_rainfall"],
            float(hydrology["corrected_ET"][color]),
            float(hydrology["river_bonus"][color]),
            float(hydrology["lake_fraction"][color]),
            hv["is_wetland"],
            params,
        )
        elev_class = elevation_class(float(bootstrap["provinces"][color]["synthetic_elevation_m"]), params)
        koppen_base = classify_koppen(values, aridity, params)
        koppen = apply_highland(koppen_base, elev_class, values["summer_temperature"], params)
        if koppen != koppen_base:
            province_warnings.append("highland Koppen override applied")
        biome_base = biome_from_koppen(koppen)
        biome_physical, overlay = physical_biome(biome_base, hv, soil, params)
        terrain_base, priority = match_terrain(lookup, koppen, biome_physical, elev_class, soil)
        if priority in (0, 1):
            province_warnings.append(f"terrain lookup fallback priority {priority} used")
            fallback_priority_counts[priority] += 1
        fantasy_zone = constraints[color]["fantasy_zone"]
        biome = apply_fantasy_label(biome_physical, fantasy_zone)
        terrain = terrain_base
        override = overrides[color]
        locked_applied = False
        if override["force_biome"] is not None or override["force_terrain"] is not None:
            if not override["locked"]:
                province_warnings.append("force_biome/force_terrain ignored because locked=false")
            else:
                locked_applied = True
                if override["force_biome"] is not None:
                    biome = str(override["force_biome"])
                if override["force_terrain"] is not None:
                    terrain = str(override["force_terrain"])
                    if terrain not in VALID_TERRAINS:
                        raise ValueError(f"invalid force_terrain: {color}={terrain}")
        if override["locked"] and override["force_biome"] is None and override["force_terrain"] is None:
            province_warnings.append("locked=true without force_biome/force_terrain")
        if override["exclude_from_sim"] and not locked_applied:
            province_warnings.append("exclude_from_sim province uses automatic biome/terrain result")
        provinces[color] = {
            "corrected_ET_scaled": round(et_scaled, 8),
            "river_bonus_scaled": round(rb_scaled, 8),
            "aridity_index": round(aridity, 8),
            "soil_moisture": round(soil, 8),
            "koppen_base_class": koppen_base,
            "koppen_class": koppen,
            "biome_climate_base": biome_base,
            "biome_physical": biome_physical,
            "biome": biome,
            "vic3_terrain_base": terrain_base,
            "vic3_terrain": terrain,
            "elevation_class": elev_class,
            "hydrology_overlay": overlay,
            "fantasy_zone": fantasy_zone,
            "is_locked_override_applied": locked_applied,
            "warnings": province_warnings,
        }
    output = {
        "schema_version": SCHEMA_VERSION,
        "source": {
            "rainfall_normalized": climate.display_path(args.rainfall_normalized, args.project_root),
            "seasonal_climate": climate.display_path(args.seasonal, args.project_root),
            "hydrology": climate.display_path(args.hydrology, args.project_root),
            "bootstrap_fields": climate.display_path(args.bootstrap, args.project_root),
            "province_graph": climate.display_path(args.province_graph, args.project_root),
            "province_constraints": climate.display_path(args.province_constraints, args.project_root),
            "province_overrides": climate.display_path(args.province_overrides, args.project_root),
            "terrain_lookup": climate.display_path(args.terrain_lookup, args.project_root),
            "climate_rules": climate.display_path(args.params, args.project_root),
        },
        "hash": {
            "rainfall_normalized_hash": file_hash(args.rainfall_normalized),
            "seasonal_hash": file_hash(args.seasonal),
            "hydrology_hash": file_hash(args.hydrology),
            "bootstrap_hash": file_hash(args.bootstrap),
            "graph_hash": graph["metadata"]["hash"]["topology_hash"],
            "constraints_hash": file_hash(args.province_constraints),
            "overrides_hash": file_hash(args.province_overrides),
            "terrain_lookup_hash": file_hash(args.terrain_lookup),
            "params_hash": canonical_hash(params),
        },
        "metadata": {
            "land_province_count": len(land),
            "terrain_lookup_fallback_priority_0": fallback_priority_counts[0],
            "terrain_lookup_fallback_priority_1": fallback_priority_counts[1],
        },
        "warnings": warnings,
        "provinces": provinces,
    }
    validate_output(output, land)
    return output, {"land": land}


def validate_output(output: dict[str, Any], land: list[str]) -> None:
    if set(output["provinces"]) != set(land):
        raise ValueError("province set mismatch")
    for color, values in output["provinces"].items():
        for key in ("corrected_ET_scaled", "river_bonus_scaled", "aridity_index", "soil_moisture"):
            climate.finite_number(values[key], f"{color}.{key}")
        if values["vic3_terrain"] not in VALID_TERRAINS:
            raise ValueError(f"invalid terrain output: {color}={values['vic3_terrain']}")
        for key in ("koppen_base_class", "koppen_class", "biome_climate_base", "biome_physical", "biome", "vic3_terrain_base", "vic3_terrain", "elevation_class"):
            if values[key] in (None, ""):
                raise ValueError(f"{color}.{key} missing")


def write_debug_outputs(args: argparse.Namespace, output: dict[str, Any]) -> list[Path]:
    args.debug_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for field, filename in [
        ("koppen_class", "koppen_class_counts.csv"),
        ("biome", "biome_counts.csv"),
        ("vic3_terrain", "terrain_counts.csv"),
        ("hydrology_overlay", "hydrology_overlay_counts.csv"),
    ]:
        counts = Counter(str(values[field]) for values in output["provinces"].values())
        path = args.debug_dir / filename
        climate.write_csv(path, ["value", "count"], [{"value": key, "count": value} for key, value in sorted(counts.items())])
        paths.append(path)
    warning_path = args.debug_dir / "koppen_biome_terrain_warnings.csv"
    rows = []
    for color, values in output["provinces"].items():
        for warning in values["warnings"]:
            rows.append({"province": color, "warning": warning})
    climate.write_csv(warning_path, ["province", "warning"], rows)
    paths.append(warning_path)
    paths.extend(write_debug_images(args.debug_image_dir, args.project_root, args.province_graph, output))
    return paths


def color_to_int(color: str) -> int:
    return int(color[1:], 16)


def stable_color(label: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(label.encode("utf-8")).digest()
    return (70 + digest[0] % 170, 70 + digest[1] % 170, 70 + digest[2] % 170)


def palette_for(field: str, label: str | None) -> tuple[int, int, int]:
    categorical: dict[str, dict[str, tuple[int, int, int]]] = {
        "biome": {
            "rainforest": (20, 115, 45),
            "monsoon_forest": (35, 150, 65),
            "savanna": (198, 178, 82),
            "hot_desert": (226, 190, 94),
            "cold_desert": (202, 180, 130),
            "hot_steppe": (188, 165, 82),
            "cold_steppe": (154, 150, 92),
            "temperate_forest": (56, 135, 72),
            "boreal_forest": (44, 100, 85),
            "taiga": (62, 112, 102),
            "mediterranean": (180, 150, 85),
            "tundra": (145, 170, 158),
            "ice": (230, 240, 250),
            "highland": (120, 105, 90),
            "river_corridor": (60, 135, 180),
            "wetland": (70, 125, 95),
            "salt_flat": (230, 220, 190),
            "lake": (65, 125, 210),
        },
        "terrain": {
            "plains": (188, 180, 105),
            "forest": (50, 130, 65),
            "hills": (130, 118, 85),
            "mountain": (100, 92, 82),
            "jungle": (20, 105, 45),
            "wetland": (65, 130, 100),
            "desert": (222, 190, 105),
            "tundra": (155, 178, 170),
            "savanna": (202, 178, 76),
            "snow": (232, 240, 248),
        },
        "koppen": {
            "Af": (20, 120, 45),
            "Am": (35, 150, 70),
            "Aw": (205, 178, 75),
            "BWh": (232, 185, 85),
            "BWk": (205, 185, 130),
            "BSh": (190, 165, 75),
            "BSk": (160, 150, 90),
            "Cfa": (75, 150, 75),
            "Cfb": (65, 130, 90),
            "Cwa": (92, 160, 82),
            "Cwb": (88, 145, 105),
            "Dfa": (80, 125, 120),
            "Dfb": (70, 115, 125),
            "Dfc": (70, 105, 135),
            "Dwa": (90, 130, 130),
            "Dwb": (80, 120, 140),
            "Dwc": (80, 110, 150),
            "ET": (155, 175, 170),
            "EF": (232, 242, 250),
            "H": (120, 105, 90),
        },
    }
    if label is None:
        return (185, 210, 235)
    table = categorical.get(field, {})
    return table.get(label, stable_color(label))


def scalar_color(value: float, low: float, high: float, palette: str) -> tuple[int, int, int]:
    t = climate.clamp((value - low) / max(high - low, 1e-12), 0.0, 1.0)
    if palette == "aridity":
        return (int(60 + 190 * t), int(115 + 90 * (1.0 - abs(t - 0.5) * 2.0)), int(210 * (1.0 - t)))
    if palette == "moisture":
        return (int(225 * (1.0 - t) + 30 * t), int(205 * (1.0 - t) + 125 * t), int(95 * (1.0 - t) + 210 * t))
    if palette == "et":
        return (int(245 * (1.0 - t) + 120 * t), int(245 * (1.0 - t) + 70 * t), int(220 * (1.0 - t) + 160 * t))
    return (int(245 * (1.0 - t)), int(245 * (1.0 - t)), int(80 + 175 * t))


def write_debug_images(debug_dir: Path, project_root: Path, graph_path: Path, output: dict[str, Any]) -> list[Path]:
    import numpy as np
    from PIL import Image

    graph = climate.load_json(graph_path, "province_graph.json")
    source = Path(graph["metadata"]["source_files"]["provinces_png"])
    if not source.is_absolute():
        source = project_root / source
    image = Image.open(source).convert("RGB")
    preview_size = (min(2048, image.width), max(1, round(image.height * min(2048, image.width) / image.width)))
    image = image.resize(preview_size, Image.Resampling.NEAREST)
    rgb = np.asarray(image, dtype=np.uint32)
    ids = (rgb[:, :, 0] << 16) | (rgb[:, :, 1] << 8) | rgb[:, :, 2]
    debug_dir.mkdir(parents=True, exist_ok=True)
    provinces = output["provinces"]
    paths: list[Path] = []

    categorical_fields = [
        ("koppen_class_map.png", "koppen_class", "koppen"),
        ("biome_map.png", "biome_physical", "biome"),
        ("terrain_map.png", "vic3_terrain", "terrain"),
    ]
    for filename, source_field, palette_name in categorical_fields:
        lookup = np.zeros((1 << 24, 3), dtype=np.uint8)
        lookup[:, :] = (185, 210, 235)
        for color, values in provinces.items():
            lookup[color_to_int(color)] = palette_for(palette_name, str(values[source_field]))
        rendered = lookup[ids]
        path = debug_dir / filename
        Image.fromarray(rendered, mode="RGB").save(path)
        paths.append(path)

    scalar_fields = [
        ("aridity_index_map.png", "aridity_index", "aridity", 0.0, 3.0),
        ("soil_moisture_map.png", "soil_moisture", "moisture", 0.0, 1.5),
        ("corrected_ET_scaled_map.png", "corrected_ET_scaled", "et", 0.0, 1.5),
        ("river_bonus_scaled_map.png", "river_bonus_scaled", "blue", 0.0, None),
    ]
    for filename, source_field, palette_name, low, fixed_high in scalar_fields:
        values_by_color = {color: float(values[source_field]) for color, values in provinces.items()}
        finite_values = list(values_by_color.values())
        high = float(fixed_high) if fixed_high is not None else max(float(np.percentile(np.asarray(finite_values), 99.0)), 1e-12)
        lookup = np.zeros((1 << 24, 3), dtype=np.uint8)
        lookup[:, :] = (185, 210, 235)
        for color, value in values_by_color.items():
            lookup[color_to_int(color)] = scalar_color(value, low, high, palette_name)
        rendered = lookup[ids]
        path = debug_dir / filename
        Image.fromarray(rendered, mode="RGB").save(path)
        paths.append(path)
    return paths


def parse_args() -> argparse.Namespace:
    defaults = default_paths()
    parser = argparse.ArgumentParser(description="Build koppen_biome_terrain.v0.7 cache")
    parser.add_argument("--project-root", type=Path, default=defaults["project_root"])
    parser.add_argument("--rainfall-normalized", type=Path, default=defaults["rainfall_normalized"])
    parser.add_argument("--seasonal", type=Path, default=defaults["seasonal"])
    parser.add_argument("--hydrology", type=Path, default=defaults["hydrology"])
    parser.add_argument("--bootstrap", type=Path, default=defaults["bootstrap"])
    parser.add_argument("--province-graph", type=Path, default=defaults["province_graph"])
    parser.add_argument("--province-constraints", type=Path, default=defaults["province_constraints"])
    parser.add_argument("--province-overrides", type=Path, default=defaults["province_overrides"])
    parser.add_argument("--params", type=Path, default=defaults["params"])
    parser.add_argument("--terrain-lookup", type=Path, default=defaults["terrain_lookup"])
    parser.add_argument("--output", type=Path, default=defaults["output"])
    parser.add_argument("--debug-dir", type=Path, default=defaults["debug_dir"])
    parser.add_argument("--debug-image-dir", type=Path, default=defaults["debug_image_dir"])
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--fail-on-warning", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output, _ = build_output(args)
        if output["warnings"] and args.fail_on_warning:
            for warning in output["warnings"]:
                print(f"WARNING: {warning}")
            return 2
        atomic_write_json(args.output, output, pretty=args.pretty)
        artifacts = write_debug_outputs(args, output) if args.debug else []
        terrain_counts = Counter(values["vic3_terrain"] for values in output["provinces"].values())
        print(f"wrote: {args.output}")
        print(f"schema_version: {output['schema_version']}")
        print(f"land_province_count: {len(output['provinces'])}")
        print(f"terrain_classes: {len(terrain_counts)}")
        print(f"fallback_priority_0: {output['metadata']['terrain_lookup_fallback_priority_0']}")
        print(f"fallback_priority_1: {output['metadata']['terrain_lookup_fallback_priority_1']}")
        print(f"warnings: {len(output['warnings'])}")
        print(f"debug_artifacts: {len(artifacts)}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
