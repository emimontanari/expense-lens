import type { DuplicateMatch, ExpenseFilters, ExpenseInput, Expense, ExpenseList, ExpenseStats } from './model';

export class ExpenseApiError extends Error {
  constructor(message: string, readonly status: number, readonly code: string, readonly detail: Record<string, unknown>) {
    super(message);
  }
  get matches(): DuplicateMatch[] {
    return Array.isArray(this.detail.matches) ? this.detail.matches as DuplicateMatch[] : [];
  }
  get fields(): string[] {
    return Array.isArray(this.detail.fields) ? this.detail.fields as string[] : [];
  }
}

const genericError = 'No se pudo completar la solicitud. Inténtalo de nuevo.';

async function expenseRequest(url: string, init?: RequestInit): Promise<Response> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let detail: Record<string, unknown> = {};
    try {
      const body = await response.json() as { detail?: unknown };
      if (body.detail && typeof body.detail === 'object') detail = body.detail as Record<string, unknown>;
      else if (typeof body.detail === 'string') detail = { code: body.detail };
    } catch {
      // Non-JSON error body: keep the generic message.
    }
    throw new ExpenseApiError(genericError, response.status, String(detail.code ?? ''), detail);
  }
  return response;
}

export function filtersQuery(filters: ExpenseFilters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value.trim() !== '') params.set(key, value.trim());
  }
  return params.toString();
}

const withQuery = (path: string, query: string) => (query ? `${path}?${query}` : path);

export const exportUrl = (filters: ExpenseFilters) => withQuery('/expenses/export.csv', filtersQuery(filters));

export async function saveExpense(input: ExpenseInput): Promise<Expense> {
  const response = await expenseRequest('/expenses', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(input),
  });
  return response.json();
}

export async function listExpenses(filters: ExpenseFilters): Promise<ExpenseList> {
  return (await expenseRequest(withQuery('/expenses', filtersQuery(filters)))).json();
}

export async function deleteExpense(id: number): Promise<void> {
  await expenseRequest(`/expenses/${id}`, { method: 'DELETE' });
}

export async function expenseStats(): Promise<ExpenseStats> {
  return (await expenseRequest('/expenses/stats')).json();
}

async function readBytes(file: File): Promise<ArrayBuffer> {
  if (typeof file.arrayBuffer === 'function') return file.arrayBuffer();
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as ArrayBuffer);
    reader.onerror = () => reject(reader.error);
    reader.readAsArrayBuffer(file);
  });
}

/** SHA-256 hex of the file, or null when Web Crypto is unavailable (e.g. insecure context). */
export async function sha256Hex(file: File): Promise<string | null> {
  try {
    const digest = await crypto.subtle.digest('SHA-256', await readBytes(file));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
  } catch {
    return null;
  }
}
