"""Tests for scripts/check_rule_sources.py.

No test in this file makes a real network call: `fetch` is always a fake injected in place of
the script's real `urllib`-backed default, per the script's own no-hidden-network-path rule.
"""

from __future__ import annotations

import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

SCRIPTS = str(Path(__file__).resolve().parent.parent / "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import check_rule_sources  # type: ignore[import-not-found]  # noqa: E402
from check_rule_sources import UrlCheck  # type: ignore[import-not-found]  # noqa: E402


def _run(fetch: check_rule_sources.Fetcher, argv: list[str] | None = None) -> int:
    return check_rule_sources.main(argv or [], fetch=fetch)


class RulesByUrlTests(unittest.TestCase):
    def test_built_in_catalog_has_source_urls(self) -> None:
        by_url = check_rule_sources._rules_by_url()
        self.assertGreater(len(by_url), 0)
        for url, rule_ids in by_url.items():
            self.assertTrue(url.startswith("https://"))
            self.assertGreater(len(rule_ids), 0)

    def test_every_rule_is_attributed_to_a_url(self) -> None:
        by_url = check_rule_sources._rules_by_url()
        catalog = check_rule_sources.default_catalog()
        attributed = sum(len(rule_ids) for rule_ids in by_url.values())
        self.assertEqual(attributed, len(catalog.rules))


class MainVerdictTests(unittest.TestCase):
    def test_all_urls_ok_passes(self) -> None:
        self.assertEqual(_run(lambda url, timeout: UrlCheck(True, "200 HEAD")), 0)

    def test_any_broken_url_fails(self) -> None:
        self.assertEqual(_run(lambda url, timeout: UrlCheck(False, "HTTP 404 GET")), 1)

    def test_reports_the_rule_ids_that_cite_a_broken_url(self) -> None:
        seen: list[str] = []

        def fetch(url: str, timeout: float) -> UrlCheck:
            seen.append(url)
            return UrlCheck(True, "200 HEAD")

        self.assertEqual(_run(fetch), 0)
        by_url = check_rule_sources._rules_by_url()
        self.assertEqual(sorted(seen), sorted(by_url))

    def test_timeout_flag_is_forwarded_to_fetch(self) -> None:
        seen_timeouts: set[float] = set()

        def fetch(url: str, timeout: float) -> UrlCheck:
            seen_timeouts.add(timeout)
            return UrlCheck(True, "200 HEAD")

        self.assertEqual(_run(fetch, ["--timeout", "3"]), 0)
        self.assertEqual(seen_timeouts, {3.0})


class DefaultFetchTests(unittest.TestCase):
    """Exercise the real `_fetch`'s branches with `urlopen` mocked — never real network I/O."""

    def test_non_http_scheme_is_rejected_without_opening_a_connection(self) -> None:
        with mock.patch.object(check_rule_sources.urllib.request, "urlopen") as urlopen:
            result = check_rule_sources._fetch("file:///etc/passwd", timeout=1.0)
        urlopen.assert_not_called()
        self.assertFalse(result.ok)
        self.assertEqual(result.detail, "unsupported URL scheme")

    def test_connection_failure_is_reported_as_broken(self) -> None:
        with mock.patch.object(
            check_rule_sources.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError("mock: name resolution failed"),
        ):
            result = check_rule_sources._fetch("https://example.invalid/", timeout=1.0)
        self.assertFalse(result.ok)
        self.assertIn("failed", result.detail)

    def test_http_404_is_reported_as_broken(self) -> None:
        with mock.patch.object(
            check_rule_sources.urllib.request,
            "urlopen",
            side_effect=urllib.error.HTTPError("https://example.com/", 404, "Not Found", {}, None),
        ):
            result = check_rule_sources._fetch("https://example.com/", timeout=1.0)
        self.assertFalse(result.ok)
        self.assertIn("404", result.detail)

    def test_head_405_falls_back_to_a_successful_get(self) -> None:
        response = mock.MagicMock()
        response.status = 200
        response.__enter__.return_value = response
        response.__exit__.return_value = False

        def fake_urlopen(request: object, timeout: float) -> mock.MagicMock:
            method = request.get_method()  # type: ignore[attr-defined]
            if method == "HEAD":
                raise urllib.error.HTTPError(
                    "https://example.com/", 405, "Method Not Allowed", {}, None
                )
            return response

        with mock.patch.object(
            check_rule_sources.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            result = check_rule_sources._fetch("https://example.com/", timeout=1.0)
        self.assertTrue(result.ok)
        self.assertEqual(result.detail, "200 GET")

    def test_both_methods_rejected_is_reported_as_broken(self) -> None:
        def fake_urlopen(request: object, timeout: float) -> None:
            raise urllib.error.HTTPError(
                "https://example.com/", 405, "Method Not Allowed", {}, None
            )

        with mock.patch.object(
            check_rule_sources.urllib.request, "urlopen", side_effect=fake_urlopen
        ):
            result = check_rule_sources._fetch("https://example.com/", timeout=1.0)
        self.assertFalse(result.ok)


if __name__ == "__main__":
    unittest.main()
