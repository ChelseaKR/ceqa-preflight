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
    for document in documents:
        if not document.is_pdf:
            continue
        if document.signature_is_pdf is None:
            outcomes.extend(_indeterminate("A PDF signature could not be determined."))
        elif not document.signature_is_pdf:
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="All inventoried PDF files have a PDF signature.",
            remediation="No action is needed for this check.",
        )
    ]


def check_pdf_readable(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF inspection facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    for document in documents:
        if not document.is_pdf:
            continue
        inspection = document.inspection
        if inspection is None or inspection.timed_out:
            outcomes.extend(
                _indeterminate("A PDF could not be fully inspected within the safe limit.")
            )
        elif not inspection.readable or inspection.encrypted:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.FAILURE,
                    message="This PDF is unreadable or encrypted.",
                    document=document.path,
                    remediation="Provide an unencrypted, readable PDF.",
                    confidence=inspection.extraction_confidence,
                )
            )
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="All inspected PDFs are readable and unencrypted.",
            remediation="No action is needed for this check.",
        )
    ]


def check_text_coverage(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    threshold = float(rule.parameters.get("minimum_coverage", 0.8))
    if incomplete or not 0 <= threshold <= 1:
        return _indeterminate("Searchable-text coverage facts or threshold are unavailable.")
    outcomes: list[RuleOutcome] = []
    for document in documents:
        inspection = document.inspection
        if not document.is_pdf or inspection is None or not inspection.readable:
            continue
        if inspection.text_coverage is None:
            outcomes.extend(_indeterminate("Sampled searchable-text coverage is unavailable."))
        elif inspection.text_coverage < threshold:
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="Inspected PDFs meet the sampled searchable-text threshold.",
            remediation="No action is needed for this check.",
        )
    ]


def check_active_content(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF active-content facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    for document in documents:
        inspection = document.inspection
        if not document.is_pdf or inspection is None:
            continue
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="No active PDF actions or embedded files were detected.",
            remediation="No action is needed for this check.",
        )
    ]


def check_flattened_forms(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag fillable form fields, which official guidance asks filers to flatten."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF form-field facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    for document in documents:
        inspection = document.inspection
        if not document.is_pdf or inspection is None:
            continue
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="No fillable form fields were detected in inspected PDFs.",
            remediation="No action is needed for this check.",
        )
    ]


def check_structure_tags(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Report a missing structure tree without claiming accessibility certification."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("PDF structure-tree facts are unavailable.")
    outcomes: list[RuleOutcome] = []
    for document in documents:
        inspection = document.inspection
        if not document.is_pdf or inspection is None or not inspection.readable:
            continue
        if inspection.structure_tree_present is None:
            outcomes.extend(_indeterminate("A PDF structure tree could not be determined."))
        elif not inspection.structure_tree_present:
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="All inspected PDFs contain a structure tree for screen readers.",
            remediation="No action is needed for this check.",
        )
    ]


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
    for document in documents:
        if document.size_bytes is None:
            outcomes.extend(_indeterminate("A file size could not be determined."))
        elif document.size_bytes > threshold_bytes:
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
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="All files are within the advisory size threshold.",
            remediation="No action is needed for this check.",
        )
    ]


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
    if not convertible:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="No documents in convertible non-PDF formats were detected.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
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
    if not flagged:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="All filenames use portable characters and lengths.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
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


def check_duplicate_hashes(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("File hash facts are unavailable.")
    groups: defaultdict[str, list[str]] = defaultdict(list)
    for document in documents:
        if document.sha256:
            groups[document.sha256].append(document.path)
    duplicates = [paths for paths in groups.values() if len(paths) > 1]
    if not duplicates:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="No duplicate file hashes were detected.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.WARNING,
            message="Duplicate files were detected in the package.",
            evidence=Evidence(details={"duplicate_groups": duplicates}),
            remediation="Remove redundant copies unless each is intentionally required.",
        )
    ]


def check_document_categories(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Warn where an actual PDF lacks the explicit category needed for comparisons."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Document-category facts are unavailable.")
    missing = [document.path for document in documents if document.is_pdf and not document.category]
    if not missing:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="Every inventoried PDF has a declared document category.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.WARNING,
            message="One or more PDFs have no declared document category.",
            evidence=Evidence(details={"uncategorized_documents": missing}),
            remediation="Add an explicit category for each PDF in package.yaml.",
            confidence=Confidence.MEDIUM,
        )
    ]


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
    if not missing:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="Every manifest document reference exists in the package.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.FAILURE,
            message="One or more manifest document references do not exist in the package.",
            evidence=Evidence(details={"missing_paths": missing}),
            remediation="Correct the manifest paths or add the referenced files to the package.",
        )
    ]


def check_descriptive_filenames(context: RuleContext, _: RuleDefinition) -> Iterable[RuleOutcome]:
    """Flag plainly non-descriptive PDF names without trying to infer legal content."""

    documents, incomplete = _documents(context)
    if incomplete:
        return _indeterminate("Filename facts are unavailable.")
    weak_names: list[str] = []
    for document in documents:
        if not document.is_pdf:
            continue
        stem = PurePosixPath(document.path).stem.casefold()
        alpha_numeric = "".join(character for character in stem if character.isalnum())
        if len(alpha_numeric) < 8 or "replacewith" in alpha_numeric:
            weak_names.append(document.path)
    if not weak_names:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.PASS,
                message="PDF filenames meet the basic descriptive-name convention.",
                remediation="No action is needed for this check.",
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.WARNING,
            message="One or more PDF filenames may not be descriptive enough for routing.",
            evidence=Evidence(details={"filenames": weak_names}),
            remediation="Rename PDFs to include a clear document type and project-derived token.",
            confidence=Confidence.MEDIUM,
        )
    ]


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
