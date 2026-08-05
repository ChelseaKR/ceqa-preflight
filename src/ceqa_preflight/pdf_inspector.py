"""Bounded, non-mutating technical inspection of local PDF documents.

This module deliberately reports only observable document signals.  In
particular, text extraction and a structure-tree flag are not accessibility
certification, and no result is legal advice.
"""

from __future__ import annotations

import multiprocessing
import warnings
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTTextContainer
from pydantic import Field
from pypdf import PdfReader

from ceqa_preflight.limits import DEFAULT_PACKAGE_LIMITS, PackageLimits
from ceqa_preflight.models import Confidence, StrictModel


class PdfInspection(StrictModel):
    """Technical PDF signals suitable for deterministic package checks."""

    readable: bool
    encrypted: bool = False
    page_count: int | None = None
    sampled_pages: list[int] = Field(default_factory=list)
    extracted_characters: dict[int, int] = Field(default_factory=dict)
    text_coverage: float | None = None
    active_form_field_count: int = 0
    active_form_field_names: list[str] = Field(default_factory=list)
    structure_tree_present: bool | None = None
    embedded_file_count: int = 0
    javascript_present: bool = False
    launch_action_present: bool = False
    parser_warnings: list[str] = Field(default_factory=list)
    extraction_confidence: Confidence = Confidence.LOW
    timed_out: bool = False


def select_sample_pages(page_count: int) -> list[int]:
    """Select one-based pages, covering small PDFs fully and large PDFs evenly."""

    if page_count <= 0:
        return []
    if page_count <= 20:
        return list(range(1, page_count + 1))

    anchors = {1, 2, page_count - 1, page_count}
    interior_count = 6
    for position in range(1, interior_count + 1):
        anchors.add(1 + round(position * (page_count - 1) / (interior_count + 1)))
    return sorted(anchors)


def _mapping(value: Any) -> Mapping[str, Any]:
    """Resolve a pypdf object to a mapping, conservatively."""

    try:
        resolved = value.get_object()
    except (AttributeError, KeyError, TypeError, ValueError):
        resolved = value
    return resolved if isinstance(resolved, Mapping) else {}


def _name(value: Any) -> str:
    return str(value)


def _contains_action(value: Any, target: str, *, depth: int = 0) -> bool:
    """Bounded search for a PDF action subtype without following arbitrary graphs."""

    if depth > 12:
        return False
    mapping = _mapping(value)
    if mapping:
        if _name(mapping.get("/S", "")) == target:
            return True
        return any(_contains_action(child, target, depth=depth + 1) for child in mapping.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_action(child, target, depth=depth + 1) for child in value)
    return False


def _name_tree_item_count(value: Any, *, depth: int = 0) -> int:
    """Count name-tree values while bounding traversal of hostile object graphs."""

    if depth > 12:
        return 0
    mapping = _mapping(value)
    if not mapping:
        return 0
    names = mapping.get("/Names", [])
    direct_count = len(names) // 2 if isinstance(names, (list, tuple)) else 0
    children = mapping.get("/Kids", [])
    child_count = (
        sum(_name_tree_item_count(child, depth=depth + 1) for child in children)
        if isinstance(children, (list, tuple))
        else 0
    )
    return direct_count + child_count


def _warning_label(prefix: str) -> str:
    """Avoid including document contents or paths in a report warning."""

    return f"{prefix}; manual review recommended"


def _active_content_signals(reader: PdfReader, root: Mapping[str, Any]) -> tuple[bool, bool]:
    names = _mapping(root.get("/Names"))
    javascript_present = names.get("/JavaScript") is not None or _contains_action(
        root.get("/OpenAction"), "/JavaScript"
    )
    launch_action_present = _contains_action(root.get("/OpenAction"), "/Launch")
    for page in reader.pages:
        page_mapping = _mapping(page)
        javascript_present = javascript_present or _contains_action(
            page_mapping.get("/AA"), "/JavaScript"
        )
        launch_action_present = launch_action_present or _contains_action(
            page_mapping.get("/AA"), "/Launch"
        )
    return javascript_present, launch_action_present


def _field_names(reader: PdfReader, parser_warnings: list[str]) -> list[str]:
    try:
        fields = reader.get_fields() or {}
        return sorted(str(name) for name in fields)
    except Exception:
        parser_warnings.append(_warning_label("PDF form fields could not be read"))
        return []


def _extract_sample_characters(
    path: Path,
    sampled_pages: list[int],
    parser_warnings: list[str],
) -> dict[int, int]:
    extracted_characters: dict[int, int] = {}
    try:
        # One parse pass for all sampled pages; pdfminer yields them in document
        # order, which matches the ascending sample order.
        layouts = extract_pages(str(path), page_numbers=[page - 1 for page in sampled_pages])
        for page_number, layout in zip(sampled_pages, layouts, strict=False):
            extracted_characters[page_number] = sum(
                len("".join(element.get_text().split()))
                for element in layout
                if isinstance(element, LTTextContainer)
            )
    except Exception:
        parser_warnings.append(
            _warning_label("Text could not be extracted from one or more sampled pages")
        )
    return extracted_characters


def _inspect_pdf_in_worker(path: Path, limits: PackageLimits) -> PdfInspection:
    """Inspect one resolved PDF.  This is invoked in an isolated worker process."""

    parser_warnings: list[str] = []
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            reader = PdfReader(path, strict=False)
        if captured:
            parser_warnings.append(_warning_label("PDF parser reported warnings"))
    except Exception:  # pypdf has several parser exception classes across releases.
        return PdfInspection(
            readable=False,
            parser_warnings=[_warning_label("PDF could not be parsed")],
            extraction_confidence=Confidence.LOW,
        )

    if reader.is_encrypted:
        return PdfInspection(
            readable=False,
            encrypted=True,
            parser_warnings=[*parser_warnings, _warning_label("Encrypted PDFs are not inspected")],
            extraction_confidence=Confidence.LOW,
        )

    try:
        page_count = len(reader.pages)
    except Exception:
        return PdfInspection(
            readable=False,
            parser_warnings=[*parser_warnings, _warning_label("PDF page count could not be read")],
            extraction_confidence=Confidence.LOW,
        )
    if page_count > limits.max_pdf_pages:
        return PdfInspection(
            readable=False,
            page_count=page_count,
            parser_warnings=[
                *parser_warnings,
                _warning_label(f"PDF exceeds the {limits.max_pdf_pages} page inspection limit"),
            ],
            extraction_confidence=Confidence.LOW,
        )

    root = _mapping(reader.trailer.get("/Root"))
    names = _mapping(root.get("/Names"))
    javascript_present, launch_action_present = _active_content_signals(reader, root)
    field_names = _field_names(reader, parser_warnings)
    sampled_pages = select_sample_pages(page_count)
    extracted_characters = _extract_sample_characters(path, sampled_pages, parser_warnings)

    searchable_pages = sum(value >= 25 for value in extracted_characters.values())
    text_coverage = searchable_pages / len(sampled_pages) if sampled_pages else None
    confidence = Confidence.MEDIUM if parser_warnings else Confidence.HIGH
    if len(extracted_characters) != len(sampled_pages):
        confidence = Confidence.LOW
    return PdfInspection(
        readable=True,
        page_count=page_count,
        sampled_pages=sampled_pages,
        extracted_characters=extracted_characters,
        text_coverage=text_coverage,
        active_form_field_count=len(field_names),
        active_form_field_names=field_names,
        structure_tree_present="/StructTreeRoot" in root,
        embedded_file_count=_name_tree_item_count(names.get("/EmbeddedFiles")),
        javascript_present=javascript_present,
        launch_action_present=launch_action_present,
        parser_warnings=parser_warnings,
        extraction_confidence=confidence,
    )


def _worker_main(connection: Any, path_string: str, limits: PackageLimits) -> None:
    """Return a JSON-safe inspection through a one-way multiprocessing pipe."""

    try:
        result = _inspect_pdf_in_worker(Path(path_string), limits)
        connection.send({"inspection": result.model_dump(mode="json")})
    except BaseException:
        connection.send({"error": "PDF inspection worker failed"})
    finally:
        connection.close()


def _timeout_result() -> PdfInspection:
    return PdfInspection(
        readable=False,
        parser_warnings=[_warning_label("PDF inspection timed out")],
        extraction_confidence=Confidence.LOW,
        timed_out=True,
    )


def inspect_pdf(path: Path, limits: PackageLimits = DEFAULT_PACKAGE_LIMITS) -> PdfInspection:
    """Inspect a local PDF in a spawned process with a hard wall-clock timeout."""

    if limits.per_file_timeout_seconds <= 0:
        raise ValueError("per_file_timeout_seconds must be greater than zero")
    resolved_path = path.resolve(strict=False)
    context = multiprocessing.get_context("spawn")
    parent_connection, child_connection = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(child_connection, str(resolved_path), limits),
        daemon=True,
    )
    process.start()
    child_connection.close()
    try:
        process.join(limits.per_file_timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join()
            return _timeout_result()
        if not parent_connection.poll():
            return PdfInspection(
                readable=False,
                parser_warnings=[_warning_label("PDF inspection worker returned no result")],
                extraction_confidence=Confidence.LOW,
            )
        payload = parent_connection.recv()
    finally:
        parent_connection.close()
        if process.is_alive():
            process.terminate()
            process.join()
    if "inspection" in payload:
        return PdfInspection.model_validate(payload["inspection"])
    return PdfInspection(
        readable=False,
        parser_warnings=[_warning_label("PDF inspection worker failed")],
        extraction_confidence=Confidence.LOW,
    )
