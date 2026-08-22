"""Quote-verified field extraction from filing-package text (ADR 0002, role 1).

The model is asked to copy, not to judge: for each field it returns a value and the
verbatim quote the value came from, or ``null`` when the text does not state it. This
module then verifies every quote against the document text and every value against its
quote. A value that does not survive verification is withheld and recorded as
``unverified``; a field the model left empty is ``unknown``. Only verified values reach the
draft manifest, and the draft manifest reaches the rule engine only after a person
confirms it.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from typing import Any, NamedTuple

from pydantic import Field

from ceqa_preflight.ai.client import ModelClient, ModelError
from ceqa_preflight.ai.corpus import normalize_for_match, normalize_whitespace
from ceqa_preflight.ai.provenance import AI_GENERATED_LABEL, Provenance, provenance_for
from ceqa_preflight.ai.text import DocumentText
from ceqa_preflight.models import (
    Contact,
    DocumentEntry,
    FilingType,
    PackageManifest,
    ProjectMetadata,
    StrictModel,
)

PROMPT_VERSION = "extract-v1"
MAX_OUTPUT_TOKENS = 4_000


class DocumentKind(StrEnum):
    """What a document is, as far as its own text says."""

    NOE_FORM = "noe_form"
    NOD_FORM = "nod_form"
    OTHER_CEQA_MATERIAL = "other_ceqa_material"
    NOT_CEQA_NOTICE = "not_ceqa_notice"
    UNKNOWN = "unknown"


class FieldStatus(StrEnum):
    FOUND = "found"  # value verified against a verbatim quote from the document
    UNKNOWN = "unknown"  # the document text does not state it, or the model said so
    UNVERIFIED = "unverified"  # the model proposed a value whose quote did not verify


class FieldSpec(NamedTuple):
    name: str
    description: str
    allowed: tuple[str, ...] | None = None


FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("project_title", "the project title as written on the notice"),
    FieldSpec("lead_agency", "the lead or public agency filing the notice"),
    FieldSpec("sch_number", "the State Clearinghouse (SCH) number, if printed"),
    FieldSpec("county", "the county of the project location"),
    FieldSpec("city_or_community", "the city or community of the project location"),
    FieldSpec("project_location", "the specific project location (address or cross streets)"),
    FieldSpec("project_applicant", "the applicant or party carrying out the project"),
    FieldSpec("contact_name", "the agency contact person's name"),
    FieldSpec(
        "exemption_status",
        "the exemption status checked on a Notice of Exemption",
        (
            "Ministerial",
            "Declared Emergency",
            "Emergency Project",
            "Categorical Exemption",
            "Statutory Exemption",
            "Common Sense Exemption",
            "Other",
        ),
    ),
    FieldSpec("exemption_citation", "the exemption type, class, section, or code number cited"),
    FieldSpec(
        "nod_environmental_document",
        "the environmental document a Notice of Determination reports",
        ("EIR", "Negative Declaration", "Mitigated Negative Declaration", "Other"),
    ),
    FieldSpec("nod_approval_date", "the project approval date on a Notice of Determination"),
    FieldSpec("signature_date", "the date next to the signature"),
)
FIELD_NAMES = tuple(spec.name for spec in FIELDS)
_FIELD_BY_NAME = {spec.name: spec for spec in FIELDS}

_KIND_DESCRIPTIONS = {
    DocumentKind.NOE_FORM: "a Notice of Exemption form",
    DocumentKind.NOD_FORM: "a Notice of Determination form",
    DocumentKind.OTHER_CEQA_MATERIAL: (
        "other CEQA filing material (findings, a fee receipt, a map, an exhibit, a resolution)"
    ),
    DocumentKind.NOT_CEQA_NOTICE: "not a CEQA notice or CEQA filing material at all",
    DocumentKind.UNKNOWN: "cannot be told from the text",
}

SYSTEM_PROMPT = (
    "You read the text of one PDF from a California CEQA filing package and copy out facts "
    "the text states. You are a transcription aid, not a reviewer.\n\n"
    "Rules:\n"
    "1. Every value you return must be copied verbatim from the text and must be accompanied "
    "by the exact verbatim quote (a contiguous span of the text, 3 to 300 characters) that "
    "contains it, plus the page number from the [[page N]] markers.\n"
    "2. If the text does not state a field, return null for that field. Never infer, "
    "normalize, translate, complete, or guess. Do not use outside knowledge.\n"
    "3. Never assess whether anything is correct, complete, valid, sufficient, or compliant. "
    "You never decide anything about the filing.\n"
    "4. Output a single JSON object and nothing else.\n\n"
    "Output shape:\n"
    '{"document_kind": {"value": <one of '
    + ", ".join(f'"{k.value}"' for k in DocumentKind)
    + '>, "quote": <verbatim quote or null>, "page": <int or null>},\n'
    ' "fields": {<field name>: {"value": <string or null>, "quote": <verbatim quote or null>, '
    '"page": <int or null>}, ...}}\n\n'
    "document_kind meanings:\n"
    + "\n".join(f"- {kind.value}: {text}" for kind, text in _KIND_DESCRIPTIONS.items())
    + "\n\nFields (include every one; use null when the text does not state it):\n"
    + "\n".join(
        f"- {spec.name}: {spec.description}"
        + (f" (value must be one of: {', '.join(spec.allowed)})" if spec.allowed else "")
        for spec in FIELDS
    )
)


class ExtractedField(StrictModel):
    """One field, with its status and the evidence that earned it."""

    name: str = Field(min_length=1)
    status: FieldStatus
    value: str | None = None
    quote: str | None = None
    page: int | None = Field(default=None, ge=1)
    withheld_value: str | None = None
    note: str | None = None


class DocumentExtraction(StrictModel):
    """Everything extracted from one document, and everything that could not be."""

    path: str = Field(min_length=1)
    attempted: bool
    reason_not_attempted: str | None = None
    document_kind: DocumentKind = DocumentKind.UNKNOWN
    document_kind_quote: str | None = None
    document_kind_page: int | None = Field(default=None, ge=1)
    pages_read: int = 0
    page_count: int | None = None
    truncated: bool = False
    fields: list[ExtractedField] = Field(default_factory=list)
    model_error: str | None = None

    def field(self, name: str) -> ExtractedField | None:
        return next((item for item in self.fields if item.name == name), None)

    def found(self, name: str) -> str | None:
        item = self.field(name)
        return item.value if item is not None and item.status is FieldStatus.FOUND else None


class ExtractionCounts(StrictModel):
    found: int = 0
    unknown: int = 0
    unverified: int = 0


class PackageExtraction(StrictModel):
    """The draft a person reviews before any rule runs on it."""

    extraction_schema_version: str = "1.0"
    label: str = AI_GENERATED_LABEL
    filing_type: FilingType
    documents: list[DocumentExtraction] = Field(default_factory=list)
    counts: ExtractionCounts = Field(default_factory=ExtractionCounts)
    draft_manifest: PackageManifest | None = None
    provenance: Provenance


class _Proposal(NamedTuple):
    value: str | None
    quote: str | None
    page: int | None


def _proposal(raw: Any) -> _Proposal:
    if not isinstance(raw, dict):
        return _Proposal(None, None, None)
    value = raw.get("value")
    quote = raw.get("quote")
    page = raw.get("page")
    return _Proposal(
        value if isinstance(value, str) and value.strip() else None,
        quote if isinstance(quote, str) and quote.strip() else None,
        page if isinstance(page, int) and page >= 1 else None,
    )


def _locate_quote(document: DocumentText, quote: str) -> int | None:
    """Return the first page whose text contains the quote, or ``None``."""

    needle = normalize_for_match(quote)
    if len(needle) < 3:
        return None
    for page in document.pages:
        if needle in normalize_for_match(page.text):
            return page.page
    return None


def _parse_model_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", candidate, re.S)
    if fenced:
        candidate = fenced.group(1)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ModelError("model output was not a JSON object") from error
    if not isinstance(parsed, dict):
        raise ModelError("model output was not a JSON object")
    return parsed


def _verify_field(spec: FieldSpec, proposal: _Proposal, document: DocumentText) -> ExtractedField:
    if proposal.value is None:
        return ExtractedField(name=spec.name, status=FieldStatus.UNKNOWN)
    if proposal.quote is None:
        return ExtractedField(
            name=spec.name,
            status=FieldStatus.UNVERIFIED,
            withheld_value=proposal.value,
            note="no quote was given for this value",
        )
    page = _locate_quote(document, proposal.quote)
    if page is None:
        return ExtractedField(
            name=spec.name,
            status=FieldStatus.UNVERIFIED,
            withheld_value=proposal.value,
            note="the quote does not appear in the document text",
        )
    if spec.allowed is not None:
        if proposal.value not in spec.allowed:
            return ExtractedField(
                name=spec.name,
                status=FieldStatus.UNVERIFIED,
                withheld_value=proposal.value,
                note="the value is not one of the allowed values",
            )
    elif normalize_for_match(proposal.value) not in normalize_for_match(proposal.quote):
        return ExtractedField(
            name=spec.name,
            status=FieldStatus.UNVERIFIED,
            withheld_value=proposal.value,
            note="the value is not contained in its quote",
        )
    return ExtractedField(
        name=spec.name,
        status=FieldStatus.FOUND,
        value=proposal.value,
        quote=normalize_whitespace(proposal.quote),
        page=page,
    )


def _verify_kind(
    proposal: _Proposal, document: DocumentText
) -> tuple[DocumentKind, str | None, int | None]:
    if proposal.value is None or proposal.value not in set(DocumentKind):
        return DocumentKind.UNKNOWN, None, None
    kind = DocumentKind(proposal.value)
    if kind in {DocumentKind.NOT_CEQA_NOTICE, DocumentKind.UNKNOWN}:
        # A negative or absent identification cannot be quoted; it carries no quote.
        return kind, None, None
    if proposal.quote is None:
        return DocumentKind.UNKNOWN, None, None
    page = _locate_quote(document, proposal.quote)
    if page is None:
        return DocumentKind.UNKNOWN, None, None
    return kind, normalize_whitespace(proposal.quote), page


def _not_attempted(document: DocumentText, reason: str) -> DocumentExtraction:
    return DocumentExtraction(
        path=document.path,
        attempted=False,
        reason_not_attempted=reason,
        pages_read=document.pages_read,
        page_count=document.page_count,
        fields=[ExtractedField(name=name, status=FieldStatus.UNKNOWN) for name in FIELD_NAMES],
    )


def extract_document(client: ModelClient, document: DocumentText) -> DocumentExtraction:
    """Ask the model for fields from one document's text and verify every one."""

    if not document.readable:
        return _not_attempted(document, f"the PDF could not be read ({document.note})")
    if not document.has_text_layer:
        return _not_attempted(
            document,
            "the PDF has no text layer (scanned image only); OCR is out of scope, so no "
            "field was extracted",
        )
    base = DocumentExtraction(
        path=document.path,
        attempted=True,
        pages_read=document.pages_read,
        page_count=document.page_count,
        truncated=document.truncated_pages,
    )
    try:
        response = client.complete(
            system=SYSTEM_PROMPT, user=document.as_prompt_text(), max_tokens=MAX_OUTPUT_TOKENS
        )
        payload = _parse_model_json(response.text)
    except ModelError as error:
        return base.model_copy(
            update={
                "model_error": str(error),
                "fields": [
                    ExtractedField(name=name, status=FieldStatus.UNKNOWN) for name in FIELD_NAMES
                ],
            }
        )
    kind, kind_quote, kind_page = _verify_kind(_proposal(payload.get("document_kind")), document)
    raw_fields = payload.get("fields")
    raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
    fields = [
        _verify_field(_FIELD_BY_NAME[name], _proposal(raw_fields.get(name)), document)
        for name in FIELD_NAMES
    ]
    if kind is DocumentKind.NOT_CEQA_NOTICE:
        # Nothing a non-CEQA document says is a filing fact.
        fields = [
            ExtractedField(
                name=item.name,
                status=FieldStatus.UNKNOWN,
                note="not extracted: the document is not a CEQA notice",
            )
            for item in fields
        ]
    return base.model_copy(
        update={
            "document_kind": kind,
            "document_kind_quote": kind_quote,
            "document_kind_page": kind_page,
            "fields": fields,
        }
    )


_FORM_KIND = {FilingType.NOE: DocumentKind.NOE_FORM, FilingType.NOD: DocumentKind.NOD_FORM}
_CATEGORY = {
    DocumentKind.NOE_FORM: "Notice of Exemption",
    DocumentKind.NOD_FORM: "Notice of Determination",
}


def draft_manifest(
    filing_type: FilingType, documents: list[DocumentExtraction]
) -> PackageManifest | None:
    """Assemble a draft manifest from verified values only.

    The primary form is marked only when exactly one document identified itself as the
    requested form. Project metadata comes from that form; if there is none, from the
    first document that states a title. A package with no PDF yields no draft.
    """

    if not documents:
        return None
    wanted = _FORM_KIND[filing_type]
    forms = [item for item in documents if item.document_kind is wanted]
    primary = forms[0].path if len(forms) == 1 else None
    entries = [
        DocumentEntry(
            path=item.path,
            category=_CATEGORY.get(item.document_kind),
            primary=item.path == primary,
        )
        for item in documents
    ]
    source = (
        forms[0]
        if len(forms) == 1
        else next((item for item in documents if item.found("project_title")), None)
    )
    project = ProjectMetadata(
        title=(source.found("project_title") if source else None) or "Replace with project title",
        sch_number=source.found("sch_number") if source else None,
        lead_agency=source.found("lead_agency") if source else None,
        county=source.found("county") if source else None,
        city_or_community=source.found("city_or_community") if source else None,
    )
    contacts: list[Contact] = []
    contact_name = source.found("contact_name") if source else None
    if contact_name:
        contacts.append(
            Contact(name=contact_name, authority=project.lead_agency, role="agency contact")
        )
    return PackageManifest(
        filing_type=filing_type, project=project, contacts=contacts, documents=entries
    )


def _count(documents: list[DocumentExtraction]) -> ExtractionCounts:
    counts = ExtractionCounts()
    for document in documents:
        for item in document.fields:
            if item.status is FieldStatus.FOUND:
                counts.found += 1
            elif item.status is FieldStatus.UNVERIFIED:
                counts.unverified += 1
            else:
                counts.unknown += 1
    return counts


def extract_package(
    client: ModelClient,
    filing_type: FilingType,
    texts: list[DocumentText],
    *,
    commit: str | None = None,
) -> PackageExtraction:
    """Extract every document and assemble the reviewable draft."""

    documents = [extract_document(client, text) for text in texts]
    return PackageExtraction(
        filing_type=filing_type,
        documents=documents,
        counts=_count(documents),
        draft_manifest=draft_manifest(filing_type, documents),
        provenance=provenance_for(client, PROMPT_VERSION, commit=commit),
    )
