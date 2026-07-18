"""Creation of explicit, local manifest templates for new filing packages."""

from __future__ import annotations

from pathlib import Path

import yaml

from ceqa_preflight.models import FilingType, PackageManifest


def manifest_template(filing_type: FilingType) -> PackageManifest:
    """Return a schema-valid template with plainly fictional placeholder values."""

    category = "Notice of Determination" if filing_type is FilingType.NOD else "Notice of Exemption"
    prefix = filing_type.value
    return PackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "filing_type": filing_type.value,
            "project": {"title": "Replace with project title"},
            "contacts": [],
            "documents": [
                {
                    "path": f"{prefix}_REPLACE_WITH_FORM.pdf",
                    "category": category,
                    "primary": True,
                }
            ],
        }
    )


def write_manifest_template(directory: Path, filing_type: FilingType) -> Path:
    """Write a non-overwriting YAML template to a user-selected local directory."""

    if directory.exists() and not directory.is_dir():
        raise ValueError("template destination must be a directory")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "package.yaml"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {destination}")
    content = yaml.safe_dump(
        manifest_template(filing_type).model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
    )
    destination.write_text(content, encoding="utf-8")
    return destination
