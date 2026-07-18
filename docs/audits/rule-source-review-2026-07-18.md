# Filing-rule source review — 2026-07-18

## Decision

The built-in NOD and NOE rule packs remain **experimental**. They are not run
by a default `ceqa-preflight check`; an operator must explicitly use
`--include-experimental`. This is an evidence-control decision, not a finding
that the cited guidance is stale or incorrect.

The rule pack uses official State Clearinghouse guidance as operational context,
but CEQA Preflight does not turn that guidance into a legal-sufficiency
determination. In particular, a manifest declaration, PDF readability result,
or the presence of a named form is only an advisory package-readiness signal.

## Sources checked

The following official Governor's Office of Land Use and Climate Innovation
(LCI) State Clearinghouse materials were reviewed on 2026-07-18:

- [State Clearinghouse document submission guidance](https://lci.ca.gov/sch/document-submission/)
  identifies the NOD and NOE attachments and points to the relevant CEQA
  Guidelines sections.
- [State Clearinghouse FAQ](https://lci.ca.gov/sch/faq/) describes NOD form,
  signature, supporting-document, fee, and posting workflow considerations.
- [CEQA Submit user guide](https://lci.ca.gov/sch/docs/20250911-CEQA-Submit-User-Guide-2025.pdf)
  provides current operational submission context.
- [CEQA Submit pre-submission checklist](https://lci.ca.gov/sch/docs/20250911-CEQA_Submit_Pre-Submission_Checklist_2025.pdf)
  and [common mistakes guidance](https://lci.ca.gov/sch/docs/20250911-Common_Mistakes_to_Avoid_in_CEQA_Submit_2025.pdf)
  inform the rule-pack citations.

These sources support an operator's need to assemble a usable NOD or NOE
submission package. They do not, by themselves, validate that every manifest
category, form-selection heuristic, or technical readability threshold is an
appropriate default automated rule for every agency workflow.

## Rule-pack disposition

| Rule group | Source relationship | Lifecycle decision |
| --- | --- | --- |
| `NOD-001`–`NOD-003`, `NOE-001`–`NOE-003` | Form and attachment guidance supports the package-readiness problem; the checks rely on local manifest labels and PDF inspection. | Experimental until practitioner validation confirms wording, edge cases, and false-positive behavior. |
| `NOD-M001`–`NOD-M003`, `NOE-M001`–`NOE-M003` | The checklist and FAQ support manual prompts about workflow considerations. | Experimental until qualified reviewers confirm the prompts are clear, non-misleading, and appropriately scoped. |
| Common technical rules | Technical file/package integrity checks; no claim of legal sufficiency. | Active, subject to normal test and security controls. |

## Activation evidence still required

Before any NOD/NOE rule becomes `active`, maintain evidence that:

1. At least two qualified CEQA reviewers approve the exact rule wording and
   intended scope.
2. The permissioned pilot has measured the rule against its independent manual
   baseline, including false positives and high-severity misses.
3. The pilot protocol's privacy, accessibility, and go/no-go criteria are met,
   with any limitations documented in the release notes.

No participant package, qualitative note, contact detail, extracted text, or
individual review outcome belongs in this repository.

## Freshness and ownership

This is a desk review, not legal advice or a substitute for qualified CEQA
review. Recheck the official sources before 2026-10-18, before a tagged
release, or earlier if LCI changes CEQA Submit or State Clearinghouse guidance.
The maintainer owns the review; activation requires the independent evidence
listed above.
