# Evaluation report

Model: `qwen/qwen3.8-27b`. Synthetic fictional dataset. Report prose translated; underlying raw evidence is unchanged.

> False verified fields: 0

- Cases evaluated: 2 of 12
- Provider failures or invalid output (not counted as correct): 10 {'http_429': 10}
- Overall field accuracy: 100.0%
- Invented fields: 0 (rate 0.0%)
- Detection recall (incorrect fields marked conflict/missing): n/a of 0
- Expected-field marking recall: 100.0%
- Review rate (cases with an untrusted field): 50.0%
- Fiscal QR status accuracy: 100.0%
- Latency (s): mean 0.408, median 0.236, max 1.349
- Tokens: 4360 input and 286 output (10 attempts with no usage reported)

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
