import csv
import io

import pytest
from fastapi.testclient import TestClient

from expense_lens.main import app
from expense_lens.storage import db_path, get_db, open_db

SHA_A = "a" * 64


@pytest.fixture
def client(tmp_path):
    path = tmp_path / "nested" / "expenses.sqlite"

    def override():
        conn = open_db(path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def raw_receipt(**overrides):
    """Factura A ficticia (comercio ficticio, CUIT de ejemplo oficial)."""
    receipt = {
        "issuer": "Comercio ficticio",
        "issuer_cuit": "30-00000000-7",
        "date": "15/10/2026",
        "number": "0001-00000001",
        "document_type": "factura",
        "letter": "A",
        "currency": "ARS",
        "subtotal": "1.000,00",
        "tax": "210,00",
        "total": "1.210,00",
    }
    receipt.update(overrides)
    return receipt


def ticket(**overrides):
    base = {
        "issuer_cuit": None,
        "document_type": "ticket",
        "letter": None,
        "subtotal": None,
        "tax": None,
    }
    return raw_receipt(**{**base, **overrides})


def payload(category="supermercado", **overrides):
    body = {
        "receipt": raw_receipt(),
        "fiscal_qr": None,
        "category": category,
        "extracted": None,
        "document_sha256": None,
        "allow_duplicate": False,
    }
    body.update(overrides)
    return body


def save(client, expected=201, **kwargs):
    response = client.post("/expenses", json=payload(**kwargs))
    assert response.status_code == expected, response.text
    return response.json()


def listing(client, **params):
    response = client.get("/expenses", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_save_and_read_back(client):
    created = save(client)
    assert created["id"] >= 1
    assert created["category"] == "supermercado"
    assert created["receipt"]["total"] == "1210.00"
    assert created["receipt"]["date"] == "2026-10-15"
    assert created["movement"] == "expense"
    assert created["signed_total"] == "1210.00"
    assert created["corrected_fields"] is None
    assert created["duplicate_of"] == []
    assert created["fiscal_qr_verified"] is False
    assert created["created_at"].endswith("Z")
    assert created["field_status"]["issuer"] == "unverified"
    fetched = client.get(f"/expenses/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == created
    assert listing(client)["items"] == [created]


def test_unknown_expense_is_404(client):
    response = client.get("/expenses/999")
    assert response.status_code == 404
    assert response.json() == {"detail": "expense_not_found"}
    assert client.put("/expenses/999", json=payload()).status_code == 404
    assert client.delete("/expenses/999").status_code == 404


def test_incomplete_expense_is_422_and_nothing_is_stored(client):
    response = client.post(
        "/expenses",
        json=payload(receipt=raw_receipt(issuer=None, total="1.234", currency=None)),
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "incomplete_expense"
    assert detail["fields"] == ["issuer", "currency", "total"]
    assert listing(client)["items"] == []


def test_client_sent_status_is_rejected(client):
    response = client.post(
        "/expenses", json=payload(field_status={"total": "verified"})
    )
    assert response.status_code == 422
    assert listing(client)["items"] == []


def test_server_recomputes_review(client):
    created = save(client, receipt=raw_receipt(total="1.300,00"))
    assert ("total_mismatch", "total") in {
        (i["code"], i["field"]) for i in created["issues"]
    }
    assert created["field_status"]["total"] == "conflict"


def test_invalid_category_is_422(client):
    assert client.post("/expenses", json=payload(category="lujos")).status_code == 422


def duplicate_reasons(response):
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "duplicate_expense"
    return {(m["id"], m["reason"]) for m in detail["matches"]}


def test_duplicate_fiscal_key_ignores_leading_zeros(client):
    first = save(client)
    other = payload(
        receipt=raw_receipt(number="00001-00000001", total="5.000,00", subtotal=None)
    )
    response = client.post("/expenses", json=other)
    assert duplicate_reasons(response) == {(first["id"], "fiscal_key")}
    assert len(listing(client)["items"]) == 1


def test_different_number_is_not_a_fiscal_key_duplicate(client):
    save(client)
    save(client, receipt=raw_receipt(number="0001-00000002", total="9.000,00"))


def test_duplicate_same_file(client):
    first = save(client, document_sha256=SHA_A)
    other = payload(
        receipt=raw_receipt(issuer="Otro", issuer_cuit=None, total="50,00"),
        document_sha256=SHA_A.upper(),
    )
    response = client.post("/expenses", json=other)
    assert duplicate_reasons(response) == {(first["id"], "same_file")}
    assert len(listing(client)["items"]) == 1


def test_duplicate_similar_by_issuer_name(client):
    first = save(client, receipt=raw_receipt(number=None, document_type="ticket"))
    other = payload(receipt=ticket(issuer="COMERCIO FICTICIO", number="77"))
    response = client.post("/expenses", json=other)
    assert duplicate_reasons(response) == {(first["id"], "similar")}
    assert len(listing(client)["items"]) == 1


def test_similar_requires_same_cuit_when_both_have_one(client):
    save(client)
    other = raw_receipt(issuer_cuit="20-00000000-1", number="0002-00000009")
    save(client, receipt=other)


def test_similar_requires_same_total_and_date(client):
    save(client)
    save(client, receipt=raw_receipt(number="0001-00000003", total="1.211,00"))
    save(client, receipt=raw_receipt(number="0001-00000004", date="16/10/2026"))


def test_allow_duplicate_stores_with_duplicate_of(client):
    first = save(client, document_sha256=SHA_A)
    second = save(client, document_sha256=SHA_A, allow_duplicate=True)
    assert second["id"] != first["id"]
    assert second["duplicate_of"] == [first["id"]]
    assert len(listing(client)["items"]) == 2


def test_update_recomputes_keeps_created_at_and_excludes_itself(client):
    created = save(client, document_sha256=SHA_A)
    body = payload(
        category="hogar",
        receipt=raw_receipt(total="1.500,00", subtotal=None, tax=None),
        document_sha256=SHA_A,
    )
    response = client.put(f"/expenses/{created['id']}", json=body)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["id"] == created["id"]
    assert updated["created_at"] == created["created_at"]
    assert updated["updated_at"] >= created["updated_at"]
    assert updated["category"] == "hogar"
    assert updated["receipt"]["total"] == "1500.00"
    assert updated["duplicate_of"] == []
    assert client.get(f"/expenses/{created['id']}").json() == updated


def test_update_conflicting_with_another_expense_is_409(client):
    first = save(client)
    other = save(client, receipt=raw_receipt(number="0001-00000002", total="9,00"))
    body = payload(receipt=raw_receipt(number="1-1"))
    response = client.put(f"/expenses/{other['id']}", json=body)
    assert duplicate_reasons(response) == {(first["id"], "fiscal_key")}
    assert client.get(f"/expenses/{other['id']}").json() == other


def test_update_incomplete_is_422_and_keeps_record(client):
    created = save(client)
    body = payload(receipt=raw_receipt(date=None))
    response = client.put(f"/expenses/{created['id']}", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["fields"] == ["date"]
    assert client.get(f"/expenses/{created['id']}").json() == created


def test_delete_then_404(client):
    created = save(client)
    assert client.delete(f"/expenses/{created['id']}").status_code == 204
    assert client.get(f"/expenses/{created['id']}").status_code == 404
    assert client.delete(f"/expenses/{created['id']}").status_code == 404
    assert listing(client)["items"] == []


def seed(client):
    rows = [
        ("Verdulería Sol", "01/10/2026", "1-1", "100,00", "supermercado", "ARS"),
        ("Shell Centro", "10/10/2026", "1-2", "5.000,00", "combustible", "ARS"),
        ("Café Árbol", "10/10/2026", "1-3", "300,00", "restaurantes", "ARS"),
        ("Hotel Miami", "12/10/2026", "9-1", "200,00", "transporte", "USD"),
    ]
    for issuer, day, number, total, category, currency in rows:
        receipt = ticket(
            issuer=issuer, date=day, number=number, total=total, currency=currency
        )
        save(client, receipt=receipt, category=category)


def issuers(result):
    return [item["receipt"]["issuer"] for item in result["items"]]


def test_ordering_is_date_desc_then_id_desc(client):
    seed(client)
    assert issuers(listing(client)) == [
        "Hotel Miami",
        "Café Árbol",
        "Shell Centro",
        "Verdulería Sol",
    ]


def test_filters(client):
    seed(client)
    assert issuers(listing(client, date_from="2026-10-10")) == [
        "Hotel Miami",
        "Café Árbol",
        "Shell Centro",
    ]
    assert issuers(listing(client, date_to="2026-10-01")) == ["Verdulería Sol"]
    assert issuers(listing(client, q="shell")) == ["Shell Centro"]
    assert issuers(listing(client, q="1-3")) == ["Café Árbol"]
    assert issuers(listing(client, category="combustible")) == ["Shell Centro"]
    ranged = listing(client, min_total="300", max_total="5000", currency="ARS")
    assert issuers(ranged) == ["Café Árbol", "Shell Centro"]
    assert issuers(listing(client, max_total="150")) == ["Verdulería Sol"]
    assert issuers(listing(client, currency="USD")) == ["Hotel Miami"]
    assert listing(client, q="nadie")["items"] == []


def test_totals_per_currency_with_credit_note_subtracting(client):
    seed(client)
    credit = ticket(
        issuer="Shell Centro",
        date="11/10/2026",
        number="1-9",
        document_type="nota_credito",
        total="1.000,50",
    )
    created = save(client, receipt=credit, category="combustible")
    assert created["movement"] == "credit"
    assert created["signed_total"] == "-1000.50"
    totals = {t["currency"]: t for t in listing(client)["totals"]}
    assert totals["ARS"] == {
        "currency": "ARS",
        "expenses": "5400.00",
        "credits": "1000.50",
        "net": "4399.50",
        "count": 4,
    }
    assert totals["USD"]["net"] == "200.00"
    assert totals["USD"]["count"] == 1
    filtered = listing(client, category="combustible")["totals"]
    assert [t["net"] for t in filtered] == ["3999.50"]


def test_empty_totals(client):
    assert listing(client) == {"items": [], "totals": []}


def read_csv(response):
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/csv; charset=utf-8"
    assert response.content.startswith(b"\xef\xbb\xbf")
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_csv_export_header_bom_signed_amount(client):
    seed(client)
    credit = ticket(
        issuer="Otro", number="1-9", document_type="nota_credito", total="10,50"
    )
    save(client, receipt=credit, category="otros")
    rows = read_csv(client.get("/expenses/export.csv"))
    assert rows[0] == [
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
    ]
    assert len(rows) == 6
    by_number = {row[5]: row for row in rows[1:]}
    assert by_number["1-9"][8] == "-10.50"
    assert by_number["1-9"][0] == "2026-10-15"
    assert by_number["1-9"][3] == "nota_credito"
    assert by_number["1-2"][8] == "5000.00"
    assert by_number["1-2"][6] == "combustible"
    filtered = read_csv(client.get("/expenses/export.csv", params={"q": "shell"}))
    assert len(filtered) == 2


def test_csv_neutralizes_formula_injection(client):
    save(client, receipt=ticket(issuer='=HYPERLINK("http://x","clic")', number="@c"))
    rows = read_csv(client.get("/expenses/export.csv"))
    assert rows[1][1] == '\'=HYPERLINK("http://x","clic")'
    assert rows[1][5] == "'@c"
    assert rows[1][8] == "1210.00"


def test_stats_correction_rates(client):
    assert client.get("/expenses/stats").json() == {
        "count": 0,
        "with_extraction": 0,
        "correction_rate_by_field": {},
        "qr_verified_rate": None,
    }
    extracted = client.post(
        "/receipts/validate", json={"receipt": raw_receipt()}
    ).json()["receipt"]
    kept = save(client, extracted=extracted)
    assert kept["corrected_fields"] == []
    fixed = save(
        client,
        extracted=extracted,
        receipt=raw_receipt(
            issuer="Comercio corregido",
            number="0001-00000009",
            total="1.300,00",
            subtotal="1.074,38",
            tax="225,62",
        ),
    )
    assert fixed["corrected_fields"] == [
        "issuer",
        "number",
        "subtotal",
        "tax",
        "total",
    ]
    save(client, receipt=raw_receipt(number="0001-00000010", total="7,00"))
    stats = client.get("/expenses/stats").json()
    assert stats["count"] == 3
    assert stats["with_extraction"] == 2
    rates = stats["correction_rate_by_field"]
    assert rates["issuer"] == 0.5
    assert rates["total"] == 0.5
    assert rates["currency"] == 0.0
    assert len(rates) == 10
    assert stats["qr_verified_rate"] == 0.0


def test_db_path_comes_from_env(tmp_path, monkeypatch):
    target = tmp_path / "x" / "y.sqlite"
    monkeypatch.setenv("EXPENSE_LENS_DB", str(target))
    assert db_path() == target
    open_db(db_path()).close()
    assert target.exists()
    monkeypatch.delenv("EXPENSE_LENS_DB")
    assert str(db_path()) == "data/expenses.sqlite"


def test_duplicate_match_identifies_the_existing_expense(client):
    """La persona necesita ver qué gasto ya existe para decidir si guardar."""
    first = save(client)
    response = client.post("/expenses", json=payload())
    assert response.status_code == 409
    [match] = response.json()["detail"]["matches"]
    assert match == {
        "id": first["id"],
        "reason": "fiscal_key",
        "issuer": first["receipt"]["issuer"],
        "date": first["receipt"]["date"],
        "total": first["receipt"]["total"],
        "currency": first["receipt"]["currency"],
    }
