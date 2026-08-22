"""Tests for quote-verified extraction: the model proposes, the verifier decides what stands."""

from __future__ import annotations

import json
from typing import Any

from ceqa_preflight.ai.client import ScriptedClient
from ceqa_preflight.ai.extraction import (
    FIELD_NAMES,
    SYSTEM_PROMPT,
    DocumentKind,
    FieldStatus,
    draft_manifest,
    extract_document,
    extract_package,
)
from ceqa_preflight.ai.text import DocumentText, PageText
from ceqa_preflight.models import FilingType

_TEXT = (
    "NOTICE OF EXEMPTION\n\nTO: Office of Planning and Research\n"
    "FROM: Kern High School District\n"
    "PROJECT TITLE & NO: Bakersfield High School Auditorium Re-roofing\n"
    "COUNTY: Kern\nPROJECT LOCATION - CITY: Bakersfield\n"
    "EXEMPT STATUS: Categorical Exemption. State type and section number: "
    "Existing Facilities CEQA 15301\n"
    "LEAD AGENCY/CONTACT PERSON: Randall Rowles, Director of Facilities\n"
)


def _document(text: str = _TEXT, *, path: str = "NOE.pdf", has_text: bool = True) -> DocumentText:
    return DocumentText(
        path=path,
        readable=True,
        page_count=1,
        pages=[PageText(page=1, text=text)],
        pages_read=1,
        has_text_layer=has_text,
    )


def _payload(kind: dict[str, Any] | None = None, **fields: dict[str, Any] | None) -> str:
    body = {
        "document_kind": kind or {"value": "noe_form", "quote": "NOTICE OF EXEMPTION", "page": 1},
        "fields": {name: fields.get(name) for name in FIELD_NAMES},
    }
    return json.dumps(body)


def test_verified_values_are_found_and_quotes_are_located_on_their_page() -> None:
    client = ScriptedClient(
        [
            _payload(
                project_title={
                    "value": "Bakersfield High School Auditorium Re-roofing",
                    "quote": "PROJECT  TITLE & NO: Bakersfield High School Auditorium Re-roofing",
                    "page": 7,  # wrong page; the verifier locates the quote itself
                },
                county={"value": "Kern", "quote": "COUNTY: Kern", "page": 1},
                exemption_status={
                    "value": "Categorical Exemption",
                    "quote": "EXEMPT STATUS: Categorical Exemption",
                    "page": 1,
                },
            )
        ]
    )

    result = extract_document(client, _document())

    assert result.attempted and result.document_kind is DocumentKind.NOE_FORM
    assert result.document_kind_quote == "NOTICE OF EXEMPTION"
    title = result.field("project_title")
    assert title is not None and title.status is FieldStatus.FOUND and title.page == 1
    assert result.found("county") == "Kern"
    assert result.found("exemption_status") == "Categorical Exemption"
    assert result.found("sch_number") is None
    assert client.calls[0]["system"] == SYSTEM_PROMPT
    assert "[[page 1]]" in client.calls[0]["user"]


def test_values_without_verifying_quotes_are_withheld_never_shown_as_values() -> None:
    client = ScriptedClient(
        [
            _payload(
                lead_agency={"value": "Kern High School District"},  # no quote
                county={"value": "Kern", "quote": "COUNTY: Fresno"},  # quote not in text
                city_or_community={"value": "Bakersfield CA", "quote": "CITY: Bakersfield"},
                exemption_status={"value": "Class 1", "quote": "Categorical Exemption"},
                sch_number={"value": "   ", "quote": "x"},  # blank value is unknown
            )
        ]
    )

    result = extract_document(client, _document())

    for name, note in {
        "lead_agency": "no quote",
        "county": "does not appear",
        "city_or_community": "not contained in its quote",
        "exemption_status": "not one of the allowed values",
    }.items():
        item = result.field(name)
        assert item is not None and item.status is FieldStatus.UNVERIFIED, name
        assert item.value is None and item.withheld_value is not None
        assert note in (item.note or "")
    sch = result.field("sch_number")
    assert sch is not None and sch.status is FieldStatus.UNKNOWN


def test_document_kind_needs_a_verifying_quote_except_for_negative_identification() -> None:
    assert (
        extract_document(
            ScriptedClient([_payload({"value": "noe_form", "quote": "NOT IN TEXT"})]),
            _document(),
        ).document_kind
        is DocumentKind.UNKNOWN
    )
    assert (
        extract_document(
            ScriptedClient([_payload({"value": "nod_form"})]), _document()
        ).document_kind
        is DocumentKind.UNKNOWN
    )
    assert (
        extract_document(
            ScriptedClient([_payload({"value": "banana", "quote": "NOTICE"})]), _document()
        ).document_kind
        is DocumentKind.UNKNOWN
    )
    negative = extract_document(
        ScriptedClient(
            [
                _payload(
                    {"value": "not_ceqa_notice"}, county={"value": "Kern", "quote": "COUNTY: Kern"}
                )
            ]
        ),
        _document(),
    )
    assert negative.document_kind is DocumentKind.NOT_CEQA_NOTICE
    assert all(item.status is FieldStatus.UNKNOWN for item in negative.fields)
    assert "not a CEQA notice" in (negative.field("county").note or "")  # type: ignore[union-attr]


def test_unreadable_and_image_only_documents_are_not_sent_to_the_model() -> None:
    client = ScriptedClient([])
    unreadable = DocumentText(path="bad.pdf", readable=False, note="encrypted")
    scanned = _document(has_text=False)

    first = extract_document(client, unreadable)
    second = extract_document(client, scanned)

    assert client.calls == []
    assert not first.attempted and "encrypted" in (first.reason_not_attempted or "")
    assert not second.attempted and "no text layer" in (second.reason_not_attempted or "")
    assert all(item.status is FieldStatus.UNKNOWN for item in second.fields)


def test_model_failures_and_bad_json_fail_closed() -> None:
    failed = extract_document(ScriptedClient([]), _document())
    assert failed.model_error and "no response left" in failed.model_error
    assert all(item.status is FieldStatus.UNKNOWN for item in failed.fields)

    garbage = extract_document(ScriptedClient(["not json"]), _document())
    assert garbage.model_error == "model output was not a JSON object"
    assert extract_document(ScriptedClient(["[1, 2]"]), _document()).model_error

    fenced = extract_document(ScriptedClient(["```json\n" + _payload() + "\n```"]), _document())
    assert fenced.model_error is None and fenced.document_kind is DocumentKind.NOE_FORM

    odd_shape = extract_document(ScriptedClient(['{"fields": 5, "document_kind": 3}']), _document())
    assert odd_shape.model_error is None
    assert all(item.status is FieldStatus.UNKNOWN for item in odd_shape.fields)


def test_draft_manifest_uses_only_verified_values() -> None:
    form = _payload(
        project_title={
            "value": "Bakersfield High School Auditorium Re-roofing",
            "quote": "PROJECT TITLE & NO: Bakersfield High School Auditorium Re-roofing",
        },
        lead_agency={
            "value": "Kern High School District",
            "quote": "FROM: Kern High School District",
        },
        county={"value": "Kern", "quote": "COUNTY: Kern"},
        contact_name={"value": "Randall Rowles", "quote": "CONTACT PERSON: Randall Rowles"},
        sch_number={"value": "2026080811", "quote": "SCH 2026080811"},  # not in text: withheld
    )
    other = _payload({"value": "other_ceqa_material", "quote": "Kern"})
    client = ScriptedClient([form, other])

    extraction = extract_package(
        client, FilingType.NOE, [_document(), _document(path="receipt.pdf")], commit="abc1234"
    )

    manifest = extraction.draft_manifest
    assert manifest is not None
    assert manifest.project.title == "Bakersfield High School Auditorium Re-roofing"
    assert manifest.project.lead_agency == "Kern High School District"
    assert manifest.project.county == "Kern"
    assert manifest.project.sch_number is None
    assert [entry.primary for entry in manifest.documents] == [True, False]
    assert manifest.documents[0].category == "Notice of Exemption"
    assert manifest.documents[1].category is None
    assert manifest.contacts[0].name == "Randall Rowles"
    assert manifest.contacts[0].authority == "Kern High School District"
    assert extraction.counts.found == 4 and extraction.counts.unverified == 1
    assert extraction.provenance.prompt_version == "extract-v1"
    assert extraction.provenance.commit == "abc1234"
    assert extraction.provenance.provider == "scripted"
    assert "not a finding" in extraction.label


def test_draft_manifest_marks_no_primary_when_the_form_is_ambiguous_or_absent() -> None:
    two_forms = extract_package(
        ScriptedClient([_payload(), _payload()]),
        FilingType.NOE,
        [_document(path="a.pdf"), _document(path="b.pdf")],
    )
    assert two_forms.draft_manifest is not None
    assert not any(entry.primary for entry in two_forms.draft_manifest.documents)
    assert two_forms.draft_manifest.project.title == "Replace with project title"

    wrong_type = extract_package(ScriptedClient([_payload()]), FilingType.NOD, [_document()])
    assert wrong_type.draft_manifest is not None
    assert wrong_type.draft_manifest.documents[0].primary is False

    titled_other = _payload(
        {"value": "other_ceqa_material", "quote": "Kern"},
        project_title={"value": "Re-roofing", "quote": "Auditorium Re-roofing"},
    )
    fallback = extract_package(ScriptedClient([titled_other]), FilingType.NOE, [_document()])
    assert fallback.draft_manifest is not None
    assert fallback.draft_manifest.project.title == "Re-roofing"

    assert draft_manifest(FilingType.NOE, []) is None
    assert extract_package(ScriptedClient([]), FilingType.NOE, []).draft_manifest is None
