# Evaluation report

Model: `qwen/qwen3.8-27b`. Synthetic fictional dataset. Report prose translated; underlying raw evidence is unchanged.

> False verified fields: 0

- Cases evaluated: 9 of 12
- Provider failures or invalid output (not counted as correct): 3 {'http_429': 3}
- Overall field accuracy: 96.7%
- Invented fields: 3 (rate 16.7%)
- Detection recall (incorrect fields marked conflict/missing): 0.0% of 3
- Expected-field marking recall: 100.0%
- Review rate (cases with an untrusted field): 33.3%
- Fiscal QR status accuracy: 100.0%
- Latency (s): mean 1.666, median 1.225, max 7.831
- Tokens: 21414 input and 1272 output (3 attempts with no usage reported)

| Field | Accuracy |
|---|---|
| issuer | 100.0% |
| issuer_cuit | 100.0% |
| date | 100.0% |
| number | 100.0% |
| document_type | 100.0% |
| letter | 100.0% |
| currency | 100.0% |
| subtotal | 66.7% |
| tax | 100.0% |
| total | 100.0% |

Small synthetic sample: this is not an estimate for real invoices.
