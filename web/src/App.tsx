import { useEffect, useState } from 'react';
import './style.css';

type Receipt = {
  issuer: string | null;
  date: string | null;
  number: string | null;
  currency: string | null;
  subtotal: string | null;
  tax: string | null;
  total: string | null;
};
type Result = {
  receipt: Receipt;
  issues: { code: string; field: string }[];
  requires_human_review: boolean;
};
type ApiError = { detail?: string | { code?: string }; code?: string };

const fields: (keyof Receipt)[] = ['issuer', 'date', 'number', 'currency', 'subtotal', 'tax', 'total'];
const labels: Record<keyof Receipt, string> = {
  issuer: 'Emisor', date: 'Fecha', number: 'Número', currency: 'Moneda',
  subtotal: 'Subtotal', tax: 'Impuestos', total: 'Total',
};
const maxFileSize = 5 * 1024 * 1024;
const acceptedTypes = ['image/jpeg', 'image/png', 'application/pdf'];

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState('');
  const [consent, setConsent] = useState(false);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [notice, setNotice] = useState('');

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
        body: JSON.stringify(result.receipt),
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
          {result.issues.length > 0 && (
            <aside aria-label="Advertencias">
              <h3>Advertencias</h3>
              <ul>{result.issues.map((issue, index) => <li key={`${issue.field}-${issue.code}-${index}`}>{issue.field}: {issue.code}</li>)}</ul>
            </aside>
          )}
          {dirty && <p role="status">Cambios pendientes de validar. Las advertencias previas ya no aplican.</p>}
          {fields.map(field => (
            <label key={field}>
              {labels[field]}
              <input
                aria-label={labels[field]}
                value={result.receipt[field] ?? ''}
                disabled={busy}
                onChange={event => {
                  setResult({
                    ...result,
                    receipt: { ...result.receipt, [field]: event.target.value === '' ? null : event.target.value },
                    issues: [],
                  });
                  setDirty(true);
                  setNotice('');
                }}
              />
            </label>
          ))}
          <button disabled={busy} onClick={validate}>Validar correcciones</button>
        </section>
      )}
      </div>
      <p>Esta versión no guarda datos ni incluye CSV, cuentas o historial.</p>
    </main>
  );
}
