"""Pipeline determinista: normalización → reglas argentinas → estado por campo.

Independiente del proveedor de IA: recibe la misma transcripción cruda venga del
modelo o de una corrección humana. Señala; nunca corrige ni aprueba datos.
"""

from datetime import date

from expense_lens.categories import suggest_by_rules
from expense_lens.fiscal_qr import compare_with_qr
from expense_lens.normalize import (
    decimal_separator,
    normalize_amount,
    normalize_cuit,
    normalize_currency,
    normalize_date,
)
from expense_lens.receipts import (
    FIELDS,
    CategorySuggestion,
    FieldName,
    FieldStatus,
    FiscalQr,
    IssueCode,
    RawReceipt,
    Receipt,
    ReceiptValidation,
    ValidationIssue,
)

BASE_REQUIRED: tuple[FieldName, ...] = ("issuer", "date", "currency", "total")
FISCAL_REQUIRED: tuple[FieldName, ...] = ("issuer_cuit", "number", "letter")
FISCAL_TYPES = {"factura", "nota_credito", "nota_debito"}
INFO_CODES: set[IssueCode] = {
    "amount_interpreted_from_document",
    "credit_note",
    "foreign_currency",
    "currency_inferred_from_symbol",
}


def required_fields(receipt: Receipt) -> tuple[FieldName, ...]:
    """Factura A discrimina IVA; B, C y tickets suelen informar solo el total."""
    required = BASE_REQUIRED
    if receipt.document_type in FISCAL_TYPES:
        required += FISCAL_REQUIRED
    if receipt.letter == "A":
        required += ("subtotal", "tax")
    return required


def normalize_receipt(raw: RawReceipt) -> tuple[Receipt, list[ValidationIssue]]:
    issues: list[ValidationIssue] = []

    def keep(field: FieldName, result):
        value, code = result
        if code:
            issues.append(issue(code, field))
        return value

    # Evidencia del propio documento: si todos los importes inequívocos usan el
    # mismo separador decimal, ese es el estilo del comprobante.
    styles = {
        decimal_separator(value) for value in (raw.subtotal, raw.tax, raw.total)
    } - {None}
    hint = styles.pop() if len(styles) == 1 else None

    receipt = Receipt.model_validate(
        {
            "issuer": (raw.issuer or "").strip() or None,
            "issuer_cuit": keep("issuer_cuit", normalize_cuit(raw.issuer_cuit)),
            "date": keep("date", normalize_date(raw.date)),
            "number": (raw.number or "").strip() or None,
            "document_type": raw.document_type,
            "letter": raw.letter,
            "currency": keep("currency", normalize_currency(raw.currency)),
            "subtotal": keep("subtotal", normalize_amount(raw.subtotal, hint)),
            "tax": keep("tax", normalize_amount(raw.tax, hint)),
            "total": keep("total", normalize_amount(raw.total, hint)),
        }
    )
    return receipt, issues


def issue(code: IssueCode, field: FieldName) -> ValidationIssue:
    severity = "info" if code in INFO_CODES else "warning"
    return ValidationIssue(code=code, field=field, severity=severity)


def check_rules(receipt: Receipt, today: date) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    subtotal, tax, total = receipt.subtotal, receipt.tax, receipt.total
    if subtotal is not None and tax is not None and total is not None:
        if subtotal == total and tax > 0:
            # El neto informado ya incluye el IVA: sumarlo otra vez duplicaría.
            issues.append(issue("tax_already_included", "subtotal"))
        elif total < subtotal:
            issues.append(issue("total_below_subtotal", "total"))
        elif subtotal + tax != total:
            issues.append(issue("total_mismatch", "total"))
    if subtotal is not None and tax is None and subtotal == total:
        # Sin IVA discriminado, un subtotal igual al total suele ser una copia del
        # total hecha por el modelo (hallazgo de eval-002), no un dato leído.
        issues.append(issue("subtotal_equals_total", "subtotal"))
    if receipt.letter == "C" and tax is not None and tax > 0:
        issues.append(issue("unexpected_tax", "tax"))
    if receipt.date is not None and receipt.date > today:
        issues.append(issue("future_date", "date"))
    if receipt.document_type == "nota_credito":
        issues.append(issue("credit_note", "document_type"))
    if receipt.currency in {"USD", "EUR"}:
        issues.append(issue("foreign_currency", "currency"))
    return issues


def movement_of(receipt: Receipt):
    if receipt.document_type is None:
        return "unknown"
    return "credit" if receipt.document_type == "nota_credito" else "expense"


def review_receipt(
    raw: RawReceipt, fiscal_qr: FiscalQr | None = None, today: date | None = None
) -> ReceiptValidation:
    receipt, issues = normalize_receipt(raw)
    flagged = {i.field for i in issues}
    issues += [
        issue("missing_field", field)
        for field in required_fields(receipt)
        if getattr(receipt, field) is None and field not in flagged
    ]
    issues += check_rules(receipt, today or date.today())
    verified: set[FieldName] = set()
    if fiscal_qr is not None:
        mismatches, verified = compare_with_qr(receipt, fiscal_qr)
        issues += [issue("qr_mismatch", field) for field in mismatches]
    return ReceiptValidation(
        receipt=receipt,
        issues=issues,
        field_status=field_status(receipt, issues, verified),
        movement=movement_of(receipt),
        fiscal_qr=fiscal_qr,
        category_suggestion=CategorySuggestion.of(
            None, suggest_by_rules(receipt.issuer)
        ),
    )


def field_status(
    receipt: Receipt, issues: list[ValidationIssue], verified: set[FieldName]
) -> dict[FieldName, FieldStatus]:
    conflicts = {
        i.field for i in issues if i.severity == "warning" and i.code != "missing_field"
    }
    missing = {i.field for i in issues if i.code == "missing_field"}
    status: dict[FieldName, FieldStatus] = {}
    for field in FIELDS:
        if field in conflicts:
            status[field] = "conflict"
        elif field in missing:
            status[field] = "missing"
        elif getattr(receipt, field) is None:
            status[field] = "empty"
        elif field in verified:
            status[field] = "verified"
        else:
            status[field] = "unverified"
    return status
