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
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message=(
                        f"Sampled searchable-text coverage is {inspection.text_coverage:.0%}, "
                        f"below the {threshold:.0%} threshold."
                    ),
                    document=document.path,
                    evidence=Evidence(
                        details={
                            "sampled_pages": len(inspection.sampled_pages),
                            "coverage": inspection.text_coverage,
                            "threshold": threshold,
                        }
                    ),
                    remediation=(
                        "Confirm that the PDF is searchable or provide an accessible source PDF."
                    ),
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
        active = inspection.active_form_field_count
        suspicious = inspection.javascript_present or inspection.launch_action_present
        suspicious = suspicious or inspection.embedded_file_count > 0
        if active or suspicious:
            outcomes.append(
                RuleOutcome(
                    status=RuleOutcomeStatus.WARNING,
                    message="This PDF contains active fields, actions, or embedded files.",
                    document=document.path,
                    evidence=Evidence(
                        details={
                            "form_field_count": active,
                            "embedded_file_count": inspection.embedded_file_count,
                            "javascript_present": inspection.javascript_present,
                            "launch_action_present": inspection.launch_action_present,
                        }
                    ),
                    remediation=(
                        "Flatten fields and remove unneeded active content before submission."
                    ),
                    confidence=inspection.extraction_confidence,
                )
            )
    return outcomes or [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="No active PDF fields, actions, or embedded files were detected.",
            remediation="No action is needed for this check.",
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
    "document_categories": check_document_categories,
    "manifest_references": check_manifest_references,
    "descriptive_filenames": check_descriptive_filenames,
    "duplicate_hashes": check_duplicate_hashes,
}
