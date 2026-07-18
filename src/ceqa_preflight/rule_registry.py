"""The built-in rule-pack registry used by the CLI and local checker."""

from __future__ import annotations

from pathlib import Path

from ceqa_preflight.models import FilingType
from ceqa_preflight.rule_catalog import RuleCatalog, load_rule_catalog
from ceqa_preflight.rule_engine import RuleCheck
from ceqa_preflight.rules.common import COMMON_RULES
from ceqa_preflight.rules.nod import NOD_RULES
from ceqa_preflight.rules.noe import NOE_RULES


def default_catalog_paths(filing_type: FilingType | None = None) -> list[Path]:
    """Return built-in source-cited rule packs in deterministic order."""

    rulepacks = Path(__file__).parent / "rulepacks"
    paths = [rulepacks / "common.yaml"]
    if filing_type is None or filing_type is FilingType.NOD:
        paths.append(rulepacks / "nod.yaml")
    if filing_type is None or filing_type is FilingType.NOE:
        paths.append(rulepacks / "noe.yaml")
    return paths


def default_catalog(filing_type: FilingType | None = None) -> RuleCatalog:
    """Load the built-in catalog without network access."""

    return load_rule_catalog(default_catalog_paths(filing_type))


def default_registry() -> dict[str, RuleCheck]:
    """Return the immutable allow-list surface as a fresh mapping."""

    return {**COMMON_RULES, **NOD_RULES, **NOE_RULES}
