"""Tests for bounded text extraction used by the opt-in AI layer."""

from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from ceqa_preflight.ai.text import (
    DocumentText,
    PageText,
    _extract_in_worker,
    _receive_text,
    extract_document_text,
)
from ceqa_preflight.limits import PackageLimits
from ceqa_preflight.synth import _pdf_bytes


def test_extracts_pages_with_markers_and_detects_a_text_layer(tmp_path: Path) -> None:
    path = tmp_path / "notice.pdf"
    path.write_bytes(_pdf_bytes(["NOTICE OF EXEMPTION Project Title: Culvert Repair", None]))

    text = extract_document_text(path)

    assert text.readable and text.has_text_layer
    assert text.page_count == 2 and text.pages_read == 2
    assert "Culvert Repair" in text.pages[0].text
    assert text.as_prompt_text().startswith("[[page 1]]")
    assert "[[page 2]]" in text.as_prompt_text()
    assert text.character_count > 0
    assert text.truncated_pages is False


def test_image_only_pdf_has_no_text_layer(tmp_path: Path) -> None:
    path = tmp_path / "scan.pdf"
    path.write_bytes(_pdf_bytes([None, None]))

    text = extract_document_text(path)

    assert text.readable is True
    assert text.has_text_layer is False


def test_encrypted_and_unparseable_pdfs_are_reported_not_read(tmp_path: Path) -> None:
    encrypted = tmp_path / "locked.pdf"
    encrypted.write_bytes(_pdf_bytes(["secret"], encrypted=True))
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot really a pdf")

    assert extract_document_text(encrypted).note == "encrypted"
    assert extract_document_text(broken).readable is False


def test_page_and_character_caps_are_enforced(tmp_path: Path) -> None:
    path = tmp_path / "long.pdf"
    path.write_bytes(_pdf_bytes(["alpha " * 40, "beta " * 40, "gamma " * 40]))

    by_pages = extract_document_text(path, max_pages=2)
    assert by_pages.pages_read == 2 and by_pages.truncated_pages is True

    by_chars = extract_document_text(path, max_characters=50)
    assert by_chars.truncated_characters is True
    assert by_chars.character_count <= 50


def test_page_limit_from_package_limits_is_respected(tmp_path: Path) -> None:
    path = tmp_path / "many.pdf"
    path.write_bytes(_pdf_bytes(["one", "two"]))

    text = _extract_in_worker(path, PackageLimits(max_pdf_pages=1), 30, 60_000)

    assert text.readable is False
    assert "page inspection limit" in (text.note or "")


def test_extraction_failure_inside_worker_is_reported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    path = tmp_path / "doc.pdf"
    path.write_bytes(_pdf_bytes(["text"]))

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError("pdfminer failed")

    monkeypatch.setattr("pdfminer.high_level.extract_pages", boom)

    text = _extract_in_worker(path, PackageLimits(), 30, 60_000)

    assert text.readable is False
    assert text.note == "text could not be extracted"


def test_timeout_terminates_worker(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Connection:
        def close(self) -> None:
            return None

        def poll(self) -> bool:
            return False

    class Process:
        def __init__(self, **_: object) -> None:
            self.terminated = False

        def start(self) -> None:
            return None

        def join(self, _: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return not self.terminated

        def terminate(self) -> None:
            self.terminated = True

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:
            return Connection(), Connection()

        def Process(self, **kwargs: object) -> Process:
            return Process(**kwargs)

    monkeypatch.setattr("ceqa_preflight.ai.text.multiprocessing.get_context", lambda _: Context())

    text = extract_document_text(
        tmp_path / "slow.pdf", limits=PackageLimits(per_file_timeout_seconds=0.01)
    )

    assert text.timed_out is True and text.readable is False


def test_worker_without_result_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """One dead worker costs one document, not the whole extraction.

    This test is why the defect survived. Its fixture used to declare
    ``def poll(self) -> bool: return False`` and assert the branch behind that guard --
    a state a real dead worker cannot produce, on any platform (see the poll test at the
    end of this module). So the unreachable branch had a passing test over it, the
    coverage report showed the line executed, and the guard read as covered while the
    path a killed worker actually takes had never been driven at all.

    The fixture now raises ``EOFError`` from ``recv()``, which is what CPython does on a
    pipe whose only writer has gone. ``ai/cli.py`` extracts every PDF in a package in one
    loop with no handler around it, so this is the difference between losing one
    document's text and ending the command with a traceback.
    """

    class Connection:
        def close(self) -> None:
            return None

        def recv(self) -> object:
            raise EOFError

    class Process:
        def __init__(self, **_: object) -> None:
            return None

        def start(self) -> None:
            return None

        def join(self, _: float | None = None) -> None:
            return None

        def is_alive(self) -> bool:
            return False

    class Context:
        def Pipe(self, *, duplex: bool) -> tuple[Connection, Connection]:
            return Connection(), Connection()

        def Process(self, **kwargs: object) -> Process:
            return Process(**kwargs)

    monkeypatch.setattr("ceqa_preflight.ai.text.multiprocessing.get_context", lambda _: Context())

    text = extract_document_text(tmp_path / "gone.pdf")

    assert text.readable is False
    assert text.note == "text extraction worker returned no result"


def test_worker_main_reports_internal_failures() -> None:
    sent: list[dict[str, object]] = []

    class Connection:
        def send(self, payload: dict[str, object]) -> None:
            sent.append(payload)

        def close(self) -> None:
            return None

    from ceqa_preflight.ai.text import _worker_main

    _worker_main(Connection(), "/nonexistent/dir/file.pdf", PackageLimits(), 30, 60_000)
    assert "text" in sent[0]  # an unreadable path is reported as a DocumentText, not a crash

    assert (
        DocumentText(
            path="x.pdf", readable=True, pages=[PageText(page=1, text="ab")]
        ).character_count
        == 2
    )


# --------------------------------------------------------------------------------------
#
# `extract_document_text` used to guard the read with
# `parent.recv() if parent.poll() else {"error": "no result"}`. That is the same defect
# `pdf_inspector` carried, and the fix for it (PR #115) reached one of this project's two
# readers of a spawned worker's pipe and not the other. These mirror
# `tests/test_pdf_inspector.py`'s, because the failure and the reasoning are the same.


def test_poll_could_not_have_guarded_this_read_either() -> None:
    """The premise the old guard rested on, measured rather than assumed.

    On POSIX a pipe whose only writer has gone is *readable*, so `poll()` returns `True`,
    control falls through to `recv()`, and `recv()` raises `EOFError`. On Windows
    `Connection._poll` raises `BrokenPipeError: [WinError 109]` out of
    `_winapi.PeekNamedPipe` at the guard line itself, before any read.

    What both platforms share is what the guard needed and never had: `poll()` never
    reports `False` for a worker that sent nothing, so it cannot distinguish "nothing was
    sent" from "something is waiting".
    """

    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        child.close()
        try:
            polled: object = parent.poll()
        except OSError as error:  # Windows: PeekNamedPipe raises instead of answering
            polled = error
        assert polled is True or isinstance(polled, OSError), (
            f"poll() returned {polled!r} at end-of-file, so the guard this replaced could "
            "have worked after all and the change needs rethinking"
        )
    finally:
        parent.close()


def test_a_worker_that_sent_nothing_is_reported_rather_than_raised() -> None:
    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        child.close()
        result = _receive_text(parent, Path("notice.pdf"))
    finally:
        parent.close()

    assert result.readable is False
    assert result.timed_out is False
    assert result.note == "text extraction worker returned no result"


def test_a_read_that_fails_at_the_pipe_layer_is_also_reported_rather_than_raised() -> None:
    """The catch is not `EOFError` alone, for the reason its sibling gives: the platforms
    disagree about how a dead pipe is spelled, and betting on one spelling is what produced
    the bug."""

    class BrokenConnection:
        def recv(self) -> object:
            raise BrokenPipeError(109, "The pipe has been ended")

    result = _receive_text(BrokenConnection(), Path("notice.pdf"))

    assert result.readable is False
    assert result.note == "text extraction worker returned no result"


def test_a_worker_error_payload_is_still_reported_as_a_failed_extraction() -> None:
    """The two no-answer states stay distinguishable: a worker that reported its own
    failure is not the same fact as one that never answered, and merging them would hide
    which of the two an operator is looking at."""

    parent, child = multiprocessing.get_context("spawn").Pipe(duplex=False)
    try:
        child.send({"error": "text extraction worker failed"})
        child.close()
        result = _receive_text(parent, Path("notice.pdf"))
    finally:
        parent.close()

    assert result.readable is False
    assert result.note == "text extraction worker failed"
