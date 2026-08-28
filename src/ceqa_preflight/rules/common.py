"""Conservative common technical checks over package inventory facts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from pathlib import PurePosixPath

from pydantic import Field, ValidationError

from ceqa_preflight.models import Confidence, Evidence, StrictModel
from ceqa_preflight.pdf_inspector import PdfInspection
from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_engine import RuleContext, RuleOutcome, RuleOutcomeStatus


class DocumentFact(StrictModel):
    """The bounded inventory and inspection facts consumed by common checks."""

    path: str = Field(min_length=1)
    is_pdf: bool
    signature_is_pdf: bool | None = None
    sha256: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)
    category: str | None = None
    primary: bool = False
    inspection: PdfInspection | None = None


def _documents(context: RuleContext) -> tuple[list[DocumentFact], bool]:
    raw_documents = context.facts.get("documents")
    if not isinstance(raw_documents, list):
        return [], True
    try:
        return [DocumentFact.model_validate(item) for item in raw_documents], False
    except (TypeError, ValidationError):
        return [], True


_NO_ACTION_NEEDED = "No action is needed for this check."


def _indeterminate(message: str) -> list[RuleOutcome]:
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.INDETERMINATE,
            message=message,
            remediation=(
                "Review this item manually after a complete package inventory is available."
            ),
            confidence=Confidence.LOW,
        )
    ]


def _examined(document: DocumentFact) -> PdfInspection | None:
    """The completed inspection a check may draw a conclusion from, or ``None``.

    A PDF that timed out, failed to parse, or is encrypted still yields a ``PdfInspection``,
    but every absence signal on it (form-field count, embedded-file count, the JavaScript
    and launch-action flags, the structure-tree flag) sits at its default because nothing
    was read, not because nothing is there. Treating those defaults as observations turns
    "not measured" into "measured clean", so such a document is never examined here.

    This gate covers a whole inspection that did not happen. A partial one, where the file
    parsed but some signal within it did not, is not visible here: the inspection carries a
    per-signal flag for each such case (``form_fields_readable``, ``active_content_readable``,
    and ``structure_tree_present is None``), and the check that consumes that signal is
    responsible for excluding the document. Every caller below does.
    """

    inspection = document.inspection
    if inspection is None or inspection.timed_out or not inspection.readable:
        return None
    return inspection


def _conclude(
    findings: list[RuleOutcome],
    *,
    examined: int,
    excluded: int,
    pass_message: str,
    nothing_examined_message: str,
) -> list[RuleOutcome]:
    """Close a per-document check so a pass can never come from an empty denominator.

    ``findings`` holds the problems the check actually observed. A pass is emitted only
    when at least one document was examined and nothing was wrong with it, and the pass
    message states how many documents that was, so an "all clear" can never be read off a
    denominator of zero. Documents the check could not examine are surfaced for manual
    review instead of being silently absorbed into the pass.
    """

    outcomes: list[RuleOutcome] = list(findings)
    if examined and not findings:
        outcomes.append(
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message=pass_message,
                remediation=_NO_ACTION_NEEDED,
            )
        )
    if excluded:
        outcomes.extend(
            _indeterminate(
                f"{excluded} PDF document(s) could not be inspected and were excluded from "
                "this check, which therefore makes no statement about them."
            )
        )
    elif not examined and not findings:
        # Nothing was examined and the check has not already said why.
        outcomes.extend(_indeterminate(nothing_examined_message))
    return outcomes


def check_pdf_present(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("The package inventory is unavailable or incomplete.")
    pdf_count = sum(document.is_pdf for document in documents)
    if pdf_count == 0:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message="The package contains no PDF documents.",
                remediation="Include the required filing form and supporting documents as PDFs.",
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=f"The package contains {pdf_count} PDF document(s).",
            remediation="No action is needed for this check.",
        )
    ]


def check_pdf_signature(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF signature facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    excluded = 0
    for document in documents:
        if not document.is_pdf:
            continue
        if document.signature_is_pdf is None:
            excluded += 1
            continue
        examined += 1
        if not document.signature_is_pdf:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.FAILURE,
                    message="This file has a PDF extension but not a PDF signature.",
                    document=document.path,
                    remediation=(
                        "Replace the file with a valid PDF exported from the source document."
                    ),
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=excluded,
        pass_message=f"All {examined} inventoried PDF file(s) have a PDF signature.",
        nothing_examined_message="No PDF file was inventoried, so no signature was checked.",
    )


def check_pdf_readable(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF inspection facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = document.inspection
        if inspection is None or inspection.timed_out:
            outcomes.extend(
                _indeterminate("A PDF could not be fully inspected within the safe limit.")
            )
            continue
        # An inspection that ran to completion and reported the document unreadable is a
        # measurement, not a gap, so it stays a failure rather than a manual-review item.
        examined += 1
        if not inspection.readable or inspection.encrypted:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.FAILURE,
                    message="This PDF is unreadable or encrypted.",
                    document=document.path,
                    remediation="Provide an unencrypted, readable PDF.",
                    confidence=inspection.extraction_confidence,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=0,  # documents that could not be inspected are already reported above
        pass_message=f"All {examined} inspected PDF(s) are readable and unencrypted.",
        nothing_examined_message="No PDF was inspected, so readability was not checked.",
    )


def check_text_coverage(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    threshold = float(rule.parameters.get("minimum_coverage", 0.8))
    if incomplete or not 0 <= threshold <= 1:
        return _indeterminate("Searchable-text coverage facts or threshold are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    excluded = 0
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = _examined(document)
        if inspection is None or inspection.text_coverage is None:
            excluded += 1
            continue
        examined += 1
        if inspection.text_coverage < threshold:
            if inspection.text_coverage == 0:
                message = (
                    "No searchable text was found on any sampled page; this PDF may be a "
                    "scanned image."
                )
                remediation = (
                    "Run optical character recognition (OCR) on the document and verify "
                    "keyword searches succeed before submission."
                )
            else:
                message = (
                    f"Sampled searchable-text coverage is {inspection.text_coverage:.0%}, "
                    f"below the {threshold:.0%} threshold."
                )
                remediation = (
                    "Confirm that the PDF is searchable or provide an accessible source PDF."
                )
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message=message,
                    document=document.path,
                    evidence=Evidence(
                        details={
                            "sampled_pages": len(inspection.sampled_pages),
                            "coverage": inspection.text_coverage,
                            "threshold": threshold,
                        }
                    ),
                    remediation=remediation,
                    confidence=inspection.extraction_confidence,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=excluded,
        pass_message=(
            f"All {examined} inspected PDF(s) meet the sampled searchable-text threshold."
        ),
        nothing_examined_message="No PDF was inspected, so searchable text was not sampled.",
    )


def check_active_content(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF active-content facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    excluded = 0
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = _examined(document)
        # An object graph that did not resolve reports no JavaScript, no launch action and
        # no embedded files; those three defaults are the absence of a reading, not the
        # absence of active content. This is the one rule in the catalog whose purpose is
        # catching a crafted or corrupt document, and an unresolvable /Root, /Names or
        # /OpenAction is precisely what such a document looks like (issue #54).
        if inspection is None or not inspection.active_content_readable:
            excluded += 1
            continue
        examined += 1
        suspicious = inspection.javascript_present or inspection.launch_action_present
        suspicious = suspicious or inspection.embedded_file_count > 0
        if suspicious:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message="This PDF contains active actions or embedded files.",
                    document=document.path,
                    evidence=Evidence(
                        details={
                            "embedded_file_count": inspection.embedded_file_count,
                            "javascript_present": inspection.javascript_present,
                            "launch_action_present": inspection.launch_action_present,
                        }
                    ),
                    remediation=(
                        "Remove unneeded scripts, actions, and embedded files before submission."
                    ),
                    confidence=inspection.extraction_confidence,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=excluded,
        pass_message=(
            f"No active PDF actions or embedded files were detected in the {examined} "
            "inspected PDF(s)."
        ),
        nothing_examined_message="No PDF was inspected, so active content was not examined.",
    )


def check_flattened_forms(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag fillable form fields, which official guidance asks filers to flatten."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF form-field facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    excluded = 0
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = _examined(document)
        # A form dictionary that could not be parsed reports zero fields; that zero is the
        # absence of a reading, not the absence of fields.
        if inspection is None or not inspection.form_fields_readable:
            excluded += 1
            continue
        examined += 1
        if inspection.active_form_field_count:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message=(
                        f"This PDF contains {inspection.active_form_field_count} fillable "
                        "form field(s); submissions are expected to be flattened and static."
                    ),
                    document=document.path,
                    evidence=Evidence(
                        details={"form_field_count": inspection.active_form_field_count}
                    ),
                    remediation=(
                        "Flatten the document to a static, fully text-searchable PDF "
                        "before submission."
                    ),
                    confidence=inspection.extraction_confidence,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=excluded,
        pass_message=(f"No fillable form fields were detected in the {examined} inspected PDF(s)."),
        nothing_examined_message="No PDF was inspected, so form fields were not examined.",
    )


def check_structure_tags(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Report a missing structure tree without claiming accessibility certification."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF structure-tree facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    examined = 0
    excluded = 0
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = _examined(document)
        if inspection is None or inspection.structure_tree_present is None:
            excluded += 1
            continue
        examined += 1
        if not inspection.structure_tree_present:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message=(
                        "No screen-reader structure tags were detected. A present structure "
                        "tree is not accessibility certification, but its absence suggests "
                        "the document is untagged."
                    ),
                    document=document.path,
                    remediation=(
                        "Tag headings, images, and tables for screen-reader compatibility "
                        "and confirm accessibility with an assistive-technology review."
                    ),
                    confidence=Confidence.MEDIUM,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=excluded,
        pass_message=(
            f"All {examined} inspected PDF(s) contain a structure tree for screen readers."
        ),
        nothing_examined_message="No PDF was inspected, so structure tags were not examined.",
    )


def check_file_size(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    """Warn on unusually large files; no official CEQA Submit size limit is documented."""

    documents, incomplete = _documents(context)
    try:
        maximum_megabytes = float(rule.parameters.get("maximum_megabytes", 50))
    except (TypeError, ValueError):
        maximum_megabytes = -1
    if incomplete or maximum_megabytes <= 0:
        return _indeterminate("File-size facts or the advisory threshold are unavailable.")
    threshold_bytes = maximum_megabytes * 1024 * 1024
    outcomes: list[RuleOutcome] = []
    examined = 0
    for document in documents:
        if document.size_bytes is None:
            outcomes.extend(_indeterminate("A file size could not be determined."))
            continue
        examined += 1
        if document.size_bytes > threshold_bytes:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message=(
                        f"This file is {document.size_bytes / (1024 * 1024):.0f} MB, above "
                        f"the {maximum_megabytes:.0f} MB advisory threshold. Large uploads "
                        "are slow and may exceed portal limits."
                    ),
                    document=document.path,
                    evidence=Evidence(
                        details={
                            "size_bytes": document.size_bytes,
                            "advisory_threshold_megabytes": maximum_megabytes,
                        }
                    ),
                    remediation=(
                        "Consider optimizing the PDF and verify current CEQA Submit upload "
                        "guidance; no official size limit is documented."
                    ),
                    confidence=Confidence.MEDIUM,
                )
            )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=0,  # a file whose size could not be read is already reported above
        pass_message=(
            f"All {examined} inventoried file(s) are within the advisory size threshold."
        ),
        nothing_examined_message="No file size was read, so no size was checked.",
    )


_CONVERTIBLE_SUFFIXES = {
    ".doc",
    ".docx",
    ".gif",
    ".htm",
    ".html",
    ".jpeg",
    ".jpg",
    ".odt",
    ".png",
    ".ppt",
    ".pptx",
    ".rtf",
    ".tif",
    ".tiff",
    ".txt",
    ".xls",
    ".xlsx",
}


def check_non_pdf_documents(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag common document formats that should be converted to static PDFs."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Package inventory facts are unavailable.")
    convertible = [
        document.path
        for document in documents
        if PurePosixPath(document.path).suffix.casefold() in _CONVERTIBLE_SUFFIXES
    ]
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.WARNING,
                message=(
                    "The package contains document or image files that are not PDFs; CEQA "
                    "Submit attachments are expected to be static, text-searchable PDFs."
                ),
                evidence=Evidence(details={"non_pdf_documents": convertible}),
                remediation=(
                    "Convert these files to static, fully text-searchable PDFs, or remove "
                    "them if they are not intended attachments."
                ),
                confidence=Confidence.MEDIUM,
            )
        ]
        if convertible
        else []
    )
    return _conclude(
        outcomes,
        examined=len(documents),
        excluded=0,
        pass_message=(
            f"None of the {len(documents)} inventoried file(s) are in a convertible non-PDF format."
        ),
        nothing_examined_message="No file was inventoried, so document formats were not examined.",
    )


_PORTABLE_FILENAME_CHARACTERS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 ._()-"
)
_MAX_FILENAME_LENGTH = 150


def check_filename_portability(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag filename characters and lengths that commonly break uploads and links."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Filename facts are unavailable.")
    flagged: list[str] = []
    for document in documents:
        name = PurePosixPath(document.path).name
        unusual = set(name) - _PORTABLE_FILENAME_CHARACTERS
        if unusual or len(name) > _MAX_FILENAME_LENGTH:
            flagged.append(document.path)
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.WARNING,
                message=(
                    "One or more filenames contain unusual characters or are very long, "
                    "which can break uploads, links, or downstream processing."
                ),
                evidence=Evidence(details={"filenames": flagged}),
                remediation=(
                    "Rename files using letters, numbers, spaces, hyphens, underscores, and "
                    "periods, keeping names reasonably short."
                ),
                confidence=Confidence.MEDIUM,
            )
        ]
        if flagged
        else []
    )
    return _conclude(
        outcomes,
        examined=len(documents),
        excluded=0,
        pass_message=(
            f"All {len(documents)} inventoried filename(s) use portable characters and lengths."
        ),
        nothing_examined_message="No file was inventoried, so no filename was checked.",
    )


def check_duplicate_hashes(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("File hash facts are unavailable.")
    groups: defaultdict[str, list[str]] = defaultdict(list)
    unhashed = 0
    for document in documents:
        if document.sha256:
            groups[document.sha256].append(document.path)
        else:
            unhashed += 1
    duplicates = [paths for paths in groups.values() if len(paths) > 1]
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.WARNING,
                message="Duplicate files were detected in the package.",
                evidence=Evidence(details={"duplicate_groups": duplicates}),
                remediation="Remove redundant copies unless each is intentionally required.",
            )
        ]
        if duplicates
        else []
    )
    examined = sum(len(paths) for paths in groups.values())
    result = _conclude(
        outcomes,
        excluded=0,  # a file with no checksum is disclosed below, in its own words
        examined=examined,
        pass_message=(
            f"No duplicate file hashes were detected among {examined} checksummed file(s)."
        ),
        nothing_examined_message="No file checksum was available, so duplicates were not checked.",
    )
    if unhashed and examined:
        # The pass above stands for the checksummed files only. When nothing was hashed at
        # all, `_conclude` has already said so and this would only repeat it.
        result.extend(
            _indeterminate(
                f"{unhashed} file(s) have no checksum and were excluded from this check, "
                "which therefore makes no statement about whether they are duplicates."
            )
        )
    return result


def check_document_categories(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Warn where an actual PDF lacks the explicit category needed for comparisons."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Document-category facts are unavailable.")
    pdf_count = sum(document.is_pdf for document in documents)
    missing = [document.path for document in documents if document.is_pdf and not document.category]
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.WARNING,
                message="One or more PDFs have no declared document category.",
                evidence=Evidence(details={"uncategorized_documents": missing}),
                remediation="Add an explicit category for each PDF in package.yaml.",
                confidence=Confidence.MEDIUM,
            )
        ]
        if missing
        else []
    )
    return _conclude(
        outcomes,
        examined=pdf_count,
        excluded=0,
        pass_message=f"All {pdf_count} inventoried PDF(s) have a declared document category.",
        nothing_examined_message="No PDF was inventoried, so no document category was checked.",
    )


def check_manifest_references(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Ensure explicit manifest entries refer to real package files."""

    declared_paths = context.facts.get("declared_paths")
    documents, incomplete = _documents(context)
    if declared_paths is None:
        return _indeterminate("No manifest was supplied for cross-document consistency checks.")
    if (
        incomplete
        or not isinstance(declared_paths, list)
        or not all(isinstance(path, str) for path in declared_paths)
    ):
        return _indeterminate("Manifest reference facts are unavailable.")
    actual_paths = {document.path for document in documents}
    missing = sorted(set(declared_paths) - actual_paths)
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message="One or more manifest document references do not exist in the package.",
                evidence=Evidence(details={"missing_paths": missing}),
                remediation=(
                    "Correct the manifest paths or add the referenced files to the package."
                ),
            )
        ]
        if missing
        else []
    )
    return _conclude(
        outcomes,
        examined=len(declared_paths),
        excluded=0,
        pass_message=(
            f"All {len(declared_paths)} manifest document reference(s) exist in the package."
        ),
        nothing_examined_message=(
            "The manifest declared no documents, so no reference was checked."
        ),
    )


def check_descriptive_filenames(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag plainly non-descriptive PDF names without trying to infer legal content."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Filename facts are unavailable.")
    weak_names: list[str] = []
    examined = 0
    for document in documents:
        if not document.is_pdf:
            continue
        examined += 1
        stem = PurePosixPath(document.path).stem.casefold()
        alpha_numeric = "".join(character for character in stem if character.isalnum())
        if len(alpha_numeric) < 8 or "replacewith" in alpha_numeric:
            weak_names.append(document.path)
    outcomes = (
        [
            RuleOutcome(
                status=RuleOutcomeStatus.WARNING,
                message="One or more PDF filenames may not be descriptive enough for routing.",
                evidence=Evidence(details={"filenames": weak_names}),
                remediation=(
                    "Rename PDFs to include a clear document type and project-derived token."
                ),
                confidence=Confidence.MEDIUM,
            )
        ]
        if weak_names
        else []
    )
    return _conclude(
        outcomes,
        examined=examined,
        excluded=0,
        pass_message=(
            f"All {examined} inventoried PDF filename(s) meet the basic descriptive-name "
            "convention."
        ),
        nothing_examined_message="No PDF was inventoried, so no filename was checked.",
    )


COMMON_RULES = {
    "pdf_present": check_pdf_present,
    "pdf_signature": check_pdf_signature,
    "pdf_readable": check_pdf_readable,
    "text_coverage": check_text_coverage,
    "active_content": check_active_content,
    "flattened_forms": check_flattened_forms,
    "structure_tags": check_structure_tags,
    "file_size": check_file_size,
    "non_pdf_documents": check_non_pdf_documents,
    "filename_portability": check_filename_portability,
    "document_categories": check_document_categories,
    "manifest_references": check_manifest_references,
    "descriptive_filenames": check_descriptive_filenames,
    "duplicate_hashes": check_duplicate_hashes,
}
