"""Synthetic, local-only tests for bounded PDF inspection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    TextStringObject,
)

from ceqa_preflight.limits import PackageLimits
from ceqa_preflight.models import Confidence
from ceqa_preflight.pdf_inspector import (
    PdfInspection,
    _contains_action,
    _inspect_pdf_in_worker,
    _mapping,
    _name_tree_item_count,
    _worker_main,
    inspect_pdf,
    select_sample_pages,
)


def _write_pdf(
    path: Path,
    *,
    text: str | None = None,
    page_count: int = 1,
    encrypted: bool = False,
    form_field: bool = False,
    tagged: bool = False,
    javascript: bool = False,
    attachment: bool = False,
) -> Path:
    writer = PdfWriter()
    pages = [writer.add_blank_page(width=612, height=792) for _ in range(page_count)]
    if text:
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode())
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        pages[0][NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        pages[0][NameObject("/Contents")] = writer._add_object(stream)
    if form_field:
        field = DictionaryObject(
            {
                NameObject("/FT"): NameObject("/Tx"),
                NameObject("/T"): TextStringObject("project_title"),
                NameObject("/Subtype"): NameObject("/Widget"),
                NameObject("/Rect"): ArrayObject(
                    [NumberObject(0), NumberObject(0), NumberObject(10), NumberObject(10)]
                ),
                NameObject("/P"): pages[0].indirect_reference,
            }
        )
        field_ref = writer._add_object(field)
        pages[0][NameObject("/Annots")] = ArrayObject([field_ref])
        writer._root_object[NameObject("/AcroForm")] = DictionaryObject(
            {NameObject("/Fields"): ArrayObject([field_ref])}
        )
    if tagged:
        writer._root_object[NameObject("/StructTreeRoot")] = writer._add_object(DictionaryObject())
    if javascript:
        writer.add_js("app.alert('synthetic')")
    if attachment:
        writer.add_attachment("notes.txt", b"synthetic attachment")
    if encrypted:
        writer.encrypt("not-a-real-password")
    with path.open("wb") as output:
        writer.write(output)
    return path


@pytest.mark.parametrize(
    ("page_count", "expected"),
    [
        (0, []),
        (1, [1]),
        (20, list(range(1, 21))),
        (21, [1, 2, 4, 7, 10, 12, 15, 18, 20, 21]),
        (100, [1, 2, 15, 29, 43, 58, 72, 86, 99, 100]),
    ],
)
def test_select_sample_pages(page_count: int, expected: list[int]) -> None:
    assert select_sample_pages(page_count) == expected


def test_inspects_searchable_and_image_only_pdfs(tmp_path: Path) -> None:
    searchable = _inspect_pdf_in_worker(
        _write_pdf(tmp_path / "searchable.pdf", text="This project has searchable text."),
        PackageLimits(),
    )
    image_only = _inspect_pdf_in_worker(_write_pdf(tmp_path / "empty.pdf"), PackageLimits())

    assert searchable.readable is True
    assert searchable.text_coverage == 1.0
    assert searchable.extracted_characters[1] >= 25
    assert searchable.extraction_confidence is Confidence.HIGH
    assert image_only.readable is True
    assert image_only.text_coverage == 0.0


def test_inspects_mixed_pdf_and_respects_page_limit(tmp_path: Path) -> None:
    mixed = _write_pdf(tmp_path / "mixed.pdf", text="This is text on the first page.", page_count=2)
    result = _inspect_pdf_in_worker(mixed, PackageLimits())
    oversized = _inspect_pdf_in_worker(mixed, PackageLimits(max_pdf_pages=1))

    assert result.sampled_pages == [1, 2]
    assert result.text_coverage == 0.5
    assert oversized.readable is False
    assert oversized.page_count == 2
    assert "page inspection limit" in oversized.parser_warnings[0]


def test_encrypted_and_corrupt_pdfs_are_structured_results(tmp_path: Path) -> None:
    encrypted = _inspect_pdf_in_worker(
        _write_pdf(tmp_path / "encrypted.pdf", encrypted=True), PackageLimits()
    )
    corrupt_path = tmp_path / "corrupt.pdf"
    corrupt_path.write_bytes(b"not a pdf")
    corrupt = _inspect_pdf_in_worker(corrupt_path, PackageLimits())

    assert encrypted.encrypted is True
    assert encrypted.readable is False
    assert corrupt.readable is False
    assert corrupt.extraction_confidence is Confidence.LOW
    assert "could not be parsed" in corrupt.parser_warnings[0]


def test_detects_form_fields_structure_and_active_content(tmp_path: Path) -> None:
    document = _write_pdf(
        tmp_path / "signals.pdf",
        form_field=True,
        tagged=True,
        javascript=True,
        attachment=True,
    )
    result = _inspect_pdf_in_worker(document, PackageLimits())

    assert result.active_form_field_count == 1
    assert result.active_form_field_names == ["project_title"]
    assert result.structure_tree_present is True
    assert result.javascript_present is True
    assert result.embedded_file_count == 1


def test_inspect_pdf_uses_isolated_worker(tmp_path: Path) -> None:
    document = _write_pdf(tmp_path / "isolated.pdf", text="Isolated worker document text.")

    result = inspect_pdf(document, PackageLimits(per_file_timeout_seconds=10))

    assert result.readable is True
    assert result.text_coverage == 1.0


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
            assert duplex is False
            return Connection(), Connection()

        def Process(self, **kwargs: object) -> Process:
            return Process(**kwargs)

    monkeypatch.setattr(
        "ceqa_preflight.pdf_inspector.multiprocessing.get_context", lambda _: Context()
    )

    result = inspect_pdf(tmp_path / "slow.pdf", PackageLimits(per_file_timeout_seconds=0.01))

    assert result.timed_out is True
    assert result.readable is False


def test_rejects_nonpositive_timeout(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="per_file_timeout_seconds"):
        inspect_pdf(tmp_path / "document.pdf", PackageLimits(per_file_timeout_seconds=0))


def test_bounded_pdf_object_helpers_cover_indirect_and_name_trees() -> None:
    class Indirect:
        def get_object(self) -> dict[str, object]:
            return {"/S": "/Launch"}

    assert _mapping(Indirect()) == {"/S": "/Launch"}
    assert _mapping(object()) == {}
    assert _contains_action([{"/Nothing": "here"}, Indirect()], "/Launch")
    assert _contains_action({}, "/Launch", depth=13) is False
    assert (
        _name_tree_item_count({"/Names": ["one", 1], "/Kids": [{"/Names": ["two", 2, "three", 3]}]})
        == 3
    )
    assert _name_tree_item_count({}, depth=13) == 0


def test_parser_warnings_and_extraction_failures_stay_structured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Reader:
        is_encrypted = False

        def __init__(self, *_: object, **__: object) -> None:
            import warnings

            self.pages: list[dict[str, object]] = [{}]
            self.trailer: dict[str, dict[str, object]] = {"/Root": {}}
            warnings.warn("synthetic parser warning", UserWarning, stacklevel=1)

        def get_fields(self) -> dict[str, object]:
            raise RuntimeError("synthetic field failure")

    monkeypatch.setattr("ceqa_preflight.pdf_inspector.PdfReader", Reader)
    monkeypatch.setattr(
        "ceqa_preflight.pdf_inspector.extract_pages",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("synthetic text failure")),
    )

    result = _inspect_pdf_in_worker(tmp_path / "ignored.pdf", PackageLimits())

    assert result.readable is True
    assert result.extraction_confidence is Confidence.LOW
    assert len(result.parser_warnings) == 3
    assert result.extracted_characters == {}
    # The field count is 0 because the form dictionary could not be read, so the
    # inspection must say so rather than let a caller read the 0 as "no form fields".
    assert result.active_form_field_count == 0
    assert result.form_fields_readable is False


def test_page_count_failure_is_a_structured_result(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class Reader:
        is_encrypted = False

        def __init__(self, *_: object, **__: object) -> None:
            self.trailer: dict[str, dict[str, Any]] = {"/Root": {}}

        @property
        def pages(self) -> object:
            raise RuntimeError("synthetic page failure")

    monkeypatch.setattr("ceqa_preflight.pdf_inspector.PdfReader", Reader)

    result = _inspect_pdf_in_worker(tmp_path / "ignored.pdf", PackageLimits())

    assert result.readable is False
    assert "page count" in result.parser_warnings[0]


def test_worker_main_sends_success_or_generic_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []
            self.closed = False

        def send(self, value: dict[str, object]) -> None:
            self.sent.append(value)

        def close(self) -> None:
            self.closed = True

    success = Connection()
    monkeypatch.setattr(
        "ceqa_preflight.pdf_inspector._inspect_pdf_in_worker",
        lambda *_: PdfInspection(readable=True, extraction_confidence=Confidence.HIGH),
    )
    _worker_main(success, "/tmp/ignored.pdf", PackageLimits())

    assert success.closed is True
    assert success.sent == [
        {
            "inspection": {
                "readable": True,
                "encrypted": False,
                "page_count": None,
                "sampled_pages": [],
                "extracted_characters": {},
                "text_coverage": None,
                "active_form_field_count": 0,
                "active_form_field_names": [],
                "form_fields_readable": True,
                "structure_tree_present": None,
                "embedded_file_count": 0,
                "javascript_present": False,
                "launch_action_present": False,
                "parser_warnings": [],
                "extraction_confidence": "high",
                "timed_out": False,
            }
        }
    ]

    failure = Connection()
    monkeypatch.setattr(
        "ceqa_preflight.pdf_inspector._inspect_pdf_in_worker",
        lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic worker failure")),
    )
    _worker_main(failure, "/tmp/ignored.pdf", PackageLimits())

    assert failure.closed is True
    assert failure.sent == [{"error": "PDF inspection worker failed"}]
