"""Tests for the built-in source-cited rule registry."""

from ceqa_preflight.models import FilingType
from ceqa_preflight.rule_registry import default_catalog, default_catalog_paths, default_registry


def test_registry_and_catalog_cover_the_supported_filing_types() -> None:
    catalog = default_catalog()

    assert {rule.id for rule in catalog.rules} >= {"CORE-001", "NOD-001", "NOE-001"}
    assert all(rule.check in default_registry() for rule in catalog.rules)
    assert [path.name for path in default_catalog_paths(FilingType.NOD)] == [
        "common.yaml",
        "nod.yaml",
    ]
    assert [path.name for path in default_catalog_paths(FilingType.NOE)] == [
        "common.yaml",
        "noe.yaml",
    ]
