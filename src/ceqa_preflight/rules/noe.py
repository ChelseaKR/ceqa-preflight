"""NOE-specific checks that use only explicit manifest and PDF facts."""

from __future__ import annotations

from collections.abc import Iterable

from ceqa_preflight.i18n import gettext as _
from ceqa_preflight.rule_catalog import RuleDefinition
from ceqa_preflight.rule_engine import RuleContext, RuleOutcome
from ceqa_preflight.rules.filing import (
    check_primary_category,
    check_primary_form,
    check_primary_readable,
    manual_confirmation,
)

_CATEGORY = "Notice of Exemption"


def noe_primary_form(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_form(context, rule, expected_category=_CATEGORY)


def noe_primary_readable(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_readable(context, rule, expected_category=_CATEGORY)


def noe_primary_category(context: RuleContext, rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return check_primary_category(context, rule, expected_category=_CATEGORY)


def noe_exemption(_context: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        _("Confirm exemption choice, citation, and reasoning manually."),
        _("Review the project record and applicable CEQA authority with a qualified reviewer."),
    )


def noe_supporting_findings(_context: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        _("Confirm supporting findings, if applicable, manually."),
        _("Review the project record and include applicable supporting materials."),
    )


def noe_signature_timing(_context: RuleContext, _rule: RuleDefinition) -> Iterable[RuleOutcome]:
    return manual_confirmation(
        _("Confirm signature and filing timing manually."),
        _("Verify authorization, signature, and filing timing against applicable requirements."),
    )


NOE_RULES = {
    "noe_primary_form": noe_primary_form,
    "noe_primary_readable": noe_primary_readable,
    "noe_primary_category": noe_primary_category,
    "noe_exemption": noe_exemption,
    "noe_supporting_findings": noe_supporting_findings,
    "noe_signature_timing": noe_signature_timing,
}
