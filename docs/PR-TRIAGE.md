# Open pull request triage

Read-only triage of the six open pull requests, all based on `main`, taken at
`origin/main` = `f2cb3ce` (`feat(i18n): render reports in Spanish through an
explicit, non-inferring gettext seam (#60)`).

Nothing in this pass merged, closed, commented on, approved, re-ran, or pushed
to any pull request. Every merge state below was recomputed locally with
`git merge-tree --write-tree` rather than read off the GitHub label, and every
failing check was read from its own job log rather than from its summary.

## Summary

| PR | Base | Real merge state | CI reality | Recommendation |
| --- | --- | --- | --- | --- |
| #61 | `main` | Conflicting, 3 files, 1 commit behind | No run ever dispatched. Starved by its own conflict | `needs work` |
| #59 | `main` | Clean, up to date | Genuinely red, `uv.lock` really is stale. Born red by ecosystem misconfiguration | `needs work` |
| #58 | `main` | Clean, 2 commits behind | All six checks green | `merge after rebase` |
| #53 | `main` | Conflicting, 14 files, 4 of them add/add | Windows red on a real defect of its own | `close as superseded by #60` |
| #52 | `main` | Clean, 2 commits behind | All six checks green | `merge after rebase` |
| #51 | `main` | Clean, 1 commit behind | All six checks green | `merge after rebase` |

Group counts: 3 ready once updated (#51, #52, #58), 2 needing author work
(#59, #61), 1 to close (#53).

## Why "behind" blocks anything at all

`.github/rulesets/main.json` sets `strict_required_status_checks_policy: true`
on the default branch, with exactly one required context,
`Verify on ubuntu-latest / Python 3.12`. Strict mode means a branch must be up
to date with `main` before it can merge, which is why #51, #52 and #58 are
green in every check and still not mergeable. For those three, updating the
branch is the whole of the remaining work.

## Why #61 has no checks at all

`ci.yml` and `security.yml` both trigger on `pull_request`, with `push`
restricted to `main`. GitHub cannot compute a merge ref for a conflicting pull
request, so no `pull_request` event is dispatched. `gh run list --branch
fix/checks-that-cannot-fail` returns nothing: not one run, of any workflow, at
any time. #61's checks are absent and starved, not failed. Its required
context cannot appear until the conflict is resolved.

---

## #61 Seven checks that could not fail, and the CI ecosystem that made every dep PR red

- Base: `main`. Head: `fix/checks-that-cannot-fail`. 8 commits ahead, 1 behind.
- Real merge state: CONFLICTING in `CHANGELOG.md`,
  `src/ceqa_preflight/rules/common.py`, `src/ceqa_preflight/rules/filing.py`.
  All three are content conflicts, not add/add. `rule_engine.py` and every test
  file auto-merge.
- CI reality: absent, never dispatched. See the section above. Not a failure
  and not a signal of quality either way.

### What it changes

Seven fixes of one shape, a check reporting a conclusion it had not measured,
plus a test for each. The PR description claims each of the seven is now
reachable. Each was checked against the code rather than the description.

| Claim | Verified? | How |
| --- | --- | --- |
| `dependabot.yml` `pip` to `uv` | Yes | `test_python_updates_use_the_ecosystem_that_maintains_the_lockfile` asserts `uv` present and `pip` absent. `origin/main` still declares `pip`, so the test fails on today's `main` and passes on the branch. Reachable in both directions. A second test forbids `--frozen` and requires `--locked` in every `uv sync` line across `.github/workflows/*.yml`, and asserts the collected list is non-empty first, so it cannot silently glob nothing. All three workflows are `.yml`, so the glob matches. |
| Engine materializes outcomes | Yes | `RuleEngine.run` now builds the full list inside `try` and extends only in the `else` branch. `test_a_check_that_raises_midway_publishes_none_of_its_outcomes` uses a real generator that yields a PASS then raises, and asserts the finding list is exactly one WARNING. Fails against `main`'s `findings.extend(...)`. |
| PDF object graph, issue #54 | Yes, at both layers | New `_Resolution` sentinel separates "unresolvable indirect reference" (`KeyError`, `TypeError`, `ValueError` from `get_object`) from "absent key" (`AttributeError`). `structure_tree_present` becomes `None` rather than `False` when `/Root` never resolved. Critically, the inspector side is tested for real: `test_an_unresolvable_object_graph_is_recorded_not_reported_as_clean` monkeypatches `PdfReader` with a reader whose `/Root` raises, then asserts `active_content_readable is False`, `structure_tree_present is None`, and a non-empty `parser_warnings`. The rule side is tested separately. Neither test stands in for the other. |
| Empty denominator across seven package rules | Yes | `_conclude` already existed on `main` and already refused to pass on `examined == 0`. The defect was that `check_file_size`, `check_non_pdf_documents`, `check_filename_portability`, `check_duplicate_hashes`, `check_document_categories`, `check_manifest_references` and `check_descriptive_filenames` did not call it. Confirmed by reading `origin/main`: only six of the fourteen `check_*` functions call `_conclude`. `test_an_empty_package_produces_no_passing_check_at_all` asserts the set of passing rules is empty, which fails on `main`. |
| NOE-003 / NOD-003 given a reachable failure | Yes | This is the "candidate set makes failure unreachable" shape, and the fix is real. `_form_candidates` selects on `primary AND category == expected`, so the pass was true by construction. The new `_miscategorized_primaries` reads the inventory directly and returns a FAILURE for a document marked primary carrying a different declared category. Tests cover the failure, the "category absent so stay indeterminate" case, and the "facts unparseable so stay indeterminate" case, which is the fail-closed direction. |
| Duplicate manifest paths, issue #55 | Yes | A pydantic `model_validator(mode="after")` on `PackageManifest` rejects repeated paths, compared after normalization so `a\b.pdf` and `a/b.pdf` collide. Three tests: the reject, the normalized reject, and a distinct-paths accept so the guard is not simply always-on. |
| Eval provenance guard | Yes | The old assertion was `{"refusal"} <= suites` derived from the result files themselves, which is circular. The new `SUITE_DIRECTORIES` is derived from `EVALS.glob("*/run.py")` and both directions are asserted. This is exactly the glob-matching-nothing shape, so it was checked against the tree: `evals/extraction/run.py`, `evals/grounding/run.py` and `evals/refusal/run.py` all exist, and all three have a `results/` directory with a committed JSON. The glob matches, and if it ever matched nothing the first assertion fails loudly rather than passing vacuously. |

Seven of seven verified reachable. No test in this PR pins a defect as correct
behaviour, and no assertion was found that would pass in both the buggy and the
fixed state.

### Correctness verdict

The code is correct, and the PR description is accurate about its own scope and
its own blockers, including the parts it declines to do. Two smaller
observations, neither blocking:

- `_contains_action` and `_name_tree_item_count` now record a depth-bound
  exhaustion at depth 12 as a resolution failure. That is the conservative
  direction (PDF-006 goes to `manual` rather than `pass`), and it matches the
  repository's fail-closed posture, but it does mean an unusually deep but
  entirely benign object graph will be reported as unexaminable rather than
  clean. Worth a sentence in the changelog entry.
- `check_file_size` passes its per-file indeterminate outcomes into `_conclude`
  as findings, which suppresses the legitimate pass for the files whose size
  *was* read. That is the same shape the author fixed for FILE-002 in
  `check_duplicate_hashes` by disclosing the excluded files separately. Applying
  the same treatment to `check_file_size` would make the two consistent.

### Why not simply "merge after rebase"

Resolving the three conflicts is necessary but not sufficient, and the blocker
is real rather than procedural. `#60` merged into `main` and wrapped every
`message=` and `remediation=` in `_()`, extracted to
`src/ceqa_preflight/locales/messages.pot`. `make verify` runs
`scripts/check_i18n.py`, whose `_flag_failures` fails on any message with an
empty `msgstr`, and whose `_extraction_failures` fails when a wrapped string
disappears from source or a new one appears without being extracted. #61
rewrites many of those wrapped messages and adds roughly 28 new user-facing
strings. After a rebase the gate fails, in both directions, until the catalogs
are regenerated, and regenerating them requires a Spanish translation for every
new string.

The author declined to write those translations and said so, on the grounds
that issue #49 reserves the Spanish terminology review for a qualified reader.
That is the correct call for this repository, and it is why the recommendation
is `needs work` rather than `merge after rebase`.

### Recommendation: `needs work`

Exactly what:

1. Update the branch onto `main` and resolve `CHANGELOG.md`,
   `rules/common.py` (9 hunks) and `rules/filing.py` (1 hunk, two import lines).
2. Wrap every new and rewritten `message=` / `remediation=` in `_()`, keeping
   `main`'s wrapping rather than reverting to bare f-strings. Note that
   `_conclude`'s pass messages are built with f-strings on this branch and with
   `.format()` on `main`; the gettext form is the one that survives.
3. Run `make i18n-update` and commit the regenerated `messages.pot` and the
   updated `.po` and `.mo` files.
4. Obtain reviewed Spanish strings for the new messages (issue #49). Until then
   `make verify` cannot pass, by design.

Optionally, apply the `check_file_size` disclosure fix noted above in the same
pass.

---

## #59 chore(deps-dev): update anthropic requirement from <1,>=0.125 to >=0.125,<2

- Base: `main`. Author: Dependabot. 1 commit ahead, 0 behind, so it is current
  with `main`.
- Real merge state: merges cleanly (`git merge-tree` exits 0). `BLOCKED` is
  purely the failing required check.
- CI reality: genuinely red, and born red, but the failure is a true one.

Every failing job, on all three platforms plus Application security, dies at
the same step with the same message:

```
uv sync --all-groups --locked
error: The lockfile at `uv.lock` needs to be updated, but `--locked` was provided.
```

This was verified rather than inferred. On the head of #59, `pyproject.toml`
declares `anthropic>=0.125,<2` while `uv.lock` still records
`specifier = ">=0.125,<1"` at three places. The lockfile really is stale and
`--locked` is correctly refusing it. The gate is right; the pull request is
incomplete.

Root cause confirmed: `origin/main`'s `.github/dependabot.yml` declares
`package-ecosystem: pip` against a project that locks with `uv` and installs
with `uv sync --locked` in all three workflows. The `pip` ecosystem edits
`pyproject.toml` and does not know `uv.lock` exists, so every Python dependency
pull request it opens is born red. #61 changes that entry to
`package-ecosystem: uv` and adds a test pinning the pairing.

### Would #61's fix make #59 green as it stands?

No. Changing `dependabot.yml` on `main` does not retroactively add a lockfile
update to a branch Dependabot already pushed. #59 would still carry a stale
`uv.lock`. Dependabot must recreate the pull request under the `uv` ecosystem,
which updates the manifest and the lockfile in one commit.

### Recommendation: `needs work`

Exactly what: land #61's `dependabot.yml` change first, then close #59 and let
the next weekly `uv` run recreate it with the lockfile included. If the bump is
wanted sooner, run `uv lock` on the branch and commit the result, which is a
maintainer action rather than something Dependabot will do on a `pip` branch.
Do not "fix" this by relaxing `--locked` to `--frozen`; #61 adds a test that
forbids exactly that.

---

## #58 fix(pdf-inspector): count pypdf's logging-based repair warnings toward confidence

- Base: `main`. Head: `bugfix/sweep-2026-08-23`. 1 commit ahead, 2 behind.
- Real merge state: clean. `git merge-tree` against `main` exits 0 with no
  conflict.
- CI reality: all six checks green, on its own head from 2026-08-27.

### What it changes

Under `strict=False`, pypdf reports the recoverable problems it worked around
(a rebuilt xref table, a missing EOF marker) through the `logging` module via
its own `logger_warning` helper, not through `warnings.warn`. The existing
`warnings.catch_warnings` block therefore never saw them, and a document pypdf
had to repair was measured as cleanly as one with no problems at all. The PR
adds a `_LogEmittedHandler` that records only *whether* a record was emitted,
never the message text, and folds that into the same
`_warning_label("PDF parser reported warnings")` path that already lowers
confidence. It also sets `logger.propagate = False` for the duration so a
caller's terminal is not filled with library-internal parser chatter, and
restores it in `finally`.

Recording only the boolean, rather than the message, is the right choice for a
tool that must not retain document-derived content.

### Correctness verdict

Correct, narrowly scoped, and it is the same class of defect #61 addresses:
"not measured" reading as "measured clean". Two notes:

- This is **not** contained in #61 and #61 is **not** a superset of it.
  Verified: `git merge-base --is-ancestor 455e89c origin/fix/checks-that-cannot-fail`
  returns false, and #61's `pdf_inspector.py` diff contains no `logging`,
  `_LogEmitted` or `propagate`. The two are independent fixes to the same file
  and they conflict with each other (see the ordering section).
- `pdf_inspector.py` carries no gettext wrapping on `main` (zero `_(` calls,
  no `i18n` import), so this PR does not disturb the i18n gate.

### Recommendation: `merge after rebase`

Update the branch onto `main` so the strict status check policy is satisfied.
No regeneration step, no changelog reposition, no translation. Merge it before
#61 so that #61's larger `pdf_inspector.py` rewrite absorbs it rather than the
other way round.

---

## #53 feat(i18n): merge the gettext seam, locale selection, EN/ES catalogs, parity gate

- Base: `main`. Head: `claude/roadmap-remainder-scope-sagguy`. 1 commit ahead,
  2 behind. Opened 2026-08-23.
- Real merge state: CONFLICTING in 14 files, four of them add/add:
  `babel.cfg`, `scripts/check_i18n.py`, `src/ceqa_preflight/i18n.py`,
  `tests/test_i18n.py`. Content conflicts in `CHANGELOG.md`, `Makefile`,
  `docs/I18N.md`, `docs/ROADMAP.md`, `pyproject.toml`, `checker.py`, `cli.py`,
  `reporting.py`, `templates/report.html.j2`, `uv.lock`.
- CI reality: five checks green, `Verify on windows-latest` red.

### How stale it really is

Completely, in its core. This is not a branch that drifted; it is a second,
independent implementation of a feature that has since been implemented and
merged another way. `main` already carries, from #60:

```
babel.cfg
docs/I18N.md
docs/adr/0003-explicit-locale-selection-with-no-inference.md
scripts/check_i18n.py
src/ceqa_preflight/i18n.py
src/ceqa_preflight/locales/messages.pot
src/ceqa_preflight/locales/{en,es}/LC_MESSAGES/messages.{po,mo}
tests/test_i18n.py
```

The four add/add conflicts are the proof: both sides create the same files with
unrelated contents. The two implementations even disagree on the gettext domain,
`ceqa_preflight.pot` / `.po` / `.mo` on #53 against `messages.pot` / `.po` /
`.mo` on `main`, so a naive resolution would ship two parallel catalog trees.

### The Windows failure is #53's own defect

`ModuleNotFoundError: No module named 'babel'`, raised from
`scripts/check_i18n.py` line 27, on Windows only. #53's Makefile invokes the
gate as `uv run python3 scripts/check_i18n.py`. On Windows `python3` does not
resolve to the project interpreter, so the script runs outside the environment
`uv sync` populated and Babel is not importable, even though #53 correctly adds
`babel>=2.14,<3` to the dev group and to `uv.lock`. `main`'s merged version uses
`uv run python scripts/check_i18n.py` and is green on all three platforms. The
defect is real, it is #53's alone, and it is already fixed on `main`.

### The parity gate is the weaker of the two

Checked specifically for the "check that cannot fail" shape, and it is present.
#53's `scripts/check_i18n.py` has **no assertion that a message is actually
translated**. Its `_key_parity_errors` compares msgid *sets* only, and its
`_placeholder_errors` opens with `if not message.id or not message.string:
continue`, which skips every untranslated entry rather than reporting it. A
Spanish catalog carrying every msgid with an empty `msgstr` would satisfy
"EN/ES parity" in full and the gate would exit 0. `main`'s version has
`_flag_failures`, which fails on both `fuzzy` and empty `msgstr`, and it also
adds a source-identity check (English `msgstr` must equal its `msgid`), a
declared-`Language:` header check, and a byte comparison of the compiled `.mo`,
none of which #53 has.

In fairness, the gap is latent rather than active: #53's shipped Spanish catalog
is genuinely populated (105 translated entries, 0 empty). The gate simply could
not have caught it if it were not.

One further defect: #53's `babel.cfg` omits `extensions = jinja2.ext.i18n` from
its `[jinja2:]` section, which `main`'s has. Without that extension Babel's
Jinja extractor does not parse `{% trans %}` blocks, so template prose would not
reach the template file.

### The one thing #53 has that `main` does not

#53 localizes the opt-in `ai` command group: 183 changed lines in
`src/ceqa_preflight/ai/messages.py` and 53 in `src/ceqa_preflight/ai/cli.py`.
Verified that #60 did not cover this: every file under
`src/ceqa_preflight/ai/` on `main` contains zero `_()` calls, and
`ai/messages.py`'s own docstring still says "Until that seam exists". That
coverage is worth having, but it is entangled with #53's incompatible i18n
module and cannot be lifted out by resolving conflicts.

### Recommendation: `close as superseded by #60`

Do not merge this. It would install a second, weaker i18n implementation
alongside the merged one, with a gate that cannot fail on an untranslated
message, a `babel.cfg` that would stop extracting template prose, and a Windows
invocation already known to break. Open a fresh, small pull request against
`main`'s seam to wrap the `ai` command group's prose in `_()`, which is the only
part of #53 that is not already delivered.

---

## #52 chore(deps): bump astral-sh/setup-uv from 10.0.0 to 10.0.1

- Base: `main`. Author: Dependabot. 1 commit ahead, 2 behind.
- Real merge state: clean, `git merge-tree` exits 0.
- CI reality: all six checks green.

Changes one pinned SHA in three workflows (`ci.yml`, `release.yml`,
`security.yml`), each with its `# v10.0.1` comment updated to match. Correct.

**Context correction:** the `pip` versus `uv` story does not apply here. This is
a `github-actions` ecosystem update. It was never born red and it is not red
now; it is blocked solely by the strict up-to-date requirement in the ruleset.

### Recommendation: `merge after rebase`

Update the branch. Nothing else.

---

## #51 chore(deps): bump the codeql-action group across 1 directory with 2 updates

- Base: `main`. Author: Dependabot. 1 commit ahead, 1 behind.
- Real merge state: clean, `git merge-tree` exits 0.
- CI reality: all six checks green, re-run 2026-08-27.

Bumps `github/codeql-action/init` and `github/codeql-action/analyze` together
from v4.37.6 to v4.37.8 in `security.yml`. Both moved in one pull request,
which is exactly what the `codeql-action` group in `dependabot.yml` exists to
guarantee, and which matters because since CodeQL Action 3.30.4 a half-applied
bump hard-errors rather than warning. Correct.

**Context correction:** same as #52. `github-actions` ecosystem, never born red,
blocked only by the strict up-to-date requirement.

### Recommendation: `merge after rebase`

Update the branch. Nothing else.

---

## Stack analysis

There is no stack. Every open pull request targets `main` directly, and no PR's
head is any other PR's base, so nothing here would auto-close as a side effect
of merging something else.

```
main (f2cb3ce)
 |
 +-- #51  codeql-action 4.37.6 -> 4.37.8      (independent, 1 commit)
 +-- #52  setup-uv 10.0.0 -> 10.0.1           (independent, 1 commit)
 +-- #58  pdf-inspector logging warnings      (independent, 1 commit)
 +-- #59  anthropic <1 -> <2                  (independent, 1 commit)
 +-- #61  fail-closed sweep                   (independent, 8 commits)
 +-- #53  i18n seam, second implementation    (independent, 1 commit)
           ^ superseded by #60, already merged into main
```

The cumulative-snapshot antipattern was specifically checked for and is **not
present**. Tested with two-dot `git diff origin/main..origin/<head>` and
`git cherry origin/main origin/<head>` on all six heads: every branch reports
its commits as `+` (not in `main`), and no branch's diff against `main` is
empty. #61 in particular is not a rebased superset of #58: verified directly
with `git merge-base --is-ancestor`, which returns false, and by the absence of
#58's `_LogEmittedHandler` from #61's `pdf_inspector.py` diff. Both fixes are
needed and they overlap textually.

The one relationship that does exist is a supersession by an *already merged*
pull request, #60 over #53, which is the same trap in a different form: the work
is delivered, but #53 will never auto-close because #60 did not come from it.

## Non-diff hazards

**Changelog section placement: hazard does not apply.** `CHANGELOG.md` on
`origin/main` has exactly one section heading, `## Unreleased` at line 7. There
is no released section for a hunk to land inside. Both #61 and #53 open their
changelog hunk at `@@ -6,6 ...`, inserting immediately below that heading, which
is correct in both cases. They conflict with each other and with `main`'s
existing entry only because all three add prose at the same offset, which is an
ordinary textual conflict.

**Two PRs appending to the same file: checked, no collision.** #51 and #52 both
modify `.github/workflows/security.yml`. They touch different jobs at different
line ranges (#51 the CodeQL steps around lines 46 to 61, #52 the `setup-uv` step
around line 17). `git merge-tree` between the two branch heads reports no
conflict, and neither is an append-to-end change, so there is no path to a
silently merged syntax error. They can be merged in either order.

**Local `make verify` exit code.** `make verify` exits 2 in this working tree
because `ruff` walks the untracked `STANDARDS/` directory, which belongs to a
different process. That is expected and is not a finding against any pull
request. `STANDARDS/` and `docs/plans/` were left untracked, unstaged, and
unmodified throughout this triage, and were deliberately not added to
`.gitignore` or to ruff's `extend-exclude`.

## Order of operations

Merge in this order. Steps 1 through 3 are independent of each other; the order
among them only matters in that each merge makes the next one behind.

1. **#51** and **#52** (either order). Update branch, confirm the required
   `Verify on ubuntu-latest / Python 3.12` context reports, merge. No
   regeneration.
2. **#58**. Update branch, merge. No regeneration. Merge this *before* #61: the
   two conflict in `pdf_inspector.py`, and #61's rewrite of that file is far the
   larger, so it is cheaper for #61 to absorb #58 than the reverse. If #61 lands
   first, #58 must be rewritten by hand against the `_Resolution` restructuring.
3. **#53**. Close as superseded by #60. No merge, no regeneration. Optionally
   open a follow-up for the `ai` command group prose.
4. **#61**. Blocked on human work. When it returns:
   - update onto `main` and resolve `CHANGELOG.md`, `rules/common.py`,
     `rules/filing.py`;
   - **regeneration step:** `make i18n-update`, then commit the regenerated
     `src/ceqa_preflight/locales/messages.pot` and every `.po` and `.mo`. This
     is mandatory. `make verify` runs `scripts/check_i18n.py`, which fails both
     when a wrapped string is missing from the template and when a catalog
     message is untranslated;
   - the Spanish strings for roughly 28 new messages need the reviewer named in
     issue #49. There is no way around this that does not involve inventing
     translations;
   - **changelog reposition:** none needed, but the entry must be re-placed
     under `## Unreleased` after the conflict resolution rather than left where
     the three-way merge puts it, and it should now also mention #58's
     logging-warning fix if #58 landed first.
5. **#59**. After step 4 has put `package-ecosystem: uv` on `main`, close #59
   and let the weekly `uv` run recreate it.
   - **regeneration step if merging by hand instead:** `uv lock` on the branch,
     committed. Without it `uv sync --locked` fails on all three platforms and
     on Application security.

## Verified versus taken on trust

### Verified in this pass

- Merge state of all six branches, recomputed with
  `git merge-tree --write-tree origin/main origin/<head>`, and the exact
  conflicting file list for #61 (3 files) and #53 (14 files, 4 add/add).
- Ahead/behind counts for all six, via `git rev-list --left-right --count`.
- Absence of any stack, and absence of the cumulative-snapshot antipattern, via
  two-dot `git diff` and `git cherry` on all six heads.
- #61 does not contain #58, via `git merge-base --is-ancestor`, and the two
  conflict in `pdf_inspector.py`.
- #61's seven claims, each read in the test and gate code rather than the
  description. All seven can fail. The eval-suite glob and the workflow glob
  were both checked against the actual tree and both match.
- #59's failure cause, read from four job logs, and confirmed structurally:
  `uv.lock` on that branch still records `specifier = ">=0.125,<1"` while its
  `pyproject.toml` says `<2`.
- #53's Windows failure cause, read from the job log and traced to
  `uv run python3` in its Makefile versus `uv run python` on `main`.
- #53's parity gate cannot fail on an untranslated message, read in
  `_key_parity_errors` and `_placeholder_errors`; `main`'s `_flag_failures`
  can. #53's Spanish catalog is in fact fully populated (105 translated,
  0 empty).
- #53's `babel.cfg` omits `extensions = jinja2.ext.i18n`; `main`'s has it.
- #60 did not localize the `ai` command group: zero `_()` calls across every
  file in `src/ceqa_preflight/ai/`.
- `main`'s `CHANGELOG.md` has exactly one heading, `## Unreleased` at line 7.
- `main` already ships `.mo`, `.po` and `.pot` in the wheel, so #53's
  packaging change adds nothing.
- #51 and #52 do not conflict with each other despite sharing `security.yml`.
- The ruleset's strict up-to-date policy and its single required context.
- #61 has no workflow runs of any kind, and both workflows trigger only on
  `pull_request` (plus `push` to `main`).

### Taken on trust

- **That #51, #52 and #58 stay green after their branches are updated.** Their
  green results are from their current heads, which are behind `main`. The
  merges are textually clean and none of the three touches a file #60 changed
  (`pdf_inspector.py` carries no gettext wrapping), so this is a low risk, but
  it is a prediction and not a measurement. CI was not re-run, per the read-only
  constraint.
- **#61's self-reported local gate results** (`mypy` clean over 36 files,
  `pytest` 385 passed at 94.91 percent, `bandit` clean, `ruff` clean over the 72
  tracked Python files). These are plausible and internally consistent, and the
  reasoning about `STANDARDS/` matches what this working tree does, but the
  suite was not run here. Nothing in this triage depends on those numbers.
- **The claim that #61's changes require roughly 28 new translated strings.**
  The order of magnitude is consistent with the diff, but the exact count was
  not derived by running the extractor.
- **That Dependabot's `uv` ecosystem will in fact open a lockfile-updating pull
  request for `anthropic`.** This follows from the documented behaviour of that
  ecosystem, but it cannot be confirmed until a weekly run happens after #61
  lands.
- **Whether `anthropic` 1.x or 2.x introduces a breaking change** that the
  widened `<2` constraint would admit. That is a compatibility question about a
  third-party package, not a repository-state question, and it was not
  investigated.
