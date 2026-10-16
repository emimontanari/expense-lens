# ExpenseLens web

React + TypeScript + Vite frontend. Run `npm install`, then `npm run dev` (127.0.0.1); the local Vite proxy forwards `/receipts` to `http://127.0.0.1:8000`.

Select a JPEG, PNG, or PDF up to 5 MiB, grant explicit consent, then click extraction. Extraction forwards raw file bytes and the external-processing consent header. The UI requires human review; corrections can be validated locally through the backend validation endpoint. The app does not persist receipts or provide CSV export, authentication, or history.
