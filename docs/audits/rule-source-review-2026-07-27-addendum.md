# Common-rule source review addendum — 2026-07-27

This addendum extends the [2026-07-18 filing-rule source
review](rule-source-review-2026-07-18.md) to cover common technical rules
added in rule catalog 1.2.0. The official LCI State Clearinghouse
[pre-submission checklist](https://lci.ca.gov/sch/docs/20250911-CEQA_Submit_Pre-Submission_Checklist_2025.pdf)
and [common mistakes guidance](https://lci.ca.gov/sch/docs/20250911-Common_Mistakes_to_Avoid_in_CEQA_Submit_2025.pdf)
were re-read on 2026-07-27 alongside the
[FAQ](https://lci.ca.gov/sch/faq/).

## New and changed rules

| Rule | Source relationship | Lifecycle decision |
| --- | --- | --- |
| `PDF-007` flattened, non-fillable PDF | Common mistakes #3/#8 and checklist section 3 explicitly require flattened, non-editable documents with no fillable fields. Split out of `PDF-006` so the official guidance is the citation. | Active; objective, correctable signal. |
| `PDF-008` screen-reader structure tags | Checklist section 3 asks for documents "properly tagged for screen reader compatibility." The rule reports only the structure-tree flag and states it is not accessibility certification, consistent with the documented accessibility boundaries. | Active as an advisory warning. |
| `FILE-003` static PDF document format | Common mistakes #8 directs filers to convert documents to static, fully text-searchable PDFs. Flags common convertible formats only, so package manifests are never flagged. | Active as an advisory warning. |
| `FILE-004` advisory file size | **No official size limit is documented** in any reviewed source. The rule is self-cited as a CEQA Preflight advisory technical rule with a parameterized threshold, and its remediation says to verify current portal guidance. | Active as an advisory warning; wording must not imply an official limit. |
| `FILE-005` portable filename characters | No official character guidance exists beyond descriptive names (already `FILE-001`). Self-cited technical portability rule. | Active as an advisory warning. |
| `PDF-006` active PDF content (narrowed) | Now covers only scripts, launch actions, and embedded files under its existing security citation; form fields moved to `PDF-007`. | Active, unchanged lifecycle. |
| `PDF-003` searchable-text coverage (remediation) | The zero-coverage remediation now recommends OCR, matching the FAQ and common mistakes #3 solution text. | Active, unchanged lifecycle. |

## Freshness

Recheck these sources on the schedule set by the 2026-07-18 review (before
2026-10-18 or a tagged release, whichever is earlier).
