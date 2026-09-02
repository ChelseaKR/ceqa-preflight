"""Every committed artifact that stands in for a computation, checked against its producer.

`scripts/check_i18n.py` already applies the rule this file generalises: regenerate in a
scratch buffer, compare byte for byte, write nothing, so `make verify` can never quietly
repair the drift it exists to report. Several other committed artifacts had no such
comparison at all:

* `schemas/*.json` are written by `python -m ceqa_preflight.schema_export`, which
  `make schemas` runs and `make verify` does not. `tests/test_schema_export.py` exported
  into `tmp_path`, asserted two `title` strings, and threw the fresh output away without
  ever looking at the committed bytes. A field added to `PackageManifest` or
  `InspectionReport` left the published contract stale with every check green.
* `examples/sample-report.html` is the output of a command written down in
  `examples/README.md`. Nothing ran it and nothing compared it, and it *had* drifted: the
  citation links still said "Source" where `reporting.py` now says "Official source" /
  "Technical reference" / "Project advisory rule", and the whole `source-kind` qualifier
  note added alongside them was missing.
* `examples/noe-fictional-package/` is `ceqa-preflight synth` output. `synth.py` reads no
  clock and draws no randomness, so it is byte-reproducible, and nothing reproduced it.
* `corpus/text/*.txt`, `corpus/passages.json` and `corpus/manifest.json` are built by
  `scripts/build_corpus.py`, which is deliberately outside `verify` because it fetches.
  But three of its invariants need no network at all, and `ai/corpus.py`'s verifier walks
  the manifest rather than the filesystem, so it cannot see an orphan in either direction.
* `docs/standards/` is vendored and pinned. Renovate bumps `.standards-version` with a
  regex that touches one line; it cannot add or remove a vendored document, so the version
  and the directory can disagree.
* The README states seven figures about the catalogue, the suite and the gates. Six are
  derivable here. `tests/test_ai_evals.py` already does this for `evals/README.md`, after
  the numbers there drifted for two commits.

Nothing in this file writes into the working tree.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ceqa_preflight.ai.corpus import Corpus, default_corpus_dir
from ceqa_preflight.cli import app
from ceqa_preflight.rule_catalog import RuleLifecycle
from ceqa_preflight.rule_registry import default_catalog
from ceqa_preflight.schema_export import export_schemas

_ROOT = Path(__file__).resolve().parents[1]
_EXAMPLES = _ROOT / "examples"
_PACKAGE = _EXAMPLES / "noe-fictional-package"
_SCHEMAS = _ROOT / "schemas"
_README = _ROOT / "README.md"
_STANDARDS = _ROOT / "docs" / "standards"

_runner = CliRunner()


def _assert_same(committed: Path, fresh: Path, how: str) -> None:
    """Byte-compare a committed artifact against freshly produced output."""
    assert committed.exists(), f"{committed.relative_to(_ROOT)} is not committed; run {how}"
    assert fresh.exists(), f"the regeneration did not produce {fresh.name}"
    want, got = committed.read_bytes(), fresh.read_bytes()
    if want == got:
        return
    raise AssertionError(
        f"{committed.relative_to(_ROOT)} is not what its producer now writes. "
        f"Regenerate it ({how}) and commit the result; do not hand-edit it."
        + _first_difference(want, got)
    )


def _first_difference(want: bytes, got: bytes) -> str:
    try:
        want_lines = want.decode("utf-8").splitlines()
        got_lines = got.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return f"\n  binary files differ (committed {len(want)} bytes, fresh {len(got)} bytes)"
    for number, (a, b) in enumerate(zip(want_lines, got_lines, strict=False), start=1):
        if a != b:
            return f"\n  first difference, line {number}:\n  committed: {a!r}\n  fresh:     {b!r}"
    return f"\n  line counts differ: committed {len(want_lines)}, fresh {len(got_lines)}"


# --------------------------------------------------------------------------------------
# schemas/
# --------------------------------------------------------------------------------------


def test_committed_schemas_match_the_exporter(tmp_path: Path) -> None:
    export_schemas(tmp_path)
    exported = {path.name for path in tmp_path.iterdir()}
    committed = {path.name for path in _SCHEMAS.iterdir() if path.is_file()}
    assert committed == exported, (
        "schemas/ and the exporter disagree about which contracts exist: "
        f"only committed {sorted(committed - exported)}, "
        f"only exported {sorted(exported - committed)}"
    )
    for name in sorted(exported):
        _assert_same(_SCHEMAS / name, tmp_path / name, "`make schemas`")


# --------------------------------------------------------------------------------------
# examples/
# --------------------------------------------------------------------------------------

#: The one field of the HTML report that is not a function of its inputs. Everything else,
#: `input_fingerprint` included, is content-derived, so only this is excluded from the
#: comparison. It is replaced rather than deleted, and the replacement is required to fire
#: exactly once on each side, so a report that stopped stating when it was generated fails
#: here instead of quietly widening what the gate ignores.
_GENERATED_AT = re.compile(r"generated \d{4}-\d{2}-\d{2}T[0-9:.]+\+00:00")

_SYNTH_ARGS = ["--filing-type", "NOE", "--defect", "scanned", "--defect", "fillable-form"]


def _without_generation_time(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    normalized, count = _GENERATED_AT.subn("generated <time>", text)
    assert count == 1, (
        f"{path} states its generation time {count} times, not once; the comparison below "
        "would be excluding the wrong thing"
    )
    return normalized


def test_sample_report_matches_a_fresh_run(tmp_path: Path) -> None:
    """`examples/README.md` writes down the command; this runs it and compares the output."""
    result = _runner.invoke(
        app,
        [
            "check",
            str(_PACKAGE),
            "--filing-type",
            "NOE",
            "--manifest",
            str(_PACKAGE / "package.yaml"),
            "--include-experimental",
            "--format",
            "html",
            "--output",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    fresh = tmp_path / "report.html"
    assert fresh.exists(), f"the check command wrote no report.html:\n{result.output}"

    committed_text = _without_generation_time(_EXAMPLES / "sample-report.html")
    fresh_text = _without_generation_time(fresh)
    assert committed_text == fresh_text, (
        "examples/sample-report.html is not what `ceqa-preflight check` now writes. "
        "Regenerate it with the command in examples/README.md and commit the result."
        + _first_difference(committed_text.encode(), fresh_text.encode())
    )


def test_example_package_matches_a_fresh_synth(tmp_path: Path) -> None:
    """`ceqa-preflight synth` reads no clock and draws no randomness, so this is exact."""
    destination = tmp_path / "package"
    result = _runner.invoke(app, ["synth", str(destination), *_SYNTH_ARGS])
    assert result.exit_code == 0, result.output

    fresh = {path.name for path in destination.iterdir()}
    committed = {path.name for path in _PACKAGE.iterdir() if path.is_file()}
    assert committed == fresh, (
        "examples/noe-fictional-package/ and a fresh synth disagree about which files "
        f"exist: only committed {sorted(committed - fresh)}, only synthesised "
        f"{sorted(fresh - committed)}"
    )
    for name in sorted(fresh):
        _assert_same(
            _PACKAGE / name,
            destination / name,
            f"`uv run ceqa-preflight synth <dir> {' '.join(_SYNTH_ARGS)}`",
        )


# --------------------------------------------------------------------------------------
# corpus/
# --------------------------------------------------------------------------------------


def _corpus() -> Corpus:
    return Corpus.load(default_corpus_dir())


def test_corpus_manifest_text_files_and_passages_name_the_same_documents() -> None:
    """`ai/corpus.py` iterates the manifest, so nothing it does can see an orphan.

    A `corpus/text/*.txt` no manifest entry names, or a `passages.json` key with no
    manifest entry, is never visited by the loader's verification and never fails it.
    """
    root = default_corpus_dir()
    manifest_ids = {document.id for document in _corpus().manifest.documents}
    text_ids = {path.stem for path in (root / "text").glob("*.txt")}
    passage_ids = set(json.loads((root / "passages.json").read_text(encoding="utf-8")))
    assert manifest_ids, "the corpus manifest lists no documents; this check would be vacuous"
    assert manifest_ids == text_ids, {
        "text files with no manifest entry": sorted(text_ids - manifest_ids),
        "manifest entries with no text file": sorted(manifest_ids - text_ids),
    }
    assert manifest_ids == passage_ids, {
        "passages.json keys with no manifest entry": sorted(passage_ids - manifest_ids),
        "manifest entries missing from passages.json": sorted(manifest_ids - passage_ids),
    }


def test_corpus_text_is_exactly_the_join_of_its_passages() -> None:
    """`build_corpus.py` writes the text as the join of the passages it just cut.

    The loader only checks containment (`normalize_for_match(passage.text) in
    normalize_for_match(text)`), which a reordering, a duplication or a dropped joiner all
    survive. This is the equality the builder actually guarantees.
    """
    corpus = _corpus()
    root = default_corpus_dir()
    mismatched = []
    for document in corpus.manifest.documents:
        text = (root / "text" / f"{document.id}.txt").read_text(encoding="utf-8")
        joined = "\n\n".join(passage.text for passage in corpus.passages(document.id)) + "\n"
        if text != joined:
            mismatched.append(document.id)
    assert not mismatched, (
        "corpus/text/<id>.txt is no longer the '\\n\\n'-join of its passages for "
        f"{mismatched}; rebuild with `scripts/build_corpus.py` and commit the result"
    )


def test_corpus_cited_by_names_only_rules_the_catalogue_still_defines() -> None:
    """The catalogue-to-manifest direction is already asserted in `tests/test_corpus.py`.

    This is the other one: a rule deleted from a rulepack leaves its identifier in
    `corpus/manifest.json` forever, and nothing notices.
    """
    rule_ids = {rule.id for rule in default_catalog().rules}
    cited = {rule_id for document in _corpus().manifest.documents for rule_id in document.cited_by}
    assert cited, "no document records a citing rule; this check would be vacuous"
    assert cited <= rule_ids, (
        "corpus/manifest.json credits rule(s) the catalogue no longer defines: "
        f"{sorted(cited - rule_ids)}"
    )


#: The one corpus document `build_corpus.py` reads from the working tree rather than the
#: network (`LOCAL_SOURCE_PATHS`), which makes it the one document whose committed text is
#: fully re-derivable offline.
_SELF_CITED_ID = "ceqa-preflight-source-review-addendum-2026-07-27"
_SELF_CITED_MARKDOWN = _ROOT / "docs" / "audits" / "rule-source-review-2026-07-27-addendum.md"


def test_self_cited_corpus_document_matches_the_markdown_it_was_built_from() -> None:
    """Editing the addendum silently invalidates two committed hashes. Detectably, offline."""
    sys.path.insert(0, str(_ROOT / "scripts"))
    try:
        import build_corpus  # type: ignore[import-not-found]
    finally:
        sys.path.remove(str(_ROOT / "scripts"))

    source = _SELF_CITED_MARKDOWN.read_text(encoding="utf-8")
    blocks = build_corpus.markdown_blocks(source)
    passages = build_corpus.passages_from_blocks(_SELF_CITED_ID, blocks)
    expected = "\n\n".join(passage.text for passage in passages) + "\n"

    committed = (default_corpus_dir() / "text" / f"{_SELF_CITED_ID}.txt").read_text(
        encoding="utf-8"
    )
    assert committed == expected, (
        f"corpus/text/{_SELF_CITED_ID}.txt no longer matches "
        f"{_SELF_CITED_MARKDOWN.relative_to(_ROOT)}, which is the file it is built from. "
        "Rebuild the corpus and commit the result."
        + _first_difference(committed.encode(), expected.encode())
    )


# --------------------------------------------------------------------------------------
# docs/standards/
# --------------------------------------------------------------------------------------


def test_vendored_standards_manifest_matches_the_directory() -> None:
    """Renovate bumps `.standards-version` with a one-line regex.

    It cannot add or remove a vendored document, so a version bump can land while the
    documents stay behind. Nothing compared the manifest to the directory it describes.
    """
    manifest = json.loads((_STANDARDS / ".standards-manifest.json").read_text(encoding="utf-8"))
    listed = set(manifest["files"])
    present = {path.name for path in _STANDARDS.glob("*.md")}
    assert listed, ".standards-manifest.json lists no files; this check would be vacuous"
    assert listed == present, {
        "listed but not vendored": sorted(listed - present),
        "vendored but not listed": sorted(present - listed),
    }


# --------------------------------------------------------------------------------------
# README figures
# --------------------------------------------------------------------------------------


def _readme_paragraph(marker: str) -> str:
    """The one blank-line-delimited README paragraph containing ``marker``, unwrapped.

    Scoped to a paragraph rather than searched for anywhere in the file: the claim is that
    *this sentence* states the number, and a figure that moved into an unrelated section
    must not keep the gate green.
    """
    paragraphs = _README.read_text(encoding="utf-8").split("\n\n")
    matching = [p for p in paragraphs if marker in p]
    assert len(matching) == 1, (
        f"expected exactly one README paragraph containing {marker!r}, found {len(matching)}"
    )
    return " ".join(matching[0].split())


def _readme_line(marker: str) -> str:
    """The one README line containing ``marker``.

    The conformance table restates two of the same numbers as the prose paragraph above,
    and a table row is not blank-line delimited, so it needs its own locator. Exactly one
    line, for the same reason `_readme_paragraph` demands exactly one paragraph.
    """
    lines = [line for line in _README.read_text(encoding="utf-8").splitlines() if marker in line]
    assert len(lines) == 1, (
        f"expected exactly one README line containing {marker!r}, found {len(lines)}"
    )
    return lines[0]


def _assert_states(text: str, pattern: str, expected: object, where: str = "README.md") -> None:
    found = re.findall(pattern, text)
    assert found, f"{where} no longer states the figure matched by {pattern!r}"
    for value in found:
        assert value == str(expected), (
            f"{where} states {value!r} where the source of truth holds {expected!r} "
            f"(pattern {pattern!r})"
        )


_CATALOGUE_MARKER = "registered rules"
_GATES_MARKER = "is the merge gate: "
_CONFORMANCE_MARKER = "| Code Quality | Applies |"


def test_readme_rule_counts_match_the_catalogue() -> None:
    rules = default_catalog().rules
    active = [rule for rule in rules if rule.lifecycle is RuleLifecycle.ACTIVE]
    experimental = [rule for rule in rules if rule.lifecycle is RuleLifecycle.EXPERIMENTAL]
    assert len(active) + len(experimental) == len(rules), (
        "a rule has a lifecycle this check does not count; the README's split would be unverifiable"
    )
    paragraph = _readme_paragraph(_CATALOGUE_MARKER)
    _assert_states(paragraph, r"reports (\d+) registered rules", len(rules))
    _assert_states(paragraph, r"of which (\d+) are active", len(active))
    _assert_states(paragraph, r"and (\d+) are experimental", len(experimental))
    _assert_states(paragraph, r"the (\d+) experimental ones", len(experimental))


def test_readme_source_file_count_matches_the_tree() -> None:
    tracked = subprocess.run(
        ["git", "ls-files", "src/*.py"],  # noqa: S607
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert tracked, "git ls-files returned no source files; this check would be vacuous"
    _assert_states(_readme_paragraph(_GATES_MARKER), r"mypy over (\d+) source files", len(tracked))


def test_readme_message_count_matches_the_catalogue_template() -> None:
    template = _ROOT / "src" / "ceqa_preflight" / "locales" / "messages.pot"
    messages = sum(
        1 for line in template.read_text(encoding="utf-8").splitlines() if line.startswith("msgid ")
    )
    assert messages, "messages.pot holds no msgid; this check would be vacuous"
    _assert_states(
        _readme_paragraph(_GATES_MARKER), r"holding (\d+) English and Spanish messages", messages
    )


def test_readme_coverage_floor_matches_pyproject() -> None:
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    floor = pyproject["tool"]["coverage"]["report"]["fail_under"]
    _assert_states(_readme_paragraph(_GATES_MARKER), r"(\d+)% branch-coverage floor", floor)


def test_readme_test_total_matches_what_pytest_collects() -> None:
    """The figure that cannot be read out of a file, so it is the one that will rot first.

    Collected in a subprocess rather than from this run's own session, so the number is the
    whole suite's whether or not the caller passed `-k` or a single file.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    match = re.search(r"^(\d+) tests collected", completed.stdout, re.MULTILINE)
    assert match, (
        "could not read a collected-test count out of pytest's own output; the README "
        f"figure cannot be checked against nothing:\n{completed.stdout[-2000:]}"
    )
    _assert_states(_readme_paragraph(_GATES_MARKER), r"gate: (\d+) tests", int(match.group(1)))


def test_readme_conformance_table_restates_the_same_gate_thresholds() -> None:
    """The same two numbers appear a second time, in the standards-conformance table.

    A gate on the prose paragraph alone would leave this copy free to drift away from it.
    """
    pyproject = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    row = _readme_line(_CONFORMANCE_MARKER)
    _assert_states(
        row,
        r"(\d+)% branch-coverage floor",
        pyproject["tool"]["coverage"]["report"]["fail_under"],
    )
    _assert_states(
        row,
        r"complexity <= (\d+)",
        pyproject["tool"]["ruff"]["lint"]["mccabe"]["max-complexity"],
    )


_I18N_DOC = _ROOT / "docs" / "I18N.md"


def test_i18n_doc_message_count_matches_the_catalogue_template() -> None:
    """`docs/I18N.md` restates the README's message count, a second uncoupled copy."""
    template = _ROOT / "src" / "ceqa_preflight" / "locales" / "messages.pot"
    messages = sum(
        1 for line in template.read_text(encoding="utf-8").splitlines() if line.startswith("msgid ")
    )
    lines = [
        line
        for line in _I18N_DOC.read_text(encoding="utf-8").splitlines()
        if "messages, both catalogs at" in line
    ]
    assert len(lines) == 1, (
        f"expected exactly one docs/I18N.md line stating the message count, found {len(lines)}"
    )
    _assert_states(lines[0], r"(\d+) messages, both catalogs at", messages, where="docs/I18N.md")


# --------------------------------------------------------------------------------------
# Line endings
# --------------------------------------------------------------------------------------


def _byte_compared_artifacts() -> list[Path]:
    """Every artifact this module compares as bytes rather than as decoded text.

    A byte comparison is only meaningful if the committed file reaches the working tree
    unchanged. Git's text/binary heuristic looks for a NUL byte in the first 8000, and the
    synthetic PDFs have none, so Git calls them text and converts them on a CRLF checkout.
    """
    return [
        *sorted(path for path in _SCHEMAS.iterdir() if path.is_file()),
        *sorted(path for path in _PACKAGE.iterdir() if path.is_file()),
        _EXAMPLES / "sample-report.html",
    ]


def test_byte_compared_artifacts_are_checked_out_unconverted() -> None:
    """The Windows leg of the merge gate is where this bites, and it did.

    Measured 2026-08-29: `Fictional_Example_Project_fillable_form.pdf` arrived on the
    windows-latest runner as 1587 bytes against the 1478 a fresh `synth` writes, exactly its
    109 line endings, and the sample report's stated input fingerprint moved with it because
    the package it hashes had been converted too. `.gitattributes` now pins these paths;
    this is the assertion that keeps them pinned.
    """
    artifacts = _byte_compared_artifacts()
    assert artifacts, "no artifact was collected; this check would be vacuous"
    converted = [
        path.relative_to(_ROOT).as_posix() for path in artifacts if b"\r\n" in path.read_bytes()
    ]
    assert not converted, (
        f"{converted} reached the working tree with CRLF line endings, so the byte "
        "comparisons above are running against files no producer ever wrote. Add the path "
        "to .gitattributes as `binary` or `text eol=lf` and re-check it out."
    )


def test_the_producers_of_those_artifacts_ask_for_lf_explicitly(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`Path.write_text()` translates to `os.linesep` unless told otherwise.

    Asserted on the call and not on the bytes it produces, so that it fails on every
    platform. On POSIX the default and `newline="\\n"` write identical output, so an output
    check here would pass no matter what the producer asked for and would only ever bite on
    the Windows job — which is how this went unnoticed until the artifact gates arrived.
    """
    calls: list[tuple[str, object]] = []
    original = Path.write_text

    def recording(self: Path, data: str, *args: object, **kwargs: object) -> int:
        calls.append((self.name, kwargs.get("newline")))
        return original(self, data, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", recording)
    export_schemas(tmp_path / "schemas")
    result = _runner.invoke(app, ["synth", str(tmp_path / "package"), *_SYNTH_ARGS])
    assert result.exit_code == 0, result.output

    assert calls, "no committed-artifact producer wrote a text file; this check is vacuous"
    platform_dependent = sorted({name for name, newline in calls if newline != "\n"})
    assert not platform_dependent, (
        f"{platform_dependent} were written with the platform's line ending. Pass "
        'newline="\\n" so the artifact is the same bytes on every platform.'
    )
