# Pilot Evidence Kit — Product Specification

## Problem

Qualified CEQA reviewers need a repeatable way to judge whether advisory
findings are useful before the tool reaches a broader audience. A shared corpus
of filing packages would create unnecessary privacy and records-management risk.

## Goals

- Let a pilot coordinator create local, controlled-label evidence templates.
- Calculate precision, high-severity false-negative rate, and report-time
  metrics without reading a package or storing reviewer notes.
- Produce an explicit go/no-go result against the documented pilot thresholds.

## Non-goals

- Collecting or uploading CEQA records, PDF text, project names, or contact data.
- Replacing qualified reviewer judgment or deciding legal sufficiency.
- Recruiting participants, granting permission, or validating official sources.

## P0 requirements

- `pilot init` creates non-overwriting CSV templates with opaque package IDs.
- `pilot summarize` accepts only exact, controlled columns and labels.
- Formula-like cells, free text, duplicate reviews, inconsistent package timing,
  unknown headers, and oversized files fail closed.
- Output contains aggregate counts and thresholds only.
- A result is `go` only when precision is at least 90%, high-severity false
  negatives are below 5%, and median report time is under five minutes.

## Success measures

- At least 20 permissioned NOD/NOE packages reviewed in the pilot.
- Every activated rule receives two qualified reviewer approvals.
- Aggregate evidence can be reproduced locally from the controlled CSV files.

## Dependencies and risks

The tool work is complete for this slice. Pilot execution is blocked on written
permission, participating organizations, qualified reviewers, and an independent
manual baseline. Qualitative notes remain private to the participant; only
controlled aggregate labels may enter the evidence kit.
