"""Export machine-readable public schemas from the typed contracts."""

from __future__ import annotations

import json
from pathlib import Path

from ceqa_preflight.models import InspectionReport, PackageManifest


def export_schemas(destination: Path) -> None:
    """Write stable JSON schema artifacts to an explicitly supplied directory."""

    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "manifest.schema.json": PackageManifest.model_json_schema(),
        "report.schema.json": InspectionReport.model_json_schema(),
    }
    for filename, schema in artifacts.items():
        path = destination / filename
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    export_schemas(Path("schemas"))
