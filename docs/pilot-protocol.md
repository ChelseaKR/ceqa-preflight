# Permissioned pilot protocol

CEQA Preflight remains pre-alpha until this protocol is completed. The pilot is
about whether the tool is accurate and useful, not about collecting a corpus of
environmental-review records.

Prospective participants and coordinators should begin with the
[pilot partner kit](pilot-partner-kit.md), which includes a non-legal
authorization template, private reviewer rubric, outreach email, and stop
conditions.

Reviewer calibration and dry runs can use plainly fictional synthetic packages
generated with `ceqa-preflight synth` (see `examples/`); these require no
authorization because they contain no real filing material.

## Entry criteria

- At least three participating organizations, including one public agency and
  one consultant.
- Written permission for every package; participants may withdraw a package at
  any time before analysis.
- At least 20 NOD/NOE packages that are not yet submitted or were recently
  submitted, plus an independent manual-review baseline.
- A qualified CEQA practitioner assigned to label findings.

## Data handling

- Run the CLI locally on a participant-controlled computer whenever possible.
- Do not upload packages, enable telemetry, or commit participant data,
  extracted text, contact details, or screenshots to the repository.
- Assign opaque package IDs in the private pilot register.
- Retain only aggregate metrics and explicitly approved synthetic regression
  cases after the pilot closes.

## Measures

Keep private qualitative notes in a participant-controlled register. For the
aggregate evidence file, record only an opaque package ID, filing type, rule
ID, finding status, controlled disposition, severity, elapsed time, and an
opaque reviewer ID. Do not put a rationale, document name, project title,
contact detail, or extracted text in the evidence file.

Run `ceqa-preflight pilot init ./pilot-evidence` to create the two CSV templates
and `ceqa-preflight pilot summarize --reviews ... --baseline ...` to calculate
the aggregate measures. The summarizer rejects free text and
spreadsheet-formula-like cells.

`reviewer_id` is required on every row and is an opaque identifier assigned in
the private pilot register, never a name or an email address. Two reviewers
labelling the same finding are two rows that differ only in that column; the
summarizer refuses two rows that agree on package, rule, finding status **and**
reviewer.

`synth_seed` and `expected_defect` are the calibration pair. Leave both empty
for a real package. Fill both for a row about a `ceqa-preflight synth` package:
`synth_seed` is an opaque label for the generated set, and `expected_defect` is
the seeded defect name (`scanned`, `fillable-form`, `duplicate`, and so on).
Half of the pair is refused, because a half-filled row cannot be told from a
real-package row.

### What the summary reports

* Aggregate precision, high-severity false-negative rate and median report
  time, as before, plus a 95% Wilson confidence interval and the sample size
  behind the precision figure.
* Per-rule precision with the same interval and `n`, and the number of distinct
  reviewers who labelled that rule against the two-reviewer requirement.
  **This is labelling coverage, not approval.** Approval of a rule's wording is
  the private rubric's "Approve / revise / do not activate" decision, which
  stays with the participant and is deliberately not an evidence-file field.
  Coverage is necessary for two approvals and is not the same as having them.
* Inter-reviewer agreement: percent agreement and Cohen's kappa for every pair
  of reviewers who labelled the same findings of a rule. Kappa is reported as
  *not defined* — never as zero and never as one — when both reviewers used a
  single identical label throughout and chance agreement is therefore total.
* Reviewer calibration: for each reviewer and seeded defect, how many of the
  synthetic findings they identified and how many they missed.

Calibration rows are excluded from the precision, timing and stop/go figures. A
synthetic package is built to contain the defect its rule looks for, so counting
it would raise the very number the pilot exists to measure on real filings.

Any figure whose denominator is zero is reported as *not measurable*, in words,
in the console and as `null` in the JSON. It is never printed as 0%.

## Stop/go decision

Do not publish a public v0.1 unless there is at least 90% precision on
actionable automated findings, fewer than 5% unresolved high-severity false
negatives in the sampled scope, a median preflight time under five minutes,
and a documented remediation plan for every material accessibility or security
issue. A failure to meet a threshold means narrow, revise, or stop; it does not
justify widening the product scope.
