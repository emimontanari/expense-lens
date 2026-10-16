import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
  it('submits edited fields with empty nullable values as null and retains review status', async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result }); vi.stubGlobal('fetch', fetch);
    render(<App />); chooseAndConsent(); fireEvent.click(screen.getByRole('button', { name: /extraer/i }));
    const issuer = await screen.findByDisplayValue('Cafe'); fireEvent.change(issuer, { target: { value: 'Cafe Uno' } });
    expect(await screen.findByText(/cambios pendientes de validar/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /validar correcciones/i }));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetch.mock.calls[1][1].body)).toMatchObject({ issuer: 'Cafe Uno', date: null, subtotal: null });
    expect(await screen.findByText(/revisión humana requerida/i)).toBeTruthy();
  });
});
