"""Tests for the `ai` command group. The model is always a scripted fake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ceqa_preflight.ai.client import ModelError, ScriptedClient
from ceqa_preflight.ai.extraction import FIELD_NAMES
from ceqa_preflight.cli import app
from ceqa_preflight.manifest import load_manifest
from ceqa_preflight.synth import _pdf_bytes

runner = CliRunner()

_TEXT = (
    "NOTICE OF EXEMPTION PROJECT TITLE: Culvert Repair COUNTY: Kern "
    "LEAD AGENCY: Kern County Public Works"
)


def _response(**fields: dict[str, str]) -> str:
    return json.dumps(
        {
            "document_kind": {"value": "noe_form", "quote": "NOTICE OF EXEMPTION", "page": 1},
            "fields": {name: fields.get(name) for name in FIELD_NAMES},
        }
    )


def _package(tmp_path: Path) -> Path:
    package = tmp_path / "package"
    package.mkdir()
    (package / "NOE_culvert.pdf").write_bytes(_pdf_bytes([_TEXT]))
    (package / "scan.pdf").write_bytes(_pdf_bytes([None]))
    (package / "notes.txt").write_text("not a pdf", encoding="utf-8")
    return package


@pytest.fixture
def scripted(monkeypatch: pytest.MonkeyPatch) -> ScriptedClient:
    client = ScriptedClient(
        [
            _response(
                project_title={"value": "Culvert Repair", "quote": "PROJECT TITLE: Culvert Repair"},
                county={"value": "Kern", "quote": "COUNTY: Kern"},
                lead_agency={"value": "Kern County", "quote": "COUNTY: Kern"},
            )
        ],
        model="fake-model",
    )
    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", lambda *a, **k: client)
    return client


def test_extract_renders_console_and_writes_a_reviewable_draft_manifest(
    tmp_path: Path, scripted: ScriptedClient
) -> None:
    package = _package(tmp_path)
    draft = tmp_path / "draft.yaml"

    result = runner.invoke(
        app,
        ["ai", "extract", str(package), "--filing-type", "NOE", "--write-manifest", str(draft)],
    )

    assert result.exit_code == 0, result.output
    assert "sends document text" in result.output  # the data-flow notice
    assert "[FOUND] project_title: Culvert Repair" in result.output
    assert "[WITHHELD] lead_agency" in result.output
    assert "[UNKNOWN] sch_number" in result.output
    assert "scan.pdf — unknown — not extracted: the PDF has no text layer" in result.output
    assert "Only that check produces findings" in result.output
    assert len(scripted.calls) == 1  # the image-only PDF was never sent

    manifest = load_manifest(draft)
    assert manifest.project.title == "Culvert Repair"
    assert manifest.project.county == "Kern"
    assert manifest.project.lead_agency is None
    assert [entry.path for entry in manifest.documents] == ["NOE_culvert.pdf", "scan.pdf"]
    assert manifest.documents[0].primary is True
    text = draft.read_text(encoding="utf-8")
    assert text.startswith("# DRAFT manifest")
    assert "not a determination" in text


def test_extract_json_output_and_record_file(tmp_path: Path, scripted: ScriptedClient) -> None:
    package = _package(tmp_path)
    record = tmp_path / "out" / "extraction.json"

    result = runner.invoke(
        app,
        [
            "ai",
            "extract",
            str(package),
            "--filing-type",
            "NOE",
            "--format",
            "json",
            "--output",
            str(record),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["provenance"]["model"] == "fake-model"
    assert payload["provenance"]["prompt_version"] == "extract-v1"
    assert payload["counts"]["found"] == 2
    assert payload["draft_manifest"]["project"]["title"] == "Culvert Repair"
    assert payload["label"].startswith("AI-generated draft")


def test_extract_refuses_to_overwrite_a_manifest(tmp_path: Path, scripted: ScriptedClient) -> None:
    package = _package(tmp_path)
    existing = tmp_path / "package.yaml"
    existing.write_text("filing_type: NOE\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["ai", "extract", str(package), "--filing-type", "NOE", "--write-manifest", str(existing)],
    )

    assert result.exit_code == 2
    assert "refusing to overwrite" in result.output
    assert existing.read_text(encoding="utf-8") == "filing_type: NOE\n"


def test_extract_fails_closed_on_model_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = _package(tmp_path)
    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", lambda *a, **k: ScriptedClient([]))
    draft = tmp_path / "draft.yaml"

    result = runner.invoke(
        app,
        ["ai", "extract", str(package), "--filing-type", "NOE", "--write-manifest", str(draft)],
    )

    assert result.exit_code == 2
    assert "model error" in result.output
    assert "No draft manifest was written" in result.output
    assert not draft.exists()


def test_extract_with_no_pdfs_writes_no_manifest(tmp_path: Path, scripted: ScriptedClient) -> None:
    package = tmp_path / "empty"
    package.mkdir()
    (package / "readme.txt").write_text("x", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "ai",
            "extract",
            str(package),
            "--filing-type",
            "NOE",
            "--write-manifest",
            str(tmp_path / "d.yaml"),
        ],
    )

    assert result.exit_code == 0, result.output
    assert "No draft manifest" in result.output
    assert not (tmp_path / "d.yaml").exists()


def test_extract_input_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    package = _package(tmp_path)

    bad_format = runner.invoke(
        app, ["ai", "extract", str(package), "--filing-type", "NOE", "--format", "xml"]
    )
    assert bad_format.exit_code == 2

    def no_client(*a: object, **k: object) -> ScriptedClient:
        raise ModelError("ANTHROPIC_API_KEY is not set in the environment")

    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", no_client)
    no_creds = runner.invoke(app, ["ai", "extract", str(package), "--filing-type", "NOE"])
    assert no_creds.exit_code == 2
    assert "AI provider error" in no_creds.output

    monkeypatch.setattr("ceqa_preflight.ai.cli.build_client", lambda *a, **k: ScriptedClient([]))
    not_a_package = tmp_path / "file.txt"
    not_a_package.write_text("x", encoding="utf-8")
    bad_input = runner.invoke(app, ["ai", "extract", str(not_a_package), "--filing-type", "NOE"])
    assert bad_input.exit_code == 2
    assert "Input error" in bad_input.output
