# Rule authoring

Rules are declarative metadata paired with an allow-listed Python function.
They never evaluate configuration, invoke a shell, or make network requests.

Every rule needs a unique ID, semantic version, filing-type scope, source
citation, lifecycle, and registered check name. A rule function returns
`RuleOutcome` values. Use `indeterminate` for uncertainty: the engine maps it
to a manual-review result, never a failure.

Only `active` rules run by default. `experimental` rules require an explicit
caller opt-in; deprecated and retired rules remain in the catalog history but
do not run. Rule functions should return stable evidence and should not include
extracted PDF text or personal information in findings.
