import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import App from './App';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
beforeEach(() => { vi.stubGlobal('URL', { createObjectURL: vi.fn(() => 'blob:preview'), revokeObjectURL: vi.fn() }); });
const file = () => new File(['receipt'], 'receipt.png', { type: 'image/png' });
const result = { receipt: { issuer: 'Cafe', date: null, number: null, currency: 'USD', subtotal: null, tax: null, total: '12.00' }, issues: [{ code: 'check', field: 'total' }], requires_human_review: true };
function chooseAndConsent() {
  fireEvent.change(screen.getByLabelText(/^archivo$/i), { target: { files: [file()] } });
  fireEvent.click(screen.getByLabelText(/procesamiento externo/i));
}

describe('ExpenseLens', () => {
  it('requires explicit consent before extracting', async () => {
    const fetch = vi.fn(); vi.stubGlobal('fetch', fetch);
    render(<App />);
    fireEvent.change(screen.getByLabelText(/^archivo$/i), { target: { files: [file()] } });
    expect(screen.getByRole('button', { name: /extraer/i }).hasAttribute('disabled')).toBe(true);
    expect((screen.getByLabelText(/procesamiento externo/i) as HTMLInputElement).checked).toBe(false);
    expect(fetch).not.toHaveBeenCalled();
  });
  it('clears result, error and consent when choosing a new file', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => result }));
    render(<App />); chooseAndConsent(); fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    expect(await screen.findByDisplayValue('Cafe')).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^archivo$/i), { target: { files: [file()] } });
    expect(screen.queryByDisplayValue('Cafe')).toBeNull();
    expect((screen.getByLabelText(/procesamiento externo/i) as HTMLInputElement).checked).toBe(false);
  });
  it('shows rate limit without retrying', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: 'provider_rate_limited' }) });
    vi.stubGlobal('fetch', fetch); render(<App />); chooseAndConsent();
    fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    expect(await screen.findByText(/límite temporal del proveedor/i)).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it('clears pending edits after a successful new extraction and shows its warnings', async () => {
    const fresh = { ...result, receipt: { ...result.receipt, issuer: 'Fresh receipt' }, issues: [{ code: 'missing_field', field: 'date' }] };
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => result })
      .mockResolvedValueOnce({ ok: true, json: async () => fresh });
    vi.stubGlobal('fetch', fetch);
    render(<App />); chooseAndConsent();
    fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    fireEvent.change(await screen.findByDisplayValue('Cafe'), { target: { value: 'Edited receipt' } });
    expect(screen.queryByText(/cambios pendientes de validar/i)).not.toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    expect(await screen.findByDisplayValue('Fresh receipt')).toBeTruthy();
    expect(screen.queryByText(/cambios pendientes de validar/i)).toBeNull();
    expect(screen.getByText(/falta este dato/i)).toBeTruthy();
    expect(screen.getByText(/revisión humana requerida/i)).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('retains edited fields and pending status when a new extraction fails', async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => result })
      .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({ detail: 'provider_rate_limited' }) });
    vi.stubGlobal('fetch', fetch);
    render(<App />); chooseAndConsent();
    fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    fireEvent.change(await screen.findByDisplayValue('Cafe'), { target: { value: 'Edited receipt' } });
    fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    expect(await screen.findByText(/límite temporal del proveedor/i)).toBeTruthy();
    expect(screen.getByDisplayValue('Edited receipt')).toBeTruthy();
    expect(screen.getByText(/cambios pendientes de validar/i)).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(2);
  });
  it('submits edited fields with empty nullable values as null and retains review status', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result }); vi.stubGlobal('fetch', fetch);
    render(<App />); chooseAndConsent(); fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    const issuer = await screen.findByDisplayValue('Cafe'); fireEvent.change(issuer, { target: { value: 'Cafe Uno' } });
    expect(await screen.findByText(/cambios pendientes de validar/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /validar correcciones/i }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ receipt: { issuer: 'Cafe Uno', date: null, subtotal: null } });
    expect(await screen.findByText(/revisión humana requerida/i)).toBeTruthy();
  });

  describe('argentine review', () => {
    const qr = {
      issuer_cuit: '30000000007', date: '2026-10-15', point_of_sale: 3, number: 45, receipt_type_code: 1,
      document_type: 'factura', letter: 'A', total: '1210.00', currency: 'ARS', exchange_rate: '1',
      authorization_type: 'CAE', authorization_code: '70123456789012',
    };
    const rich = {
      receipt: { issuer: 'Cafe', issuer_cuit: null, date: '2026-10-14', number: null, document_type: 'factura', letter: 'A', currency: 'ARS', subtotal: '1000.00', tax: '210.00', total: '1200.00' },
      issues: [{ code: 'qr_mismatch', field: 'total', severity: 'warning' }, { code: 'foreign_currency', field: 'currency', severity: 'info' }],
      field_status: { issuer: 'unverified', issuer_cuit: 'empty', date: 'verified', number: 'missing', document_type: 'verified', letter: 'verified', currency: 'verified', subtotal: 'unverified', tax: 'unverified', total: 'conflict' },
      movement: 'credit', fiscal_qr: qr, fiscal_qr_status: 'found', requires_human_review: true,
    };
    async function extractRich() {
      const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => rich }); vi.stubGlobal('fetch', fetch);
      render(<App />); chooseAndConsent(); fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
      await screen.findByDisplayValue('Cafe');
      return fetch;
    }
    const fieldOf = (label: string) => within(screen.getByLabelText(label).closest('.field') as HTMLElement);

    it('shows a textual status badge per field', async () => {
      await extractRich();
      expect(fieldOf('Fecha').getByText('Verificado por QR')).toBeTruthy();
      expect(fieldOf('Total').getByText('Revisar: hay una advertencia')).toBeTruthy();
      expect(fieldOf('Número').getByText('Faltante')).toBeTruthy();
      expect(fieldOf('Emisor').getByText('Sin verificar')).toBeTruthy();
      expect(fieldOf('CUIT del emisor').getByText('Vacío')).toBeTruthy();
    });
    it('renders selects with allowed values', async () => {
      await extractRich();
      const letter = screen.getByLabelText('Letra') as HTMLSelectElement;
      expect(letter.value).toBe('A');
      expect(within(letter).getAllByRole('option').map(o => o.textContent)).toEqual(['—', 'A', 'B', 'C', 'E', 'M']);
      expect((screen.getByLabelText('Tipo de comprobante') as HTMLSelectElement).value).toBe('factura');
    });
    it('explains issues in Spanish with severity', async () => {
      await extractRich();
      const warning = screen.getByText(/no coincide con el del QR fiscal/i).closest('li') as HTMLElement;
      expect(warning.className).toContain('issue-warning');
      const info = screen.getByText(/no se convirtió a pesos/i).closest('li') as HTMLElement;
      expect(info.className).toContain('issue-info');
    });
    it('shows the credit notice', async () => {
      await extractRich();
      expect(screen.getByText(/resta, no es una compra/i)).toBeTruthy();
    });
    it('shows the fiscal QR panel', async () => {
      await extractRich();
      const panel = within(screen.getByLabelText('QR fiscal'));
      expect(panel.getByText(/QR fiscal encontrado/i)).toBeTruthy();
      expect(panel.getByText('CAE 70123456789012')).toBeTruthy();
      expect(panel.getByText('00003-00000045')).toBeTruthy();
      expect(panel.getByText('1210.00')).toBeTruthy();
    });
    it('uses the QR value only for that field, marks pending and does not validate', async () => {
      const fetch = await extractRich();
      fireEvent.click(screen.getByRole('button', { name: /usar valor del qr para total/i }));
      expect((screen.getByLabelText('Total') as HTMLInputElement).value).toBe('1210.00');
      expect((screen.getByLabelText('Fecha') as HTMLInputElement).value).toBe('2026-10-14');
      expect(screen.getByText(/cambios pendientes de validar/i)).toBeTruthy();
      expect(screen.queryByRole('button', { name: /usar valor del qr para total/i })).toBeNull();
      expect(screen.getByRole('button', { name: /usar valor del qr para número/i })).toBeTruthy();
      expect(screen.queryByRole('button', { name: /usar valor del qr para fecha/i })).toBeNull();
      expect(fetch).toHaveBeenCalledTimes(1);
    });
    it('sends fiscal_qr on validate and keeps the returned qr status', async () => {
      const fetch = await extractRich();
      fetch.mockResolvedValueOnce({ ok: true, json: async () => ({ ...rich, issues: [], fiscal_qr_status: 'invalid', fiscal_qr: null }) });
      fireEvent.click(screen.getByRole('button', { name: /validar correcciones/i }));
      await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
      expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ receipt: { issuer: 'Cafe' }, fiscal_qr: { authorization_code: '70123456789012' } });
      expect(await screen.findByText(/no es un QR fiscal válido/i)).toBeTruthy();
    });
  });
});
