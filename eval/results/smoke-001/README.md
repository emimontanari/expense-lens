# First real-world test: two responses and two provider limits

Four formats of the **same fictional receipt** were sent to Groq once each, with no retries or repair. This is not a benchmark or an estimate of accuracy on real invoices.

| Input | Result | Matching fields |
|---|---|---|
| PNG | Provider HTTP 429 | Not evaluable |
| JPEG | Valid response | 7 of 7 |
| PDF with text | Valid response | 7 of 7 |
| Scanned PDF | Provider HTTP 429 | Not evaluable |

The 429 failures do not demonstrate reading problems with those formats. Nor do the two correct responses demonstrate generalization: the content, format, and values are simple, synthetic, and equivalent. Real multipage extraction was not tested.

## Evidence

- `plan.json`: model, prompt hash, input hashes, and expected values fixed before execution.
- `attempts.jsonl`: four attempts, latencies, sanitized errors, validated responses, and reported usage. It contains no keys or headers.
- Model that responded: `qwen/qwen3.8-27b`.
- Known tokens for two responses: 4,128 input and 198 output. Usage for the other two attempts is unknown, not zero. No cost calculation.
- The runner exited with status 0 because capture completed, **not because every call succeeded**. Errors were neither retried nor replaced.

## Follow-up change

After this capture, HTTP 429 was given a distinguishable error: `503 provider_rate_limited`. The original evidence retains `provider_error`, which was the contract at the time. The application does not retry automatically.

Continue with upload, preview, and manual review; expand the evaluation with varied cases in another authorized run, without reusing this set as a holdout.

Its runner lived in commit `466bbfa` (`eval/smoke.py`); it was replaced by `eval/run.py` and `eval/score.py`.
