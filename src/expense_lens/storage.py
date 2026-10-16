"""Persistencia local de gastos con sqlite3 (stdlib).

Los importes se guardan como texto decimal canónico, nunca como float. Todo el SQL
es parametrizado; los filtros por importe y texto se aplican en Python con Decimal.
"""

import os
import sqlite3
from collections.abc import Iterator
from pathlib import Path

DEFAULT_DB = "data/expenses.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    category TEXT NOT NULL,
    issuer TEXT NOT NULL,
    issuer_cuit TEXT,
    date TEXT NOT NULL,
    number TEXT,
    document_type TEXT,
    letter TEXT,
    currency TEXT NOT NULL,
    subtotal TEXT,
    tax TEXT,
    total TEXT NOT NULL,
    movement TEXT NOT NULL,
    signed_total TEXT NOT NULL,
    issues TEXT NOT NULL,
    field_status TEXT NOT NULL,
    fiscal_qr_verified INTEGER NOT NULL,
    corrected_fields TEXT,
    document_sha256 TEXT,
    duplicate_of TEXT NOT NULL,
    fiscal_key TEXT,
    category_suggestion TEXT,
    suggestion_accepted INTEGER
);
CREATE INDEX IF NOT EXISTS expenses_date ON expenses (date);
CREATE INDEX IF NOT EXISTS expenses_sha ON expenses (document_sha256);
CREATE INDEX IF NOT EXISTS expenses_fiscal_key ON expenses (fiscal_key);
"""
# Columnas agregadas después de la primera versión del esquema.
MIGRATIONS = (
    ("category_suggestion", "TEXT"),
    ("suggestion_accepted", "INTEGER"),
)


def migrate(conn: sqlite3.Connection) -> None:
    """Agrega columnas faltantes sin tocar los datos existentes (idempotente)."""
    present = {row[1] for row in conn.execute("PRAGMA table_info(expenses)")}
    for column, kind in MIGRATIONS:
        if column not in present:
            conn.execute(f"ALTER TABLE expenses ADD COLUMN {column} {kind}")


def db_path() -> Path:
    return Path(os.environ.get("EXPENSE_LENS_DB") or DEFAULT_DB)


def open_db(path: Path) -> sqlite3.Connection:
    """Abre la base (creando directorio y esquema) en modo autocommit."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    migrate(conn)
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """Dependencia FastAPI; los tests la reemplazan por una base en tmp_path."""
    conn = open_db(db_path())
    try:
        yield conn
    finally:
        conn.close()


def begin(conn: sqlite3.Connection) -> None:
    conn.execute("BEGIN IMMEDIATE")


def commit(conn: sqlite3.Connection) -> None:
    conn.execute("COMMIT")


def rollback(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        conn.execute("ROLLBACK")


INSERT_SQL = """
INSERT INTO expenses (
    created_at, updated_at, category, issuer, issuer_cuit, date, number,
    document_type, letter, currency, subtotal, tax, total, movement,
    signed_total, issues, field_status, fiscal_qr_verified, corrected_fields,
    document_sha256, duplicate_of, fiscal_key, category_suggestion,
    suggestion_accepted
) VALUES (
    :created_at, :updated_at, :category, :issuer, :issuer_cuit, :date, :number,
    :document_type, :letter, :currency, :subtotal, :tax, :total, :movement,
    :signed_total, :issues, :field_status, :fiscal_qr_verified, :corrected_fields,
    :document_sha256, :duplicate_of, :fiscal_key, :category_suggestion,
    :suggestion_accepted
)
"""

UPDATE_SQL = """
UPDATE expenses SET
    updated_at = :updated_at, category = :category, issuer = :issuer,
    issuer_cuit = :issuer_cuit, date = :date, number = :number,
    document_type = :document_type, letter = :letter, currency = :currency,
    subtotal = :subtotal, tax = :tax, total = :total, movement = :movement,
    signed_total = :signed_total, issues = :issues, field_status = :field_status,
    fiscal_qr_verified = :fiscal_qr_verified,
    corrected_fields = :corrected_fields, document_sha256 = :document_sha256,
    duplicate_of = :duplicate_of, fiscal_key = :fiscal_key,
    category_suggestion = :category_suggestion,
    suggestion_accepted = :suggestion_accepted
WHERE id = :id
"""

SEARCH_SQL = """
SELECT * FROM expenses
WHERE (:date_from IS NULL OR date >= :date_from)
  AND (:date_to IS NULL OR date <= :date_to)
  AND (:category IS NULL OR category = :category)
  AND (:currency IS NULL OR currency = :currency)
ORDER BY date DESC, id DESC
"""


def insert(conn: sqlite3.Connection, values: dict[str, object]) -> int:
    cursor = conn.execute(INSERT_SQL, values)
    return cursor.lastrowid or 0


def update(conn: sqlite3.Connection, expense_id: int, values: dict[str, object]):
    conn.execute(UPDATE_SQL, {**values, "id": expense_id})


def get(conn: sqlite3.Connection, expense_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()


def delete(conn: sqlite3.Connection, expense_id: int) -> bool:
    return conn.execute("DELETE FROM expenses WHERE id = ?", (expense_id,)).rowcount > 0


def search(
    conn: sqlite3.Connection,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    currency: str | None = None,
) -> list[sqlite3.Row]:
    """Filtros exactos en SQL; orden fecha desc, luego id desc."""
    params = {
        "date_from": date_from,
        "date_to": date_to,
        "category": category,
        "currency": currency,
    }
    return conn.execute(SEARCH_SQL, params).fetchall()


def duplicate_candidates(
    conn: sqlite3.Connection, exclude_id: int | None
) -> list[sqlite3.Row]:
    """Los gastos con los que comparar; el propio id se excluye (PUT)."""
    return conn.execute(
        "SELECT * FROM expenses WHERE id != ? ORDER BY id", (exclude_id or 0,)
    ).fetchall()
