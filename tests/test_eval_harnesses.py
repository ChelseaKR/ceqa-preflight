"""Offline tests for the eval harness helpers. No network, no model."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for folder in ("evals", "evals/extraction", "scripts"):
    candidate = str(ROOT / folder)
    if candidate not in sys.path:
        sys.path.insert(0, candidate)


def _load(name: str, relative: str):
    """Load a runner by path. Every suite names its module ``run``, so importing the
    grounding runner by name would return whichever ``run`` is first on ``sys.path``."""

    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import fetch_ceqanet_sample as fetcher  # type: ignore[import-not-found]  # noqa: E402
from run import (  # type: ignore[import-not-found]  # noqa: E402
    aggregate,
    redact,
    score_field,
    values_match,
)

from ceqa_preflight.ai.explain import ExplainMode, FindingExplanation  # noqa: E402
from ceqa_preflight.ai.extraction import (  # noqa: E402
    DocumentExtraction,
    ExtractedField,
    FieldStatus,
)
from ceqa_preflight.ai.grounding import Citation, Claim  # noqa: E402
from ceqa_preflight.models import FindingStatus  # noqa: E402

grounding_run = _load("grounding_run", "evals/grounding/run.py")

_PAGE = """
<h2>Attachments</h2>
<div>Notice of Exemption</div>
<a class="btn" href="/2026080811/1/Attachment/_TyUga">CEQA NOE <span>PDF</span> 485 K</a>
<div>Exemption Findings</div>
<a class="btn" href="/2026080811/1/Attachment/abc">Findings PDF 12 K</a>
"""

_CSV = (
    "SCH Number,Lead Agency Name,Document Title,Document Type,Project Title,Contact Full Name,"
    "Contact Email Address,Contact Phone Number,Cities,Counties,Location Cross Streets,"
    "NOE Exempt Status,NOE Exempt Citation,NOD Approved Date,"
    "NOD Environmental Impact Report Prepared,NOD Negative Declaration Prepared,"
    "NOD Mitigation Measures\n"
    "2026080811,Kern Union High School District,Bakersfield High School Auditorium Re-roofing,"
    "NOE,Auditorium Re-roofing,Randall Rowles,someone@example.org,6613964969,Bakersfield,Kern,"
    'California Ave. & H St.,Categorical Exemption,"California Code of Regulations, Title 14, '
    'Section 15301",,,Yes,Yes\n'
)


def test_document_links_and_attachments_parse_page_structure() -> None:
    links = fetcher.document_links('<a href="/2026080811/1">x</a><a href="/2026080811/1">y</a>')
    assert links == [("2026080811", "1")]
    found = fetcher.attachments(_PAGE)
    assert found[0][0] == "Notice of Exemption"
    assert found[0][1].startswith("CEQA NOE")
    assert found[0][2] == "/2026080811/1/Attachment/_TyUga"
    assert found[1][0] == "Exemption Findings"


def test_gold_from_csv_maps_fields_and_never_keeps_contact_details() -> None:
    gold = fetcher.gold_from_csv(_CSV)
    assert gold["lead_agency"] == "Kern Union High School District"
    assert gold["project_title"] == [
        "Bakersfield High School Auditorium Re-roofing",
        "Auditorium Re-roofing",
    ]
    assert gold["contact_name"] == "Randall Rowles"
    assert gold["exemption_citation"].endswith("Section 15301")
    assert gold["nod_environmental_document"] == [
        "Negative Declaration",
        "Mitigated Negative Declaration",
    ]
    assert "example.org" not in str(gold) and "6613964969" not in str(gold)


def test_values_match_normalizes_and_uses_field_specific_rules() -> None:
    assert values_match("county", "Kern", "Kern, Tulare")
    assert (
        values_match("lead_agency", "Kern High School District", "Kern Union High School District")
        is False
    )
    assert values_match("lead_agency", "City of Belmont", "Belmont, City of")
    assert values_match("county", "San Mateo County", "San Mateo")
    assert values_match("lead_agency", "County of Los Angeles", "Los Angeles County")
    assert values_match(
        "lead_agency",
        "Solano County Dept. of Resource Management",
        "Solano County, Resource Management Department of",
    )
    assert values_match("city_or_community", "City of Lake Elsinore", "Lake Elsinore")
    assert not values_match("lead_agency", "San Francisco Planning Department", "Fresno")
    assert values_match("project_title", "Re-roofing", "Auditorium Re-roofing")
    assert values_match(
        "exemption_citation", "Existing Facilities CEQA § 15301", "CCR Title 14, Section 15301"
    )
    assert values_match("nod_approval_date", "March 4, 2024", "3/4/2024")
    assert values_match("nod_approval_date", "3-4-24", "03/04/2024")
    assert not values_match("nod_approval_date", "no date", "3/4/2024")
    assert values_match("sch_number", "2026080811", "2026080811")


def test_score_field_outcomes_and_redaction() -> None:
    extraction = DocumentExtraction(
        path="x.pdf",
        attempted=True,
        fields=[
            ExtractedField(
                name="county", status=FieldStatus.FOUND, value="Kern", quote="COUNTY: Kern"
            ),
            ExtractedField(
                name="city_or_community",
                status=FieldStatus.FOUND,
                value="Bakersfield",
                quote="CITY: Bakersfield, call (661) 396-4969",
            ),
            ExtractedField(name="sch_number", status=FieldStatus.UNKNOWN),
            ExtractedField(name="lead_agency", status=FieldStatus.UNVERIFIED, withheld_value="x"),
            ExtractedField(
                name="contact_name",
                status=FieldStatus.FOUND,
                value="Randall Rowles",
                quote="Randall Rowles",
            ),
            ExtractedField(
                name="project_location",
                status=FieldStatus.FOUND,
                value="1241 G St.",
                quote="1241 G St.",
            ),
        ],
    )
    assert score_field("county", extraction, "Kern")["outcome"] == "match"
    city = score_field("city_or_community", extraction, "Fresno")
    assert city["outcome"] == "mismatch" and "[phone redacted]" in city["quote"]
    assert (
        score_field("sch_number", extraction, "2026080811")["outcome"] == "abstained_gold_present"
    )
    assert score_field("sch_number", extraction, None)["outcome"] == "both_absent"
    assert score_field("lead_agency", extraction, "Kern")["outcome"] == "withheld"
    contact = score_field("contact_name", extraction, "Randall Rowles")
    assert contact["outcome"] == "match" and "extracted" not in contact and "quote" not in contact
    assert score_field("project_location", extraction, None)["outcome"] == "filled_gold_absent"
    assert score_field("exemption_status", extraction, None)["outcome"] == "both_absent"
    assert (
        redact("mail me at a.b@c.org or 661-396-4969")
        == "mail me at [email redacted] or [phone redacted]"
    )
    assert redact(None) is None


def test_aggregate_reports_the_defect_separately() -> None:
    rows = [
        {
            "attempted": True,
            "has_text_layer": True,
            "model_error": None,
            "document_kind_correct": True,
            "fields": [
                {"field": "county", "outcome": "match"},
                {"field": "city_or_community", "outcome": "mismatch"},
                {"field": "project_location", "outcome": "filled_gold_absent"},
            ],
        }
    ]
    metrics = aggregate(rows)
    assert metrics["exact_or_normalized_match_rate_when_filled"] == 0.5
    assert metrics["filled_gold_absent"] == 1
    assert metrics["per_field"]["county"] == {"match": 1}


def _explained(claims: list[Claim], withheld: list[object] | None = None) -> FindingExplanation:
    return FindingExplanation(
        rule_id="common.scanned-pdf",
        rule_version="1.0",
        status=FindingStatus.FAILURE,
        title="A scanned PDF",
        message="This document has no text layer.",
        claims=claims,
        withheld=withheld or [],
    )


def _cited(text: str) -> Claim:
    return Claim(text=text, citations=[Citation(passage_id="p1", quote="q", verified=True)])


def test_a_determination_that_reaches_display_is_counted_not_assumed() -> None:
    """The count must come off the shown claims, so a verifier regression moves it.

    This figure was a hardcoded ``0`` annotated "by construction". Nothing measured it,
    so a claim reaching display with determination language -- the exact failure the
    number exists to rule out -- left it reading zero.
    """

    leaked = _cited("Your filing complies with CEQA and will be accepted.")
    row = grounding_run.row_for("synthetic-noe", ExplainMode.EXPLAIN, _explained([leaked]))

    assert row["determinations_shown"] == 1, (
        "a determination reached display and the row did not count it"
    )
    assert row["determination_phrases_shown"], "a nonzero count must name the phrase"

    metrics = grounding_run.summarize([row])
    assert metrics["determinations_reaching_display"] == 1
    assert metrics["determination_phrases_reaching_display"]


def test_clean_claims_reaching_display_count_zero() -> None:
    row = grounding_run.row_for(
        "synthetic-noe",
        ExplainMode.EXPLAIN,
        _explained([_cited("The form has no text layer, so a reviewer cannot search it.")]),
    )
    assert row["determinations_shown"] == 0
    assert row["determination_phrases_shown"] == []
    assert grounding_run.summarize([row])["determinations_reaching_display"] == 0
    assert grounding_run.summarize([row])["determination_phrases_reaching_display"] == []


def test_summarize_still_reports_what_the_verifier_withheld() -> None:
    """The withheld count and the reached-display count are different measurements."""

    from ceqa_preflight.ai.grounding import WithheldClaim

    item = _explained(
        [_cited("The signature field is empty.")],
        [WithheldClaim(reason="determination language: 'complies with ceqa'", citation_count=1)],
    )
    metrics = grounding_run.summarize([grounding_run.row_for("r", ExplainMode.EXPLAIN, item)])
    assert metrics["withheld_determination"] == 1
    assert metrics["determinations_reaching_display"] == 0
    assert metrics["claims_produced"] == 2
    assert metrics["claims_shown"] == 1
