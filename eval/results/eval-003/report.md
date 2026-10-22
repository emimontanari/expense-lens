# Evaluation report

Model: `qwen/qwen3.8-27b`. Synthetic fictional dataset. Report prose translated; underlying raw evidence is unchanged.

> False verified fields: 0

- Cases evaluated: 10 of 12
- Provider failures or invalid output (not counted as correct): 2 {'http_429': 2}
- Overall field accuracy: 100.0%
- Invented fields: 0 (rate 0.0%)
- Detection recall (incorrect fields marked conflict/missing): n/a of 0
- Expected-field marking recall: 100.0%
- Review rate (cases with an untrusted field): 40.0%
- Fiscal QR status accuracy: 100.0%
- Category accuracy: model 100.0%, rules 30.0% (10 cases)
- Latency (s): mean 1.012, median 1.039, max 1.414
- Tokens: 24350 input and 1419 output (2 attempts with no usage reported)

| Field | Accuracy |
|---|---|
| issuer | 100.0% |
| issuer_cuit | 100.0% |
| date | 100.0% |
| number | 100.0% |
| document_type | 100.0% |
| letter | 100.0% |
| currency | 100.0% |
| subtotal | 100.0% |
| tax | 100.0% |
| total | 100.0% |

Small synthetic sample: this is not an estimate for real invoices.
