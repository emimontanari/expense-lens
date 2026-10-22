from fastapi.testclient import TestClient

from expense_lens.main import app
from expense_lens.qr_signature import sign_qr, verify_qr
from expense_lens.receipts import FiscalQr

QR = FiscalQr.model_validate(
    {
        "issuer_cuit": "30000000007",
        "date": "2020-10-13",
        "point_of_sale": 10,
        "number": 94,
        "receipt_type_code": 1,
        "document_type": "factura",
        "letter": "A",
        "total": "12100",
        "currency": "ARS",
        "exchange_rate": "1",
        "authorization_type": "CAE",
        "authorization_code": "70417054367476",
    }
)


def test_signatures_are_stable_and_verified():
    signature = sign_qr(QR)
    assert signature == sign_qr(QR)
    assert verify_qr(QR, signature)
    assert not verify_qr(QR, None)


def test_a_different_secret_rejects_an_old_signature(monkeypatch):
    import expense_lens.qr_signature as signatures

    monkeypatch.setenv("EXPENSE_LENS_SECRET", "old-secret")
    monkeypatch.setattr(signatures, "_secret", None)
    old_signature = sign_qr(QR)
    monkeypatch.setenv("EXPENSE_LENS_SECRET", "new-secret")
    monkeypatch.setattr(signatures, "_secret", None)
    assert not verify_qr(QR, old_signature)


def test_unsigned_and_tampered_qr_are_rejected_without_persistence(tmp_path):
    from expense_lens import storage
    from expense_lens.expenses import get_db

    path = tmp_path / "expenses.sqlite"

    def override():
        conn = storage.open_db(path)
        try:
            yield conn
        finally:
            conn.close()

    app.dependency_overrides[get_db] = override
    receipt = {
        "issuer": "Comercio",
        "issuer_cuit": "30-00000000-7",
        "date": "13/10/2020",
        "number": "00010-00000094",
        "document_type": "factura",
        "letter": "A",
        "currency": "ARS",
        "subtotal": "10000",
        "tax": "2100",
        "total": "12100",
    }
    qr = QR.model_dump(mode="json")
    try:
        with TestClient(app) as client:
            for signature in (None, "bad"):
                response = client.post(
                    "/expenses",
                    json={
                        "receipt": receipt,
                        "fiscal_qr": qr,
                        "fiscal_qr_signature": signature,
                        "category": "otros",
                    },
                )
                assert response.status_code == 422
                assert response.json()["detail"]["code"] == (
                    "fiscal_qr_signature_invalid"
                )
            changed = {**qr, "total": "999"}
            response = client.post(
                "/receipts/validate",
                json={
                    "receipt": receipt,
                    "fiscal_qr": changed,
                    "fiscal_qr_signature": sign_qr(QR),
                },
            )
            assert response.status_code == 422
            assert client.get("/expenses").json()["items"] == []
    finally:
        app.dependency_overrides.clear()


def test_non_ascii_signature_is_rejected_not_a_server_error():
    """compare_digest lanza TypeError con texto no ASCII: debe ser un 422."""
    assert not verify_qr(QR, "ñ" * 64)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/receipts/validate",
            json={
                "receipt": {},
                "fiscal_qr": QR.model_dump(mode="json"),
                "fiscal_qr_signature": "ñ",
            },
        )
    assert response.status_code == 422
