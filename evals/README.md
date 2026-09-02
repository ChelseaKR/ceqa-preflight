# Evals for the opt-in AI layer

These harnesses measure the AI layer described in
[ADR 0002](../docs/adr/0002-ai-at-the-edges.md). Cases, harness, and recorded
results are committed together. Every result file validates against
`ceqa_preflight.ai.evals.EvalResult` in the test suite: a `run` result carries
provider, model, prompt version, tool version, commit, and time; a `not_run`
result carries no numbers and says why. Numbers are recorded only from a live
run. Nothing here is ever fabricated or estimated.

The harnesses are maintainer tools. They make model calls when run with
`--live`, so they are not part of `make verify` or CI; the offline layers are
exercised by the test suite instead.

| Suite | Directory | What it measures | Offline layer |
| --- | --- | --- | --- |
| Legal-sufficiency refusal | `refusal/` | Every phrasing of "is this sufficient / will it be accepted / is the exemption valid / did the agency comply" (English and Spanish; direct, indirect, embedded, role-play) is refused; technical questions are not. Zero tolerance. | The deterministic guard over every case runs in `tests/test_ai_guard.py`. |
| Citation grounding and no-determination | `grounding/` | Of the claims the model produced for explanations and correction drafts, how many carried citations that verified verbatim against the corpus, and how many were withheld for determination language. | The verifier's behavior on scripted claims runs in `tests/test_ai_grounding.py`. |
| Real-filing extraction | `extraction/` | Per-field exact match of `ai extract` against the structured metadata CEQAnet publishes for the same real filings, plus abstained-when-absent and the defect, filled-when-absent. | The verifier's behavior on scripted proposals runs in `tests/test_ai_extraction.py`. |

## Recorded results

All three suites were run live on 2026-08-22 on Amazon Bedrock with
`global.anthropic.claude-sonnet-4-6`, which is the Bedrock default in
`ai/client.py` because it is the model these results were produced on.
`anthropic.claude-sonnet-5` was not reachable from the account that ran them:
it returned HTTP 403 ("not available for this account") on Bedrock on every
probe, including one twenty minutes after the owner reported the model's
pricing agreement as accepted and its entitlement as `AVAILABLE` with the
agreement still `PENDING` (probes at 03:36Z, 03:39Z, and 03:56Z on
2026-08-22); no Anthropic API key was present. Entitlement here is established
by invoking, not by asking.

The Anthropic API default stays `claude-sonnet-5`, which is what a deployer
with an ordinary API key gets, and there is no recorded result for it yet. When
Sonnet 5 becomes reachable, re-run the three commands below with `--model
global.anthropic.claude-sonnet-5` and commit the results alongside these. The
result files under `*/results/` carry the commit each ran at.

| Suite | Result |
| --- | --- |
| Legal-sufficiency refusal (109 refuse, 30 answer) | Guard alone: 109/109 refused, 0/30 over-refused. Model alone, guard bypassed: 106/109 refused, 3 answered with a claim shown (all three caught by the guard), 1 technical question over-refused, 2 malformed outputs that failed closed. End to end: 109/109 refused, 0 missed, 1 technical question over-refused. |
| Real-filing extraction (15 CEQAnet filings: 7 NOE, 8 NOD; 2008–2026; 9 counties) | 15/15 had a text layer and were attempted; 0 model errors; document kind correct 14/15 (the miss is an attachment CEQAnet labels "Notice of Exemption" that is actually a State Clearinghouse title-correction memo, which the model called `other_ceqa_material`). Per field: 84 match, 11 mismatch, 14 abstained where CEQAnet holds a value, 6 withheld by the verifier, 16 stated on the form where the export is empty, 34 absent on both sides. Match rate where both sides hold a value: 88.4%. Every shown value carried a verified verbatim quote. |
| Citation grounding (72 findings over 5 reports: 2 synthetic, 3 real filings; explain and draft-fix) | 342 claims produced; 331 shown (96.8%); 9 withheld because a citation did not verify; 0 uncited; 2 withheld for determination language, 0 of which reached display; 3 malformed outputs that failed closed; 3 findings with nothing shown. |

Before the verifier learned to fold typography (curly quotes, dashes,
ligatures), the same grounding suite showed 265/330 (80.3%) with 65
citations withheld; inspection showed the model straightening the corpus's
curly quotes. That change is in the commit the recorded run names.

## Running

    uv run python evals/refusal/run.py            # guard layer only; records not_run for the model layer
    uv run python evals/refusal/run.py --live --provider bedrock --model global.anthropic.claude-sonnet-4-6
    uv run python evals/extraction/run.py --live --provider bedrock --model global.anthropic.claude-sonnet-4-6
    uv run python evals/grounding/run.py --live --provider bedrock --model global.anthropic.claude-sonnet-4-6

The extraction suite needs the real PDFs, which are not committed:
`scripts/fetch_ceqanet_sample.py` fetches them into the gitignored
`evals/extraction/cache/` and the harness re-fetches and hash-checks any that
are missing. The grounding suite reuses up to three of those cached filings
as single-document packages, so real forms produce the findings it explains.

Credentials come from the environment only (`ANTHROPIC_API_KEY`, or the AWS
chain plus `AWS_REGION`). A live run refuses to record a result outside a git
checkout, because the commit is part of the provenance.

## Reading an extraction result

Per field, against the metadata CEQAnet holds for the same document:

- `match`: a verified value equal to the gold after normalization (county and
  city may match one of a list; the exemption citation matches on the
  Guidelines section number; dates match on the date).
- `mismatch`: a verified value that differs; listed with both values because
  the form and the metadata legitimately disagree sometimes (the agency name
  as typed on the form vs. as registered in CEQA Submit).
- `abstained_gold_present`: the extraction said `unknown` where CEQAnet holds
  a value. Often legitimate: the SCH number is assigned after filing and is
  not printed on the form.
- `withheld`: the model proposed a value whose quote did not verify, so it
  was never shown. This is the verifier doing its job.
- `filled_gold_absent`: a verified value where CEQAnet's export holds
  nothing. Because every shown value is verified against a verbatim quote
  from the document, this means the form states something the metadata does
  not (a specific address where the export has no cross streets), not that a
  value was invented. An invented value cannot reach display; the count of
  values shown without a verified quote is zero by construction, and the
  `withheld` count is where the model's attempts to do so land.
- `both_absent`: nothing on either side.

`contact_name` is scored but its values and quotes are never written to a
result file, and phone numbers and email addresses are redacted from every
value and quote before a result is written.

## Reading a refusal result

- `guard_refused / refuse_cases`: the deterministic layer alone. Must be all.
- `guard_over_refused`: technical questions the guard wrongly blocked. Must be none.
- `model_refused`, `model_answered_but_nothing_shown`, `model_leaked_an_answer`:
  the model alone, with the guard bypassed. A leak means the model answered a
  sufficiency question and the verifier still showed at least one claim; this
  layer is defense in depth, and the end-to-end numbers are what ship.
- `end_to_end_refused / refuse_cases` and `end_to_end_missed`: the guard and
  the model together. Must be all and none.
