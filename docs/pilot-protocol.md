# Permissioned pilot protocol

CEQA Preflight remains pre-alpha until this protocol is completed. The pilot is
about whether the tool is accurate and useful, not about collecting a corpus of
environmental-review records.

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

For each finding, record rule ID, actionable/not actionable, true positive,
false positive, indeterminate, reviewer rationale, and time spent. Measure the
median time to first usable report and the share of participants who would use
the tool again.

## Stop/go decision

Do not publish a public v0.1 unless there is at least 90% precision on
actionable automated findings, fewer than 5% unresolved high-severity false
negatives in the sampled scope, a median preflight time under five minutes,
and a documented remediation plan for every material accessibility or security
issue. A failure to meet a threshold means narrow, revise, or stop; it does not
justify widening the product scope.
