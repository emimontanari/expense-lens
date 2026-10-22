"""Contratos de comprobantes: transcripción cruda y datos normalizados.

No es validación tributaria: las reglas señalan inconsistencias para revisión humana.
"""

import re
from datetime import date as Date
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
)

from expense_lens.categories import Category

AMOUNT_PATTERN = r"[0-9]{1,10}(\.[0-9]{1,2})?"


def parse_amount(value: object) -> Decimal:
    """Exige texto decimal canónico: nunca convierte desde float ni redondea."""
    if not isinstance(value, str) or re.fullmatch(AMOUNT_PATTERN, value) is None:
        raise ValueError(
            "Use texto decimal no negativo, hasta 10 enteros y 2 decimales"
        )
    return Decimal(value)


Amount = Annotated[
    Decimal,
    BeforeValidator(parse_amount),
    WithJsonSchema({"type": "string", "pattern": "^" + AMOUNT_PATTERN + "$"}),
]
Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
]
RawText = Annotated[str, StringConstraints(max_length=200)]
Cuit = Annotated[str, StringConstraints(pattern=r"^[0-9]{11}$")]
DocumentType = Literal["factura", "nota_credito", "nota_debito", "ticket", "otro"]
Letter = Literal["A", "B", "C", "E", "M"]
Currency = Literal["ARS", "USD", "EUR"]


class RawReceipt(BaseModel):
    """Valores tal como figuran en el documento o los escribe la persona.

    Lo produce el modelo (importes "1.234,56", fechas "15/10/2026", "$") o la
    interfaz al corregir. La normalización y las reglas son código determinista.
    """

    model_config = ConfigDict(extra="forbid")

    issuer: RawText | None = None
    issuer_cuit: RawText | None = None
    date: RawText | None = None
    number: RawText | None = None
    document_type: DocumentType | None = None
    letter: Letter | None = None
    currency: RawText | None = None
    subtotal: RawText | None = None
    tax: RawText | None = None
    total: RawText | None = None


class Receipt(BaseModel):
    """Datos normalizados. Los importes son absolutos: el signo lo da el tipo."""

    model_config = ConfigDict(extra="forbid")

    issuer: Text | None = None
    issuer_cuit: Cuit | None = None
    date: Date | None = None
    number: Text | None = None
    document_type: DocumentType | None = None
    letter: Letter | None = None
    currency: Currency | None = None
    subtotal: Amount | None = None
    tax: Amount | None = None
    total: Amount | None = None


FieldName = Literal[
    "issuer",
    "issuer_cuit",
    "date",
    "number",
    "document_type",
    "letter",
    "currency",
    "subtotal",
    "tax",
    "total",
]
FIELDS: tuple[FieldName, ...] = FieldName.__args__
IssueCode = Literal[
    "missing_field",
    "ambiguous_amount",
    "amount_interpreted_from_document",
    "unparseable_amount",
    "invalid_date",
    "unknown_currency",
    "invalid_cuit",
    "total_mismatch",
    "total_below_subtotal",
    "tax_already_included",
    "subtotal_equals_total",
    "unexpected_tax",
    "future_date",
    "credit_note",
    "foreign_currency",
    "currency_inferred_from_symbol",
    "qr_mismatch",
]
FieldStatus = Literal["verified", "conflict", "missing", "unverified", "empty"]


class ValidationIssue(BaseModel):
    code: IssueCode
    field: FieldName
    severity: Literal["warning", "info"] = "warning"


class FiscalQr(BaseModel):
    """Datos del QR fiscal ARCA (RG 4892/2020), normalizados para contrastar."""

    model_config = ConfigDict(extra="forbid")

    issuer_cuit: Cuit
    date: Date
    point_of_sale: int = Field(ge=0, le=99_999)
    number: int = Field(ge=0, le=99_999_999)
    receipt_type_code: int = Field(ge=0, le=999)
    document_type: DocumentType | None = None
    letter: Letter | None = None
    total: Amount
    currency: Currency | None = None
    exchange_rate: str
    authorization_type: Literal["CAE", "CAEA"]
    authorization_code: Annotated[str, StringConstraints(pattern=r"^[0-9]{14}$")]


class CategorySuggestion(BaseModel):
    """Sugerencia del modelo y de las reglas; `suggested` prefiere al modelo."""

    model_config = ConfigDict(extra="forbid")

    model: Category | None = None
    rules: Category | None = None
    suggested: Category | None = None
    source: Literal["model", "rules"] | None = None

    @classmethod
    def of(cls, model: Category | None, rules: Category | None) -> "CategorySuggestion":
        suggested = model or rules
        source = "model" if model else "rules" if rules else None
        return cls(model=model, rules=rules, suggested=suggested, source=source)


class ReceiptValidation(BaseModel):
    receipt: Receipt
    issues: list[ValidationIssue] = Field(default_factory=list)
    field_status: dict[FieldName, FieldStatus]
    movement: Literal["expense", "credit", "unknown"]
    fiscal_qr: FiscalQr | None = None
    fiscal_qr_signature: str | None = None
    fiscal_qr_status: Literal["found", "not_found", "invalid"] | None = None
    category_suggestion: CategorySuggestion | None = None
    requires_human_review: Literal[True] = True


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: RawReceipt
    fiscal_qr: FiscalQr | None = None
    fiscal_qr_signature: str | None = None
