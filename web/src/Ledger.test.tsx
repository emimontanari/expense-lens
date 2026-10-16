import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import AppShell from './AppShell';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => { vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:preview'), revokeObjectURL: vi.fn() }); });

const receipt = { issuer: 'Cafe', issuer_cuit: null, date: '2026-10-14', number: null, document_type: 'factura', letter: 'B', currency: 'ARS', subtotal: null, tax: null, total: '1200.00' };
const extractResult = { receipt, issues: [], movement: 'expense', fiscal_qr: null, fiscal_qr_status: 'not_found', requires_human_review: true };
const expense = (id: number, over: object = {}) => ({
  id, created_at: '', updated_at: '', receipt, category: 'otros', movement: 'expense', signed_total: '1200.00', issues: [],
  field_status: {}, fiscal_qr_verified: false, corrected_fields: null, document_sha256: null, duplicate_of: [], ...over,
});
const list = {
  items: [
    expense(1, { category: 'supermercado', fiscal_qr_verified: true }),
    expense(2, { movement: 'credit', signed_total: '-300.00', receipt: { ...receipt, issuer: 'Devolucion' } }),
    expense(3, { signed_total: '10.00', receipt: { ...receipt, currency: 'USD', issuer: 'Shop' } }),
  ],
  totals: [
    { currency: 'ARS', expenses: '1200.00', credits: '300.00', net: '900.00', count: 2 },
    { currency: 'USD', expenses: '10.00', credits: '0.00', net: '10.00', count: 1 },
  ],
};
const stats = { count: 4, with_extraction: 3, correction_rate_by_field: { issuer: 0.25, total: 0.5 }, qr_verified_rate: 0.75 };
const ok = (body: unknown, status = 200) => ({ ok: true, status, json: async () => body });
const fail = (status: number, detail: unknown) => ({ ok: false, status, json: async () => ({ detail }) });

function route(overrides: Record<string, (init?: RequestInit) => unknown> = {}) {
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    const key = `${init?.method ?? 'GET'} ${url.split('?')[0]}`;
    if (overrides[key]) return overrides[key](init);
    if (key === 'POST /receipts/extract') return ok(extractResult);
    if (key === 'GET /expenses') return ok(list);
    if (key === 'GET /expenses/stats') return ok(stats);
    if (key === 'POST /expenses') return ok(expense(9), 201);
    if (key === 'DELETE /expenses/1') return { ok: true, status: 204, json: async () => { throw new Error('no body'); } };
    throw new Error(`unexpected ${key}`);
  });
  vi.stubGlobal('fetch', fetch);
  return fetch;
}
const callsTo = (fetch: ReturnType<typeof vi.fn>, method: string, path: string) =>
  fetch.mock.calls.filter(([url, init]) => (init?.method ?? 'GET') === method && String(url).split('?')[0] === path);

async function reviewed() {
  fireEvent.change(screen.getByLabelText(/^archivo$/i), { target: { files: [new File(['receipt'], 'r.png', { type: 'image/png' })] } });
  fireEvent.click(screen.getByLabelText(/procesamiento externo/i));
  fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
  await screen.findByDisplayValue('Cafe');
}

describe('confirm expense', () => {
  it('posts the exact body with extracted kept after edits and the file sha256', async () => {
    const fetch = route(); render(<AppShell />); await reviewed();
    fireEvent.change(screen.getByLabelText('Emisor'), { target: { value: 'Cafe Uno' } });
    fireEvent.change(screen.getByLabelText('Categoría del gasto'), { target: { value: 'restaurantes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar gasto' }));
    expect(await screen.findByText(/gasto guardado/i)).toBeTruthy();
    const body = JSON.parse(callsTo(fetch, 'POST', '/expenses')[0][1].body);
    expect(body).toEqual({
      receipt: { ...receipt, issuer: 'Cafe Uno' }, fiscal_qr: null, category: 'restaurantes',
      extracted: receipt, document_sha256: expect.stringMatching(/^[0-9a-f]{64}$/), allow_duplicate: false,
    });
    await waitFor(() => expect(callsTo(fetch, 'GET', '/expenses').length).toBe(2));
  });
  it('shows duplicate matches and resends with allow_duplicate', async () => {
    let first = true;
    const fetch = route({ 'POST /expenses': () => {
      if (first) { first = false; return fail(409, { code: 'duplicate_expense', matches: [{ id: 5, reason: 'same_file', issuer: 'Super Uno', date: '2026-10-01', total: '1500.00', currency: 'ARS' }, { id: 6, reason: 'similar' }] }); }
      return ok(expense(9), 201);
    } });
    render(<AppShell />); await reviewed();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar gasto' }));
    expect(await screen.findByText(/mismo archivo/i)).toBeTruthy();
    expect(screen.getByText(/Gasto #5 · Super Uno · 2026-10-01 · 1500.00 ARS/)).toBeTruthy();
    expect(screen.getByText(/operación similar/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Guardar de todos modos' }));
    expect(await screen.findByText(/gasto guardado/i)).toBeTruthy();
    const posts = callsTo(fetch, 'POST', '/expenses');
    expect(posts).toHaveLength(2);
    expect(JSON.parse(posts[1][1].body).allow_duplicate).toBe(true);
  });
  it('lists missing fields on incomplete_expense', async () => {
    route({ 'POST /expenses': () => fail(422, { code: 'incomplete_expense', fields: ['date', 'total'] }) });
    render(<AppShell />); await reviewed();
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar gasto' }));
    expect(await screen.findByText(/faltan datos obligatorios.*fecha, total/i)).toBeTruthy();
  });
});

describe('ledger', () => {
  it('sends filters in the query string and in the export link', async () => {
    const fetch = route(); render(<AppShell />);
    await screen.findByText('Devolucion');
    fireEvent.change(screen.getByLabelText('Desde'), { target: { value: '2026-10-01' } });
    fireEvent.change(screen.getByLabelText('Búsqueda'), { target: { value: 'caf' } });
    fireEvent.change(screen.getByLabelText('Categoría'), { target: { value: 'salud' } });
    fireEvent.change(screen.getByLabelText('Importe mínimo'), { target: { value: '10' } });
    fireEvent.change(screen.getByLabelText('Moneda'), { target: { value: 'ars' } });
    fireEvent.click(screen.getByRole('button', { name: 'Filtrar' }));
    await waitFor(() => expect(callsTo(fetch, 'GET', '/expenses')).toHaveLength(2));
    const query = (u: string) => Object.fromEntries(new URLSearchParams(u.split('?')[1] ?? ''));
    const sent = query(String(callsTo(fetch, 'GET', '/expenses')[1][0]));
    expect(sent).toEqual({ date_from: '2026-10-01', q: 'caf', category: 'salud', min_total: '10', currency: 'ARS' });
    const href = screen.getByRole('link', { name: 'Exportar CSV' }).getAttribute('href')!;
    expect(href.split('?')[0]).toBe('/expenses/export.csv');
    expect(query(href)).toEqual(sent);
  });
  it('renders totals per currency and negative credit notes', async () => {
    route(); render(<AppShell />);
    const ars = within(await screen.findByLabelText('Totales ARS'));
    expect(ars.getByText('900.00 ARS')).toBeTruthy();
    expect(ars.getByText('300.00 ARS')).toBeTruthy();
    expect(within(screen.getByLabelText('Totales USD')).getAllByText('10.00 USD')).toHaveLength(2);
    const credit = screen.getByText('-300.00 ARS');
    expect(credit.className).toContain('negative');
    expect(screen.getAllByText('QR verificado')).toHaveLength(1);
  });
  it('requires confirmation before deleting and refreshes', async () => {
    const fetch = route(); render(<AppShell />);
    await screen.findByText('Devolucion');
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar gasto 1' }));
    expect(callsTo(fetch, 'DELETE', '/expenses/1')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(callsTo(fetch, 'DELETE', '/expenses/1')).toHaveLength(0);
    fireEvent.click(screen.getByRole('button', { name: 'Eliminar gasto 1' }));
    fireEvent.click(screen.getByRole('button', { name: 'Confirmar eliminación' }));
    await waitFor(() => expect(callsTo(fetch, 'DELETE', '/expenses/1')).toHaveLength(1));
    await waitFor(() => expect(callsTo(fetch, 'GET', '/expenses')).toHaveLength(2));
  });
  it('shows the corrections card', async () => {
    route(); render(<AppShell />);
    const card = within(await screen.findByLabelText('Correcciones'));
    expect(card.getByText('Emisor')).toBeTruthy();
    expect(card.getByText('25%')).toBeTruthy();
    expect(card.getByText('50%')).toBeTruthy();
    expect(card.getByText('75%')).toBeTruthy();
  });
});
