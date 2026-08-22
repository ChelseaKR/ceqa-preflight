"""Bounded, process-isolated text extraction for the opt-in AI layer.

The default ``check`` path counts characters per sampled page and discards the text. The
``ai extract`` command needs the text itself, so this module reads it the same way: in a
spawned worker with a hard wall-clock timeout, from a capped number of pages, into a capped
number of characters. A document with no text layer is reported as such and never sent to
a model; OCR remains out of scope.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

from pydantic import Field

from ceqa_preflight.limits import DEFAULT_PACKAGE_LIMITS, PackageLimits
from ceqa_preflight.models import StrictModel

# A page with fewer text-layer characters than this is treated as image-only, matching the
# inspector's searchable-page threshold.
MIN_TEXT_CHARACTERS_PER_PAGE = 25
DEFAULT_MAX_PAGES = 30
DEFAULT_MAX_CHARACTERS = 60_000


class PageText(StrictModel):
    """The text layer of one page, as extracted."""

    page: int = Field(ge=1)
    text: str


class DocumentText(StrictModel):
    """Bounded text of one PDF, with every reason it may be incomplete stated."""

    path: str = Field(min_length=1)
    readable: bool
    page_count: int | None = None
    pages: list[PageText] = Field(default_factory=list)
    pages_read: int = 0
    truncated_pages: bool = False
    truncated_characters: bool = False
    timed_out: bool = False
    has_text_layer: bool = False
    note: str | None = None

    @property
    def character_count(self) -> int:
        return sum(len(page.text) for page in self.pages)

    def as_prompt_text(self) -> str:
        """Render the pages with explicit page markers so quotes can name a page."""

        return "\n".join(f"[[page {page.page}]]\n{page.text.strip()}" for page in self.pages)


def _extract_in_worker(
    path: Path, limits: PackageLimits, max_pages: int, max_characters: int
) -> DocumentText:
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LTTextContainer
    from pypdf import PdfReader

    relative = path.name
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            return DocumentText(path=relative, readable=False, note="encrypted")
        page_count = len(reader.pages)
    except Exception:
        return DocumentText(path=relative, readable=False, note="could not be parsed")
    if page_count > limits.max_pdf_pages:
        return DocumentText(
            path=relative,
            readable=False,
            page_count=page_count,
            note=f"exceeds the {limits.max_pdf_pages} page inspection limit",
        )
    pages_to_read = min(page_count, max_pages)
    pages: list[PageText] = []
    total = 0
    truncated_characters = False
    try:
        layouts = extract_pages(str(path), page_numbers=list(range(pages_to_read)))
        for index, layout in enumerate(layouts, start=1):
            text = "\n".join(
                element.get_text() for element in layout if isinstance(element, LTTextContainer)
            )
            remaining = max_characters - total
            if len(text) > remaining:
                text = text[:remaining]
                truncated_characters = True
            total += len(text)
            pages.append(PageText(page=index, text=text))
            if truncated_characters:
                break
    except Exception:
        return DocumentText(
            path=relative,
            readable=False,
            page_count=page_count,
            note="text could not be extracted",
        )
    has_text_layer = any(
        len("".join(page.text.split())) >= MIN_TEXT_CHARACTERS_PER_PAGE for page in pages
    )
    return DocumentText(
        path=relative,
        readable=True,
        page_count=page_count,
        pages=pages,
        pages_read=len(pages),
        truncated_pages=pages_to_read < page_count or truncated_characters,
        truncated_characters=truncated_characters,
        has_text_layer=has_text_layer,
    )


def _worker_main(
    connection: Any, path_string: str, limits: PackageLimits, max_pages: int, max_characters: int
) -> None:
    try:
        result = _extract_in_worker(Path(path_string), limits, max_pages, max_characters)
        connection.send({"text": result.model_dump(mode="json")})
    except BaseException:
        connection.send({"error": "text extraction worker failed"})
    finally:
        connection.close()


def extract_document_text(
    path: Path,
    *,
    limits: PackageLimits = DEFAULT_PACKAGE_LIMITS,
    max_pages: int = DEFAULT_MAX_PAGES,
    max_characters: int = DEFAULT_MAX_CHARACTERS,
) -> DocumentText:
    """Extract bounded text from one local PDF in a spawned process with a timeout."""

    resolved = path.resolve(strict=False)
    context = multiprocessing.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_worker_main,
        args=(child, str(resolved), limits, max_pages, max_characters),
        daemon=True,
    )
    process.start()
    child.close()
    try:
        process.join(limits.per_file_timeout_seconds)
        if process.is_alive():
            process.terminate()
            process.join()
            return DocumentText(
                path=path.name, readable=False, timed_out=True, note="extraction timed out"
            )
        payload = parent.recv() if parent.poll() else {"error": "no result"}
    finally:
        parent.close()
        if process.is_alive():
            process.terminate()
            process.join()
    if "text" in payload:
        return DocumentText.model_validate(payload["text"])
    return DocumentText(path=path.name, readable=False, note="text extraction worker failed")
