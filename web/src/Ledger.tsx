import { useCallback, useEffect, useState } from 'react';
import { deleteExpense, exportUrl, expenseStats, listExpenses } from './api';
import { categories, categoryLabels, emptyFilters, labels } from './model';
import type { ExpenseFilters, ExpenseList, ExpenseStats, FieldName } from './model';

const percent = (rate: number) => `${Math.round(rate * 100)}%`;
const rateText = (rate: number | null) => (rate === null ? 'n/a' : percent(rate));

function StatsCard({ stats }: { stats: ExpenseStats }) {
  const entries = Object.entries(stats.correction_rate_by_field) as [FieldName, number][];
  return (
    <section className="stats-card" aria-label="Correcciones">
      <h3>Correcciones</h3>
      <p className="muted">Con qué frecuencia corregís lo que extrajo el modelo ({stats.with_extraction} de {stats.count} gastos con extracción).</p>
      {entries.length > 0 ? (
        <ul>
          {entries.map(([field, rate]) => (
            <li key={field}>
              <span>{labels[field] ?? field}</span>
              <span className="bar"><span style={{ width: percent(rate) }} /></span>
              <strong>{percent(rate)}</strong>
            </li>
          ))}
        </ul>
      ) : <p className="muted">Sin datos de corrección todavía.</p>}
      {stats.suggestion_acceptance && (
        <p>Aceptación de la sugerencia: IA <strong>{rateText(stats.suggestion_acceptance.model)}</strong> · reglas <strong>{rateText(stats.suggestion_acceptance.rules)}</strong></p>
      )}
      <p>Verificados por QR: <strong>{stats.qr_verified_rate === null ? 'Sin datos' : percent(stats.qr_verified_rate)}</strong></p>
    </section>
  );
}

export function Ledger({ refreshKey = 0 }: { refreshKey?: number }) {
  const [draft, setDraft] = useState<ExpenseFilters>(emptyFilters);
  const [applied, setApplied] = useState<ExpenseFilters>(emptyFilters);
  const [data, setData] = useState<ExpenseList | null>(null);
  const [stats, setStats] = useState<ExpenseStats | null>(null);
  const [error, setError] = useState('');
  const [pendingDelete, setPendingDelete] = useState<number | null>(null);
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let active = true;
    listExpenses(applied)
      .then(next => { if (active) { setData(next); setError(''); } })
      .catch(() => { if (active) setError('No se pudo cargar el historial.'); });
    expenseStats()
      .then(next => { if (active) setStats(next); })
      .catch(() => { if (active) setStats(null); });
    return () => { active = false; };
  }, [applied, refreshKey, version]);

  const set = (key: keyof ExpenseFilters) => (value: string) => setDraft(current => ({ ...current, [key]: value }));

  const remove = useCallback(async (id: number) => {
    try {
      await deleteExpense(id);
      setPendingDelete(null);
      setVersion(value => value + 1);
    } catch {
      setError('No se pudo eliminar el gasto.');
    }
  }, []);

  return (
    <section className="ledger" aria-label="Mis gastos">
      <h2>Mis gastos</h2>
      <form className="filters" onSubmit={event => { event.preventDefault(); setApplied(draft); }}>
        <label>Desde<input type="date" aria-label="Desde" value={draft.date_from} onChange={event => set('date_from')(event.target.value)} /></label>
        <label>Hasta<input type="date" aria-label="Hasta" value={draft.date_to} onChange={event => set('date_to')(event.target.value)} /></label>
        <label>Búsqueda<input aria-label="Búsqueda" placeholder="Emisor o número" value={draft.q} onChange={event => set('q')(event.target.value)} /></label>
        <label>Categoría
          <select aria-label="Categoría" value={draft.category} onChange={event => set('category')(event.target.value)}>
            <option value="">Todas</option>
            {categories.map(value => <option key={value} value={value}>{categoryLabels[value]}</option>)}
          </select>
        </label>
        <label>Importe mínimo<input inputMode="decimal" aria-label="Importe mínimo" value={draft.min_total} onChange={event => set('min_total')(event.target.value)} /></label>
        <label>Importe máximo<input inputMode="decimal" aria-label="Importe máximo" value={draft.max_total} onChange={event => set('max_total')(event.target.value)} /></label>
        <label>Moneda<input aria-label="Moneda" maxLength={3} placeholder="ARS" value={draft.currency} onChange={event => set('currency')(event.target.value.toUpperCase())} /></label>
        <div className="filter-actions">
          <button type="submit" className="primary">Filtrar</button>
          <button type="button" onClick={() => { setDraft(emptyFilters); setApplied(emptyFilters); }}>Limpiar</button>
          <a className="button-link" href={exportUrl(applied)} download>Exportar CSV</a>
        </div>
      </form>
      {error && <p role="alert">{error}</p>}
      {data && data.totals.length > 0 && (
        <div className="totals" aria-label="Totales por moneda">
          {data.totals.map(total => (
            <article key={total.currency} className="total-card" aria-label={`Totales ${total.currency}`}>
              <h3>{total.currency} <small>{total.count} {total.count === 1 ? 'comprobante' : 'comprobantes'}</small></h3>
              <dl>
                <dt>Gastos</dt><dd>{total.expenses} {total.currency}</dd>
                <dt>Créditos</dt><dd>{total.credits} {total.currency}</dd>
                <dt>Neto</dt><dd className="net">{total.net} {total.currency}</dd>
              </dl>
            </article>
          ))}
        </div>
      )}
      {data && data.items.length === 0 && <p className="muted">No hay gastos para estos filtros.</p>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Fecha</th><th>Emisor</th><th>Categoría</th><th className="num">Importe</th><th>QR</th><th><span className="sr-only">Acciones</span></th></tr>
            </thead>
            <tbody>
              {data.items.map(item => {
                const negative = item.signed_total.trim().startsWith('-');
                return (
                  <tr key={item.id} className={item.movement === 'credit' ? 'row-credit' : undefined}>
                    <td>{item.receipt.date}</td>
                    <td>{item.receipt.issuer}</td>
                    <td>{categoryLabels[item.category] ?? item.category}{item.suggestion_accepted === false && <small className="muted"> · categoría cambiada</small>}</td>
                    <td className={`num amount${negative ? ' negative' : ''}`}>{item.signed_total} {item.receipt.currency}</td>
                    <td>{item.fiscal_qr_verified ? <span className="badge badge-verified">QR verificado</span> : <span className="muted">—</span>}</td>
                    <td className="row-actions">
                      {pendingDelete === item.id ? (
                        <span role="group" aria-label={`Confirmar eliminación del gasto ${item.id}`}>
                          ¿Eliminar definitivamente?{' '}
                          <button className="danger" onClick={() => remove(item.id)}>Confirmar eliminación</button>
                          <button onClick={() => setPendingDelete(null)}>Cancelar</button>
                        </span>
                      ) : (
                        <button aria-label={`Eliminar gasto ${item.id}`} onClick={() => setPendingDelete(item.id)}>Eliminar</button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {stats && <StatsCard stats={stats} />}
    </section>
  );
}
