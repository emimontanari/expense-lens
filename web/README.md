# ExpenseLens web

React + TypeScript + Vite frontend. Run `npm install`, then `npm run dev` (127.0.0.1); the local Vite proxy forwards `/receipts` and `/expenses` to `http://127.0.0.1:8000`.

Select a JPEG, PNG, or PDF up to 5 MiB, grant explicit consent, then click extraction. Extraction forwards the raw file bytes and the external-processing consent header. The UI requires human review; corrections can be validated locally through the backend validation endpoint. Reviewed receipts can be saved as expenses (see below); images are never stored and there are no accounts.

## Argentine receipt review

The review panel shows CUIT, document type, letter, and currency, plus a per-field status from `field_status` (verified by fiscal QR, conflict, missing, unverified, empty) as text and color. Issues appear as Spanish messages styled by severity, with a notice for credit notes. A fiscal QR panel shows the QR read status, authorization (CAE/CAEA), and QR values. On conflict/missing/empty fields, “Usar valor del QR” (“Use QR value”) sets only that field and marks changes as pending; nothing is validated automatically. Validation posts `{receipt, fiscal_qr, fiscal_qr_signature}` and keeps the returned signature and `fiscal_qr_status`. The signature comes from extraction; the client cannot create it.

## Expense ledger

After review, choose a category and press “Confirmar gasto” (“Confirm expense”): the UI POSTs `/expenses` with the reviewed receipt, `fiscal_qr`, `fiscal_qr_signature`, the originally extracted receipt (`extracted`, kept even if you edit), and the file's SHA-256 (`document_sha256`, via Web Crypto; null if unavailable). A 409 `duplicate_expense` lists the matches (same fiscal receipt, same file, similar operation) with “Guardar de todos modos” (“Save anyway”), which resends with `allow_duplicate: true`; a 422 `incomplete_expense` lists the missing fields.

“Mis gastos” (“My expenses”) lists saved expenses with filters (from, to, search, category, minimum/maximum amount, currency), totals per currency (never mixed; credit notes subtract), deletion with an explicit confirmation step, and “Exportar CSV” (“Export CSV”, `/expenses/export.csv` with the active filters). The “Correcciones” (“Corrections”) card shows `/expenses/stats`. Code layout: `App.tsx` (review), `ExpenseConfirm.tsx`, `Ledger.tsx`, `api.ts`, `model.ts`, `AppShell.tsx` (composition).
