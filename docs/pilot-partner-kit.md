# CEQA Preflight pilot partner kit

## What participation is

CEQA Preflight is an independent, pre-alpha, local command-line tool that
checks the technical readiness of an intended NOD or NOE filing package. It is
not legal advice, a CEQA compliance determination, or a State of California
service.

The permissioned pilot asks qualified practitioners to test whether a small
set of advisory findings is accurate and useful. A participant keeps every
package on a participant-controlled computer. The project receives no package,
extracted text, project title, contact information, screenshot, or reviewer
rationale.

This kit is an operational starting point, not a legal agreement. A participant
should use its own legal, records-management, procurement, and security review
processes before sharing any result or allowing any package to be used.

## Why participate

- Help shape a local-first public-interest tool before its filing-specific
  rules are activated.
- Test whether the tool catches objective, correctable package issues without
  adding a hosted repository or telemetry.
- Influence the wording, scope, and stop/go decision for the initial NOD/NOE
  rules.

Participation does not require endorsement, publication of the participant's
name, or permission to retain a package.

## Who is needed

The pilot needs at least three organizations, including one public agency and
one consultant. Each filing-specific rule needs two independent qualified CEQA
reviewers before it can be activated.

A qualified reviewer should have current professional responsibility for CEQA
document review or filing support and recent experience with NODs, NOEs, or
State Clearinghouse submission workflows. The coordinator records the basis
for qualification privately; it is not put in the public repository or pilot
CSV files.

## What a participant does

1. Decide internally whether a synthetic package, an unsubmitted package, or a
   recently submitted package may be used. Do not use a package without written
   authorization from the organization that controls it.
2. Run CEQA Preflight locally on a participant-controlled machine. Use
   `--include-experimental` only for the pilot rules under review.
3. Have the assigned reviewer compare the advisory output with an independent
   manual review and complete the private reviewer rubric below.
4. Put only controlled labels and an opaque package ID into the local pilot
   CSV templates. Do not include a document name, rationale, project detail,
   or any free text.
5. The participant may withdraw a package before aggregate analysis. Delete
   its local controlled-label row instead of sending package information.

The technical commands are documented in the [pilot protocol](pilot-protocol.md).
The pilot coordinator may receive an aggregate, controlled-label CSV only if
the participant approves that transfer through its own process.

## Data boundary

| May remain with participant | May enter the controlled-label evidence file | Never place in the repository or evidence file |
| --- | --- | --- |
| Package files, manual-review notes, authorization record, reviewer qualification basis | Opaque package ID, filing type, rule ID, finding status, controlled disposition, severity, elapsed seconds | Project/document names, addresses, contacts, screenshots, extracted text, legal analysis, free-text rationale |

The tool rejects unexpected columns, free text, spreadsheet-formula-like
values, duplicate review rows, and inconsistent package timing. See the
[data card](data/local-filing-packages.md) for the project data boundary.

## Permission confirmation template

Use this as a starting point for a participant's internal approval record; it
is deliberately not a substitute for an organization-specific agreement.

> **Pilot package authorization**
>
> Organization: `[organization]`  
> Authorized by: `[name and role retained by participant]`  
> Package reference: `[participant-private reference]`  
> Date: `[date]`
>
> `[Organization]` authorizes its designated personnel to run CEQA Preflight
> locally on the identified package solely for the CEQA Preflight pilot. The
> package will remain on a participant-controlled system and will not be
> uploaded, committed, or otherwise provided to the project. Only an
> organization-approved aggregate of controlled labels with an opaque package
> ID may be shared. `[Organization]` may withdraw the package before aggregate
> analysis by directing its personnel to remove the associated local evidence
> rows.
>
> This authorization does not endorse CEQA Preflight, transfer intellectual
> property, waive any confidentiality obligation, or represent a conclusion
> about CEQA compliance or legal sufficiency.

## Private reviewer rubric

Each reviewer completes this rubric independently. Keep any explanation or
examples in the participant-controlled private register; the pilot CSV accepts
only the specified controlled labels.

| Review question | Allowed result | What is recorded in the pilot CSV |
| --- | --- | --- |
| Did the rule apply to the package as scoped? | Applicable / not applicable / unclear | `not_actionable` only when the automated finding should not be actioned; otherwise use the matching disposition below. |
| Was an automated warning or failure correct? | True positive / false positive / indeterminate | `true_positive`, `false_positive`, or `indeterminate` |
| Did the independent manual review find a high-severity issue the rule missed? | Yes / no | A separate `manual-baseline.csv` row with `was_missed` and severity |
| Was the rule title, message, and remediation safe and clear? | Approve / revise / do not activate | Private rubric only; it is not an evidence-file field. |

A rule is not eligible for activation until two qualified reviewers independently
select **Approve** for its wording and scope, and the aggregate pilot metrics
meet the documented thresholds. A disagreement, unclear scope, privacy concern,
or potentially misleading output means revise or stop; it does not mean widen
the rule.

## Outreach email template

**Subject:** Invitation: local-first CEQA filing-readiness pilot

Hello `[Name]`,

I’m inviting a small group of CEQA practitioners to evaluate CEQA Preflight, an
open-source, local-first tool for checking the technical readiness of intended
NOD/NOE filing packages. It is advisory only: it does not upload documents,
retain package data, submit filings, or determine CEQA compliance.

The pilot asks reviewers to run the tool on a participant-controlled synthetic,
unsubmitted, or recently submitted package that their organization has approved
for this purpose. Packages stay local; the only possible shared artifact is an
organization-approved aggregate of controlled labels with opaque IDs. I’m
seeking reviewer feedback on whether specific findings are accurate, clear,
and appropriately scoped before any filing-specific rule is activated.

Would you be open to a short conversation about whether `[organization]` could
participate or refer a qualified reviewer? The participant kit and protocol are
here: `[repository URL]/blob/main/docs/pilot-partner-kit.md` and
`[repository URL]/blob/main/docs/pilot-protocol.md`.

Thank you,

`[Your name]`

## Coordinator checklist

- Confirm that the organization is a public agency, consultant, or another
  appropriate CEQA-practice partner; track names and contact details outside
  this repository.
- Confirm internal written authorization before any non-synthetic package is
  run.
- Confirm two independent qualified reviewers for each rule under evaluation.
- Give participants the exact tool version and the rule IDs being evaluated.
- Verify that any supplied evidence file contains only the controlled headers
  accepted by `ceqa-preflight pilot summarize`.
- Publish aggregate results only after participant approval and a privacy
  review; never publish the participant roster or package-level results.

## Stop conditions

Stop the package's pilot use and notify the participant if a package is
accidentally copied outside its approved location, an evidence file contains
free text or identifying information, a reviewer identifies a potentially
misleading legal implication, or authorization becomes unclear. Delete the
unapproved local evidence row, document the incident privately with the
participant, and do not substitute a speculative result.
