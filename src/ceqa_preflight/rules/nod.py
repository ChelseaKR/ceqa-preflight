"""NOD-specific checks that use only explicit manifest and PDF facts."""

from __future__ import annotations

from collections.abc import Iterable

from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_engine import RuleContext, RuleOutcome
from ceqa_preflight.rules.filing import (
    check_primary_category,
    check_primary_form,
    check_primary_readable,
    manual_confirmation,
)

_CATEGORY = "Notice of Determination"


def nod_primary_form(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_form(context, rule, expected_category=_CATEGORY)


def nod_primary_readable(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_readable(context, rule, expected_category=_CATEGORY)


def nod_primary_category(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_category(context, rule, expected_category=_CATEGORY)


def nod_cdfw_fee(_: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        "Confirm applicable CDFW fee handling and any required receipt manually.",
        "Review the filing requirements and attach or retain supporting records as applicable.",
    )


def nod_supporting_materials(_: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        (
            "Confirm whether mitigation monitoring, findings, overriding considerations, "
            "or final materials apply."
        ),
        "Review the project record and include applicable supporting materials.",
    )


def nod_signature_timing(_: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        "Confirm signature and filing timing manually.",
        "Verify authorization, signature, and filing timing against applicable requirements.",
    )


NOD_RULES = {
    "nod_primary_form": nod_primary_form,
    "nod_primary_readable": nod_primary_readable,
    "nod_primary_category": nod_primary_category,
    "nod_cdfw_fee": nod_cdfw_fee,
    "nod_supporting_materials": nod_supporting_materials,
    "nod_signature_timing": nod_signature_timing,
}
