"""Tests for the gettext seam: locale resolution, translation, and no hidden inference."""

from __future__ import annotations

import pytest

from ceqa_preflight import i18n


class TestBcp47Validity:
    @pytest.mark.parametrize("tag", ["en", "es", "en-US", "es-419", "zh-Hans-CN"])
    def test_valid_tags(self, tag: str) -> None:
        assert i18n.is_valid_bcp47(tag) is True

    @pytest.mark.parametrize("tag", ["", "e", "en_US", "en US", "en--US", "en-", "-en"])
    def test_invalid_tags(self, tag: str) -> None:
        assert i18n.is_valid_bcp47(tag) is False


class TestResolveLocale:
    def test_none_resolves_to_default(self) -> None:
        assert i18n.resolve_locale(None) == i18n.DEFAULT_LOCALE

    def test_supported_locale_resolves_to_itself(self) -> None:
        assert i18n.resolve_locale("es") == "es"

    def test_region_subtag_resolves_to_primary_subtag(self) -> None:
        assert i18n.resolve_locale("es-MX") == "es"

    def test_case_insensitive(self) -> None:
        assert i18n.resolve_locale("ES") == "es"

    def test_syntactically_valid_but_unsupported_falls_back_to_english(self) -> None:
        """A typo or an unshipped language must never take the tool down (docs/I18N.md)."""

        assert i18n.resolve_locale("fr") == i18n.DEFAULT_LOCALE
        assert i18n.resolve_locale("fr-CA") == i18n.DEFAULT_LOCALE

    def test_malformed_tag_raises(self) -> None:
        with pytest.raises(i18n.InvalidLocaleTagError):
            i18n.resolve_locale("not a tag")


class TestActiveLocaleState:
    def test_default_is_english(self) -> None:
        assert i18n.get_locale() == "en"

    def test_set_locale_changes_translation_output(self) -> None:
        i18n.set_locale("es")
        try:
            assert i18n.get_locale() == "es"
            assert i18n._("Rule") == "Regla"
        finally:
            i18n.set_locale("en")

    def test_using_locale_restores_previous_locale_on_exit(self) -> None:
        i18n.set_locale("en")
        with i18n.using_locale("es"):
            assert i18n.get_locale() == "es"
        assert i18n.get_locale() == "en"

    def test_using_locale_restores_previous_locale_on_exception(self) -> None:
        i18n.set_locale("en")
        with pytest.raises(ValueError, match="boom"), i18n.using_locale("es"):
            raise ValueError("boom")
        assert i18n.get_locale() == "en"

    def test_english_translation_is_identity(self) -> None:
        """English is the msgid's own language: translating it is a documented no-op."""

        assert i18n.get_locale() == "en"
        assert i18n._("Rule") == "Rule"

    def test_unknown_string_falls_back_to_the_literal(self) -> None:
        literal = "this string is not in any catalog"
        with i18n.using_locale("es"):
            assert i18n._(literal) == literal


class TestNgettext:
    def test_ngettext_selects_plural_form_under_active_locale(self) -> None:
        # No plural-form strings are wrapped in this codebase yet, but the seam itself must
        # work: gettext's fallback returns the English singular/plural argument verbatim.
        with i18n.using_locale("en"):
            assert i18n.ngettext_("one item", "{n} items", 1) == "one item"
            assert i18n.ngettext_("one item", "{n} items", 2) == "{n} items"
