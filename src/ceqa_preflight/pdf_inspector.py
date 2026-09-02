"""Bounded, non-mutating technical inspection of local PDF documents.

This module deliberately reports only observable document signals.  In
particular, text extraction and a structure-tree flag are not accessibility
certification, and no result is legal advice.
"""

from __future__ import annotations

import contextlib
import logging
import multiprocessing
import warnings
from collections.abc import Iterator, Mapping
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
    # False when the form dictionary could not be parsed. Without this flag, an
    # unreadable AcroForm and a document with no form fields are both a count of zero,
    # and "not measured" reads as "measured clean".
    form_fields_readable: bool = True
    # False when part of the object graph the active-content signals walk (/Root, /Names,
    # /OpenAction, a page's /AA) could not be resolved. Same reason as the flag above: an
    # unresolvable reference and a document with no JavaScript, no launch action and no
    # embedded files both arrive here as False/False/0, so without this flag "not measured"
    # reads as "measured clean" for the one rule whose job is catching active content.
    active_content_readable: bool = True
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


class _Resolution:
    """Whether every indirect reference a walk needed actually resolved.

    An empty mapping is what a genuinely absent key yields *and* what an unresolvable
    reference used to yield. Collapsing the two makes "this graph could not be read"
    indistinguishable from "there is nothing here", which is how a corrupt PDF earned a
    clean PDF-006 pass. Walks record their failures here instead.
    """

    __slots__ = ("complete",)

    def __init__(self) -> None:
        self.complete = True

    def failed(self) -> None:
        self.complete = False


def _mapping(value: Any, resolution: _Resolution | None = None) -> Mapping[str, Any]:
    """Resolve a pypdf object to a mapping, conservatively.

    A direct object (or ``None`` for an absent key) has no ``get_object``; that
    ``AttributeError`` is the ordinary path and resolves nothing. The other three are how
    pypdf reports a dangling, circular, or corrupt-xref indirect reference, and they mean
    the graph was not read rather than found empty.
    """

    try:
        resolved = value.get_object()
    except AttributeError:
        resolved = value
    except (KeyError, TypeError, ValueError):
        if resolution is not None:
            resolution.failed()
        return {}
    return resolved if isinstance(resolved, Mapping) else {}


def _name(value: Any) -> str:
    return str(value)


def _contains_action(value: Any, target: str, *, resolution: _Resolution, depth: int = 0) -> bool:
    """Bounded search for a PDF action subtype without following arbitrary graphs.

    Reaching the depth bound is recorded as a failure to resolve: the search stopped
    before it had seen the whole graph, so a ``False`` from that branch is "not found
    within the bound", not "not present".
    """

    if depth > 12:
        resolution.failed()
        return False
    mapping = _mapping(value, resolution)
    if mapping:
        if _name(mapping.get("/S", "")) == target:
            return True
        return any(
            _contains_action(child, target, resolution=resolution, depth=depth + 1)
            for child in mapping.values()
        )
    if isinstance(value, (list, tuple)):
        return any(
            _contains_action(child, target, resolution=resolution, depth=depth + 1)
            for child in value
        )
    return False


def _name_tree_item_count(value: Any, *, resolution: _Resolution, depth: int = 0) -> int:
    """Count name-tree values while bounding traversal of hostile object graphs.

    As above, an exhausted depth bound means the count is a floor rather than a total.
    """

    if depth > 12:
        resolution.failed()
        return 0
    mapping = _mapping(value, resolution)
    if not mapping:
        return 0
    names = mapping.get("/Names", [])
    direct_count = len(names) // 2 if isinstance(names, (list, tuple)) else 0
    children = mapping.get("/Kids", [])
    child_count = (
        sum(
            _name_tree_item_count(child, resolution=resolution, depth=depth + 1)
            for child in children
        )
        if isinstance(children, (list, tuple))
        else 0
    )
    return direct_count + child_count


def _warning_label(prefix: str) -> str:
    """Avoid including document contents or paths in a report warning."""

    return f"{prefix}; manual review recommended"


class _LogEmittedHandler(logging.Handler):
    """Note only whether a record was emitted; never retain document-derived message text."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.emitted = False

    def emit(self, record: logging.LogRecord) -> None:
        self.emitted = True


@contextlib.contextmanager
def _capture_pypdf_log_warnings() -> Iterator[_LogEmittedHandler]:
    """Capture pypdf's own robustness-fix warnings, which bypass ``warnings.catch_warnings``.

    Under ``strict=False`` (used here so a non-compliant PDF still gets inspected), pypdf
    reports the recoverable problems it worked around — a rebuilt xref table, a missing EOF
    marker, and the like — through Python's ``logging`` module via its own ``logger_warning``
    helper, not ``warnings.warn``. Without this, a document pypdf had to repair is measured as
    cleanly as one with no problems at all: a real "this needed a robustness fix" signal
    silently becomes "measured clean" instead of lowering confidence like every other parser
    warning already does. The handler is also kept from propagating to the real root logger, so
    a caller's terminal is not spammed with library-internal parser chatter for every recovered
    document.
    """

    handler = _LogEmittedHandler()
    logger = logging.getLogger("pypdf")
    previous_propagate = logger.propagate
    logger.propagate = False
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.propagate = previous_propagate


def _active_content_signals(
    reader: PdfReader, root: Mapping[str, Any], resolution: _Resolution
) -> tuple[bool, bool]:
    names = _mapping(root.get("/Names"), resolution)
    javascript_present = names.get("/JavaScript") is not None or _contains_action(
        root.get("/OpenAction"), "/JavaScript", resolution=resolution
    )
    launch_action_present = _contains_action(
        root.get("/OpenAction"), "/Launch", resolution=resolution
    )
    for page in reader.pages:
        page_mapping = _mapping(page, resolution)
        javascript_present = javascript_present or _contains_action(
            page_mapping.get("/AA"), "/JavaScript", resolution=resolution
        )
        launch_action_present = launch_action_present or _contains_action(
            page_mapping.get("/AA"), "/Launch", resolution=resolution
        )
    return javascript_present, launch_action_present


def _field_names(reader: PdfReader, parser_warnings: list[str]) -> tuple[list[str], bool]:
    """Return the form-field names and whether the form dictionary could be read at all."""

    try:
        fields = reader.get_fields() or {}
        return sorted(str(name) for name in fields), True
    except Exception:
        parser_warnings.append(_warning_label("PDF form fields could not be read"))
        return [], False


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
    with _capture_pypdf_log_warnings() as log_warnings:
        try:
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                reader = PdfReader(path, strict=False)
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
                parser_warnings=[
                    *parser_warnings,
                    _warning_label("Encrypted PDFs are not inspected"),
                ],
                extraction_confidence=Confidence.LOW,
            )

        try:
            page_count = len(reader.pages)
        except Exception:
            return PdfInspection(
                readable=False,
                parser_warnings=[
                    *parser_warnings,
                    _warning_label("PDF page count could not be read"),
                ],
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

        # A robustness fix pypdf applied while reading (a rebuilt xref table, a missing EOF
        # marker) is exactly the kind of parser warning that lowers confidence below, whether
        # it surfaced through ``warnings.warn`` or, as most of pypdf's own recovery messages
        # do, through ``logging``.
        if captured or log_warnings.emitted:
            parser_warnings.append(_warning_label("PDF parser reported warnings"))

    resolution = _Resolution()
    root = _mapping(reader.trailer.get("/Root"), resolution)
    # Snapshot before the deeper walks: /StructTreeRoot is read off /Root alone, so it stays
    # a measurement whenever /Root itself resolved, even if some page's /AA did not.
    root_readable = resolution.complete
    names = _mapping(root.get("/Names"), resolution)
    javascript_present, launch_action_present = _active_content_signals(reader, root, resolution)
    embedded_file_count = _name_tree_item_count(names.get("/EmbeddedFiles"), resolution=resolution)
    field_names, form_fields_readable = _field_names(reader, parser_warnings)
    sampled_pages = select_sample_pages(page_count)
    extracted_characters = _extract_sample_characters(path, sampled_pages, parser_warnings)
    if not resolution.complete:
        parser_warnings.append(
            _warning_label("Parts of the PDF object graph could not be resolved")
        )

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
        form_fields_readable=form_fields_readable,
        active_content_readable=resolution.complete,
        # Not False when /Root never resolved: an absent structure tree and an unreadable
        # one are different facts, and only None keeps PDF-008 from asserting the document
        # is untagged on the strength of a graph it could not read.
        structure_tree_present="/StructTreeRoot" in root if root_readable else None,
        embedded_file_count=embedded_file_count,
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
