"""Prove the locale seam changes human-readable report prose but never anything

machine-readable — the report-schema guarantee docs/I18N.md requires before the first
tagged release: locale selection changes human-readable prose but never machine-readable
keys, rule IDs, finding status values, or citations.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ceqa_preflight.checker import DISCLAIMER
from ceqa_preflight.i18n import using_locale
from ceqa_preflight.models import (
    Finding,
    FindingStatus,
    InspectionReport,
    SkippedCheck,
    SkipReason,
    SourceCitation,
)
from ceqa_preflight.reporting import (
    render_checklist,
    render_console,
    render_html,
    render_json,
)


def _report() -> InspectionReport:
    source = SourceCitation(title="Guidelines § 15062", url="https://example.invalid/15062")
    return InspectionReport(
        tool_version="0.1.0",
        ruleset_version="1",
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        input_fingerprint="fingerprint123",
        filing_type="NOE",
        findings=[
            Finding(
                rule_id="NOE-001",
                rule_version="1",
                status=FindingStatus.FAILURE,
                title="Missing signature page",
                message="The notice is missing a signature page.",
                remediation="Add a signed signature page.",
                source=source,
            )
        ],
        manual_review=[
            Finding(
                rule_id="NOE-002",
                rule_version="1",
                status=FindingStatus.MANUAL,
                title="Review project description",
                message="Confirm the project description matches the application.",
                remediation="Have a reviewer confirm the description.",
            )
        ],
        not_run=[
            SkippedCheck(
                rule_id="NOE-003",
                rule_version="1",
                title="Experimental threshold check",
                reason=SkipReason.EXPERIMENTAL_NOT_INCLUDED,
                detail="Experimental rules are excluded unless explicitly requested.",
            )
        ],
        disclaimer=DISCLAIMER(),
    )


def test_disclaimer_is_localized_when_the_report_is_built() -> None:
    with using_locale("en"):
        english_report = _report()
    with using_locale("es"):
        spanish_report = _report()

    assert english_report.disclaimer != spanish_report.disclaimer
    assert "advisory" in english_report.disclaimer
    assert "consultivo" in spanish_report.disclaimer


def test_console_prose_differs_by_locale_but_identifiers_do_not() -> None:
    with using_locale("en"):
        report = _report()
        english = render_console(report)
    with using_locale("es"):
        spanish = render_console(report)

    assert english != spanish
    assert "Manual review" in english
    assert "Revisión manual" in spanish
    for text in (english, spanish):
        assert "NOE-001" in text
        assert "NOE-002" in text
        assert "NOE-003" in text


def test_checklist_prose_differs_by_locale_but_identifiers_do_not() -> None:
    with using_locale("en"):
        report = _report()
        english = render_checklist(report)
    with using_locale("es"):
        spanish = render_checklist(report)

    assert english != spanish
    assert "Resolve before submission" in english
    assert "Resolver antes de la presentación" in spanish
    for text in (english, spanish):
        assert "NOE-001" in text
        assert "NOE-002" in text
        assert "NOE-003" in text


def test_html_prose_and_lang_attribute_differ_by_locale_but_identifiers_do_not() -> None:
    with using_locale("en"):
        report = _report()
        english = render_html(report)
    with using_locale("es"):
        spanish = render_html(report)

    assert '<html lang="en">' in english
    assert '<html lang="es">' in spanish
    assert "Automated findings" in english
    assert "Hallazgos automatizados" in spanish
    for text in (english, spanish):
        assert "NOE-001" in text
        assert "NOE-002" in text
        assert "NOE-003" in text
        assert "https://example.invalid/15062" in text


def test_json_report_is_locale_independent_for_every_machine_readable_field() -> None:
    """Only Finding.message/.remediation prose may vary; every structural key must not."""

    with using_locale("en"):
        report = _report()
        english = render_json(report)
    with using_locale("es"):
        # Rebuild with the SAME report object (already constructed in English) so this test
        # isolates render_json's own behavior, not report construction.
        spanish = render_json(report)

    assert english == spanish, "render_json must not re-translate an already-built report"
    for key in ('"rule_id"', '"status"', '"filing_type"', '"url"', '"title"'):
        assert key in english


def test_fallback_locale_is_deterministic_english() -> None:
    from ceqa_preflight.i18n import resolve_locale

    with using_locale(resolve_locale("fr")):  # unsupported but syntactically valid
        report = _report()
        rendered = render_console(report)

    assert "Manual review" in rendered
    assert "Revisión manual" not in rendered
