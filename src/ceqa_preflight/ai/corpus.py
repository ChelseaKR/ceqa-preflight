"""The committed corpus of official source text, and verification against it.

``corpus/`` holds the plain text of every source the rule catalog cites, split into
addressable passages, with the hash of the bytes that were fetched, the hash of the
extracted text, and the retrieval time. It is the only text an explanation may quote.
Loading verifies the text files against the manifest so a silently edited corpus cannot
pass as the official source.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

from pydantic import Field, ValidationError

from ceqa_preflight.models import SourceKind, StrictModel

MANIFEST_NAME = "manifest.json"
PASSAGES_NAME = "passages.json"
TEXT_DIR_NAME = "text"

_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z0-9]+")


class CorpusError(ValueError):
    """Raised when the corpus is missing, malformed, or does not match its manifest."""


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace so wrapped lines compare equal to their unwrapped form."""

    return _WHITESPACE.sub(" ", text).strip()


class Passage(StrictModel):
    """One addressable unit of source text."""

    id: str = Field(min_length=1)
    heading: str | None = None
    text: str = Field(min_length=1)


class CorpusDocument(StrictModel):
    """Provenance for one source document in the corpus."""

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    kind: SourceKind
    retrieved_at: datetime
    content_type: str = Field(min_length=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    text_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    passage_count: int = Field(ge=0)
    cited_by: list[str] = Field(default_factory=list)


class CorpusManifest(StrictModel):
    """The committed list of corpus documents."""

    manifest_version: str = "1.0"
    built_at: datetime
    documents: list[CorpusDocument] = Field(default_factory=list)


def default_corpus_dir() -> Path:
    """Return the corpus directory: packaged inside the wheel, or ``corpus/`` in a checkout."""

    package_dir = Path(__file__).resolve().parent.parent
    packaged = package_dir / "corpus"
    if (packaged / MANIFEST_NAME).is_file():
        return packaged
    return package_dir.parent.parent / "corpus"


class Corpus:
    """A verified, in-memory view of the committed corpus."""

    def __init__(self, manifest: CorpusManifest, passages: dict[str, list[Passage]]) -> None:
        self.manifest = manifest
        self._documents = {document.id: document for document in manifest.documents}
        self._passages = passages
        self._by_id = {passage.id: passage for entries in passages.values() for passage in entries}
        self._by_url = {document.url: document.id for document in manifest.documents}

    @classmethod
    def load(cls, corpus_dir: Path | None = None) -> Corpus:
        """Load and verify the corpus, refusing any text that does not match its manifest."""

        root = corpus_dir or default_corpus_dir()
        manifest = _load_manifest(root / MANIFEST_NAME)
        passages = _load_passages(root / PASSAGES_NAME)
        for document in manifest.documents:
            text_path = root / TEXT_DIR_NAME / f"{document.id}.txt"
            try:
                text = text_path.read_text(encoding="utf-8")
            except OSError as error:
                raise CorpusError(f"corpus text is missing: {text_path.name}") from error
            if hashlib.sha256(text.encode("utf-8")).hexdigest() != document.text_sha256:
                raise CorpusError(f"corpus text does not match its manifest hash: {document.id}")
            entries = passages.get(document.id, [])
            if len(entries) != document.passage_count:
                raise CorpusError(f"corpus passage count does not match manifest: {document.id}")
            for passage in entries:
                if not passage.id.startswith(f"{document.id}#"):
                    raise CorpusError(f"passage {passage.id} is filed under {document.id}")
                if normalize_whitespace(passage.text) not in normalize_whitespace(text):
                    raise CorpusError(f"passage text is not in its document text: {passage.id}")
        return cls(manifest, passages)

    @property
    def documents(self) -> list[CorpusDocument]:
        return list(self.manifest.documents)

    def document(self, document_id: str) -> CorpusDocument:
        try:
            return self._documents[document_id]
        except KeyError as error:
            raise CorpusError(f"unknown corpus document: {document_id}") from error

    def document_for_url(self, url: str) -> CorpusDocument | None:
        """Return the corpus document for a citation URL, or ``None`` when it is not held."""

        document_id = self._by_url.get(url)
        return None if document_id is None else self._documents[document_id]

    def passages(self, document_id: str) -> list[Passage]:
        self.document(document_id)
        return list(self._passages.get(document_id, []))

    def passage(self, passage_id: str) -> Passage | None:
        return self._by_id.get(passage_id)

    def quote_verifies(self, passage_id: str, quote: str) -> bool:
        """Return whether ``quote`` appears verbatim (modulo whitespace) in the passage."""

        passage = self.passage(passage_id)
        if passage is None:
            return False
        needle = normalize_whitespace(quote)
        return bool(needle) and needle in normalize_whitespace(passage.text)

    def retrieve(self, document_ids: list[str], query: str, *, limit: int = 6) -> list[Passage]:
        """Rank passages from the given documents by lexical overlap with ``query``.

        Retrieval is scoped by the caller (normally to the documents a rule cites) and
        ranked by shared tokens, so it is inspectable and needs no additional provider.
        Ties keep document order so the result is deterministic.
        """

        query_tokens = set(_TOKEN.findall(query.casefold()))
        scored: list[tuple[int, int, Passage]] = []
        position = 0
        for document_id in document_ids:
            for passage in self.passages(document_id):
                tokens = set(_TOKEN.findall(passage.text.casefold()))
                if passage.heading:
                    tokens |= set(_TOKEN.findall(passage.heading.casefold()))
                scored.append((len(query_tokens & tokens), position, passage))
                position += 1
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [passage for _, _, passage in scored[:limit]]


def _load_manifest(path: Path) -> CorpusManifest:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return CorpusManifest.model_validate(raw)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise CorpusError(f"corpus manifest could not be loaded: {path}") from error


def _load_passages(path: Path) -> dict[str, list[Passage]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise CorpusError("corpus passages must be a mapping of document id to passages")
        return {
            str(document_id): [Passage.model_validate(item) for item in entries]
            for document_id, entries in raw.items()
        }
    except (OSError, json.JSONDecodeError, ValidationError, TypeError) as error:
        raise CorpusError(f"corpus passages could not be loaded: {path}") from error
