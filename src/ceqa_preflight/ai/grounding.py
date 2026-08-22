"""Grounded generation: the model narrates, the corpus is the evidence, a verifier decides.

Every substantive sentence a model produces here must cite one or more corpus passages by
identifier and quote each verbatim. ``verify_claims`` checks every citation against the
passages the model was actually shown, checks every quote against the corpus text, and
checks every sentence for determination language. A claim that fails any check is withheld
and counted. Nothing reaches a reader that did not pass.
"""

from __future__ import annotations

import json
import re
from typing import Any

from pydantic import Field

from ceqa_preflight.ai.client import ModelClient, ModelError
from ceqa_preflight.ai.corpus import Corpus, Passage, normalize_for_match
from ceqa_preflight.ai.guard import determination_language
from ceqa_preflight.models import SourceKind, StrictModel
from ceqa_preflight.rule_catalog import RuleDefinition

# The LCI document-submission page is retrieved for every filing-specific rule, since it
# names the NOD and NOE attachments, even though no rule cites it directly.
_FILING_CONTEXT_DOCUMENT = "lci-sch-document-submission"


class Citation(StrictModel):
    passage_id: str = Field(min_length=1)
    quote: str = Field(min_length=1)
    verified: bool = False


class Claim(StrictModel):
    text: str = Field(min_length=1)
    citations: list[Citation] = Field(default_factory=list)


class WithheldClaim(StrictModel):
    """A claim that did not pass verification, kept for the count and the audit trail."""

    reason: str = Field(min_length=1)
    citation_count: int = Field(ge=0)


class SourceSummary(StrictModel):
    """What a reader needs to find the passage a claim quotes."""

    passage_id: str
    title: str
    url: str
    kind: SourceKind
    heading: str | None = None


def passages_for_rule(
    corpus: Corpus, rule: RuleDefinition, query: str, *, limit: int = 6
) -> list[Passage]:
    """Retrieve passages from the documents a rule cites, ranked against ``query``."""

    document = corpus.document_for_url(rule.source.url)
    document_ids = [] if document is None else [document.id]
    if len(rule.filing_types) == 1 and any(
        item.id == _FILING_CONTEXT_DOCUMENT for item in corpus.documents
    ):
        document_ids.append(_FILING_CONTEXT_DOCUMENT)
    return corpus.retrieve(document_ids, query, limit=limit) if document_ids else []


def render_passages(passages: list[Passage]) -> str:
    """Render passages for a prompt with their identifiers, so citations can name them."""

    blocks = []
    for passage in passages:
        heading = f" ({passage.heading})" if passage.heading else ""
        blocks.append(f"[{passage.id}]{heading}\n{passage.text}")
    return "\n\n".join(blocks)


def parse_claims(text: str) -> list[Claim]:
    """Parse the model's JSON claims strictly; anything unparseable is a model error."""

    candidate = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", candidate, re.S)
    if fenced:
        candidate = fenced.group(1)
    try:
        parsed: Any = json.loads(candidate)
    except json.JSONDecodeError as error:
        raise ModelError("model output was not a JSON object") from error
    if not isinstance(parsed, dict) or not isinstance(parsed.get("claims"), list):
        raise ModelError("model output did not contain a claims list")
    claims: list[Claim] = []
    for raw in parsed["claims"]:
        if not isinstance(raw, dict) or not isinstance(raw.get("text"), str):
            continue
        text_value = raw["text"].strip()
        if not text_value:
            continue
        citations = [
            Citation(passage_id=str(item["passage_id"]), quote=str(item["quote"]))
            for item in raw.get("citations") or []
            if isinstance(item, dict) and item.get("passage_id") and item.get("quote")
        ]
        claims.append(Claim(text=text_value, citations=citations))
    return claims


def quote_in(passage: Passage, quote: str) -> bool:
    """Return whether ``quote`` appears verbatim (modulo whitespace) in the passage."""

    needle = normalize_for_match(quote)
    return bool(needle) and needle in normalize_for_match(passage.text)


def verify_claims(
    shown: list[Passage], claims: list[Claim]
) -> tuple[list[Claim], list[WithheldClaim]]:
    """Keep only claims whose every citation verifies and whose text makes no determination.

    A citation verifies only against a passage the model was shown: the quote must appear
    verbatim in that passage. Shown passages come from the verified corpus (or, for
    questions, from the report itself), so this is also a check against the corpus.
    """

    by_id = {passage.id: passage for passage in shown}
    verified: list[Claim] = []
    withheld: list[WithheldClaim] = []
    for claim in claims:
        phrase = determination_language(claim.text)
        if phrase is not None:
            withheld.append(
                WithheldClaim(
                    reason=f"determination language: {phrase!r}",
                    citation_count=len(claim.citations),
                )
            )
            continue
        if not claim.citations:
            withheld.append(WithheldClaim(reason="no citation", citation_count=0))
            continue
        checked = [
            citation.model_copy(
                update={
                    "verified": citation.passage_id in by_id
                    and quote_in(by_id[citation.passage_id], citation.quote)
                }
            )
            for citation in claim.citations
        ]
        if all(citation.verified for citation in checked):
            verified.append(claim.model_copy(update={"citations": checked}))
        else:
            failed = sum(not citation.verified for citation in checked)
            withheld.append(
                WithheldClaim(
                    reason=f"{failed} citation(s) did not verify against the corpus",
                    citation_count=len(checked),
                )
            )
    return verified, withheld


def sources_for(corpus: Corpus, claims: list[Claim]) -> list[SourceSummary]:
    """List each cited passage once, in first-cited order, with its document's provenance."""

    seen: dict[str, SourceSummary] = {}
    for claim in claims:
        for citation in claim.citations:
            if citation.passage_id in seen:
                continue
            passage = corpus.passage(citation.passage_id)
            if passage is None:
                continue
            document = corpus.document(citation.passage_id.split("#", 1)[0])
            seen[citation.passage_id] = SourceSummary(
                passage_id=citation.passage_id,
                title=document.title,
                url=document.url,
                kind=document.kind,
                heading=passage.heading,
            )
    return list(seen.values())


def generate_grounded(
    client: ModelClient,
    corpus: Corpus,
    *,
    system: str,
    user: str,
    shown: list[Passage],
    max_tokens: int,
) -> tuple[list[Claim], list[WithheldClaim], str | None]:
    """Run one grounded generation and return (verified, withheld, model_error)."""

    try:
        response = client.complete(system=system, user=user, max_tokens=max_tokens)
        claims = parse_claims(response.text)
    except ModelError as error:
        return [], [], str(error)
    verified, withheld = verify_claims(shown, claims)
    return verified, withheld, None
