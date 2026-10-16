import { useState } from 'react';
import { ExpenseApiError, saveExpense, sha256Hex } from './api';
import { categories, categoryLabels, duplicateReasonText, labels } from './model';
import type { Category, DuplicateMatch, FieldName, Receipt, Result } from './model';

type Props = {
  file: File | null;
  result: Result;
  /** Receipt exactly as /receipts/extract returned it; kept even when the user edits the form. */
  extracted: Receipt | null;
  disabled: boolean;
  onSaved: () => void;
};

export function ExpenseConfirm({ file, result, extracted, disabled, onSaved }: Props) {
  const [category, setCategory] = useState<Category>('otros');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState('');
  const [missing, setMissing] = useState<string[]>([]);
  const [matches, setMatches] = useState<DuplicateMatch[]>([]);

  async function submit(allowDuplicate: boolean) {
    setSaving(true);
    setError('');
    setMissing([]);
    setMatches([]);
    try {
      await saveExpense({
        receipt: result.receipt,
        fiscal_qr: result.fiscal_qr ?? null,
        category,
        extracted,
        document_sha256: file ? await sha256Hex(file) : null,
        allow_duplicate: allowDuplicate,
      });
      setSaved(true);
      onSaved();
    } catch (cause) {
      if (cause instanceof ExpenseApiError && cause.status === 409 && cause.code === 'duplicate_expense') {
        setMatches(cause.matches);
      } else if (cause instanceof ExpenseApiError && cause.status === 422 && cause.code === 'incomplete_expense') {
        setMissing(cause.fields);
      } else {
        setError((cause as Error).message);
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <section className="confirm-panel" aria-label="Confirmar gasto">
      <h3>Guardar en mis gastos</h3>
      <label>
        Categoría del gasto
        <select aria-label="Categoría del gasto" value={category} disabled={disabled || saving || saved} onChange={event => { setCategory(event.target.value as Category); setSaved(false); }}>
          {categories.map(value => <option key={value} value={value}>{categoryLabels[value]}</option>)}
        </select>
      </label>
      <button className="primary" disabled={disabled || saving || saved} onClick={() => submit(false)}>
        {saving ? 'Guardando…' : 'Confirmar gasto'}
      </button>
      {saved && <p role="status" className="notice-success">Gasto guardado. Ya figura en tu historial.</p>}
      {error && <p role="alert">{error}</p>}
      {missing.length > 0 && (
        <p role="alert" className="incomplete-expense">
          Faltan datos obligatorios para guardar: {missing.map(field => labels[field as FieldName] ?? field).join(', ')}.
          Completalos y volvé a confirmar.
        </p>
      )}
      {matches.length > 0 && (
        <aside aria-label="Posibles duplicados" className="duplicate-warning">
          <strong>Este gasto podría estar duplicado.</strong>
          <ul>
            {matches.map(match => (
              <li key={`${match.id}-${match.reason}`}>
                Gasto #{match.id}{match.issuer ? ` · ${match.issuer}` : ''}{match.date ? ` · ${match.date}` : ''}{match.total ? ` · ${match.total} ${match.currency ?? ''}` : ''}: {duplicateReasonText[match.reason] ?? match.reason}
              </li>
            ))}
          </ul>
          <button disabled={saving} onClick={() => submit(true)}>Guardar de todos modos</button>
        </aside>
      )}
    </section>
  );
}
