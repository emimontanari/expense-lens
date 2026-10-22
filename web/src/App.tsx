import { useEffect, useState } from 'react';
import './style.css';

import {
  acceptedTypes, fields, labels, maxFileSize, qrStatusText, qrValue, qrReplaceable, selectOptions, statusText, issueMessages,
} from './model';
import type { ApiError, CategorySuggestion, FieldName, Receipt, Result } from './model';
import { ExpenseConfirm } from './ExpenseConfirm';

export default function App({ onExpenseSaved }: { onExpenseSaved?: () => void } = {}) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState('');
  const [extracted, setExtracted] = useState<Receipt | null>(null);
  const [extractedSuggestion, setExtractedSuggestion] = useState<CategorySuggestion | null>(null);
  const [session, setSession] = useState(0);

  useEffect(() => {
    if (!file) {
      setPreview('');
      return;
    }
    const url = URL.createObjectURL(file);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  function selectFile(next: File | null) {
    setFile(next);
    setResult(null);
    setError('');
    setNotice('');
    setDirty(false);
    setConsent(false);
    setExtracted(null);
    setExtractedSuggestion(null);
    setSession(value => value + 1);
  }

  async function request(url: string, init: RequestInit) {
    const response = await fetch(url, init);
    if (!response.ok) {
      let code = '';
      try {
        const body = await response.json() as ApiError;
        code = typeof body.detail === 'string'
          ? body.detail
          : body.detail?.code ?? body.code ?? '';
      } catch {
        // Keep the generic message for non-JSON server errors.
      }
      if (response.status === 503 && code === 'provider_rate_limited') {
        throw new Error('Límite temporal del proveedor de extracción. Inténtalo más tarde; no se reintentó.');
      }
      if (code === 'fiscal_qr_signature_invalid') {
        throw new Error('No se pudo comprobar el QR fiscal (por ejemplo, porque el servidor se reinició). Vuelve a extraer el comprobante.');
      }
      if (code === 'groq_disabled' || code === 'groq_not_configured') {
        throw new Error('La extracción automática no está habilitada o configurada en el servidor.');
      }
      throw new Error('No se pudo completar la solicitud. Revisa el archivo e inténtalo de nuevo.');
    }
    return response.json();
  }

  async function extract() {
    if (!file || !consent) {
      setError('Selecciona un archivo y acepta el procesamiento externo antes de extraer.');
      return;
    }
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const extracted = await request('/receipts/extract', {
        method: 'POST',
        headers: {
          'X-Allow-External-Processing': 'true',
          'Content-Type': 'application/octet-stream',
        },
        body: file,
      });
      setResult(extracted);
      setExtracted(extracted.receipt);
      setExtractedSuggestion(extracted.category_suggestion ?? null);
      setSession(value => value + 1);
      setDirty(false);
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (!result) return;
    setBusy(true);
    setError('');
    setNotice('');
    try {
      const validated = await request('/receipts/validate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ receipt: result.receipt, fiscal_qr: result.fiscal_qr ?? null, fiscal_qr_signature: result.fiscal_qr_signature ?? null }),
      });
      setResult(validated);
      setDirty(false);
      setNotice('Validación completada. La revisión humana sigue siendo obligatoria.');
    } catch (cause) {
      setError((cause as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function editField(field: FieldName, value: string) {
    if (!result) return;
    setResult({
      ...result,
      receipt: { ...result.receipt, [field]: value === '' ? null : value },
      field_status: { ...result.field_status, [field]: 'unverified' },
      issues: [],
    });
    setDirty(true);
    setNotice('');
  }

  function handleFileChange(next: File | null) {
    if (next && (!acceptedTypes.includes(next.type) || next.size > maxFileSize)) {
      selectFile(null);
      setError('Elige un archivo JPEG, PNG o PDF de hasta 5 MiB.');
      return;
    }
    selectFile(next);
  }

  return (
    <main>
      <h1>ExpenseLens</h1>
      <p>Extrae y revisa los datos de un recibo.</p>
      <div className="workspace">
      <section className="document-panel" aria-label="Documento">
      <label>
        Archivo (JPEG, PNG o PDF; máximo 5 MiB)
        <input
          aria-label="Archivo"
          type="file"
          accept="image/jpeg,image/png,application/pdf"
          disabled={busy}
          onChange={event => handleFileChange(event.target.files?.[0] ?? null)}
        />
      </label>
      {preview && file && (
        <section aria-label="Vista previa">
          {file.type === 'application/pdf'
            ? <><embed src={preview} type="application/pdf" title="Vista previa PDF" /><a href={preview} target="_blank" rel="noreferrer">Abrir PDF</a></>
            : <img src={preview} alt="Vista previa del recibo" />}
        </section>
      )}
      <label>
        <input
          type="checkbox"
          aria-label="Consentimiento para procesamiento externo"
          checked={consent}
          disabled={busy || !file}
          onChange={event => setConsent(event.target.checked)}
        />
        {' '}Acepto el procesamiento externo del archivo
      </label>
      <p className="privacy-note">Al extraer, la imagen o las páginas del PDF se envían a Groq. Usa solo documentos cuyo envío esté autorizado.</p>
      <button disabled={busy || !file || !consent} onClick={extract}>
        {busy ? 'Procesando…' : 'Extraer datos'}
      </button>
      {busy && <p role="status">Solicitud en curso…</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      </section>
      {result && (
        <section className="review-panel">
          <h2>Datos del recibo</h2>
          <p role="status">Revisión humana requerida. Comprueba todos los campos y advertencias.</p>
          {result.movement === 'credit' && (
            <p className="credit-notice" role="status">Nota de crédito: resta, no es una compra.</p>
          )}
          {result.fiscal_qr_status && (
            <section className={`qr-panel qr-${result.fiscal_qr_status}`} aria-label="QR fiscal">
              <h3>QR fiscal</h3>
              <p className="qr-status">{qrStatusText[result.fiscal_qr_status]}</p>
              {result.fiscal_qr && (
                <dl>
                  <dt>Autorización</dt><dd>{result.fiscal_qr.authorization_type} {result.fiscal_qr.authorization_code}</dd>
                  {fields.map(field => {
                    const value = qrValue(result.fiscal_qr, field);
                    return value ? <div key={field}><dt>{labels[field]}</dt><dd>{value}</dd></div> : null;
                  })}
                </dl>
              )}
            </section>
          )}
          {result.issues.length > 0 && (
            <aside aria-label="Advertencias">
              <h3>Advertencias</h3>
              <ul>
                {result.issues.map((issue, index) => {
                  const severity = issue.severity ?? 'warning';
                  return (
                    <li key={`${issue.field}-${issue.code}-${index}`} className={`issue issue-${severity}`}>
                      <span className="issue-tag">{severity === 'info' ? 'Info' : 'Advertencia'}</span>
                      <strong>{labels[issue.field as FieldName] ?? issue.field}:</strong>{' '}
                      {issueMessages[issue.code] ?? issue.code}
                    </li>
                  );
                })}
              </ul>
            </aside>
          )}
          {dirty && <p role="status">Cambios pendientes de validar. Las advertencias previas ya no aplican.</p>}
          <div className="fields">
            {fields.map(field => {
              const status = result.field_status?.[field];
              const fromQr = qrValue(result.fiscal_qr, field);
              const options = selectOptions[field];
              const value = result.receipt[field] ?? '';
              return (
                <div key={field} className={`field${status ? ` field-${status}` : ''}`} data-field={field}>
                  <label>
                    {labels[field]}
                    {options ? (
                      <select aria-label={labels[field]} value={value} disabled={busy} onChange={event => editField(field, event.target.value)}>
                        <option value="">—</option>
                        {options.map(([optionValue, text]) => <option key={optionValue} value={optionValue}>{text}</option>)}
                      </select>
                    ) : (
                      <input aria-label={labels[field]} value={value} disabled={busy} onChange={event => editField(field, event.target.value)} />
                    )}
                  </label>
                  <div className="field-meta">
                    {status && <span className={`badge badge-${status}`}>{statusText[status]}</span>}
                    {status && qrReplaceable.includes(status) && fromQr && fromQr !== value && (
                      <button type="button" className="qr-use" aria-label={`Usar valor del QR para ${labels[field]}`} disabled={busy} onClick={() => editField(field, fromQr)}>
                        Usar valor del QR ({fromQr})
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
          <button disabled={busy} onClick={validate}>Validar correcciones</button>
          <ExpenseConfirm key={session} file={file} result={result} extracted={extracted} extractedSuggestion={extractedSuggestion} disabled={busy} onSaved={() => onExpenseSaved?.()} />
        </section>
      )}
      </div>
      <p className="privacy-note">Solo se guardan los datos que confirmas, nunca la imagen del documento.</p>
    </main>
  );
}
