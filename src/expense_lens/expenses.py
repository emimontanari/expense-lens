"""Gastos confirmados: guardar, duplicados, historial, totales, CSV y telemetría.

El cliente envía la transcripción cruda; el servidor vuelve a normalizar y validar
con `review_receipt` y nunca confía en estados enviados. Los importes son Decimal
de punta a punta y se guardan como texto canónico.
"""

import csv
import io
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, StringConstraints

from expense_lens import storage
from expense_lens.receipts import (
    FIELDS,
    Currency,
    FieldName,
    FieldStatus,
    FiscalQr,
    RawReceipt,
    Receipt,
    ValidationIssue,
)
from expense_lens.rules import BASE_REQUIRED, review_receipt
from expense_lens.storage import get_db

Category = Literal[
    "supermercado",
    "combustible",
    "restaurantes",
    "servicios",
    "transporte",
    "salud",
    "hogar",
    "otros",
]
Sha256 = Annotated[str, StringConstraints(pattern=r"^[0-9a-fA-F]{64}$")]
DuplicateReason = Literal["fiscal_key", "same_file", "similar"]
Movement = Literal["expense", "credit", "unknown"]


class ExpenseInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    receipt: RawReceipt
    fiscal_qr: FiscalQr | None = None
    category: Category
    extracted: Receipt | None = None
    document_sha256: Sha256 | None = None
    allow_duplicate: bool = False


class Expense(BaseModel):
    id: int
    created_at: str
    updated_at: str
    receipt: Receipt
    category: Category
    movement: Movement
    signed_total: str
    issues: list[ValidationIssue]
    field_status: dict[FieldName, FieldStatus]
    fiscal_qr_verified: bool
    corrected_fields: list[FieldName] | None
    document_sha256: str | None
    duplicate_of: list[int]


class CurrencyTotals(BaseModel):
    currency: Currency
    expenses: str
    credits: str
    net: str
    count: int


class ExpenseList(BaseModel):
    items: list[Expense]
    totals: list[CurrencyTotals]


class ExpenseStats(BaseModel):
    count: int
    with_extraction: int
    correction_rate_by_field: dict[FieldName, float]
    qr_verified_rate: float | None


Db = Annotated[sqlite3.Connection, Depends(get_db)]
router = APIRouter(prefix="/expenses", tags=["expenses"])


@dataclass
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    q: str | None = None
    category: Category | None = None
    min_total: Decimal | None = None
    max_total: Decimal | None = None
    currency: Currency | None = None


def read_filters(
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    category: Category | None = None,
    min_total: Decimal | None = Query(default=None, ge=0, allow_inf_nan=False),
    max_total: Decimal | None = Query(default=None, ge=0, allow_inf_nan=False),
    currency: Currency | None = None,
) -> Filters:
    return Filters(date_from, date_to, q, category, min_total, max_total, currency)


def now_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def fiscal_key(receipt: Receipt) -> str | None:
    """Clave del comprobante: punto de venta y número comparados como enteros."""
    parts = re.findall(r"\d+", receipt.number or "")
    fields = (receipt.issuer_cuit, receipt.document_type, receipt.letter)
    if not parts or None in fields:
        return None
    number = "-".join(str(int(part)) for part in parts)
    return "|".join([*(f or "" for f in fields), number])


def corrected_fields(
    receipt: Receipt, extracted: Receipt | None
) -> list[FieldName] | None:
    if extracted is None:
        return None
    return [f for f in FIELDS if getattr(receipt, f) != getattr(extracted, f)]


def find_duplicates(
    conn: sqlite3.Connection,
    receipt: Receipt,
    key: str | None,
    sha: str | None,
    exclude_id: int | None,
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    for row in storage.duplicate_candidates(conn, exclude_id):
        reason: DuplicateReason | None = None
        if key is not None and row["fiscal_key"] == key:
            reason = "fiscal_key"
        elif sha is not None and row["document_sha256"] == sha:
            reason = "same_file"
        elif is_similar(row, receipt):
            reason = "similar"
        if reason is not None:
            matches.append(
                {
                    "id": row["id"],
                    "reason": reason,
                    "issuer": row["issuer"],
                    "date": row["date"],
                    "total": row["total"],
                    "currency": row["currency"],
                }
            )
    return matches


def is_similar(row: sqlite3.Row, receipt: Receipt) -> bool:
    if (
        row["date"] != str(receipt.date)
        or row["currency"] != receipt.currency
        or Decimal(row["total"]) != receipt.total
    ):
        return False
    if row["issuer_cuit"] and receipt.issuer_cuit:
        return row["issuer_cuit"] == receipt.issuer_cuit
    return row["issuer"].casefold() == (receipt.issuer or "").casefold()


def persist(
    conn: sqlite3.Connection, body: ExpenseInput, expense_id: int | None
) -> sqlite3.Row:
    """Revalida, comprueba duplicados y guarda (alta si no hay `expense_id`)."""
    if expense_id is not None and storage.get(conn, expense_id) is None:
        raise HTTPException(status_code=404, detail="expense_not_found")
    review = review_receipt(body.receipt, body.fiscal_qr)
    receipt = review.receipt
    missing = [f for f in BASE_REQUIRED if getattr(receipt, f) is None]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"code": "incomplete_expense", "fields": missing},
        )
    assert receipt.date and receipt.total is not None
    sha = body.document_sha256.lower() if body.document_sha256 else None
    key = fiscal_key(receipt)
    signed = -receipt.total if review.movement == "credit" else receipt.total
    now = now_utc()
    storage.begin(conn)
    try:
        matches = find_duplicates(conn, receipt, key, sha, expense_id)
        if matches and not body.allow_duplicate:
            raise HTTPException(
                status_code=409,
                detail={"code": "duplicate_expense", "matches": matches},
            )
        corrected = corrected_fields(receipt, body.extracted)
        values: dict[str, object] = {
            "created_at": now,
            "updated_at": now,
            "category": body.category,
            "issuer": receipt.issuer,
            "issuer_cuit": receipt.issuer_cuit,
            "date": receipt.date.isoformat(),
            "number": receipt.number,
            "document_type": receipt.document_type,
            "letter": receipt.letter,
            "currency": receipt.currency,
            "subtotal": None if receipt.subtotal is None else str(receipt.subtotal),
            "tax": None if receipt.tax is None else str(receipt.tax),
            "total": str(receipt.total),
            "movement": review.movement,
            "signed_total": str(signed),
            "issues": json.dumps([i.model_dump() for i in review.issues]),
            "field_status": json.dumps(review.field_status),
            "fiscal_qr_verified": int("verified" in review.field_status.values()),
            "corrected_fields": None if corrected is None else json.dumps(corrected),
            "document_sha256": sha,
            "duplicate_of": json.dumps([m["id"] for m in matches]),
            "fiscal_key": key,
        }
        if expense_id is None:
            expense_id = storage.insert(conn, values)
        else:
            storage.update(conn, expense_id, values)
        storage.commit(conn)
    except BaseException:
        storage.rollback(conn)
        raise
    row = storage.get(conn, expense_id)
    assert row is not None
    return row


def to_expense(row: sqlite3.Row) -> Expense:
    receipt = Receipt.model_validate(
        {
            field: row[field]
            for field in FIELDS
            if row[field] is not None  # claves ausentes quedan en None
        }
    )
    corrected = row["corrected_fields"]
    return Expense(
        id=row["id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        receipt=receipt,
        category=row["category"],
        movement=row["movement"],
        signed_total=row["signed_total"],
        issues=json.loads(row["issues"]),
        field_status=json.loads(row["field_status"]),
        fiscal_qr_verified=bool(row["fiscal_qr_verified"]),
        corrected_fields=None if corrected is None else json.loads(corrected),
        document_sha256=row["document_sha256"],
        duplicate_of=json.loads(row["duplicate_of"]),
    )


def filtered(conn: sqlite3.Connection, f: Filters) -> list[Expense]:
    rows = storage.search(
        conn,
        date_from=f.date_from.isoformat() if f.date_from else None,
        date_to=f.date_to.isoformat() if f.date_to else None,
        category=f.category,
        currency=f.currency,
    )
    needle = f.q.strip().casefold() if f.q else ""
    items: list[Expense] = []
    for row in rows:
        total = Decimal(row["total"])
        if f.min_total is not None and total < f.min_total:
            continue
        if f.max_total is not None and total > f.max_total:
            continue
        haystack = f"{row['issuer']}\n{row['number'] or ''}".casefold()
        if needle and needle not in haystack:
            continue
        items.append(to_expense(row))
    return items


def totals_by_currency(items: list[Expense]) -> list[CurrencyTotals]:
    zero = Decimal("0.00")
    sums: dict[str, list[Decimal | int]] = {}
    for item in items:
        assert item.receipt.currency and item.receipt.total is not None
        entry = sums.setdefault(item.receipt.currency, [zero, zero, 0])
        index = 1 if item.movement == "credit" else 0
        entry[index] += item.receipt.total
        entry[2] += 1
    return [
        CurrencyTotals(
            currency=currency,  # type: ignore[arg-type]
            expenses=str(spent),
            credits=str(credits),
            net=str(spent - credits),  # type: ignore[operator]
            count=int(count),
        )
        for currency, (spent, credits, count) in sorted(sums.items())
    ]


CSV_COLUMNS = (
    "fecha",
    "emisor",
    "cuit",
    "tipo",
    "letra",
    "numero",
    "categoria",
    "moneda",
    "importe",
    "subtotal",
    "iva",
    "verificado_qr",
)


def text_cell(value: object) -> str:
    """Prefija con `'` lo que una planilla interpretaría como fórmula."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def amount_cell(value: object) -> str:
    return "" if value is None else str(value)


def csv_row(item: Expense) -> list[str]:
    r = item.receipt
    return [
        text_cell(r.date),
        text_cell(r.issuer),
        text_cell(r.issuer_cuit),
        text_cell(r.document_type),
        text_cell(r.letter),
        text_cell(r.number),
        text_cell(item.category),
        text_cell(r.currency),
        item.signed_total,
        amount_cell(r.subtotal),
        amount_cell(r.tax),
        "si" if item.fiscal_qr_verified else "no",
    ]


@router.post("", status_code=201, response_model=Expense)
def create_expense(body: ExpenseInput, conn: Db) -> Expense:
    """Guarda el gasto que la persona confirmó, tras revalidarlo en el servidor."""
    return to_expense(persist(conn, body, None))


@router.get("", response_model=ExpenseList)
def list_expenses(conn: Db, f: Annotated[Filters, Depends(read_filters)]):
    items = filtered(conn, f)
    return ExpenseList(items=items, totals=totals_by_currency(items))


@router.get("/export.csv")
def export_csv(conn: Db, f: Annotated[Filters, Depends(read_filters)]) -> Response:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(CSV_COLUMNS)
    writer.writerows(csv_row(item) for item in filtered(conn, f))
    return Response(
        content=("\ufeff" + buffer.getvalue()).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="gastos.csv"'},
    )


@router.get("/stats", response_model=ExpenseStats)
def expense_stats(conn: Db) -> ExpenseStats:
    """Cuánto corrige la persona a la extracción, por campo."""
    rows = conn.execute(
        "SELECT corrected_fields, fiscal_qr_verified FROM expenses"
    ).fetchall()
    extracted = [
        json.loads(r["corrected_fields"])
        for r in rows
        if r["corrected_fields"] is not None
    ]
    with_extraction = len(extracted)
    rates: dict[FieldName, float] = {}
    if with_extraction:
        rates = {
            f: sum(1 for fields in extracted if f in fields) / with_extraction
            for f in FIELDS
        }
    verified = sum(r["fiscal_qr_verified"] for r in rows)
    return ExpenseStats(
        count=len(rows),
        with_extraction=with_extraction,
        correction_rate_by_field=rates,
        qr_verified_rate=verified / len(rows) if rows else None,
    )


@router.get("/{expense_id}", response_model=Expense)
def read_expense(expense_id: int, conn: Db) -> Expense:
    row = storage.get(conn, expense_id)
    if row is None:
        raise HTTPException(status_code=404, detail="expense_not_found")
    return to_expense(row)


@router.put("/{expense_id}", response_model=Expense)
def replace_expense(expense_id: int, body: ExpenseInput, conn: Db) -> Expense:
    """Recalcula todo desde la entrada; conserva `created_at`."""
    return to_expense(persist(conn, body, expense_id))


@router.delete("/{expense_id}", status_code=204)
def delete_expense(expense_id: int, conn: Db) -> Response:
    if not storage.delete(conn, expense_id):
        raise HTTPException(status_code=404, detail="expense_not_found")
    return Response(status_code=204)
