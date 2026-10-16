"""Contrato normalizado para comprobantes simples; no es validación tributaria."""

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


class Receipt(BaseModel):
    """Los campos desconocidos quedan en null; no se infieren valores faltantes."""

    model_config = ConfigDict(extra="forbid")

    issuer: Text | None = None
    date: Date | None = None
    number: Text | None = None
    currency: Literal["ARS"] | None = None
    subtotal: Amount | None = None
    tax: Amount | None = None
    total: Amount | None = None


FieldName = Literal["issuer", "date", "number", "currency", "subtotal", "tax", "total"]
REQUIRED_FIELDS: tuple[FieldName, ...] = (
    "issuer",
    "date",
    "number",
    "currency",
    "subtotal",
    "tax",
    "total",
)


class ValidationIssue(BaseModel):
    code: Literal["missing_field", "total_mismatch"]
    field: FieldName


class ReceiptValidation(BaseModel):
    receipt: Receipt
    issues: list[ValidationIssue] = Field(default_factory=list)
    requires_human_review: Literal[True] = True


def validate_receipt(receipt: Receipt) -> ReceiptValidation:
    """Señala faltantes y diferencias exactas; nunca modifica ni aprueba datos."""
    issues = [
        ValidationIssue(code="missing_field", field=field)
        for field in REQUIRED_FIELDS
        if getattr(receipt, field) is None
    ]
    if (
        receipt.subtotal is not None
        and receipt.tax is not None
        and receipt.total is not None
        and receipt.subtotal + receipt.tax != receipt.total
    ):
        issues.append(ValidationIssue(code="total_mismatch", field="total"))
    return ReceiptValidation(receipt=receipt, issues=issues)
