"""Tests for declarative rule catalog validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from ceqa_preflight.rule_catalog import RuleCatalogError, load_rule_catalog


def _rule(rule_id: str = "CORE-001", *, version: str = "1.0.0") -> str:
    return f'''catalog_version: "1.0.0"
rules:
  - id: "{rule_id}"
    version: "{version}"
    title: "A test rule"
    check: "test_check"
    filing_types: ["NOD", "NOE"]
    source:
      title: "Official guidance"
      url: "https://lci.ca.gov/sch/document-submission/"
'''


def test_loads_catalog_in_file_order(tmp_path: Path) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text(_rule("CORE-001"), encoding="utf-8")
    second.write_text(_rule("PDF-001"), encoding="utf-8")

    catalog = load_rule_catalog([first, second])

    assert catalog.catalog_version == "1.0.0"
    assert [rule.id for rule in catalog.rules] == ["CORE-001", "PDF-001"]


@pytest.mark.parametrize(
    ("first", "second", "match"),
    [
        (_rule("CORE-001"), _rule("CORE-001"), "duplicate rule identifier"),
        (_rule(version="one"), None, "invalid rule catalog"),
        (
            _rule().replace('check: "test_check"', 'check: "os.system"'),
            None,
            "invalid rule catalog",
        ),
        (
            _rule().replace(
                'url: "https://lci.ca.gov/sch/document-submission/"', 'url: "relative"'
            ),
            None,
            "invalid rule catalog",
        ),
        (
            _rule().replace(
                "    source:",
                '    parameters:\n      shell: "eval(unsafe)"\n    source:',
            ),
            None,
            "invalid rule catalog",
        ),
    ],
)
def test_rejects_invalid_catalogs(
    tmp_path: Path, first: str, second: str | None, match: str
) -> None:
    first_path = tmp_path / "first.yaml"
    first_path.write_text(first, encoding="utf-8")
    paths = [first_path]
    if second is not None:
        second_path = tmp_path / "second.yaml"
        second_path.write_text(second, encoding="utf-8")
        paths.append(second_path)

    with pytest.raises(RuleCatalogError, match=match):
        load_rule_catalog(paths)


def test_rejects_missing_or_incompatible_catalogs(tmp_path: Path) -> None:
    invalid_root = tmp_path / "root.yaml"
    invalid_root.write_text("- not\n- a mapping\n", encoding="utf-8")
    mismatch = tmp_path / "mismatch.yaml"
    mismatch.write_text(
        _rule().replace('catalog_version: "1.0.0"', 'catalog_version: "1.1.0"'), encoding="utf-8"
    )
    valid = tmp_path / "valid.yaml"
    valid.write_text(_rule(), encoding="utf-8")

    with pytest.raises(RuleCatalogError, match="root must be a mapping"):
        load_rule_catalog([invalid_root])
    with pytest.raises(RuleCatalogError, match="same catalog version"):
        load_rule_catalog([valid, mismatch])
    with pytest.raises(RuleCatalogError, match="at least one"):
        load_rule_catalog([])


def test_guidelines_must_be_ccr_section_numbers() -> None:
    from ceqa_preflight.rule_catalog import RuleDefinition

    base = {
        "id": "X-1",
        "version": "1.0.0",
        "title": "t",
        "check": "pdf_present",
        "filing_types": ["NOE"],
        "source": {"title": "s", "url": "https://example.test/"},
    }
    assert RuleDefinition.model_validate({**base, "guidelines": ["15062", "15064.3"]}).guidelines
    with pytest.raises(ValueError, match="section numbers"):
        RuleDefinition.model_validate({**base, "guidelines": ["Section 15062"]})


def test_filing_rules_are_wired_to_guidelines_sections() -> None:
    from ceqa_preflight.rule_registry import default_catalog

    rules = {rule.id: rule for rule in default_catalog().rules}
    assert rules["NOE-001"].guidelines == ["15062"]
    assert set(rules["NOD-001"].guidelines) == {"15075", "15094"}
    assert rules["PDF-003"].guidelines == []
