"""Shared conservative checks for an explicitly classified filing form."""

from __future__ import annotations

from collections.abc import Iterable

from ceqa_preflight.i18n import gettext as _
from ceqa_preflight.models import Confidence
from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_engine import RuleContext, RuleOutcome, RuleOutcomeStatus
from ceqa_preflight.rules.common import DocumentFact, _documents, _no_action_needed


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
    context: RuleContext, _rule: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message=_(
                    "At least one PDF has no declared category, so the primary filing form "
                    "cannot be determined conservatively."
                ),
                remediation=_(
                    "Declare document categories and mark exactly one filing form as primary."
                ),
                confidence=Confidence.LOW,
            )
        ]
    if len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message=_("Expected exactly one primary {category} form; found {count}.").format(
                    category=expected_category, count=len(candidates)
                ),
                remediation=_(
                    "Declare exactly one PDF as the primary {category} form in the manifest."
                ).format(category=expected_category),
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=_("Exactly one primary {category} form is declared.").format(
                category=expected_category
            ),
            document=candidates[0].path,
            remediation=_no_action_needed(),
        )
    ]


def check_primary_readable(
    context: RuleContext, _rule: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain or len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message=_(
                    "A single, confidently identified primary form is unavailable for inspection."
                ),
                remediation=_(
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
                message=_("The primary form could not be fully inspected within the safe limit."),
                document=form.path,
                remediation=_(
                    "Review the primary form manually and provide a readable PDF if needed."
                ),
                confidence=Confidence.LOW,
            )
        ]
    if not form.inspection.readable or form.inspection.encrypted:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.FAILURE,
                message=_("The primary filing form is unreadable or encrypted."),
                document=form.path,
                remediation=_("Provide an unencrypted, readable primary filing form PDF."),
                confidence=form.inspection.extraction_confidence,
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=_("The primary filing form is readable and unencrypted."),
            document=form.path,
            remediation=_no_action_needed(),
            confidence=form.inspection.extraction_confidence,
        )
    ]


def check_primary_category(
    context: RuleContext, _rule: RuleDefinition, *, expected_category: str
) -> Iterable[RuleOutcome]:
    candidates, uncertain = _form_candidates(context, expected_category)
    if uncertain or len(candidates) != 1:
        return [
            RuleOutcome(
                status=RuleOutcomeStatus.INDETERMINATE,
                message=_("The primary form category cannot be established conservatively."),
                remediation=_(
                    "Declare a category and primary flag for the filing form in the manifest."
                ),
                confidence=Confidence.LOW,
            )
        ]
    return [
        RuleOutcome(
            status=RuleOutcomeStatus.PASS,
            message=_("The primary form is categorized as {category}.").format(
                category=expected_category
            ),
            document=candidates[0].path,
            remediation=_no_action_needed(),
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
