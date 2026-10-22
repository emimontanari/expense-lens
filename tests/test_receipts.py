import pytest
from fastapi.testclient import TestClient

from expense_lens.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def receipt():
    """Factura A ficticia con IVA discriminado y CUIT de ejemplo oficial."""
    return {
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


def validate(client, receipt, **extra):
    response = client.post("/receipts/validate", json={"receipt": receipt, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def codes(result):
    return {(issue["code"], issue["field"]) for issue in result["issues"]}


def test_valid_factura_is_normalized_and_still_requires_review(client, receipt):
    result = validate(client, receipt)
    assert result["issues"] == []
    assert result["receipt"] == {
        "issuer": "Comercio ficticio",
        "issuer_cuit": "30000000007",
        "date": "2026-10-15",
        "number": "0001-00000001",
        "document_type": "factura",
        "letter": "A",
        "currency": "ARS",
        "subtotal": "1000.00",
        "tax": "210.00",
        "total": "1210.00",
    }
    assert result["movement"] == "expense"
    assert result["requires_human_review"] is True
    assert set(result["field_status"].values()) == {"unverified"}


def test_mismatch_is_reported_without_changing_total(client, receipt):
    receipt["total"] = "1.211,00"
    result = validate(client, receipt)
    assert result["receipt"]["total"] == "1211.00"
    assert codes(result) == {("total_mismatch", "total")}
    assert result["field_status"]["total"] == "conflict"


def test_total_is_not_confused_with_subtotal(client, receipt):
    receipt.update(subtotal="1.210,00", tax="210,00", total="1.000,00")
    assert codes(validate(client, receipt)) == {("total_below_subtotal", "total")}


def test_vat_already_included_is_not_added_twice(client, receipt):
    receipt.update(subtotal="1.210,00", tax="210,00", total="1.210,00")
    assert codes(validate(client, receipt)) == {("tax_already_included", "subtotal")}


def test_credit_note_is_not_an_ordinary_purchase(client, receipt):
    receipt["document_type"] = "nota_credito"
    result = validate(client, receipt)
    assert result["movement"] == "credit"
    assert ("credit_note", "document_type") in codes(result)
    assert all(i["severity"] == "info" for i in result["issues"])


def test_dollars_are_never_converted_to_pesos(client, receipt):
    receipt.update(currency="US$", subtotal="100,00", tax="21,00", total="121,00")
    result = validate(client, receipt)
    assert result["receipt"]["currency"] == "USD"
    assert result["receipt"]["total"] == "121.00"
    assert codes(result) == {("foreign_currency", "currency")}


def test_invalid_cuit_is_flagged_and_left_empty(client, receipt):
    receipt["issuer_cuit"] = "30-00000000-8"
    result = validate(client, receipt)
    assert result["receipt"]["issuer_cuit"] is None
    assert codes(result) == {("invalid_cuit", "issuer_cuit")}
    assert result["field_status"]["issuer_cuit"] == "conflict"


def test_future_date_is_flagged(client, receipt):
    receipt["date"] = "01/01/2999"
    assert codes(validate(client, receipt)) == {("future_date", "date")}


def test_factura_c_does_not_discriminate_vat(client, receipt):
    receipt.update(letter="C", subtotal=None, tax="210,00", total="1.210,00")
    assert codes(validate(client, receipt)) == {("unexpected_tax", "tax")}


def test_factura_b_and_ticket_do_not_require_subtotal_or_tax(client, receipt):
    receipt.update(letter="B", subtotal=None, tax=None)
    assert validate(client, receipt)["issues"] == []
    receipt.update(document_type="ticket", letter=None, issuer_cuit=None, number=None)
    result = validate(client, receipt)
    assert result["issues"] == []
    assert result["field_status"]["tax"] == "empty"


def test_factura_a_requires_discriminated_vat(client, receipt):
    receipt.update(subtotal=None, tax=None)
    assert codes(validate(client, receipt)) == {
        ("missing_field", "subtotal"),
        ("missing_field", "tax"),
    }


def test_ambiguous_amount_stays_null_with_warning(client, receipt):
    receipt.update(letter="B", subtotal=None, tax=None, total="1.210")
    result = validate(client, receipt)
    assert result["receipt"]["total"] is None
    assert codes(result) == {("ambiguous_amount", "total")}
    assert result["field_status"]["total"] == "conflict"


def test_missing_fields_stay_missing_and_skip_sum(client):
    result = validate(client, {})
    assert all(value is None for value in result["receipt"].values())
    assert codes(result) == {
        ("missing_field", field) for field in ("issuer", "date", "currency", "total")
    }
    assert result["movement"] == "unknown"
    assert result["field_status"]["issuer"] == "missing"


@pytest.mark.parametrize(
    "change",
    [
        {"document_type": "remito"},
        {"letter": "Z"},
        {"issuer": "x" * 201},
        {"unexpected": "ignored?"},
        {"total": 121.0},
    ],
)
def test_invalid_contract_is_rejected(client, receipt, change):
    receipt.update(change)
    response = client.post("/receipts/validate", json={"receipt": receipt})
    assert response.status_code == 422


def test_subtotal_copied_from_total_without_tax_is_flagged(client, receipt):
    """eval-002: el modelo copió el total como subtotal en facturas B, C y E."""
    receipt.update(letter="B", subtotal="3.900,00", tax=None, total="3.900,00")
    result = validate(client, receipt)
    assert codes(result) == {("subtotal_equals_total", "subtotal")}
    assert result["receipt"]["subtotal"] == "3900.00"
    assert result["field_status"]["subtotal"] == "conflict"


def test_subtotal_equal_to_total_with_zero_tax_is_not_flagged(client, receipt):
    receipt.update(letter="B", subtotal="3.900,00", tax="0,00", total="3.900,00")
    assert validate(client, receipt)["issues"] == []


def test_ambiguous_total_uses_the_document_own_decimal_style(client, receipt):
    """Si el resto del comprobante usa coma decimal, "1.234" son miles."""
    receipt.update(subtotal="1.000,00", tax="234,00", total="1.234")
    result = validate(client, receipt)
    assert result["receipt"]["total"] == "1234"
    assert result["issues"] == [
        {
            "code": "amount_interpreted_from_document",
            "field": "total",
            "severity": "info",
        }
    ]
    assert result["field_status"]["total"] == "unverified"


def test_mixed_decimal_styles_give_no_evidence(client, receipt):
    receipt.update(subtotal="1.000,00", tax="234.00", total="1.234")
    result = validate(client, receipt)
    assert result["receipt"]["total"] is None
    assert ("ambiguous_amount", "total") in codes(result)
