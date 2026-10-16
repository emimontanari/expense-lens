# ExpenseLens web

React + TypeScript + Vite frontend. Run `npm install`, then `npm run dev` (127.0.0.1); the local Vite proxy forwards `/receipts` to `http://127.0.0.1:8000`.

Select a JPEG, PNG, or PDF up to 5 MiB, grant explicit consent, then click extraction. Extraction forwards raw file bytes and the external-processing consent header. The UI requires human review; corrections can be validated locally through the backend validation endpoint. The app does not persist receipts or provide CSV export, authentication, or history.

## Argentine receipt review

The review panel shows CUIT, document type, letter, and currency, plus a per-field status from `field_status` (verified by fiscal QR, conflict, missing, unverified, empty) as text and color. Issues appear as Spanish messages styled by severity, with a notice for credit notes. A fiscal QR panel shows the QR read status, authorization (CAE/CAEA), and QR values. On conflict/missing/empty fields, "Usar valor del QR" sets only that field and marks changes as pending; nothing is validated automatically. Validation posts `{receipt, fiscal_qr}` and keeps the returned `fiscal_qr_status`.
