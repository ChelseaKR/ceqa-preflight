"""Tests for machine-readable public schemas."""

from __future__ import annotations

import json
from pathlib import Path

from ceqa_preflight.schema_export import export_schemas


def test_export_schemas_writes_manifest_and_report_contracts(tmp_path: Path) -> None:
    export_schemas(tmp_path)

    manifest_schema = json.loads((tmp_path / "manifest.schema.json").read_text(encoding="utf-8"))
    report_schema = json.loads((tmp_path / "report.schema.json").read_text(encoding="utf-8"))

    assert manifest_schema["title"] == "PackageManifest"
    assert report_schema["title"] == "InspectionReport"
