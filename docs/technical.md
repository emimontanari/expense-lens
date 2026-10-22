# ExpenseLens: Technical Documentation

Contracts, limits, and design decisions. See the [README](../README.md) for an overview.

## Validate and normalize a receipt

`POST /receipts/validate` accepts a transcript from the model or a human correction,
plus optional fiscal QR data returned by extraction. QR data must be accompanied
by its server-issued `fiscal_qr_signature` (see [Signed QR](#signed-qr-hmac)).

```json
{
  "receipt": {
    "issuer": "Comercio ficticio",
    "issuer_cuit": "30-00000000-7",
    "date": "15/10/2026",
    "number": "0001-00000001",
    "document_type": "factura",
    "letter": "A",
    "currency": "$",
    "subtotal": "1.000,00",
    "tax": "210,00",
    "total": "1.210,00"
  },
  "fiscal_qr": null
}
```

The response includes a normalized `receipt` (`"1210.00"`, `"2026-10-15"`,
`"30000000007"`, `"ARS"`), `issues` with `code`, `field`, and `severity`,
per-field `field_status`, `movement`, and `requires_human_review: true`.

### Normalization (`normalize.py`)

| Input | Result | Rule |
|---|---|---|
| `1.234,56`, `$ 1.234,56`, `1,234.56` | `1234.56` | The last separator followed by 1–2 digits is decimal. |
| `1.234` or `1,234`, without supporting context | `null` + `ambiguous_amount` | Do not guess whether a single three-digit group represents thousands or decimals. |
| `1.234` on a peso receipt, or alongside amounts such as `1.000,00` | `1234` + `amount_interpreted_from_document` (info) | Unambiguous amounts take precedence; conflicting styles provide no hint. Otherwise use the document currency: pesos and euros default to decimal commas, dollars to decimal points. Unknown currency leaves the amount ambiguous. These are application defaults, not universal currency-format guarantees. |
| `-150,00`, `(150,00)` | `150.00` | Amounts are absolute; document type determines the sign. |
| `15/10/2026` | `2026-10-15` | Argentine day-first format. |
| `$` | `ARS` + `currency_inferred_from_symbol` (info) | The Argentine default is pesos, but the inference is reported. |
| `US$`, `U$S` | `USD` | Never converted to pesos. |
| `30-00000000-7` | `30000000007` | Validate the modulus-11 check digit; invalid values become `null` + `invalid_cuit`. |

### Rules (`rules.py`)

| Code | Trigger | Severity |
|---|---|---|
| `missing_field` | A required field is absent. Always: issuer, date, currency, total. Invoices and notes: CUIT, number, letter. Invoice A: subtotal and VAT. | warning |
| `tax_already_included` | `subtotal == total` with VAT > 0: the purported net amount already includes VAT. | warning |
| `total_below_subtotal` | Total is below subtotal: possible field confusion. | warning |
| `total_mismatch` | `subtotal + tax != total`, compared exactly with `Decimal`. | warning |
| `subtotal_equals_total` | Subtotal equals total without itemized VAT: possibly copied from total (discovered in `eval-002`). | warning |
| `unexpected_tax` | Invoice C includes itemized VAT. | warning |
| `future_date` | Date is later than today. | warning |
| `qr_mismatch` | A field contradicts the fiscal QR. | warning |
| `credit_note` | Credit note: `movement = credit`, subtract rather than add. | info |
| `foreign_currency` | USD or EUR: preserve the original currency. | info |
| `amount_interpreted_from_document` | Resolve an ambiguous amount using document format evidence or currency defaults. | info |

`field_status` summarizes each field: `verified` (matches the QR), `conflict`,
`missing`, `unverified` (read by the model, without a second source), or `empty`.
Rules flag issues; they **never correct or approve** data.

## ARCA fiscal QR (`fiscal_qr.py`)

Argentine electronic invoices include a QR (RG 4892/2020) containing
`https://www.arca.gob.ar/fe/qr/?p={Base64 JSON}`, according to the
[official specification](https://www.arca.gob.ar/fe/qr/documentos/QRespecificaciones.pdf).

- Decode **locally** with zxing-cpp before calling the model, using already
  decoded and validated image pixels or rendered PDF pages.
- Require `https`, an `afip.gob.ar` or `arca.gob.ar` host, the `/fe/qr/` path,
  valid Base64 and JSON, `ver = 1`, a valid CUIT check digit, numeric amounts
  with at most two decimal places, and CAE/CAEA authorization. Other decoded
  QR content is reported as `fiscal_qr_status = invalid`.
- Compare CUIT, date, point of sale and number, type, letter, currency, and total.
  Agreement produces `verified`; disagreement produces `qr_mismatch`.
- QR data **never fills empty fields** or replaces document reading. It does not
  contain the issuer name, subtotal, taxes, or line items. The UI lets the person
  explicitly use its value one field at a time.
- A valid QR does not prove invoice authenticity: ARCA is not queried.

## Signed QR (HMAC)

The server extracts the QR and returns its data to the browser, which sends it
back when requesting validation or confirming an expense. Without proof of origin,
a client could invent QR data and obtain `verified` fields (shown as
“Verificado por QR”). The server therefore signs extracted QR data before returning it.

The signature is HMAC-SHA-256 over canonical JSON of the normalized model
(sorted keys, compact separators, UTF-8). `/receipts/extract` returns
`fiscal_qr_signature`; `/receipts/validate` and `/expenses` check it against the
received QR using constant-time comparison. Altered QR data, missing signatures,
and invented signatures produce HTTP 422 `fiscal_qr_signature_invalid`.
`fiscal_qr: null` requires no signature. Verification happens in the HTTP layer;
`review_receipt` stays independent.

Set `EXPENSE_LENS_SECRET` to a strong, random, stable secret in the server
environment. If absent, the process generates a random in-memory secret: a restart
invalidates signatures already issued, requiring the user to extract again.
Do not use an ephemeral secret for deployments that must preserve in-flight requests.

This prevents forging signatures without the secret. It does not prove that ARCA
issued the invoice or replace authentication and access controls.

## Extract a receipt with Groq (opt-in, local only)

`POST /receipts/extract` accepts JPEG, PNG, or PDF as a binary body, with the same
inspection limits. It requires `X-Allow-External-Processing: true`; without it,
the response is 403. A disabled provider or missing key produces 503.
**This header expresses consent, not authentication or access control.**

When enabled, the endpoint sends the entire image to Groq, including any embedded
metadata. For PDFs it sends rendered images of all pages, not the original file or
non-visible metadata. Use only fictional examples or documents authorized for
external processing; the provider's retention policy has not been assessed here.
Do not enable SDK/HTTP debug logging with real documents or credentials.

The Adapter uses `qwen/qwen3.8-27b`, referenced in the
[Groq vision documentation](https://console.groq.com/docs/vision). The account
returned results for JPEG and text PDF in the first test; PNG and scanned PDF
received HTTP 429 instead of extraction results.

JSON mode is not a schema guarantee: require exactly the ten `RawReceipt` keys
plus `category` (eleven total), validated with Pydantic. The model **transcribes**
values as printed (`"1.234,56"`, `"15/10/2026"`, `"$"`); deterministic code handles
normalization, calculation, and validation. Unknown values stay `null`; amounts
are not corrected. Human review remains mandatory.

Each request makes at most one call: no retries or repair, at most 1024 output
tokens, and an SDK timeout of 20 seconds per network operation (not a total
request-duration limit). Errors 502/503/504 do not expose raw provider responses.
HTTP 429 is distinguished as `503 provider_rate_limited`, without retrying.
Tests use MockTransport and fictional credentials.

### Category suggestion (`categories.py`)

`CATEGORY_GUIDE` defines the criteria used by the model prompt and dataset labels.
Without written definitions, the metric would be arbitrary.

| Category identifier | Definition |
|---|---|
| `supermercado` | Supermarkets, grocery stores, and convenience grocery outlets: everyday food, drinks, cleaning, and hygiene products. |
| `combustible` | Gas stations: gasoline, diesel, CNG, and lubricants. |
| `restaurantes` | Food and drinks consumed out or delivered: restaurants, bars, cafes, and grills. |
| `servicios` | Utilities and household subscriptions: electricity, gas, water, internet, phone, TV, and monthly maintenance. |
| `transporte` | SUBE, taxis, private hire, ride-hailing, tolls, parking, and tickets. |
| `salud` | Pharmacies, medical appointments, health plans, and laboratories. |
| `hogar` | Hardware, paint, furniture, appliances, and home repairs. |
| `otros` | Everything else, including professional fees, consulting, software and licenses, stationery, and repairs unrelated to housing. |

Issuer rules never return `otros`: without a match they abstain (`null`), which
counts as incorrect in baseline category accuracy.

The same call returns `category`, which is **classification, not transcription**:
one of the eight expense categories or `null`. A missing key produces
`502 invalid_model_output` under the same strict key policy. An out-of-list value
invalidates only the suggestion (`model: null`); extraction still returns 200.

The deterministic, offline baseline lowercases the issuer, removes accents, and
matches whole words (`dia` does not match `Diaz`). Keywords:

| Category | Issuer keywords |
|---|---|
| `combustible` | ypf, shell, axion, puma |
| `supermercado` | coto, carrefour, dia, jumbo, disco, vea, changomas, supermercado |
| `salud` | farmacia, farmacity |
| `servicios` | edenor, edesur, metrogas, aysa, telecom, movistar, claro, personal |
| `transporte` | sube, uber, cabify, peaje, taxi, estacionamiento |
| `restaurantes` | restaurante, parrilla, pizzeria, cafe, bar |
| `hogar` | easy, sodimac, ferreteria, pintureria |

`ReceiptValidation.category_suggestion` (default `null`) is
`{model, rules, suggested, source}`. `suggested` uses `model` when non-null,
otherwise `rules`; `source` identifies which. `/receipts/extract` fills both;
`/receipts/validate` computes only `rules` (`model: null`, no model call).

### Text and scanned PDFs

Render every page in order, without a separate text-extraction path. Send pages
together in **one call**, producing one receipt result; never automatically sum
totals across pages. One file must contain one receipt. The prompt asks not to
mix identities, but there is no deterministic multiple-receipt detector.

- At most 3 pages and 5 MiB input; reject encrypted PDFs.
- Run PDFium in a new process per document without inheriting server keys or
  environment variables. Do not run PDFium concurrently in threads.
- At most 1400 pixels per side, 2 million pixels per page, and 5 MiB of generated
  JPEG data total; maximum scale is 2 pixels per point. Downscaling may lose small
  text and does not establish reading accuracy.
- Rendering has a 10-second timeout. Failures/timeouts return 422; excessive
  geometry/output returns 413. Process everything before calling Groq.
- Close pages and bitmaps per page. No intermediate storage.

The pixel budget limits requested bitmaps, **not native-parser RAM usage**. The
separate process bounds duration and avoids concurrent PDFium calls in threads,
but is not a sandbox. Initial pypdf inspection still runs in the server process
without a dedicated timeout. Extraction persists nothing; only `POST /expenses`
saves data, after human confirmation.

## Inspect a file (local development only)

`POST /documents/inspect` accepts the **file as a binary body**, not multipart,
JSON, Base64, or a URL. It does not trust extensions, filenames, or declared MIME
types. It neither writes the document to disk nor sends it to third parties.

```bash
curl --fail-with-body http://127.0.0.1:8000/documents/inspect \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @examples/synthetic/receipt.png
```

Response: `format` (`jpeg`, `png`, or `pdf`), `size_bytes`, `pages` (PDF only;
`null` for images), and `requires_human_review: true`. No extracted fields.

| Control | Limit / behavior |
|---|---|
| Actual bytes | At most 5 MiB, checked while receiving without trusting Content-Length. |
| JPEG / PNG | At most 12 million pixels; verify and decode; reject animation. |
| PDF | At most 3 pages; reject encryption, empty documents, and detectable structural errors. |
| Errors | 413: limit exceeded; 415: unsupported format; 422: empty or invalid. |

`/documents/inspect` applies the same structural inspection to scanned and text
PDFs. It does not render or validate every stream: 200 does not guarantee a PDF
can render, is safe, or contains a receipt. One receipt per file is a usage
convention, not automatic detection.

Check pixel limits before image decoding; page limits require parsing the PDF.
Inspection runs in a thread; only extraction's PDF rendering has a separate
process and timeout. **No sandbox, hard memory limit, or concurrency control.**
Public exposure or WhatsApp integration requires server/proxy limits, isolation
of all parsers, receive timeouts, authentication, and usage controls. This is not
an antivirus or sanitizer.

### Fictional examples

`examples/synthetic/` contains the same fictional receipt as PNG, JPEG, rasterized
(scanned-equivalent) PDF, text PDF, and an invalid PDF. They contain no real data
and have no fiscal validity; they test ingestion, not OCR quality. Regenerate with:

```bash
uv run python examples/generate_receipts.py
```

## Saved expenses (`expenses.py`, `storage.py`)

Save an expense only after human confirmation. **No images or PDFs are stored**:
only normalized data and `document_sha256`, a file hash for duplicate detection.

**Storage:** standard-library SQLite (`sqlite3`, no extra dependencies) at
`EXPENSE_LENS_DB`, defaulting to `data/expenses.sqlite`. Create the directory as
needed; `data/` is Git-ignored. Create the schema when opening the database.
Amounts are canonical decimal strings, never `float`, and SQL is parameterized.
Tests override `get_db` with a database in a temporary directory.

| Endpoint | Response |
|---|---|
| `POST /expenses` | 201 `Expense` |
| `GET /expenses?date_from&date_to&q&category&min_total&max_total&currency` | 200 `{items, totals}`; date then id, descending |
| `GET /expenses/{id}` | 200 `Expense` or 404 `expense_not_found` |
| `PUT /expenses/{id}` | 200 `Expense`; recompute everything, preserve `created_at` |
| `DELETE /expenses/{id}` | 204; permanent deletion |
| `GET /expenses/export.csv` (same filters) | UTF-8 CSV with BOM |
| `GET /expenses/stats` | `{count, with_extraction, correction_rate_by_field, qr_verified_rate, suggestion_acceptance}` |

POST/PUT bodies contain `{receipt, fiscal_qr, fiscal_qr_signature, category,
extracted, document_sha256, allow_duplicate, category_suggestion}`.
Categories: `supermercado`, `combustible`, `restaurantes`, `servicios`,
`transporte`, `salud`, `hogar`, `otros`.

`extracted` is the original normalized `/receipts/extract` output, or `null` for
manual entry. Extra fields are rejected: **the client cannot send statuses**;
the server reruns `review_receipt` to compute `issues`, `field_status`, and `movement`.

Optional `category_suggestion` (default `null`) records the displayed suggestion.
The server derives `suggested` and `source` from `model` and `rules`. Returned
`Expense` includes `category_suggestion` and `suggestion_accepted`
(`category == suggested`; `null` without a suggestion). Add the new
`category_suggestion` JSON and `suggestion_accepted` columns to existing databases
through an idempotent migration (`ALTER TABLE` when missing), preserving data.

### Errors

- **422 `incomplete_expense`**: normalized `issuer`, `date`, `currency`, or `total`
  is missing. `detail.fields` lists missing fields; nothing is stored.
- **409 `duplicate_expense`**: `detail.matches` identifies existing expenses with
  `{id, reason, issuer, date, total, currency}`. Nothing is stored unless
  `allow_duplicate: true`, which saves with matching ids in `duplicate_of`.

| `reason` | Condition |
|---|---|
| `fiscal_key` | Same non-null CUIT, type, letter, point of sale, and number. Compare number parts as integers: `0001-00000001` == `00001-00000001`. |
| `same_file` | Same `document_sha256`. |
| `similar` | Same date, currency, and total, plus same CUIT if both have one; otherwise case-insensitive issuer match. |

PUT excludes the record itself from duplicate comparison.

### Totals, CSV, and telemetry

- Group `totals` by currency, never mixing currencies: `expenses` sums expenses,
  `credits` sums credit notes, `net = expenses - credits`. Use `Decimal` throughout.
- `signed_total` is negative for credit notes. CSV uses `importe = signed_total`,
  comma-delimited columns, and decimal points. Prefix text cells beginning with
  `=`, `+`, `-`, `@`, tab, or carriage return with `'` to prevent formula injection;
  numeric amounts are excluded from this transformation.
- `corrected_fields` identifies normalized final values differing from
  `extracted` (`null` without extraction). `/expenses/stats` computes per-field
  correction rates over expenses with extraction, and the share of all expenses
  containing at least one QR-verified field.
- `suggestion_acceptance` is `{model, rules}`: per source, the fraction of expenses
  whose saved category matches that source's suggestion (`null` without samples).
- Text and amount filters run in Python with `Decimal`, targeting local single-user
  use. There is no authentication or pagination.

## Planned input channels

Separate ingestion from processing:

```text
Web (first) ──────────────┐
                         ├─ inspect file → extract → validate data → review
WhatsApp (future) ────────┘
```

Processing should not depend on HTTP objects or WhatsApp messages. A future
integration would be an input Adapter, not a second extractor. There is currently
no connection, webhook, attachment download, or messaging integration.

Treat document content as untrusted data, not model instructions. ZIP archives,
Office files, and arbitrary URLs are unsupported.

WhatsApp would additionally require webhook authentication, attachment access
controls, event deduplication, and retention/deletion policies. Explicitly inform
users when sending documents to an external provider. Missing these controls does
not authorize public deployment.
