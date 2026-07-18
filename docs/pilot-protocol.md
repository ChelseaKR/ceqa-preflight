# Permissioned pilot protocol

CEQA Preflight remains pre-alpha until this protocol is completed. The pilot is
about whether the tool is accurate and useful, not about collecting a corpus of
environmental-review records.

Prospective participants and coordinators should begin with the
[pilot partner kit](pilot-partner-kit.md), which includes a non-legal
authorization template, private reviewer rubric, outreach email, and stop
conditions.

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
ID, finding status, controlled disposition, severity, and elapsed time. Do not
put a rationale, document name, project title, contact detail, or extracted
text in the evidence file.

Run `ceqa-preflight pilot init ./pilot-evidence` to create the two CSV templates
and `ceqa-preflight pilot summarize --reviews ... --baseline ...` to calculate
aggregate precision, high-severity false-negative rate, and median report time.
The summarizer rejects free text and spreadsheet-formula-like cells.

## Stop/go decision

Do not publish a public v0.1 unless there is at least 90% precision on
actionable automated findings, fewer than 5% unresolved high-severity false
negatives in the sampled scope, a median preflight time under five minutes,
and a documented remediation plan for every material accessibility or security
issue. A failure to meet a threshold means narrow, revise, or stop; it does not
justify widening the product scope.
