import pytest
from fastapi.testclient import TestClient

from expense_lens.main import app


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


@pytest.fixture
def receipt():
    return {
        "issuer": "Comercio ficticio",
        "date": "2026-10-15",
        "number": "0001-00000001",
        "currency": "ARS",
        "subtotal": "0.10",
        "tax": "0.20",
        "total": "0.30",
    }


def test_valid_receipt_keeps_decimal_strings_and_requires_human_review(client, receipt):
    response = client.post("/receipts/validate", json=receipt)
    assert response.status_code == 200
    result = response.json()
    assert result["issues"] == []
    assert result["requires_human_review"] is True
    assert result["receipt"]["total"] == "0.30"


def test_mismatch_is_reported_without_changing_total(client, receipt):
    receipt["total"] = "0.31"
    response = client.post("/receipts/validate", json=receipt)
    assert response.status_code == 200
    result = response.json()
    assert result["receipt"]["total"] == "0.31"
    assert result["issues"] == [{"code": "total_mismatch", "field": "total"}]


def test_missing_fields_stay_missing_and_skip_sum(client):
    response = client.post("/receipts/validate", json={})
    assert response.status_code == 200
    result = response.json()
    assert all(value is None for value in result["receipt"].values())
    assert {issue["field"] for issue in result["issues"]} == {
        "issuer",
        "date",
        "number",
        "currency",
        "subtotal",
        "tax",
        "total",
    }
    assert all(issue["code"] == "missing_field" for issue in result["issues"])
    assert result["requires_human_review"] is True


@pytest.mark.parametrize("amount", ["0.00", "12", "12.5", "9999999999.99"])
def test_supported_amounts(client, receipt, amount):
    receipt.update(subtotal=amount, tax="0", total=amount)
    response = client.post("/receipts/validate", json=receipt)
    assert response.status_code == 200
    assert response.json()["issues"] == []


@pytest.mark.parametrize(
    "amount",
    [
        -1,
        0.1,
        10,
        True,
        "-0.01",
        "NaN",
        "Infinity",
        "1.001",
        "1,20",
        "1e2",
        "",
        " 1.00 ",
        "10000000000.00",
    ],
)
def test_invalid_amounts_are_rejected(client, receipt, amount):
    receipt["total"] = amount
    assert client.post("/receipts/validate", json=receipt).status_code == 422


@pytest.mark.parametrize(
    "change",
    [
        {"currency": "USD"},
        {"date": "2026-02-30"},
        {"issuer": "   "},
        {"unexpected": "ignored?"},
    ],
)
def test_invalid_contract_is_rejected(client, receipt, change):
    receipt.update(change)
    assert client.post("/receipts/validate", json=receipt).status_code == 422


def test_explicit_null_is_reported_not_invented(client, receipt):
    receipt["tax"] = None
    response = client.post("/receipts/validate", json=receipt)
    assert response.status_code == 200
    assert response.json()["issues"] == [{"code": "missing_field", "field": "tax"}]
    assert response.json()["receipt"]["tax"] is None
