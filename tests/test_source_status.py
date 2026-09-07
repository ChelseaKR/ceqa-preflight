"""Reading a source-watch record as a statement about rules.

The watch reports on documents; ``rules list --source-status`` reports on rules. Every
test here is about a way that translation could quietly lose one of the record's
distinctions -- above all the one the watch was built for, that a document nobody could
read is not a document that turned out to be fine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from ceqa_preflight.cli import app
from ceqa_preflight.source_status import (
    RuleSourceStatus,
    SourceStatusError,
    load_watch_record,
    record_preamble,
    rule_source_reports,
    status_label,
)

runner = CliRunner()


def _document(
    document_id: str,
    status: str,
    *,
    rules_bound: list[str],
    lost: list[str] | None = None,
    rules_with_lost_passages: list[str] | None = None,
    failure_kind: str | None = None,
) -> dict[str, Any]:
    """One document entry shaped exactly as ``scripts/watch_sources.py`` writes it."""

    return {
        "id": document_id,
        "url": f"https://example.invalid/{document_id}",
        "title": document_id,
        "status": status,
        "failure_kind": failure_kind,
        "detail": "",
        "recorded_text_sha256": "a" * 64,
        "observed_text_sha256": None if status == "unverifiable" else "b" * 64,
        "passages_recorded": 2,
        "passages_surviving": None if status == "unverifiable" else [],
        "passages_lost": lost,
        "rules_bound": rules_bound,
        "rules_with_lost_passages": rules_with_lost_passages,
    }


def _record(documents: list[dict[str, Any]], version: int = 1) -> dict[str, Any]:
    return {
        "watch_schema_version": version,
        "checked_at": "2026-09-07T00:00:00Z",
        "read_from": "offline-cache",
        "corpus_built_at": "2026-08-22T03:58:49Z",
        "adopts_nothing": "This record reports what the sources said when they were read.",
        "summary": {},
        "documents": documents,
    }


def _written(tmp_path: Path, record: dict[str, Any]) -> Path:
    path = tmp_path / "source-watch.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path


CLEAN = _document("doc-clean", "unchanged", rules_bound=["NOE-001"], lost=[])
LOST = _document(
    "doc-lost",
    "changed",
    rules_bound=["NOE-002"],
    lost=["doc-lost#1"],
    rules_with_lost_passages=["NOE-002"],
)
CHANGED_SURVIVING = _document(
    "doc-moved",
    "changed",
    rules_bound=["NOE-003"],
    lost=[],
    rules_with_lost_passages=[],
)
UNREAD = _document(
    "doc-unread",
    "unverifiable",
    rules_bound=["NOD-001"],
    lost=None,
    rules_with_lost_passages=None,
    failure_kind="transport",
)


def _statuses(tmp_path: Path, documents: list[dict[str, Any]], rule_ids: list[str]):
    record = load_watch_record(_written(tmp_path, _record(documents)))
    reports = rule_source_reports(record, rule_ids)
    return {rule_id: reports[rule_id].status for rule_id in rule_ids}


class TestTheFourVerdicts:
    def test_an_unchanged_document_reports_its_rules_unchanged(self, tmp_path: Path) -> None:
        assert _statuses(tmp_path, [CLEAN], ["NOE-001"]) == {"NOE-001": RuleSourceStatus.UNCHANGED}

    def test_a_rule_whose_passages_are_gone_says_so(self, tmp_path: Path) -> None:
        assert _statuses(tmp_path, [LOST], ["NOE-002"]) == {
            "NOE-002": RuleSourceStatus.PASSAGES_LOST
        }

    def test_a_changed_document_whose_passages_survived_is_its_own_state(
        self, tmp_path: Path
    ) -> None:
        assert _statuses(tmp_path, [CHANGED_SURVIVING], ["NOE-003"]) == {
            "NOE-003": RuleSourceStatus.SOURCE_CHANGED
        }

    def test_an_unread_document_is_not_examined_rather_than_unchanged(self, tmp_path: Path) -> None:
        # The whole point of the watch's `null`. Reading it as "unchanged" would
        # publish a source nobody could open as a source that was verified.
        assert _statuses(tmp_path, [UNREAD], ["NOD-001"]) == {
            "NOD-001": RuleSourceStatus.NOT_EXAMINED
        }


class TestSilenceIsNotAVerdict:
    def test_a_rule_no_document_binds_is_not_watched(self, tmp_path: Path) -> None:
        assert _statuses(tmp_path, [CLEAN], ["PDF-007"]) == {
            "PDF-007": RuleSourceStatus.NOT_WATCHED
        }

    def test_an_empty_record_leaves_every_rule_not_watched(self, tmp_path: Path) -> None:
        assert _statuses(tmp_path, [], ["NOE-001", "NOD-001"]) == {
            "NOE-001": RuleSourceStatus.NOT_WATCHED,
            "NOD-001": RuleSourceStatus.NOT_WATCHED,
        }

    def test_not_watched_and_not_examined_are_different_words(self) -> None:
        assert RuleSourceStatus.NOT_WATCHED != RuleSourceStatus.NOT_EXAMINED
        assert status_label(RuleSourceStatus.NOT_WATCHED) != status_label(
            RuleSourceStatus.NOT_EXAMINED
        )


class TestSeveralDocumentsTakeTheWorst:
    def test_one_unread_document_is_not_averaged_away_by_a_clean_one(self, tmp_path: Path) -> None:
        both = [
            _document("doc-clean", "unchanged", rules_bound=["NOE-001"], lost=[]),
            _document(
                "doc-unread",
                "unverifiable",
                rules_bound=["NOE-001"],
                lost=None,
                rules_with_lost_passages=None,
                failure_kind="not_found",
            ),
        ]
        assert _statuses(tmp_path, both, ["NOE-001"]) == {"NOE-001": RuleSourceStatus.NOT_EXAMINED}

    def test_a_lost_passage_outranks_an_unread_document(self, tmp_path: Path) -> None:
        both = [
            _document(
                "doc-unread",
                "unverifiable",
                rules_bound=["NOE-002"],
                lost=None,
                rules_with_lost_passages=None,
                failure_kind="transport",
            ),
            _document(
                "doc-lost",
                "changed",
                rules_bound=["NOE-002"],
                lost=["doc-lost#1"],
                rules_with_lost_passages=["NOE-002"],
            ),
        ]
        assert _statuses(tmp_path, both, ["NOE-002"]) == {"NOE-002": RuleSourceStatus.PASSAGES_LOST}

    def test_every_binding_is_reported_not_only_the_deciding_one(self, tmp_path: Path) -> None:
        both = [
            _document("doc-clean", "unchanged", rules_bound=["NOE-001"], lost=[]),
            _document(
                "doc-unread",
                "unverifiable",
                rules_bound=["NOE-001"],
                lost=None,
                rules_with_lost_passages=None,
                failure_kind="not_found",
            ),
        ]
        record = load_watch_record(_written(tmp_path, _record(both)))
        report = rule_source_reports(record, ["NOE-001"])["NOE-001"]
        assert [binding.document_id for binding in report.documents] == [
            "doc-clean",
            "doc-unread",
        ]
        assert [binding.failure_kind for binding in report.documents] == [None, "not_found"]


class TestARecordThatContradictsItselfIsRefused:
    def test_an_unverifiable_document_that_reports_passages_examined(self, tmp_path: Path) -> None:
        broken = _document(
            "doc-unread",
            "unverifiable",
            rules_bound=["NOE-001"],
            lost=[],
            failure_kind="transport",
        )
        with pytest.raises(SourceStatusError, match="unverifiable and as examined"):
            load_watch_record(_written(tmp_path, _record([broken])))

    def test_an_unchanged_document_that_examined_nothing(self, tmp_path: Path) -> None:
        broken = _document("doc-clean", "unchanged", rules_bound=["NOE-001"], lost=None)
        with pytest.raises(SourceStatusError, match="reports nothing examined"):
            load_watch_record(_written(tmp_path, _record([broken])))

    def test_an_unknown_document_status_is_named_rather_than_mapped(self, tmp_path: Path) -> None:
        broken = _document("doc-odd", "probably-fine", rules_bound=["NOE-001"], lost=[])
        with pytest.raises(SourceStatusError, match="unknown status"):
            load_watch_record(_written(tmp_path, _record([broken])))

    def test_a_document_without_an_id_is_refused(self, tmp_path: Path) -> None:
        broken = dict(CLEAN)
        del broken["id"]
        with pytest.raises(SourceStatusError, match="no id"):
            load_watch_record(_written(tmp_path, _record([broken])))


class TestARecordThisBuildCannotReadIsRefusedByName:
    def test_a_future_schema_version_is_named_rather_than_parsed(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _record([CLEAN], version=2))
        with pytest.raises(SourceStatusError, match="version 1"):
            load_watch_record(path)

    def test_a_record_with_no_declared_version_is_refused(self, tmp_path: Path) -> None:
        record = _record([CLEAN])
        del record["watch_schema_version"]
        with pytest.raises(SourceStatusError, match="no watch_schema_version"):
            load_watch_record(_written(tmp_path, record))

    def test_a_missing_file_is_reported_as_a_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(SourceStatusError, match="No source-watch record"):
            load_watch_record(tmp_path / "absent.json")

    def test_a_file_that_is_not_json_is_refused(self, tmp_path: Path) -> None:
        path = tmp_path / "source-watch.json"
        path.write_text("not json at all", encoding="utf-8")
        with pytest.raises(SourceStatusError, match="not valid JSON"):
            load_watch_record(path)

    def test_a_json_array_is_not_a_record(self, tmp_path: Path) -> None:
        path = tmp_path / "source-watch.json"
        path.write_text("[]", encoding="utf-8")
        with pytest.raises(SourceStatusError, match="top level is not an object"):
            load_watch_record(path)

    def test_a_document_entry_that_is_not_an_object_is_refused(self, tmp_path: Path) -> None:
        record = _record([CLEAN])
        record["documents"].append("doc-lost")
        with pytest.raises(SourceStatusError, match="document 1 is not an object"):
            load_watch_record(_written(tmp_path, record))

    def test_a_path_that_cannot_be_opened_is_reported_not_treated_as_absent(
        self, tmp_path: Path
    ) -> None:
        # A directory is not a missing file. Folding every OSError into "no record
        # here" would tell a maintainer to write a record that already exists.
        directory = tmp_path / "watch-records"
        directory.mkdir()
        with pytest.raises(SourceStatusError, match="Could not read the source-watch record"):
            load_watch_record(directory)

    def test_a_record_with_no_documents_list_is_refused(self, tmp_path: Path) -> None:
        record = _record([CLEAN])
        del record["documents"]
        with pytest.raises(SourceStatusError, match="no documents list"):
            load_watch_record(_written(tmp_path, record))


class TestThePreambleRefusesToImplyAdoption:
    def test_it_names_the_record_and_denies_being_a_review(self, tmp_path: Path) -> None:
        record = load_watch_record(_written(tmp_path, _record([CLEAN])))
        preamble = record_preamble(record)
        assert "2026-09-07T00:00:00Z" in preamble
        assert "offline-cache" in preamble
        assert "is not a review" in preamble

    def test_it_publishes_how_much_of_the_corpus_the_record_covers(self, tmp_path: Path) -> None:
        # A record from a run narrowed with `--document` says nothing about the rest,
        # and this reader cannot tell what was left out. Naming the extent is the only
        # honest way to keep a two-document record from reading as a clean corpus.
        narrow = load_watch_record(_written(tmp_path, _record([CLEAN, UNREAD])))
        wide = load_watch_record(
            _written(tmp_path, _record([CLEAN, LOST, CHANGED_SURVIVING, UNREAD]))
        )
        assert "2 document(s)" in record_preamble(narrow)
        assert "4 document(s)" in record_preamble(wide)
        assert "not a source that was checked" in record_preamble(narrow)

    def test_a_record_with_no_checked_at_says_so_instead_of_showing_a_blank(
        self, tmp_path: Path
    ) -> None:
        record = _record([CLEAN])
        del record["checked_at"]
        del record["read_from"]
        preamble = record_preamble(load_watch_record(_written(tmp_path, record)))
        assert "unrecorded time" in preamble
        assert "unrecorded origin" in preamble


class TestTheCommandLineSurface:
    def test_without_the_flag_the_listing_is_unchanged(self) -> None:
        plain = runner.invoke(app, ["rules", "list"])
        assert plain.exit_code == 0
        assert "source unchanged" not in plain.stdout

    def test_the_console_listing_carries_a_status_for_every_rule(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _record([CLEAN, LOST, UNREAD]))
        result = runner.invoke(app, ["rules", "list", "--source-status", str(path)])

        assert result.exit_code == 0
        assert "is not a review" in result.stdout
        rows = [line for line in result.stdout.splitlines() if line.startswith(("NOE-", "NOD-"))]
        assert rows, result.stdout
        for row in rows:
            assert row.count("\t") == 4, row
        assert any("source unchanged" in row for row in rows)
        assert any("no longer occur" in row for row in rows)
        assert any("could not be read" in row for row in rows)
        assert any("names no source for it" in row for row in rows)

    def test_the_json_listing_carries_the_bindings_that_decided_each_status(
        self, tmp_path: Path
    ) -> None:
        path = _written(tmp_path, _record([CLEAN, LOST, UNREAD]))
        result = runner.invoke(
            app, ["rules", "list", "--format", "json", "--source-status", str(path)]
        )

        assert result.exit_code == 0
        by_id = {rule["id"]: rule for rule in json.loads(result.stdout)}
        assert by_id["NOE-001"]["source_status"]["status"] == "unchanged"
        assert by_id["NOE-002"]["source_status"]["status"] == "passages_lost"
        assert by_id["NOD-001"]["source_status"]["status"] == "not_examined"
        assert by_id["NOD-001"]["source_status"]["documents"] == [
            {
                "document_id": "doc-unread",
                "document_status": "unverifiable",
                "failure_kind": "transport",
                "rule_status": "not_examined",
            }
        ]
        assert by_id["PDF-007"]["source_status"]["status"] == "not_watched"
        assert by_id["PDF-007"]["source_status"]["documents"] == []

    def test_the_json_listing_without_the_flag_grows_no_field(self) -> None:
        result = runner.invoke(app, ["rules", "list", "--format", "json"])

        assert result.exit_code == 0
        assert all("source_status" not in rule for rule in json.loads(result.stdout))

    def test_an_unreadable_record_exits_two_and_names_the_reason(self, tmp_path: Path) -> None:
        path = _written(tmp_path, _record([CLEAN], version=99))
        result = runner.invoke(app, ["rules", "list", "--source-status", str(path)])

        assert result.exit_code == 2
        assert "watch_schema_version 99" in result.stderr

    def test_a_missing_record_exits_two_rather_than_listing_without_status(
        self, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            app, ["rules", "list", "--source-status", str(tmp_path / "absent.json")]
        )

        assert result.exit_code == 2
        assert "NOE-001" not in result.stdout

    def test_the_spanish_listing_translates_the_status_and_not_the_rule_id(
        self, tmp_path: Path
    ) -> None:
        path = _written(tmp_path, _record([CLEAN]))
        result = runner.invoke(
            app, ["--locale", "es", "rules", "list", "--source-status", str(path)]
        )

        assert result.exit_code == 0
        assert "NOE-001" in result.stdout
        assert "source unchanged" not in result.stdout
        assert "unchanged" not in result.stdout.split("NOE-001")[1].split("\n")[0]
