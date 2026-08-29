"""The gettext seam: what locale selection may change, and what it must never change.

`docs/I18N.md` splits the product's strings in two. Report prose is localizable. Rule
identifiers, finding status values, JSON field names, command names, and source citations
are stable identifiers. The tests here hold that line from both sides: prose really does
change language, and everything a machine or a reviewer keys on really does not.

The failure this file is most concerned with is the quiet one. A locale that is accepted,
raises nothing, and then renders English anyway is worse than a locale that is refused,
because the reader has no signal that they did not get what they asked for.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from babel.messages import mofile, pofile
from pypdf import PdfWriter
from typer.testing import CliRunner

from ceqa_preflight import i18n
from ceqa_preflight.checker import check_package
from ceqa_preflight.cli import app
from ceqa_preflight.models import FilingType
from ceqa_preflight.reporting import render_console, render_html, render_json

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:  # pragma: no cover - import bookkeeping
    sys.path.insert(0, SCRIPTS)

import check_i18n  # type: ignore[import-not-found]  # noqa: E402

runner = CliRunner()

LOCALES = Path(i18n.__file__).parent / "locales"


def _package(tmp_path: Path) -> Path:
    """A minimal readable package, enough to produce findings in every status band."""

    package = tmp_path / "package"
    package.mkdir()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with (package / "Notice_of_Exemption_form.pdf").open("wb") as handle:
        writer.write(handle)
    return package


# --------------------------------------------------------------------------------------
# Tag handling
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "catalog", "unavailable"),
    [
        (None, "en", None),
        ("en", "en", None),
        ("es", "es", None),
        ("ES", "es", None),
        ("es-MX", "es", None),
        ("es_MX", "es", None),
        ("fr", "en", "fr"),
        ("pt-BR", "en", "pt-BR"),
    ],
)
def test_resolve_maps_a_request_onto_a_shipped_catalog(
    requested: str | None, catalog: str, unavailable: str | None
) -> None:
    assert i18n.resolve(requested) == (catalog, unavailable)


# The last case is written as an escape because it is the point: "\uff11\uff12" is
# FULLWIDTH DIGIT ONE/TWO, which Python's `\d` matches and `int()` converts. A region
# subtag pattern written with `\d` would accept it. `ceqa_preflight.i18n` writes `[0-9]`.
@pytest.mark.parametrize(
    "tag", ["", "e", "english", "es-", "es-MEXICO", "es-x-private", "es-\uff11\uff12\uff13"]
)
def test_a_malformed_tag_is_refused_rather_than_quietly_becoming_english(tag: str) -> None:
    with pytest.raises(i18n.LocaleError):
        i18n.resolve(tag)


def test_use_locale_restores_the_previous_catalog() -> None:
    assert i18n.active_locale() == "en"
    with i18n.use_locale("es"):
        assert i18n.active_locale() == "es"
    assert i18n.active_locale() == "en"


def test_an_unshipped_catalog_cannot_be_forced_into_force() -> None:
    with pytest.raises(i18n.LocaleError):
        i18n.set_locale("fr")
    with pytest.raises(i18n.LocaleError), i18n.use_locale("fr"):
        pass  # pragma: no cover - the context body never runs


# --------------------------------------------------------------------------------------
# Catalog integrity at runtime
# --------------------------------------------------------------------------------------


def _template_messages() -> list[str]:
    with (LOCALES / "messages.pot").open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream)
    return [message.id for message in catalog if message.id and isinstance(message.id, str)]


def test_every_supported_locale_ships_a_catalog_that_actually_loads() -> None:
    """The seam must never satisfy a locale request out of the untranslated msgid."""

    messages = _template_messages()
    assert messages, "extraction template is empty"
    for locale in i18n.SUPPORTED_LOCALES:
        with i18n.use_locale(locale):
            rendered = [i18n.gettext(message) for message in messages]
        assert all(rendered), f"{locale}: a message rendered empty"


def test_spanish_actually_differs_from_english_across_most_of_the_catalog() -> None:
    """Guard the silent-fallback failure: a stale or missing catalog looks like English.

    A handful of messages are legitimately identical in both languages (bare placeholder
    lines and the signature rule are the same characters either way), so this asserts a
    large majority rather than every single message.
    """

    messages = _template_messages()
    with i18n.use_locale("es"):
        translated = [i18n.gettext(message) for message in messages]
    differing = sum(
        1 for source, spanish in zip(messages, translated, strict=True) if source != spanish
    )
    assert differing > len(messages) * 0.95


def test_english_catalog_returns_the_source_string_unchanged() -> None:
    for message in _template_messages():
        with i18n.use_locale("en"):
            assert i18n.gettext(message) == message


def test_ngettext_selects_a_plural_form_per_catalog() -> None:
    for locale in i18n.SUPPORTED_LOCALES:
        with i18n.use_locale(locale):
            assert i18n.ngettext("check", "checks", 1) == "check"
            assert i18n.ngettext("check", "checks", 2) == "checks"


def test_the_gate_script_and_the_seam_agree_on_which_locales_ship() -> None:
    """Two lists of locales in two files is a drift hazard, so it is pinned."""

    assert tuple(check_i18n.EXPECTED_LOCALES) == i18n.SUPPORTED_LOCALES
    shipped = sorted(
        entry.name
        for entry in LOCALES.iterdir()
        if entry.is_dir() and (entry / "LC_MESSAGES" / "messages.mo").is_file()
    )
    assert shipped == sorted(i18n.SUPPORTED_LOCALES)


# --------------------------------------------------------------------------------------
# What locale selection must never change
# --------------------------------------------------------------------------------------


def test_locale_changes_prose_but_not_one_machine_readable_value(tmp_path: Path) -> None:
    package = _package(tmp_path)

    with i18n.use_locale("en"):
        english_report, english_exit = check_package(package, FilingType.NOE)
        english = json.loads(render_json(english_report))
    with i18n.use_locale("es"):
        spanish_report, spanish_exit = check_package(package, FilingType.NOE)
        spanish = json.loads(render_json(spanish_report))

    # The advisory verdict is not a matter of language.
    assert english_exit == spanish_exit

    assert english.keys() == spanish.keys()
    prose = {"message", "remediation", "title", "detail", "disclaimer"}
    for section in ("findings", "manual_review", "not_run"):
        assert len(english[section]) == len(spanish[section])
        for left, right in zip(english[section], spanish[section], strict=True):
            assert left.keys() == right.keys()
            for key in left.keys() - prose:
                assert left[key] == right[key], f"{section}.{key} changed with the locale"

    # Identifiers, statuses, and citations survive verbatim.
    assert [f["rule_id"] for f in english["findings"]] == [
        f["rule_id"] for f in spanish["findings"]
    ]
    assert [f["status"] for f in english["findings"]] == [f["status"] for f in spanish["findings"]]
    assert [f["source"] for f in english["findings"]] == [f["source"] for f in spanish["findings"]]
    assert english["report_schema_version"] == spanish["report_schema_version"]


def test_console_and_html_prose_follows_the_locale(tmp_path: Path) -> None:
    package = _package(tmp_path)
    with i18n.use_locale("en"):
        report, _ = check_package(package, FilingType.NOE)
        english_console = render_console(report)
        english_html = render_html(report)
    with i18n.use_locale("es"):
        report, _ = check_package(package, FilingType.NOE)
        spanish_console = render_console(report)
        spanish_html = render_html(report)

    assert "CEQA Preflight advisory report" in english_console
    assert "Informe orientativo de CEQA Preflight" in spanish_console
    assert "advisory technical checker" not in spanish_console
    assert "verificador técnico orientativo" in spanish_console

    assert '<html lang="en">' in english_html
    assert '<html lang="es">' in spanish_html
    assert "Automated findings" in english_html
    assert "Hallazgos automatizados" in spanish_html
    # Rule identifiers and citation URLs are not prose and do not move.
    assert "CORE-001" in spanish_html
    assert "https://lci.ca.gov/sch/faq/" in spanish_html


def test_the_spanish_report_never_claims_a_legal_determination(tmp_path: Path) -> None:
    """The one line docs/I18N.md refuses to let any translation cross."""

    package = _package(tmp_path)
    with i18n.use_locale("es"):
        report, _ = check_package(package, FilingType.NOE)
    assert "no constituye asesoramiento legal" in report.disclaimer
    assert "determinación de cumplimiento de CEQA" in report.disclaimer


# --------------------------------------------------------------------------------------
# The command-line boundary
# --------------------------------------------------------------------------------------


def test_locale_is_explicit_and_never_inferred_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A report must be reproducible from its command line, not from a shell's mood."""

    package = _package(tmp_path)
    for variable in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        monkeypatch.setenv(variable, "es_ES.UTF-8")
    result = runner.invoke(app, ["check", str(package), "--filing-type", "NOE"])
    assert "CEQA Preflight advisory report" in result.stdout
    assert "Informe orientativo" not in result.stdout


def test_an_unshipped_language_falls_back_to_english_and_says_so(tmp_path: Path) -> None:
    package = _package(tmp_path)
    result = runner.invoke(app, ["--locale", "fr", "check", str(package), "--filing-type", "NOE"])
    assert "No catalog ships for fr; reporting in English instead." in result.output
    assert "CEQA Preflight advisory report" in result.output


def test_a_malformed_locale_is_a_usage_error(tmp_path: Path) -> None:
    package = _package(tmp_path)
    result = runner.invoke(
        app, ["--locale", "espanol!", "check", str(package), "--filing-type", "NOE"]
    )
    assert result.exit_code == 2
    assert "not a well-formed language tag" in result.output


def test_a_spanish_run_says_the_translation_is_not_yet_reviewed(tmp_path: Path) -> None:
    package = _package(tmp_path)
    result = runner.invoke(app, ["--locale", "es", "check", str(package), "--filing-type", "NOE"])
    assert "has not yet approved its terminology" in result.output
    assert "English wording is authoritative" in result.output


def test_locale_does_not_change_the_exit_code(tmp_path: Path) -> None:
    """Exit codes are how a pipeline routes. They key on status, never on wording."""

    package = tmp_path / "empty"
    package.mkdir()
    (package / "notes.txt").write_text("not a pdf", encoding="utf-8")
    english = runner.invoke(app, ["check", str(package), "--filing-type", "NOE"])
    spanish = runner.invoke(app, ["--locale", "es", "check", str(package), "--filing-type", "NOE"])
    assert english.exit_code == spanish.exit_code == 1


def test_check_i18n_passes_against_the_committed_catalogs() -> None:
    """The merge gate's own script, run the way `make verify` runs it."""

    root = Path(__file__).resolve().parents[1]
    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(root / "scripts" / "check_i18n.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "at parity" in completed.stdout


def test_report_json_stays_valid_against_its_schema_in_every_locale(tmp_path: Path) -> None:
    """Locale is prose. The schema contract does not bend for it."""

    package = _package(tmp_path)
    for locale in i18n.SUPPORTED_LOCALES:
        with i18n.use_locale(locale):
            report, _ = check_package(package, FilingType.NOE)
            document: dict[str, Any] = json.loads(render_json(report))
        assert document["report_schema_version"] == "1.1"
        assert document["filing_type"] == "NOE"
        for finding in document["findings"]:
            assert finding["status"] in {"pass", "warning", "failure", "manual"}


# --------------------------------------------------------------------------------------
# Proof that the merge gate can fail
# --------------------------------------------------------------------------------------
#
# A guardrail that is green because it cannot go red is not a guardrail. Each case below
# breaks exactly one property `scripts/check_i18n.py` claims to enforce, against a throwaway
# copy of the real catalogs, and asserts the script fails and names what broke. If a future
# refactor removes a check, the matching case here goes green-but-wrong and this test fails.


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the gate at a disposable copy of the shipped catalogs."""

    copied = tmp_path / "locales"
    shutil.copytree(LOCALES, copied)
    monkeypatch.setattr(check_i18n, "LOCALES", copied)
    monkeypatch.setattr(check_i18n, "TEMPLATE", copied / "messages.pot")
    return copied


def _po(root: Path, locale: str) -> Path:
    return root / locale / "LC_MESSAGES" / "messages.po"


def _recompile(root: Path, locale: str) -> None:
    """Compile one catalog the way `make i18n` does, so only the edit under test differs."""

    with _po(root, locale).open(encoding="utf-8") as stream:
        catalog = pofile.read_po(stream, locale=locale)
    with (root / locale / "LC_MESSAGES" / "messages.mo").open("wb") as out:
        mofile.write_mo(out, catalog)


def _run_gate(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = check_i18n.main()
    return code, capsys.readouterr().err


def test_gate_is_green_on_an_unmodified_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The control case. Without it, every red case below could be red for another reason."""

    _sandbox(tmp_path, monkeypatch)
    code, _ = _run_gate(capsys)
    assert code == 0


def test_gate_fails_when_a_spanish_message_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('msgid "Batch summary"\nmsgstr "Resumen del lote"\n', ""), encoding="utf-8"
    )
    _recompile(root, "es")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "missing message from the template" in stderr


def test_gate_fails_when_a_translation_drops_a_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'msgstr "Error de entrada: {error}"', 'msgstr "Error de entrada"'
        ),
        encoding="utf-8",
    )
    _recompile(root, "es")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "placeholder mismatch" in stderr


def test_gate_fails_when_a_message_is_left_untranslated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    path.write_text(
        path.read_text(encoding="utf-8").replace('msgstr "Resumen del lote"', 'msgstr ""'),
        encoding="utf-8",
    )
    _recompile(root, "es")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "untranslated message" in stderr


def test_gate_fails_when_english_drifts_away_from_the_source_string(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """English is a catalog, so English prose can drift. This is what catches it."""

    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "en")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'msgid "Batch summary"\nmsgstr "Batch summary"',
            'msgid "Batch summary"\nmsgstr "Batch Summary"',
        ),
        encoding="utf-8",
    )
    _recompile(root, "en")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "msgstr differs from msgid" in stderr


def test_gate_fails_when_a_compiled_catalog_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The silent-fallback bug in its purest form: edited source, unchanged binary."""

    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            'msgstr "Resumen del lote"', 'msgstr "Resumen por lotes"'
        ),
        encoding="utf-8",
    )
    # Deliberately not recompiled.
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "stale" in stderr


def test_gate_fails_when_a_compiled_catalog_is_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    (root / "es" / "LC_MESSAGES" / "messages.mo").unlink()
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "no compiled catalog" in stderr


def test_gate_fails_on_a_locale_directory_that_is_not_a_valid_language_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    shutil.copytree(root / "es", root / "spanish")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "not a valid BCP 47 locale directory name" in stderr


def test_gate_fails_when_a_catalog_declares_a_different_language_than_its_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    path.write_text(
        path.read_text(encoding="utf-8").replace('"Language: es\\n"', '"Language: pt\\n"'),
        encoding="utf-8",
    )
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "declares Language:" in stderr


def test_gate_fails_when_a_supported_locale_stops_shipping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Removing Spanish must break the build, not quietly return everyone to English."""

    root = _sandbox(tmp_path, monkeypatch)
    shutil.rmtree(root / "es")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "do not match expected" in stderr


def test_gate_fails_on_an_empty_extraction_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    (root / "messages.pot").write_text("", encoding="utf-8")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "extraction template is empty" in stderr


def test_a_locale_does_not_leak_out_of_the_command_that_asked_for_it(tmp_path: Path) -> None:
    """One process, two commands: the second must not inherit the first one's language.

    This is a regression test with a real history. The first cut of the seam set a
    process-global locale and never put it back, so a Spanish run left every later run in
    the same process Spanish, including a later run that asked for nothing.
    """

    package = _package(tmp_path)
    assert i18n.active_locale() == "en"
    spanish = runner.invoke(app, ["--locale", "es", "check", str(package), "--filing-type", "NOE"])
    assert "Informe orientativo de CEQA Preflight" in spanish.output
    assert i18n.active_locale() == "en"
    english = runner.invoke(app, ["check", str(package), "--filing-type", "NOE"])
    assert "CEQA Preflight advisory report" in english.output
    assert "Informe orientativo" not in english.output


def test_gate_fails_when_a_wrapped_string_never_reached_the_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Extraction freshness: a string can be translated only if it was extracted."""

    root = _sandbox(tmp_path, monkeypatch)
    template = root / "messages.pot"
    text = template.read_text(encoding="utf-8")
    template.write_text(text.replace('msgid "Batch summary"\nmsgstr ""\n', ""), encoding="utf-8")
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "is wrapped in source but not extracted" in stderr
    assert "make i18n-update" in stderr


def test_gate_fails_when_the_template_carries_a_message_source_no_longer_has(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The other direction: a reworded string must not leave its old self behind."""

    root = _sandbox(tmp_path, monkeypatch)
    template = root / "messages.pot"
    template.write_text(
        template.read_text(encoding="utf-8") + '\nmsgid "A string no source wraps."\nmsgstr ""\n',
        encoding="utf-8",
    )
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "extracted but no longer in source" in stderr


def test_gate_fails_when_a_compiled_catalog_differs_only_in_its_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The byte check backstops the semantic one, which cannot see a header change."""

    root = _sandbox(tmp_path, monkeypatch)
    path = _po(root, "es")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            '"Project-Id-Version: CEQA Preflight\\n"', '"Project-Id-Version: CEQA Preflight 9\\n"'
        ),
        encoding="utf-8",
    )
    # Every message still agrees, so only the byte comparison can catch this.
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "does not match its source" in stderr


def test_gate_is_green_when_the_template_is_checked_out_with_crlf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A CRLF working tree is a checkout setting, not catalog drift.

    Reproduces the Windows CI failure this check was hardened against: Babel always writes
    LF, so a byte comparison against a CRLF checkout reported a stale template on a clean
    tree. `.gitattributes` pins `.pot` and `.po` to LF; this proves the check does not
    depend on that pin holding.
    """

    root = _sandbox(tmp_path, monkeypatch)
    template = root / "messages.pot"
    template.write_bytes(template.read_bytes().replace(b"\n", b"\r\n"))
    code, stderr = _run_gate(capsys)
    assert code == 0, stderr


def test_crlf_tolerance_does_not_hide_a_genuinely_stale_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The newline allowance must not become a hole the freshness check falls through."""

    root = _sandbox(tmp_path, monkeypatch)
    template = root / "messages.pot"
    text = template.read_text(encoding="utf-8").replace('msgid "Batch summary"\nmsgstr ""\n', "")
    template.write_bytes(text.replace("\n", "\r\n").encode("utf-8"))
    code, stderr = _run_gate(capsys)
    assert code == 1
    assert "is wrapped in source but not extracted" in stderr
