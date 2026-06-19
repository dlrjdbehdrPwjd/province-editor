from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import write_pipeline_run_manifest as manifest


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class PipelineRunManifestTests(unittest.TestCase):
    def make_project(self) -> Path:
        root = Path(tempfile.mkdtemp())
        write_json(
            root / "config" / "pipeline_input_manifest.json",
            {
                "schema_version": "pipeline_input_manifest.v0.1",
                "map_data": {
                    "provinces_png": "../map_data/provinces.png",
                    "default_map": "../map_data/default.map",
                    "world_yaml": "config/world.yaml",
                    "heightmap_png": None,
                },
                "inputs": {
                    "province_constraints": "revisions/{revision_dir_name}/province_constraints.yaml",
                    "province_overrides": "revisions/{revision_dir_name}/province_overrides.yaml",
                    "climate_rules": "config/climate_rules.yaml",
                    "terrain_lookup": "config/terrain_lookup.csv",
                },
            },
        )
        for rel in [
            "config/world.yaml",
            "config/climate_rules.yaml",
            "config/terrain_lookup.csv",
            "revisions/dev_empty/province_constraints.yaml",
            "revisions/dev_empty/province_overrides.yaml",
        ]:
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("x: 1\n", encoding="utf-8")
        return root

    def write_stage_outputs(self, root: Path) -> None:
        for stage in manifest.STAGES:
            write_json(
                root / stage["output"],
                {
                    "schema_version": stage["name"] + ".test",
                    "metadata": {"land_province_count": 2},
                    "warnings": [],
                    "provinces": {"x111111": {}, "x222222": {}},
                },
            )
        write_json(
            root / "cache" / "debug" / "province_graph_build_report.json",
            {"schema_version": "report.test", "validation_status": "success", "warnings": ["one"]},
        )

    def args(self, root: Path, require_existing_outputs: bool = False) -> argparse.Namespace:
        return argparse.Namespace(
            project_root=root,
            input_manifest=root / "config" / "pipeline_input_manifest.json",
            revision_dir_name="dev_empty",
            output=root / "cache" / "pipeline_run_manifest.json",
            history_dir=root / "cache" / "pipeline_runs",
            run_id="test_run",
            pretty=True,
            require_existing_outputs=require_existing_outputs,
        )

    def test_manifest_records_stage_outputs_and_history(self) -> None:
        root = self.make_project()
        self.write_stage_outputs(root)
        built = manifest.build_manifest(self.args(root, require_existing_outputs=True))
        self.assertEqual(built["schema_version"], manifest.SCHEMA_VERSION)
        self.assertEqual(built["run_id"], "test_run")
        self.assertEqual(len(built["stages"]), 6)
        self.assertEqual(built["totals"]["missing_stage_outputs"], 0)
        self.assertGreaterEqual(built["totals"]["warnings_count"], 1)
        self.assertTrue(built["stages"][0]["output"]["sha256"].startswith("sha256:"))
        self.assertIn("inputs.province_constraints", built["input_files"])

    def test_require_existing_outputs_rejects_missing_stage_output(self) -> None:
        root = self.make_project()
        with self.assertRaises(FileNotFoundError):
            built = manifest.build_manifest(self.args(root, require_existing_outputs=True))
            missing = [
                stage["output"]["path"]
                for stage in built["stages"]
                if not stage["output"]["exists"]
            ]
            if missing:
                raise FileNotFoundError("missing required stage outputs: " + ", ".join(missing))


if __name__ == "__main__":
    unittest.main()
