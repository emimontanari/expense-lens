export type Receipt = {
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
export type FieldName = keyof Receipt;
export type FieldStatus = 'verified' | 'conflict' | 'missing' | 'unverified' | 'empty';
export type FiscalQr = {
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
export type Issue = { code: string; field: string; severity?: 'warning' | 'info' };
export type Result = {
  receipt: Receipt;
  issues: Issue[];
  field_status?: Partial<Record<FieldName, FieldStatus>>;
  movement?: 'expense' | 'credit' | 'unknown';
  fiscal_qr?: FiscalQr | null;
  fiscal_qr_status?: 'found' | 'not_found' | 'invalid' | null;
  requires_human_review: boolean;
};
export type ApiError = { detail?: string | { code?: string }; code?: string };

export const fields: FieldName[] = [
  'issuer', 'issuer_cuit', 'date', 'number', 'document_type', 'letter',
  'currency', 'subtotal', 'tax', 'total',
];
export const labels: Record<FieldName, string> = {
  issuer: 'Emisor', issuer_cuit: 'CUIT del emisor', date: 'Fecha', number: 'Número',
  document_type: 'Tipo de comprobante', letter: 'Letra', currency: 'Moneda',
  subtotal: 'Subtotal', tax: 'Impuestos', total: 'Total',
};
export const selectOptions: Partial<Record<FieldName, [string, string][]>> = {
  document_type: [
    ['factura', 'Factura'], ['nota_credito', 'Nota de crédito'], ['nota_debito', 'Nota de débito'],
    ['ticket', 'Ticket'], ['otro', 'Otro'],
  ],
  letter: ['A', 'B', 'C', 'E', 'M'].map(letter => [letter, letter]),
};
export const statusText: Record<FieldStatus, string> = {
  verified: 'Verificado por QR',
  conflict: 'Revisar: hay una advertencia',
  missing: 'Faltante',
  unverified: 'Sin verificar',
  empty: 'Vacío',
};
export const qrReplaceable: FieldStatus[] = ['conflict', 'missing', 'empty'];
export const issueMessages: Record<string, string> = {
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
export const qrStatusText = {
  found: 'QR fiscal encontrado y leído.',
  not_found: 'No se encontró un QR fiscal en el documento.',
  invalid: 'Se encontró un QR, pero no es un QR fiscal válido.',
};
export function qrValue(qr: FiscalQr | null | undefined, field: FieldName): string | null {
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
export const maxFileSize = 5 * 1024 * 1024;
export const acceptedTypes = ['image/jpeg', 'image/png', 'application/pdf'];

export const categories = [
  'supermercado', 'combustible', 'restaurantes', 'servicios', 'transporte', 'salud', 'hogar', 'otros',
] as const;
export type Category = typeof categories[number];
export const categoryLabels: Record<Category, string> = {
  supermercado: 'Supermercado', combustible: 'Combustible', restaurantes: 'Restaurantes',
  servicios: 'Servicios', transporte: 'Transporte', salud: 'Salud', hogar: 'Hogar', otros: 'Otros',
};
export type ExpenseInput = {
  receipt: Receipt;
  fiscal_qr: FiscalQr | null;
  category: Category;
  extracted: Receipt | null;
  document_sha256: string | null;
  allow_duplicate: boolean;
};
export type DuplicateReason = 'fiscal_key' | 'same_file' | 'similar';
export type DuplicateMatch = {
  id: number;
  reason: DuplicateReason;
  issuer?: string;
  date?: string;
  total?: string;
  currency?: string;
};
export type Expense = {
  id: number;
  created_at: string;
  updated_at: string;
  receipt: Receipt;
  category: Category;
  movement: 'expense' | 'credit' | 'unknown';
  signed_total: string;
  issues: Issue[];
  field_status: Partial<Record<FieldName, FieldStatus>>;
  fiscal_qr_verified: boolean;
  corrected_fields: FieldName[] | null;
  document_sha256: string | null;
  duplicate_of: number[];
};
export type CurrencyTotals = { currency: string; expenses: string; credits: string; net: string; count: number };
export type ExpenseList = { items: Expense[]; totals: CurrencyTotals[] };
export type ExpenseStats = {
  count: number;
  with_extraction: number;
  correction_rate_by_field: Partial<Record<FieldName, number>>;
  qr_verified_rate: number | null;
};
export type ExpenseFilters = {
  date_from: string; date_to: string; q: string; category: string;
  min_total: string; max_total: string; currency: string;
};
export const emptyFilters: ExpenseFilters = {
  date_from: '', date_to: '', q: '', category: '', min_total: '', max_total: '', currency: '',
};
export const duplicateReasonText: Record<DuplicateReason, string> = {
  fiscal_key: 'Mismo comprobante fiscal (CUIT, tipo, letra y número).',
  same_file: 'Es el mismo archivo que ya guardaste.',
  similar: 'Operación similar: misma fecha, moneda, importe y emisor.',
};
