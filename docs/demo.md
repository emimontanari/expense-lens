# ExpenseLens local demo

A 60–90-second presentation script, starting after extraction is complete. Use fictional receipts only. Extraction sends the file to Groq and consumes quota; HTTP 429 errors may interrupt the demo. No offline demo mode is implemented, and no screenshots or video were produced for this closure.

## Setup

First stop the usual API server to free port 8000. From `expense-lens/`, in a new terminal, create a unique temporary directory and start the API with extraction enabled (`GROQ_API_KEY` must be in `.env`):

```bash
DEMO_DIR=$(mktemp -d)
EXPENSE_LENS_DB="$DEMO_DIR/expenses.sqlite" EXPENSE_LENS_ENABLE_GROQ=1 \
  uv run --env-file .env uvicorn expense_lens.main:app --host 127.0.0.1 --port 8000
```

In another terminal, from `expense-lens/web/`:

```bash
npm run dev
```

The Vite proxy targets the API on port 8000; no configuration changes are needed. If the web app is already running, you can keep that instance.

Use `eval/dataset/factura_a_qr_coincide.png`, which contains a fictional fiscal QR code. The temporary database is isolated from your personal expenses. Do not regenerate the signing secret during the session; restarting without a stable secret requires extracting again. ARCA authenticity will not be checked.

## Walkthrough

1. **Upload and consent.** Open `http://127.0.0.1:5173`, select the fictional invoice, and approve external processing. Extract once. If HTTP 429 occurs, show the error without claiming extraction succeeded; another attempt consumes quota. Waiting time is not included in the 60–90 seconds.
2. **Review and QR.** Show the invoice alongside its fields and the QR panel. Explain that “Verificado por QR” (“Verified by QR”) means the server-read QR agrees with the value, not that the invoice is authentic. Change the total to a value that differs from the QR and validate; a conflict should appear. Use “Usar valor del QR” (“Use QR value”) to restore it and validate again. These validations do not call the model.
3. **Confirm.** Choose a category and confirm the expense. Point out that the server validates it again and stores data only, not the image.
4. **Duplicate (optional, outside the short walkthrough).** After saving, the form disables confirmation. To demonstrate duplicate detection, extract the same file again: this makes another provider call and requires consent for that usage. On confirmation, the existing expense and the explicit option to save anyway are shown. Do not force a second save. Skip this step if you do not authorize the additional call.
5. **History and CSV.** Show the entry under “Mis gastos” (“My expenses”), filter by issuer, review totals separated by currency, and export the CSV.

## What to show without using the provider

If you do not authorize external calls, limit the presentation to the architecture, tests, and historical reports in `eval/results/`. Do not present a historical output as a new extraction or a script as a demo that was actually run.

When finished, stop both servers. The demo’s temporary directory contains fictional data only; remove it manually when you no longer need the session. Do not delete your usual database to prepare a presentation.
