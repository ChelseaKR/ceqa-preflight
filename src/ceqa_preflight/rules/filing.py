"""Shared conservative checks for an explicitly classified filing form."""

from __future__ import annotations

from collections.abc import Iterable

from ceqa_preflight.models import Confidence, Evidence
from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_engine import RuleContext, RuleOutcome, RuleOutcomeStatus
from ceqa_preflight.rules.common import DocumentFact, _documents


def _category(value: str | None) -> str | None:
    return " ".join(value.casefold().split()) if value else None


def _form_candidates(
    context: RuleContext, expected_category: str
) -> tuple[list[DocumentFact], bool]:
    documents, incomplete = _documents(context)
    if incomplete:
        return [], True
    expected = _category(expected_category)
    uncertain = any(document.is_pdf and document.category is None for document in documents)
    candidates = [
        document
        for document in documents
        if document.is_pdf and document.primary and _category(document.category) == expected
    ]
    return candidates, uncertain


def check_primary_form(
    context: RuleContext, _: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message=(
                    "At least one PDF has no declared category, so the primary filing form "
                    "cannot be determined conservatively."
                ),
                remediation=(
                    "Declare document categories and mark exactly one filing form as primary."
                ),
                confidence=Confidence.LOW,
            )
        ]
    if len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message=(
                    f"Expected exactly one primary {expected_category} form; found "
                    f"{len(candidates)}."
                ),
                remediation=(
                    f"Declare exactly one PDF as the primary {expected_category} form in "
                    "the manifest."
                ),
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=f"Exactly one primary {expected_category} form is declared.",
            document=candidates[0].path,
            remediation="No action is needed for this check.",
        )
    ]


def check_primary_readable(
    context: RuleContext, _: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain or len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message=(
                    "A single, confidently identified primary form is unavailable for inspection."
                ),
                remediation=(
                    "Declare document categories and resolve the primary-form finding first."
                ),
                confidence=Confidence.LOW,
            )
        ]
    form = candidates[0]
    if form.inspection is None or form.inspection.timed_out:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message="The primary form could not be fully inspected within the safe limit.",
                document=form.path,
                remediation=(
                    "Review the primary form manually and provide a readable PDF if needed."
                ),
                confidence=Confidence.LOW,
            )
        ]
    if not form.inspection.readable or form.inspection.encrypted:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message="The primary filing form is unreadable or encrypted.",
                document=form.path,
                remediation="Provide an unencrypted, readable primary filing form PDF.",
                confidence=form.inspection.extraction_confidence,
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message="The primary filing form is readable and unencrypted.",
            document=form.path,
            remediation="No action is needed for this check.",
            confidence=form.inspection.extraction_confidence,
        )
    ]


def _miscategorized_primaries(context: RuleContext, expected_category: str) -> list[DocumentFact]:
    """Documents declared primary whose declared category is some other, stated category.

    ``_form_candidates`` selects on ``primary and category == expected``, so a document the
    manifest marks primary while giving it a different category is simply dropped from the
    candidate list. Nothing downstream can then name it: the primary-form rule reports
    "found 0" and the category rule reported that it could not establish anything. The
    contradiction the person actually made is the one thing the report never said.
    """

    documents, incomplete = _documents(context)
    if incomplete:
        return []
    expected = _category(expected_category)
    return [
        document
        for document in documents
        if document.is_pdf
        and document.primary
        and document.category is not None
        and _category(document.category) != expected
    ]


def check_primary_category(
    context: RuleContext, _: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    """Report a primary form whose declared category contradicts the filing being checked.

    Before this had a failure branch the check could only pass or go indeterminate: its
    candidates were *defined* as the documents whose category already equalled the expected
    one, so "the primary form is categorized as X" was true by construction and no input
    could make the rule report otherwise. A check with no reachable failure adds a green
    line to the report and nothing else.

    The failure below is a statement about the manifest contradicting itself, not about
    CEQA. No official source is cited for it beyond the one this rule already carries,
    because none is needed to observe that a document declared as the primary filing form
    carries a category other than the filing type the run was asked to check.
    """

    mismatched = _miscategorized_primaries(context, expected_category)
    if mismatched:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message=(
                    f"{len(mismatched)} document(s) are declared as the primary filing form "
                    f"but carry a declared category other than {expected_category}, which is "
                    "the category this run was asked to check."
                ),
                document=mismatched[0].path,
                evidence=Evidence(
                    details={
                        "expected_category": expected_category,
                        "declared": {document.path: document.category for document in mismatched},
                    }
                ),
                remediation=(
                    f"Correct the manifest so the primary form's category is "
                    f"{expected_category}, or check this package as the filing type its "
                    "primary form actually declares."
                ),
            )
        ]
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain or len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message="The primary form category cannot be established conservatively.",
                remediation=(
                    "Declare a category and primary flag for the filing form in the manifest."
                ),
                confidence=Confidence.LOW,
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=f"The primary form is categorized as {expected_category}.",
            document=candidates[0].path,
            remediation="No action is needed for this check.",
        )
    ]


def manual_confirmation(message: str, remediation: str) -> list[RuleOutcome]:
    """Return an explicit manual review item for non-automatable filing questions."""

    return [
        RuleOutcome(
            status=RuleOutcomeStatus.INDETERMINATE,
            message=message,
            remediation=remediation,
            confidence=Confidence.LOW,
        )
    ]
