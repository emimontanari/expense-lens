import base64
import json
from io import BytesIO

import httpx
import pytest
import segno
from fastapi.testclient import TestClient
from groq import Groq
from PIL import Image

from expense_lens import extraction
from expense_lens.fiscal_qr import find_fiscal_qr, parse_fiscal_qr
from expense_lens.main import app

# Ejemplo de la especificación oficial (moneda cambiada a pesos).
QR_DATA = {
    "ver": 1,
    "fecha": "2020-10-13",
    "cuit": 30000000007,
    "ptoVta": 10,
    "tipoCmp": 1,
    "nroCmp": 94,
    "importe": 12100,
    "moneda": "PES",
    "ctz": 1,
    "tipoDocRec": 80,
    "nroDocRec": 20000000001,
    "tipoCodAut": "E",
    "codAut": 70417054367476,
}
TRANSCRIBED = {
    "issuer": "Comercio ficticio",
    "issuer_cuit": "30-00000000-7",
    "date": "13/10/2020",
    "number": "00010-00000094",
    "document_type": "factura",
    "letter": "A",
    "currency": "$",
    "subtotal": "10.000,00",
    "tax": "2.100,00",
    "total": "12.100,00",
}
CONSENT = {"X-Allow-External-Processing": "true"}


def qr_url(data=QR_DATA, host="www.afip.gob.ar"):
    payload = base64.b64encode(json.dumps(data).encode()).decode()
    return f"https://{host}/fe/qr/?p={payload}"


def receipt_image(text: str | None, fmt="PNG") -> bytes:
    canvas = Image.new("RGB", (800, 1000), "white")
    if text is not None:
        qr = BytesIO()
        segno.make(text, error="m").save(qr, kind="png", scale=4, border=4)
        canvas.paste(Image.open(BytesIO(qr.getvalue())).convert("RGB"), (420, 560))
    output = BytesIO()
    canvas.save(output, fmt)
    return output.getvalue()


def test_parses_official_example_into_normalized_fields():
    qr = parse_fiscal_qr(qr_url())
    assert qr is not None
    assert qr.model_dump(mode="json") == {
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


@pytest.mark.parametrize(
    "code,document_type,letter",
    [(6, "factura", "B"), (13, "nota_credito", "C"), (2, "nota_debito", "A")],
)
def test_maps_receipt_type_codes(code, document_type, letter):
    qr = parse_fiscal_qr(qr_url({**QR_DATA, "tipoCmp": code}))
    assert (qr.document_type, qr.letter) == (document_type, letter)


def test_accepts_arca_host_and_dollar_amounts_without_conversion():
    data = {**QR_DATA, "moneda": "DOL", "ctz": 65, "importe": 121.5}
    qr = parse_fiscal_qr(qr_url(data, host="www.arca.gob.ar"))
    assert (qr.currency, str(qr.total), qr.exchange_rate) == ("USD", "121.5", "65")


@pytest.mark.parametrize(
    "text",
    [
        qr_url(host="afip.gob.ar.evil.example"),
        qr_url().replace("https://", "ftp://"),
        "https://www.afip.gob.ar/fe/qr/?p=%%%",
        "https://www.afip.gob.ar/fe/qr/",
        qr_url({**QR_DATA, "ver": 2}),
        qr_url({**QR_DATA, "cuit": 30000000008}),
        qr_url({k: v for k, v in QR_DATA.items() if k != "importe"}),
        qr_url({**QR_DATA, "importe": "12100"}),
        qr_url({**QR_DATA, "tipoCodAut": "X"}),
        "https://www.afip.gob.ar/fe/qr/?p=" + "A" * 3000,
        "hola",
    ],
)
def test_rejects_untrusted_or_malformed_payloads(text):
    assert parse_fiscal_qr(text) is None


def test_finds_qr_in_jpeg_and_reports_invalid_or_absent():
    assert find_fiscal_qr([receipt_image(qr_url(), "JPEG")])[1] == "found"
    assert find_fiscal_qr([receipt_image("https://example.com")]) == (
        None,
        "invalid",
    )
    assert find_fiscal_qr([receipt_image(None)]) == (None, "not_found")


@pytest.fixture
def extract(monkeypatch):
    def run(image: bytes, transcribed: dict):
        def handler(request):
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "role": "assistant",
                                "content": json.dumps(
                                    {**transcribed, "category": None}
                                ),
                            },
                        }
                    ]
                },
            )

        monkeypatch.setattr(
            extraction,
            "configured_client",
            lambda: Groq(
                api_key="test-not-a-real-key",
                max_retries=0,
                http_client=httpx.Client(transport=httpx.MockTransport(handler)),
            ),
        )
        with TestClient(app) as client:
            response = client.post("/receipts/extract", content=image, headers=CONSENT)
        assert response.status_code == 200, response.text
        return response.json()

    return run


def test_matching_qr_marks_fields_verified(extract):
    result = extract(receipt_image(qr_url()), TRANSCRIBED)
    assert result["fiscal_qr_status"] == "found"
    assert result["fiscal_qr"]["authorization_code"] == "70417054367476"
    status = result["field_status"]
    for field in (
        "issuer_cuit",
        "date",
        "number",
        "document_type",
        "letter",
        "currency",
        "total",
    ):
        assert status[field] == "verified", field
    assert status["issuer"] == "unverified"
    assert status["subtotal"] == "unverified"


def test_differences_between_qr_and_visible_content_are_flagged(extract):
    transcribed = {**TRANSCRIBED, "total": "12.000,00", "letter": "B"}
    result = extract(receipt_image(qr_url()), transcribed)
    mismatches = {i["field"] for i in result["issues"] if i["code"] == "qr_mismatch"}
    assert mismatches == {"total", "letter"}
    assert result["receipt"]["total"] == "12000.00"
    assert result["field_status"]["total"] == "conflict"
    assert result["field_status"]["issuer_cuit"] == "verified"


def test_without_qr_nothing_is_verified(extract):
    result = extract(receipt_image(None), TRANSCRIBED)
    assert result["fiscal_qr_status"] == "not_found"
    assert result["fiscal_qr"] is None
    assert "verified" not in result["field_status"].values()


def test_validate_rechecks_corrections_against_returned_qr():
    qr = parse_fiscal_qr(qr_url()).model_dump(mode="json")
    with TestClient(app) as client:
        response = client.post(
            "/receipts/validate",
            json={"receipt": {**TRANSCRIBED, "total": "12.000,00"}, "fiscal_qr": qr},
        )
    assert response.status_code == 200
    result = response.json()
    assert result["field_status"]["total"] == "conflict"
    assert result["field_status"]["date"] == "verified"


def test_qr_confirms_a_total_interpreted_from_the_document():
    """ "12.100" con importes en coma decimal se lee 12100 y el QR lo confirma."""
    qr = parse_fiscal_qr(qr_url()).model_dump(mode="json")
    with TestClient(app) as client:
        response = client.post(
            "/receipts/validate",
            json={"receipt": {**TRANSCRIBED, "total": "12.100"}, "fiscal_qr": qr},
        )
    result = response.json()
    assert result["receipt"]["total"] == "12100"
    assert result["field_status"]["total"] == "verified"
    assert {
        "code": "amount_interpreted_from_document",
        "field": "total",
        "severity": "info",
    } in result["issues"]
