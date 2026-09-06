"""Export machine-readable public schemas from the typed contracts."""

from __future__ import annotations

import json
from pathlib import Path

from ceqa_preflight.diffing import DiffReport
from ceqa_preflight.models import InspectionReport, PackageManifest


def export_schemas(destination: Path) -> None:
    """Write stable JSON schema artifacts to an explicitly supplied directory."""

    destination.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "manifest.schema.json": PackageManifest.model_json_schema(),
        "report.schema.json": InspectionReport.model_json_schema(),
        "diff.schema.json": DiffReport.model_json_schema(),
    }
    for filename, schema in artifacts.items():
        path = destination / filename
        # newline="\n" rather than the default: the default translates to os.linesep, so a
        # Windows run of `make schemas` would write CRLF and the published contract would
        # differ from a POSIX one byte for byte. .gitattributes pins the checkout to LF;
        # this pins the producer to the same thing, on every platform.
        path.write_text(
            json.dumps(schema, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )


if __name__ == "__main__":
    export_schemas(Path("schemas"))
