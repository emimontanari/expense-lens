import json
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from groq import Groq
from pypdf import PdfWriter

from expense_lens import extraction
from expense_lens.main import app

EXAMPLES = Path(__file__).parents[1] / "examples" / "synthetic"
RESULT = {
    "issuer": "Comercio ficticio",
    "issuer_cuit": "30-00000000-7",
    "date": "15/10/2026",
    "number": "0001-00000001",
    "document_type": "factura",
    "letter": "A",
    "currency": "$",
    "subtotal": "100,00",
    "tax": "21,00",
    "total": "121,00",
}
NORMALIZED = {
    "issuer": "Comercio ficticio",
    "issuer_cuit": "30000000007",
    "date": "2026-10-15",
    "number": "0001-00000001",
    "document_type": "factura",
    "letter": "A",
    "currency": "ARS",
    "subtotal": "100.00",
    "tax": "21.00",
    "total": "121.00",
}
CONSENT = {"X-Allow-External-Processing": "true"}


@pytest.fixture
def requests(monkeypatch):
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(RESULT),
                        },
                    }
                ],
            },
        )

    def install(custom_handler=handler):
        monkeypatch.setattr(
            extraction,
            "configured_client",
            lambda: Groq(
                api_key="test-not-a-real-key",
                max_retries=0,
                base_url="https://api.groq.com",
                http_client=httpx.Client(transport=httpx.MockTransport(custom_handler)),
            ),
        )

    install()
    return sent, install


@pytest.mark.parametrize(
    "filename,mime",
    [
        ("receipt.png", "image/png"),
        ("receipt.jpg", "image/jpeg"),
        ("receipt-scanned.pdf", "image/jpeg"),
        ("receipt-text.pdf", "image/jpeg"),
    ],
)
def test_extracts_image_via_mocked_sdk_and_validates(requests, filename, mime):
    sent, _ = requests
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / filename).read_bytes(),
            headers=CONSENT,
        )
    assert response.status_code == 200
    assert response.json()["receipt"] == NORMALIZED
    assert response.json()["issues"] == [
        {
            "code": "currency_inferred_from_symbol",
            "field": "currency",
            "severity": "info",
        }
    ]
    assert response.json()["requires_human_review"] is True
    assert len(sent) == 1
    body = json.loads(sent[0].content)
    assert body["model"] == extraction.MODEL
    assert body["max_completion_tokens"] == 1024
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][1]["content"][1]["image_url"]["url"].startswith(
        f"data:{mime};base64,"
    )


@pytest.mark.parametrize(
    "filename,headers,code",
    [
        ("receipt.png", {}, 403),
        ("receipt-scanned.pdf", {}, 403),
        ("invalid.pdf", CONSENT, 422),
    ],
)
def test_rejects_before_provider(requests, filename, headers, code):
    sent, _ = requests
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / filename).read_bytes(),
            headers=headers,
        )
    assert response.status_code == code
    assert sent == []


@pytest.mark.parametrize(
    "content,reason",
    [
        ("not json", "stop"),
        ("{}", "stop"),
        (json.dumps({**RESULT, "total": 121.0}), "stop"),
        (json.dumps(RESULT), "length"),
        ("null", "stop"),
    ],
)
def test_rejects_invalid_model_output_without_repair(requests, content, reason):
    sent, install = requests

    def handler(request):
        sent.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "finish_reason": reason,
                        "message": {"role": "assistant", "content": content},
                    }
                ]
            },
        )

    install(handler)
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / "receipt.png").read_bytes(),
            headers=CONSENT,
        )
    assert response.status_code == 502
    assert response.json() == {"detail": "invalid_model_output"}
    assert len(sent) == 1


@pytest.mark.parametrize("status,code", [(401, 502), (429, 503), (500, 502)])
def test_sanitizes_provider_failures_and_does_not_retry(requests, status, code):
    sent, install = requests

    def handler(request):
        sent.append(request)
        return httpx.Response(status, json={"error": {"message": "SENSITIVE-DOCUMENT"}})

    install(handler)
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / "receipt.png").read_bytes(),
            headers=CONSENT,
        )
    assert response.status_code == code
    assert response.json()["detail"] == (
        "provider_rate_limited" if status == 429 else "provider_error"
    )
    assert "SENSITIVE-DOCUMENT" not in response.text
    assert len(sent) == 1


@pytest.mark.parametrize(
    "error_type,code", [(httpx.ReadTimeout, 504), (httpx.ConnectError, 502)]
)
def test_network_failures_are_sanitized_without_retry(requests, error_type, code):
    sent, install = requests

    def handler(request):
        sent.append(request)
        raise error_type("SENSITIVE-DOCUMENT", request=request)

    install(handler)
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / "receipt.png").read_bytes(),
            headers=CONSENT,
        )
    assert response.status_code == code
    assert "SENSITIVE-DOCUMENT" not in response.text
    assert len(sent) == 1


def test_invalid_provider_envelope_is_sanitized(requests):
    sent, install = requests

    def handler(request):
        sent.append(request)
        return httpx.Response(
            200, content=b"{", headers={"content-type": "application/json"}
        )

    install(handler)
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract",
            content=(EXAMPLES / "receipt.png").read_bytes(),
            headers=CONSENT,
        )
    assert response.status_code == 502
    assert response.json() == {"detail": "invalid_model_output"}
    assert len(sent) == 1


def test_pdf_pages_share_one_request_and_keep_review_required(requests):
    sent, _ = requests
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=600, height=800)
    output = BytesIO()
    writer.write(output)
    with TestClient(app) as client:
        response = client.post(
            "/receipts/extract", content=output.getvalue(), headers=CONSENT
        )
    assert response.status_code == 200
    assert response.json()["requires_human_review"] is True
    assert len(sent) == 1
    images = json.loads(sent[0].content)["messages"][1]["content"][1:]
    assert len(images) == 3
    assert all(
        image["image_url"]["url"].startswith("data:image/jpeg;base64,")
        for image in images
    )


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EXPENSE_LENS_ENABLE_GROQ", raising=False)
    with pytest.raises(extraction.ExtractionError) as error:
        extraction.configured_client()
    assert error.value.status_code == 503


def test_missing_key_fails_closed(monkeypatch):
    monkeypatch.setenv("EXPENSE_LENS_ENABLE_GROQ", "1")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(extraction.ExtractionError) as error:
        extraction.configured_client()
    assert error.value.status_code == 503
