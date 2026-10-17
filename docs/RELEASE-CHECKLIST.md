# Release checklist

This is the release checklist that [DEFINITION_OF_DONE.md](../DEFINITION_OF_DONE.md)
asks a maintainer to review and that the [roadmap](ROADMAP.md#before-first-tagged-release)
requires to be signed before a tag. Every item comes from one of these sources,
named in brackets: `release.yml` ([.github/workflows/release.yml](../.github/workflows/release.yml)
and the reusable `release-authorize.yml` it pins), `claims`
([tests/test_release_claims.py](../tests/test_release_claims.py)), `roadmap`
([docs/ROADMAP.md](ROADMAP.md)), `DoD`, and `ADR 0004`
([the Spanish-catalog decision](adr/0004-ship-spanish-as-labelled-unreviewed-draft.md)).
Nothing here is a new requirement.

Copy the sign-off table at the end into the release pull request or the release
record, and fill it in there. Do not tick boxes in this file.

## 1. Gates that must be closed before the tag

All but the first are decisions or reviews by people that no commit can close.

- [ ] **The Spanish catalog is labelled as an unreviewed machine draft** in
      every place [ADR 0004](adr/0004-ship-spanish-as-labelled-unreviewed-draft.md)
      lists: each Spanish report's disclaimer, the stderr note on every
      non-English run, the catalog header, the README, I18N.md, and the
      composite action's `locale` input. `tests/test_i18n.py` holds the first
      two. On 2026-10-17 this replaced the #49 review as a first-tag condition.
      \[ADR 0004]
- [ ] **Central applicability registry** marks CEQA Preflight as I18N `applies`.
      [I18N.md](I18N.md) release gate item 5; outside this repository. \[roadmap]
- [ ] **Accessibility review of console and HTML output with recorded
      assistive-technology evidence**: keyboard-only navigation, VoiceOver and
      NVDA, 200% browser zoom, automated checks, and a manual WCAG 2.2 AA review
      of representative reports, with defects and remediation logged in the
      release record ([accessibility.md](accessibility.md)). \[roadmap, DoD]
- [ ] **Residual-risk review.** Re-review
      [the residual-risk register](audits/residual-risk-register-2026-07-18.md)
      and commit a dated successor under `docs/audits/`. \[roadmap]
- [ ] **Responsible-tech release record.** Record what the
      [responsible technology audits](RESPONSIBLE-TECH-AUDITS.md#release-gate)
      ask for before each tagged release: test and security results, dependency
      and SBOM review, representative HTML and console accessibility checks,
      source freshness for activated rules (`make audit-sources`,
      `make watch-sources`), and unresolved residual risks. \[DoD]
- [ ] **No open critical vulnerability**: `make audit` clean, and no open
      critical Dependabot, CodeQL, or secret-scanning alert. \[roadmap]
- [ ] **All CI and security checks green** on the commit to be tagged. \[roadmap]
- [ ] **The release remains advisory-only**: no wording in the README, reports,
      or release notes implies a legal determination. \[roadmap]

## Gates before 1.0, not before this tag

- **Spanish/CEQA terminology review, [#49](https://github.com/ChelseaKR/ceqa-preflight/issues/49).**
  A qualified Spanish-language reviewer approves the CEQA terminology and the
  advisory, non-legal framing of the `es` catalog, the Spanish refusal
  phrasings, and the `ai` prompts ([I18N.md](I18N.md) release gate item 3).
  Required before `1.0.0`; until it closes, the unreviewed-draft label stays.
  \[roadmap, ADR 0004]

## 2. The release commit

The tag goes on the commit that declares the version \[claims]. Before the tag
exists, the release-claims tests require the opposite of what they require once
it does, so the commit that dates the release cannot pass CI until its tag is
pushed with it. Prepare it locally, on an up-to-date `main`:

- [ ] `pyproject.toml` `[project] version`, `CITATION.cff` `version`, and
      `src/ceqa_preflight/__init__.py` agree, and equal the tag without its `v`.
      \[release.yml, claims]
- [ ] `CHANGELOG.md`: change `## [X.Y.Z] - Unreleased` to `## [X.Y.Z] - YYYY-MM-DD`,
      the UTC date the tag is created. `release.yml` requires a heading matching
      `^##\s+\[?X.Y.Z\]?`, and the claims tests require that heading to carry a
      date once the tag exists. Keep the empty `## [Unreleased]` heading above it.
      \[release.yml, claims]
- [ ] `CITATION.cff`: add `date-released: "YYYY-MM-DD"`, the same date. It must
      be absent while untagged and present once tagged. \[claims]
- [ ] `README.md`: rewrite every sentence that says the declared version has no
      tag, starting with the `**Status:**` line and the `Release & Versioning`
      row. Once a tag names the version, the claims tests stop requiring the
      disclosure, so nothing will flag a stale one. Do not claim the GitHub
      Release, SBOM, or provenance exist until `release.yml` has produced them.
      `grep -n "no tag\|not tagged\|untagged\|Unreleased" README.md CHANGELOG.md docs/*.md`
      finds the candidates. \[claims]

## 3. Tag, push, dispatch

`release.yml` has only a `workflow_dispatch` trigger. Pushing a tag does not
start it. The pinned authorize job then requires \[release.yml]:

- the run to be dispatched on `main`, with `main` still at the commit it was
  dispatched from;
- a stable SemVer tag, `vX.Y.Z`, with no pre-release suffix;
- an **annotated** tag object, signed with an SSH key listed in
  [.github/allowed_signers](../.github/allowed_signers);
- the tagged commit to be an ancestor of `origin/main`.

A squash or rebase merge rewrites the commit, so a tag on a pull request's head
commit is not on `main` after either. Tag the commit that is on `main`.

```sh
git switch main && git pull --ff-only
# make the section 2 edits, then:
git commit -am "release: v0.1.0"
git tag -s v0.1.0 -m "ceqa-preflight v0.1.0"          # with gpg.format=ssh and user.signingkey set
git -c gpg.ssh.allowedSignersFile=.github/allowed_signers verify-tag v0.1.0
git push --atomic origin main v0.1.0
gh workflow run release.yml --ref main -f tag=v0.1.0
gh run list --workflow release.yml --limit 1           # then: gh run watch <run-id>
```

`--atomic` pushes the commit and the tag together, so `main` is never at a
dated commit with no tag. The push goes straight to `main`, which the committed
ruleset ([.github/rulesets/main.json](../.github/rulesets/main.json)) allows only
to its bypass actor. If that is not available, push the release commit on a
branch, push the tag on that commit, re-run the pull request's checks (they
pass once the tag exists), merge with a **merge commit**, and dispatch.

What the workflow does, so its failures can be read \[release.yml]:

- [ ] `authorize`: verifies the tag as above.
- [ ] `build-and-attest`: checks out the tagged commit with full history,
      requires tag, `pyproject.toml` version, and CHANGELOG heading to agree,
      runs `make verify`, builds the wheel and sdist, writes a CycloneDX SBOM
      (`dist/sbom.cdx.json`), and attests build provenance.
- [ ] `publish-release`: re-reads the tag and refuses if the tag object changed
      since `authorize`, then creates the GitHub Release `ceqa-preflight vX.Y.Z`
      with the assets and generated notes.

## 4. After the Release exists

- [ ] The Release lists exactly one wheel, the sdist, and `sbom.cdx.json`, and
      the provenance attestation is visible. The composite action installs
      exactly one wheel from the Release and refuses anything else. \[DoD]
- [ ] Release notes are published: the generated notes, plus the dated
      CHANGELOG section. \[DoD]
- [ ] The README's install commands, the composite action section ("It cannot
      run yet"), and the `Release & Versioning` row describe the published
      Release, in a follow-up pull request.
- [ ] The central standards register is updated now that the repository has a
      release (README, *Standards conformance*). \[roadmap]

## Sign-off

| Item | Evidence (link) | Signed by | Date |
| --- | --- | --- | --- |
| Section 1 gates closed | | | |
| Release commit prepared and tagged | | | |
| `release.yml` run green, Release published | | | |
| Post-release updates merged | | | |
