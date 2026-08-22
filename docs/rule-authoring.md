# Rule authoring

Rules are declarative metadata paired with an allow-listed Python function.
They never evaluate configuration, invoke a shell, or make network requests.

Every rule needs a unique ID, semantic version, filing-type scope, source
citation, lifecycle, and registered check name. A citation's `kind` is
`official` (State guidance) unless the rule rests on a technical reference
(`technical_reference`) or on the project's own reasoning
(`project_advisory`); the report labels the link accordingly, and a new
citation URL must be added to `corpus/` (see [corpus/README.md](../corpus/README.md))
so the AI explanation layer can quote it. A rule function returns
`RuleOutcome` values. Use `indeterminate` for uncertainty: the engine maps it
to a manual-review result, never a failure.

Only `active` rules run by default. `experimental` rules require an explicit
caller opt-in; deprecated and retired rules remain in the catalog history but
do not run. Every rule that applies to the filing type and does not run is
recorded in the report's `not_run` list with its reason, so a lifecycle change
is visible to report readers rather than only to catalog readers. A rule that
does not apply to the requested filing type is not a skipped check and is not
listed. Rule functions should return stable evidence and should not include
extracted PDF text or personal information in findings.
