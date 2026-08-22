#!/usr/bin/env python3
"""Maintainer tool: check every rule-catalog source citation URL still resolves.

CEQA Preflight's credibility rests on its rules being *source-cited* — each one points at
specific official guidance (see `docs/audits/rule-source-review-*.md`). Those citations are
reviewed by hand periodically, but link rot on a government site can happen between reviews
and nothing currently notices between them. This script closes that gap: it loads the full
built-in rule catalog, collects the unique source URLs, and issues one HTTP request per URL
to confirm it still resolves.

This is deliberately NOT part of `make verify`, the shipped CLI, or CI. The product itself
makes no runtime network calls (see the roadmap's "no runtime network calls" baseline) and
this script must never become a hidden path around that — it is a maintainer-run, offline-of-
the-product check, the automated counterpart to the manual source review. Run it by hand, or
wire it into a periodic (not per-PR) maintenance job if one exists.

    python3 scripts/check_rule_sources.py [--timeout SECONDS]
"""

from __future__ import annotations

import argparse
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from ceqa_preflight.rule_registry import default_catalog  # noqa: E402

_DEFAULT_TIMEOUT = 10.0
_USER_AGENT = "ceqa-preflight-source-check/1.0 (+https://github.com/ChelseaKR/ceqa-preflight)"


class UrlCheck(NamedTuple):
    ok: bool
    detail: str


Fetcher = Callable[[str, float], UrlCheck]


def _fetch(url: str, timeout: float) -> UrlCheck:
    """Issue one request for `url`, preferring HEAD and falling back to GET.

    Some servers reject HEAD (405) or block requests with no recognizable User-Agent (403);
    both are worth retrying with a full GET before concluding the citation is actually broken.
    """

    if not url.startswith(("http://", "https://")):
        # SourceCitation.require_http_url already enforces this on every catalog entry, but a
        # script that opens arbitrary URLs checks it again at the point of use rather than
        # trusting an upstream validator to have run.
        return UrlCheck(False, "unsupported URL scheme")

    for method in ("HEAD", "GET"):
        request = urllib.request.Request(  # noqa: S310 — scheme checked above; never file:/custom
            url, method=method, headers={"User-Agent": _USER_AGENT}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                return UrlCheck(True, f"{response.status} {method}")
        except urllib.error.HTTPError as error:
            if error.code in {403, 405} and method == "HEAD":
                continue
            return UrlCheck(False, f"HTTP {error.code} {method}")
        except urllib.error.URLError as error:
            return UrlCheck(False, f"{method} failed: {error.reason}")
        except TimeoutError:
            return UrlCheck(False, f"{method} timed out after {timeout:.0f}s")
    return UrlCheck(False, "request failed after HEAD and GET")


def _rules_by_url() -> dict[str, list[str]]:
    catalog = default_catalog()
    by_url: dict[str, list[str]] = {}
    for rule in catalog.rules:
        by_url.setdefault(rule.source.url, []).append(rule.id)
    return by_url


def main(argv: list[str] | None = None, fetch: Fetcher = _fetch) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DEFAULT_TIMEOUT,
        help=f"per-request timeout in seconds (default: {_DEFAULT_TIMEOUT:.0f})",
    )
    args = parser.parse_args(argv)

    by_url = _rules_by_url()
    if not by_url:
        print("No rule source citations were found in the built-in catalog.")
        return 1

    broken: list[tuple[str, list[str], str]] = []
    for url in sorted(by_url):
        rule_ids = sorted(by_url[url])
        result = fetch(url, args.timeout)
        status = "ok" if result.ok else "BROKEN"
        print(f"[{status}] {url}  ({result.detail}) — cited by {', '.join(rule_ids)}")
        if not result.ok:
            broken.append((url, rule_ids, result.detail))

    rule_count = sum(len(rule_ids) for rule_ids in by_url.values())
    print(f"\nChecked {len(by_url)} unique source URL(s) across {rule_count} rule(s).")
    if broken:
        print(f"{len(broken)} citation(s) did not resolve:")
        for url, rule_ids, detail in broken:
            print(f"  - {url} ({detail}) — {', '.join(rule_ids)}")
        return 1
    print("All rule source citations resolved.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
