# ADR 0002: Add an opt-in AI layer at the edges; the rule engine stays the only thing that produces a finding

## Status

Accepted — 2026-08-21 (owner-directed change of direction).

Amends [ADR 0001](../decisions/0001-local-first-deterministic-cli.md). The
default `check` path keeps every ADR 0001 guarantee. This record adds a
separate, explicitly opt-in command group outside that path.

## Context

ADR 0001 excluded "AI or model-based findings" from version 0.1, and every
public claim followed from it: "no network requests at runtime", "no AI
runtime", the README's `AI Evaluation: N/A` row, and the data card's "makes
no runtime network request".

The owner has directed that the product needs real document-understanding
and explanation features. The places where a language model helps a filer
are concrete: reading a package and proposing the structured facts a manifest
needs, explaining a technical finding in plain language against the official
guidance the rule cites, and drafting a correction. They are also exactly
where an ungrounded model does the most damage: a model that invents a lead
agency, an exemption class, or a requirement that no official source states
is this portfolio's dominant defect, "absence rendered as a value."

The founding boundary does not move. CEQA Preflight never determines legal
sufficiency, never says a filing "will be accepted", and never evaluates
whether an exemption or a determination was correct. A model in the loop must
be prevented from doing those things by code, not by prompt wording.

## Decision

Add a model-backed layer in four bounded roles, behind an explicit `ai`
command group that is never invoked by `check`, `init`, `synth`, `rules`, or
`pilot`.

1. **Field extraction structures input; it does not decide.** `ai extract`
   reads the package's PDF text through the same bounded, process-isolated
   inspection path `check` uses, and asks the model to propose the facts a
   manifest carries (filing form kind, document category, project title, lead
   agency, county, city, SCH number, exemption citation, and the like). Every
   proposed value must carry a verbatim quote from the document text. The
   tool verifies each quote programmatically against the extracted text; a
   value whose quote does not appear is downgraded to `unknown` with the
   reason recorded. Fields the text does not answer are `unknown`, never
   guessed. The output is a draft manifest the user reviews and confirms.
   `check --manifest` then runs on the confirmed facts exactly as it does
   today; the model's output never reaches the rule engine directly.

2. **The rule engine is unchanged and is the only source of findings.** No
   rule consumes model output. No model output is a finding, a status, a
   remediation, or a `not_run` entry. The JSON report schema does not gain an
   AI field.

3. **Explanations and correction drafts narrate; the committed corpus is the
   evidence.** `ai explain` and `ai draft-fix` take an existing JSON report.
   For each finding they retrieve passages from `corpus/`, the committed,
   hashed, dated text of the official sources the rule cites, and ask the
   model for a plain-language explanation (or a concrete correction draft)
   in which every substantive claim cites a passage by identifier and quotes
   it verbatim. A verifier checks each quote against the corpus text before
   anything is displayed. A claim whose quotes do not all verify is withheld
   and the withheld count is shown. Output is labeled AI-generated, advisory,
   and carries the existing non-legal disclaimer. A rule whose citation is
   not an official source (the self-cited FILE-004 and FILE-005) is explained
   only from the project's own documented reasoning and says so.

4. **Legal-sufficiency questions are refused, in every phrasing.** `ai ask`
   answers questions about the technical findings in a report and nothing
   else. A deterministic guard runs before the model and again on the
   model's output. Any form of "is this filing legally sufficient", "will it
   be accepted", "will it survive challenge", "is this exemption valid", or
   "did the agency comply" is refused with a redirect to the objective
   findings and to qualified review. The refusal suite in `evals/` is the
   evaluation that matters most and its tolerance is zero.

Consequential choices:

- **Provider and model.** The public `anthropic` SDK; `claude-sonnet-5` is the
  configurable default there. Amazon Bedrock is supported through the same SDK
  for environments that have it, and defaults to `claude-sonnet-4-6`, the model
  every recorded eval run was produced on — Sonnet 5 answers 403 on the account
  this project has. The two defaults differ deliberately; either is overridden
  by `--model`. The credential comes only from the environment.
  No key is written to any file, and the tool never logs document text.
- **Lazy import, no new default dependency.** The SDK is an optional extra
  (`ceqa-preflight[ai]`) imported only inside the `ai` commands. The default
  path has no new import, no new dependency, and byte-for-byte unchanged
  output, which a test asserts.
- **Honest refusals.** A PDF with no text layer is reported as such and not
  extracted (OCR remains out of scope). A document the model cannot identify
  as a CEQA notice yields no fields. A field the text does not state is
  `unknown`.
- **Evaluation is committed and model-independent.** `evals/` holds the
  cases, the harness, and recorded results for: extraction against the
  structured metadata CEQAnet publishes for the same real filings (per-field
  exact match, abstained-when-absent, and the defect, filled-when-absent);
  the legal-sufficiency refusal suite; citation grounding; and a check that
  an explanation never upgrades an advisory finding into a determination.
  Recorded numbers carry provider, model, prompt version, commit, and date; a
  test rejects results without that provenance. Numbers are committed only
  from a recorded live run; otherwise the result is `not_run`.
- **Real filings are referenced, not committed.** The real-filing eval stores
  CEQAnet document identifiers, hashes, gold metadata, and extraction
  results, plus the fetch script. The PDFs themselves are fetched on demand
  and are never committed.

## Consequences

- Public claims are rewritten in the same change series. "No network requests
  at runtime" becomes "none on the default path; the opt-in `ai` commands send
  document text to the configured model provider." The data card, threat
  model, README, and conformance table say so. `AI Evaluation` moves from
  N/A to Applies with the committed harness as evidence.
- Sending document text to a model provider is a new data flow. Filing
  packages may contain personal contact details. The `ai` commands state this
  before running, and an operator who cannot accept the provider's processing
  terms must not use them. The default path is unaffected.
- The i18n release gate ([docs/I18N.md](../I18N.md), issue #39) gains
  surface area: AI user-facing strings are localizable content. Until the
  gettext seam exists they are kept in one module so the seam can wrap them.
- Runtime cost, latency, and provider availability become product
  properties of the `ai` commands only. Every `ai` command fails closed: on
  any provider error it produces no draft and no explanation, and says why.

## Alternatives considered

- **Keep ADR 0001's exclusion.** Rejected by the owner: a purely deterministic
  checker leaves the hardest part of preparing a package (knowing what the
  package says) to the filer.
- **Let rules consume extracted fields directly.** Rejected. A model output
  that flows into a rule without confirmation makes the finding
  unfalsifiable. The confirmed manifest is the boundary.
- **Free-text Q&A over the package.** Rejected. Anchoring `ai ask` to the
  findings in a report keeps the question space bounded and makes the
  refusal guard tractable.
- **Vector retrieval over the corpus.** Not needed. Retrieval is scoped by the
  rule's citation and ranked lexically; it is inspectable and needs no
  additional provider.
