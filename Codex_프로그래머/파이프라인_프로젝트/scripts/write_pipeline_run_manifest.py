from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "pipeline_run_manifest.v0.1"

STAGES: list[dict[str, str]] = [
    {
        "name": "build_province_graph",
        "output": "cache/province_graph.json",
        "report": "cache/debug/province_graph_build_report.json",
    },
    {
        "name": "build_bootstrap_fields",
        "output": "cache/bootstrap_fields.json",
        "report": "cache/debug/bootstrap_fields_build_report.json",
    },
    {
        "name": "seasonal_climate",
        "output": "cache/seasonal_climate.json",
        "report": "cache/debug/seasonal_climate_build_report.json",
    },
    {
        "name": "hydrology",
        "output": "cache/hydrology.json",
        "report": "",
    },
    {
        "name": "rainfall_normalization",
        "output": "cache/rainfall_normalized.json",
        "report": "cache/debug/rainfall_normalization_report.json",
    },
    {
        "name": "koppen_biome_terrain",
        "output": "cache/koppen_biome_terrain.json",
        "report": "cache/debug/koppen_biome_terrain_warnings.csv",
    },
]

REPRESENTATIVE_OUTPUTS = [
    "outputs/draft_rivers.png",
    "outputs/debug/annual_rainfall_raw_map.png",
    "outputs/debug/annual_rainfall_log_map.png",
    "outputs/debug/zonal_mean_rainfall.png",
    "outputs/debug/koppen_class_map.png",
    "outputs/debug/biome_map.png",
    "outputs/debug/terrain_map.png",
    "outputs/debug/aridity_index_map.png",
    "outputs/debug/soil_moisture_map.png",
    "outputs/debug/corrected_ET_scaled_map.png",
    "outputs/debug/river_bonus_scaled_map.png",
]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def atomic_write_json(path: Path, value: dict[str, Any], pretty: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2 if pretty else None, sort_keys=True)
        handle.write("\n")
    temp_path.replace(path)


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"JSON top level must be an object: {path}")
    return value


def display_path(path: Path, root: Path) -> str:
    try:
        return Path(os.path.relpath(path.resolve(), root.resolve())).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def resolve_manifest_path(project_root: Path, raw_path: str | None, revision_dir_name: str) -> Path | None:
    if raw_path is None:
        return None
    resolved = raw_path.replace("{revision_dir_name}", revision_dir_name)
    return (project_root / resolved).resolve()


def file_record(path: Path | None, project_root: Path) -> dict[str, Any]:
    if path is None:
        return {"path": None, "exists": False, "sha256": None, "bytes": None, "schema_version": None}
    exists = path.is_file()
    record: dict[str, Any] = {
        "path": display_path(path, project_root),
        "exists": exists,
        "sha256": sha256_file(path) if exists else None,
        "bytes": path.stat().st_size if exists else None,
        "schema_version": None,
    }
    if exists and path.suffix.lower() == ".json":
        try:
            data = load_json(path)
            record["schema_version"] = data.get("schema_version")
        except Exception as error:  # Keep manifest writing useful for diagnostics.
            record["json_error"] = str(error)
    return record


def run_git(project_root: Path, args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=project_root,
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except Exception:
        return None
    return result.stdout.strip()


def git_metadata(project_root: Path) -> dict[str, Any]:
    commit = run_git(project_root, ["rev-parse", "HEAD"])
    short_commit = run_git(project_root, ["rev-parse", "--short", "HEAD"])
    branch = run_git(project_root, ["branch", "--show-current"])
    status = run_git(project_root, ["status", "--short", "--", "."])
    status_lines = [line for line in (status or "").splitlines() if line.strip()]
    return {
        "commit": commit,
        "short_commit": short_commit,
        "branch": branch,
        "project_tree_dirty": bool(status_lines),
        "project_status_short": status_lines,
    }


def count_csv_data_rows(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    return max(0, len(rows) - 1)


def compact_summary(data: dict[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    if "metadata" in data and isinstance(data["metadata"], dict):
        metadata = data["metadata"]
        for key in (
            "validation_status",
            "land_province_count",
            "terrain_lookup_fallback_priority_0",
            "terrain_lookup_fallback_priority_1",
            "absolute_clamped_count",
            "final_min_count",
            "final_max_count",
        ):
            if key in metadata:
                summary[key] = metadata[key]
    if "spinup" in data and isinstance(data["spinup"], dict):
        spinup = data["spinup"]
        summary["spinup"] = {
            key: spinup.get(key)
            for key in ("converged", "years", "max_years", "transport_converged")
            if key in spinup
        }
    if "provinces" in data and isinstance(data["provinces"], dict):
        summary["province_count"] = len(data["provinces"])
    if "warnings" in data and isinstance(data["warnings"], list):
        summary["warnings_count"] = len(data["warnings"])
    return summary


def stage_record(stage: dict[str, str], project_root: Path) -> dict[str, Any]:
    output_path = (project_root / stage["output"]).resolve()
    report_path = (project_root / stage["report"]).resolve() if stage["report"] else None
    output = file_record(output_path, project_root)
    report = file_record(report_path, project_root)
    warnings_count = 0
    validation_status = None
    summary: dict[str, Any] = {}

    if output_path.is_file() and output_path.suffix.lower() == ".json":
        try:
            data = load_json(output_path)
            summary = compact_summary(data)
            if isinstance(data.get("warnings"), list):
                warnings_count += len(data["warnings"])
        except Exception as error:
            summary["output_read_error"] = str(error)

    if report_path and report_path.is_file():
        if report_path.suffix.lower() == ".json":
            try:
                report_data = load_json(report_path)
                validation_status = report_data.get("validation_status")
                if isinstance(report_data.get("warnings"), list):
                    warnings_count += len(report_data["warnings"])
                if "metadata" in report_data and isinstance(report_data["metadata"], dict):
                    summary.setdefault("report_metadata", report_data["metadata"])
            except Exception as error:
                summary["report_read_error"] = str(error)
        elif report_path.suffix.lower() == ".csv":
            warnings_count += count_csv_data_rows(report_path)

    return {
        "name": stage["name"],
        "output": output,
        "report": report,
        "validation_status": validation_status,
        "warnings_count": warnings_count,
        "summary": summary,
    }


def collect_input_files(manifest: dict[str, Any], project_root: Path, revision_dir_name: str) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for section_name in ("map_data", "inputs"):
        section = manifest.get(section_name, {})
        if not isinstance(section, dict):
            continue
        for key, raw_path in section.items():
            if key.startswith("_") or key.endswith("_dir"):
                continue
            if not isinstance(raw_path, str) and raw_path is not None:
                continue
            path = resolve_manifest_path(project_root, raw_path, revision_dir_name)
            records[f"{section_name}.{key}"] = file_record(path, project_root)
    return records


def build_manifest(args: argparse.Namespace) -> dict[str, Any]:
    project_root = args.project_root.resolve()
    input_manifest = load_json(args.input_manifest)
    generated_at = utc_now()
    run_id = args.run_id or generated_at.strftime("%Y%m%dT%H%M%SZ")
    stages = [stage_record(stage, project_root) for stage in STAGES]
    representative_outputs = {
        path: file_record((project_root / path).resolve(), project_root)
        for path in REPRESENTATIVE_OUTPUTS
    }
    missing_required = [
        stage["output"]["path"]
        for stage in stages
        if not bool(stage["output"]["exists"])
    ]
    if args.require_existing_outputs and missing_required:
        raise FileNotFoundError("missing required stage outputs: " + ", ".join(missing_required))

    manifest: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "generated_at": generated_at.isoformat(),
        "project_root": display_path(project_root, project_root),
        "revision_dir_name": args.revision_dir_name,
        "git": git_metadata(project_root),
        "input_manifest": file_record(args.input_manifest.resolve(), project_root),
        "input_files": collect_input_files(input_manifest, project_root, args.revision_dir_name),
        "stages": stages,
        "representative_outputs": representative_outputs,
        "totals": {
            "stage_count": len(stages),
            "missing_stage_outputs": len(missing_required),
            "warnings_count": sum(int(stage["warnings_count"]) for stage in stages),
        },
    }
    return manifest


def default_paths(project_root: Path) -> dict[str, Path]:
    return {
        "input_manifest": project_root / "config" / "pipeline_input_manifest.json",
        "latest_manifest": project_root / "cache" / "pipeline_run_manifest.json",
        "history_dir": project_root / "cache" / "pipeline_runs",
    }


def parse_args() -> argparse.Namespace:
    inferred_project_root = Path(__file__).resolve().parents[1]
    defaults = default_paths(inferred_project_root)
    parser = argparse.ArgumentParser(description="Write pipeline_run_manifest.v0.1 from existing pipeline artifacts")
    parser.add_argument("--project-root", type=Path, default=inferred_project_root)
    parser.add_argument("--input-manifest", type=Path, default=defaults["input_manifest"])
    parser.add_argument("--revision-dir-name", default="dev_empty")
    parser.add_argument("--output", type=Path, default=defaults["latest_manifest"])
    parser.add_argument("--history-dir", type=Path, default=defaults["history_dir"])
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--require-existing-outputs", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        manifest = build_manifest(args)
        latest_path = args.output.resolve()
        history_path = (args.history_dir / f"{manifest['run_id']}.json").resolve()
        atomic_write_json(latest_path, manifest, pretty=args.pretty)
        atomic_write_json(history_path, manifest, pretty=args.pretty)
        print(f"wrote: {latest_path}")
        print(f"history: {history_path}")
        print(f"run_id: {manifest['run_id']}")
        print(f"warnings: {manifest['totals']['warnings_count']}")
        print(f"missing_stage_outputs: {manifest['totals']['missing_stage_outputs']}")
        return 0
    except Exception as error:
        print(f"FATAL: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
