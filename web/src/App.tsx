import { useEffect, useState } from 'react';
import './style.css';

type Receipt = {
  issuer: string | null;
  issuer_cuit: string | null;
  date: string | null;
  number: string | null;
  document_type: string | null;
  letter: string | null;
  currency: string | null;
  subtotal: string | null;
  tax: string | null;
  total: string | null;
};
type FieldName = keyof Receipt;
type FieldStatus = 'verified' | 'conflict' | 'missing' | 'unverified' | 'empty';
type FiscalQr = {
  issuer_cuit: string;
  date: string;
  point_of_sale: number;
  number: number;
  receipt_type_code: number;
  document_type: string | null;
  letter: string | null;
  total: string;
  currency: string | null;
  exchange_rate: string;
  authorization_type: 'CAE' | 'CAEA';
  authorization_code: string;
};
type Issue = { code: string; field: string; severity?: 'warning' | 'info' };
type Result = {
  receipt: Receipt;
  issues: Issue[];
  field_status?: Partial<Record<FieldName, FieldStatus>>;
  movement?: 'expense' | 'credit' | 'unknown';
  fiscal_qr?: FiscalQr | null;
  fiscal_qr_status?: 'found' | 'not_found' | 'invalid' | null;
  requires_human_review: boolean;
};
type ApiError = { detail?: string | { code?: string }; code?: string };

const fields: FieldName[] = [
  'issuer', 'issuer_cuit', 'date', 'number', 'document_type', 'letter',
  'currency', 'subtotal', 'tax', 'total',
];
const labels: Record<FieldName, string> = {
  issuer: 'Emisor', issuer_cuit: 'CUIT del emisor', date: 'Fecha', number: 'Número',
  document_type: 'Tipo de comprobante', letter: 'Letra', currency: 'Moneda',
  subtotal: 'Subtotal', tax: 'Impuestos', total: 'Total',
};
const selectOptions: Partial<Record<FieldName, [string, string][]>> = {
  document_type: [
    ['factura', 'Factura'], ['nota_credito', 'Nota de crédito'], ['nota_debito', 'Nota de débito'],
    ['ticket', 'Ticket'], ['otro', 'Otro'],
  ],
  letter: ['A', 'B', 'C', 'E', 'M'].map(letter => [letter, letter]),
};
const statusText: Record<FieldStatus, string> = {
  verified: 'Verificado por QR',
  conflict: 'Revisar: hay una advertencia',
  missing: 'Faltante',
  unverified: 'Sin verificar',
  empty: 'Vacío',
};
const qrReplaceable: FieldStatus[] = ['conflict', 'missing', 'empty'];
const issueMessages: Record<string, string> = {
  missing_field: 'Falta este dato en el comprobante.',
  ambiguous_amount: 'El importe es ambiguo; no se adivinó. Escríbelo a mano.',
  unparseable_amount: 'No se pudo interpretar el importe.',
  invalid_date: 'La fecha no es válida.',
  unknown_currency: 'La moneda no se reconoce.',
  invalid_cuit: 'El CUIT no es válido (revisa los 11 dígitos y el dígito verificador).',
  total_mismatch: 'El total no coincide con subtotal + impuestos.',
  total_below_subtotal: 'El total es menor que el subtotal; puede ser un subtotal confundido con el total.',
  tax_already_included: 'El subtotal parece incluir ya el IVA; no se suma de nuevo.',
  subtotal_equals_total: 'El subtotal es igual al total sin IVA discriminado: puede ser una copia del total. Confírmalo o déjalo vacío.',
  unexpected_tax: 'Este tipo de comprobante no suele discriminar impuestos.',
  future_date: 'La fecha es posterior a hoy.',
  credit_note: 'Es una nota de crédito: no es una compra común.',
  foreign_currency: 'Importe en moneda extranjera; no se convirtió a pesos.',
  currency_inferred_from_symbol: 'La moneda se dedujo del símbolo del importe. Confírmala.',
  qr_mismatch: 'El valor visible no coincide con el del QR fiscal.',
};
const qrStatusText = {
  found: 'QR fiscal encontrado y leído.',
  not_found: 'No se encontró un QR fiscal en el documento.',
  invalid: 'Se encontró un QR, pero no es un QR fiscal válido.',
};
function qrValue(qr: FiscalQr | null | undefined, field: FieldName): string | null {
  if (!qr) return null;
  switch (field) {
    case 'issuer_cuit': return qr.issuer_cuit;
    case 'date': return qr.date;
    case 'total': return qr.total;
    case 'currency': return qr.currency;
    case 'document_type': return qr.document_type;
    case 'letter': return qr.letter;
    case 'number': return `${String(qr.point_of_sale).padStart(5, '0')}-${String(qr.number).padStart(8, '0')}`;
    default: return null;
  }
}
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
        body: JSON.stringify({ receipt: result.receipt, fiscal_qr: result.fiscal_qr ?? null }),
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
        </section>
      )}
      </div>
      <p>Esta versión no guarda datos ni incluye CSV, cuentas o historial.</p>
    </main>
  );
}
