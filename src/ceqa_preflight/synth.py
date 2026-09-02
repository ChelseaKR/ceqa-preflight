"""Deterministic generation of plainly fictional synthetic filing packages.

Synthetic packages support demos, regression tests, reviewer calibration, and
pilot dry runs without touching any real filing material. Every generated
document is labeled as fictional test data.
"""

from __future__ import annotations

from enum import StrEnum
from io import BytesIO
from pathlib import Path

import yaml
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from ceqa_preflight.models import FilingType, PackageManifest


class SyntheticDefect(StrEnum):
    """Seedable, objective package defects with a matching built-in rule."""

    ENCRYPTED = "encrypted"
    UNREADABLE = "unreadable"
    SCANNED = "scanned"
    FILLABLE_FORM = "fillable-form"
    DUPLICATE = "duplicate"
    NON_PDF = "non-pdf"
    BAD_SIGNATURE = "bad-signature"
    WEAK_FILENAME = "weak-filename"
    MISSING_MANIFEST_REFERENCE = "missing-manifest-reference"


_PROJECT_TITLE = "Fictional Example Project (synthetic test data)"
_BANNER = (
    "Synthetic CEQA Preflight test data for the Fictional Example Project. "
    "This document is not a real filing and cites no real project."
)


def _pdf_bytes(
    page_texts: list[str | None],
    *,
    tagged: bool = True,
    form_field: bool = False,
    encrypted: bool = False,
) -> bytes:
    """Build a small synthetic PDF; pages with text stay text-searchable."""

    writer = PdfWriter()
    pages = [writer.add_blank_page(width=612, height=792) for _ in page_texts]
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    for page, text in zip(pages, page_texts, strict=True):
        if text is None:
            continue
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    if form_field:
        field = DictionaryObject(
            {
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject("synthetic_field"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/Rect"): ArrayObject(
                    [NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]
                ),
                NameObject("/P"): pages[0].indirect_reference,
            }
        )
        field_ref = writer._add_object(field)
        pages[0][NameObject("/Annots")] = ArrayObject([field_ref])
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/Fields"): ArrayObject([field_ref])}
        )
    if tagged:
        writer._root_object[NameObject("/StructTreeRoot")] = writer._add_object(DictionaryObject())
    if encrypted:
        writer.encrypt("synthetic-not-a-secret")
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def _searchable_pdf(label: str, *, tagged: bool = True, form_field: bool = False) -> bytes:
    # Distinct per-document text keeps synthetic files from sharing a hash.
    text = f"{_BANNER} Document: {label}."
    return _pdf_bytes([text, text], tagged=tagged, form_field=form_field)


def _defect_documents(
    requested: set[SyntheticDefect], supporting: bytes
) -> list[tuple[str, bytes, str | None]]:
    """Return the extra file entries seeded by the requested objective defects."""

    files: list[tuple[str, bytes, str | None]] = []
    if SyntheticDefect.ENCRYPTED in requested:
        files.append(
            (
                "Fictional_Example_Project_encrypted.pdf",
                _pdf_bytes([_BANNER], encrypted=True),
                "Supporting Findings",
            )
        )
    if SyntheticDefect.UNREADABLE in requested:
        files.append(
            (
                "Fictional_Example_Project_truncated.pdf",
                b"%PDF-1.7\n% synthetic truncated document, intentionally unreadable\n",
                "Supporting Findings",
            )
        )
    if SyntheticDefect.SCANNED in requested:
        files.append(
            (
                "Fictional_Example_Project_scanned_notice.pdf",
                _pdf_bytes([None, None]),
                "Supporting Findings",
            )
        )
    if SyntheticDefect.FILLABLE_FORM in requested:
        files.append(
            (
                "Fictional_Example_Project_fillable_form.pdf",
                _searchable_pdf("fillable form", form_field=True),
                "Supporting Findings",
            )
        )
    if SyntheticDefect.DUPLICATE in requested:
        files.append(
            ("Fictional_Example_Project_duplicate_copy.pdf", supporting, "Supporting Findings")
        )
    if SyntheticDefect.NON_PDF in requested:
        files.append(
            (
                "Fictional_Example_Project_source_form.docx",
                b"Synthetic non-PDF placeholder that should be converted to a PDF.\n",
                None,
            )
        )
    if SyntheticDefect.BAD_SIGNATURE in requested:
        files.append(
            (
                "Fictional_Example_Project_notes.pdf",
                b"Synthetic plain text with a PDF extension but no PDF signature.\n",
                "Supporting Findings",
            )
        )
    if SyntheticDefect.WEAK_FILENAME in requested:
        files.append(("doc1.pdf", _searchable_pdf("weakly named document"), "Supporting Findings"))
    return files


def _write_manifest(
    directory: Path,
    filing_type: FilingType,
    files: list[tuple[str, bytes, str | None]],
    primary_category: str,
    requested: set[SyntheticDefect],
) -> Path:
    """Write the package manifest describing the synthetic documents."""

    documents = [
        {"path": name, "category": file_category, "primary": file_category == primary_category}
        for name, _, file_category in files
        if file_category is not None
    ]
    if SyntheticDefect.MISSING_MANIFEST_REFERENCE in requested:
        documents.append(
            {
                "path": "Fictional_Example_Project_missing_attachment.pdf",
                "category": "Supporting Findings",
                "primary": False,
            }
        )
    manifest = PackageManifest.model_validate(
        {
            "schema_version": "1.0",
            "filing_type": filing_type.value,
            "project": {"title": _PROJECT_TITLE},
            "contacts": [],
            "documents": documents,
        }
    )
    manifest_path = directory / "package.yaml"
    # newline="\n" rather than the default: `synth` output is byte-reproducible by design,
    # and it is hashed into the report's input fingerprint, so it must not vary with
    # os.linesep.
    manifest_path.write_text(
        yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
        newline="\n",
    )
    return manifest_path


def write_synthetic_package(
    directory: Path,
    filing_type: FilingType,
    defects: list[SyntheticDefect],
) -> list[Path]:
    """Write a fictional package plus manifest and return the created paths."""

    if directory.exists() and not directory.is_dir():
        raise ValueError("synthetic package destination must be a directory")
    if directory.is_dir() and any(directory.iterdir()):
        raise FileExistsError(f"refusing to write into a non-empty directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)

    category = "Notice of Determination" if filing_type is FilingType.NOD else "Notice of Exemption"
    prefix = filing_type.value
    supporting = _searchable_pdf("supporting findings")
    files: list[tuple[str, bytes, str | None]] = [
        (f"{prefix}_Fictional_Example_Project_form.pdf", _searchable_pdf("filing form"), category),
        (
            "Fictional_Example_Project_supporting_findings.pdf",
            supporting,
            "Supporting Findings",
        ),
    ]
    requested = set(defects)
    files.extend(_defect_documents(requested, supporting))

    created: list[Path] = []
    for name, content, _ in files:
        destination = directory / name
        destination.write_bytes(content)
        created.append(destination)

    created.append(_write_manifest(directory, filing_type, files, category, requested))
    return created
