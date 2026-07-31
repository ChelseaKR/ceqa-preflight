"""Creation of explicit, local manifest templates for new filing packages."""

from __future__ import annotations

from pathlib import Path

import yaml

from ceqa_preflight.models import DocumentEntry, FilingType, PackageManifest


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


def manifest_from_package(directory: Path, filing_type: FilingType) -> PackageManifest:
    """Prepopulate manifest documents from the PDFs actually present in a package.

    Categories and the primary flag stay explicit user declarations; only paths
    are filled in, so no filing-form classification is ever guessed.
    """

    pdf_paths = sorted(
        path.relative_to(directory).as_posix()
        for path in directory.rglob("*")
        if path.is_file() and not path.is_symlink() and path.suffix.casefold() == ".pdf"
    )
    if not pdf_paths:
        raise ValueError("no PDF files were found to prepopulate the manifest")
    template = manifest_template(filing_type)
    return template.model_copy(
        update={
            "documents": [
                DocumentEntry(path=pdf_path, category=None, primary=False) for pdf_path in pdf_paths
            ]
        }
    )


def write_manifest_template(
    directory: Path, filing_type: FilingType, *, from_package: bool = False
) -> Path:
    """Write a non-overwriting YAML template to a user-selected local directory."""

    if directory.exists() and not directory.is_dir():
        raise ValueError("template destination must be a directory")
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "package.yaml"
    if destination.exists():
        raise FileExistsError(f"refusing to overwrite existing manifest: {destination}")
    manifest = (
        manifest_from_package(directory, filing_type)
        if from_package
        else manifest_template(filing_type)
    )
    content = yaml.safe_dump(
        manifest.model_dump(mode="json"),
        sort_keys=False,
        allow_unicode=True,
    )
    destination.write_text(content, encoding="utf-8")
    return destination
