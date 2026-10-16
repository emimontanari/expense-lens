import asyncio
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from pypdf import PdfWriter
from starlette.requests import Request

from expense_lens.main import app, check_document

EXAMPLES = Path(__file__).parents[1] / "examples" / "synthetic"
LIMIT = 5 * 1024 * 1024


@pytest.fixture
def client():
    with TestClient(app) as client:
        yield client


def pdf_bytes(pages=1, encrypted=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=600, height=800)
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize(
    "name,kind,pages",
    [
        ("receipt.png", "png", None),
        ("receipt.jpg", "jpeg", None),
        ("receipt-scanned.pdf", "pdf", 1),
    ],
)
def test_accepts_real_synthetic_files_by_content(client, name, kind, pages):
    data = (EXAMPLES / name).read_bytes()
    response = client.post(
        "/documents/inspect",
        content=data,
        headers={"content-type": "application/octet-stream"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "format": kind,
        "size_bytes": len(data),
        "pages": pages,
        "requires_human_review": True,
    }


@pytest.mark.parametrize(
    "data,code",
    [
        (b"", 422),
        (b"<html>not an image</html>", 415),
        (b"\x89PNG\r\n\x1a\ntruncated", 422),
        ((EXAMPLES / "invalid.pdf").read_bytes(), 422),
        (b"x" * (LIMIT + 1), 413),
    ],
)
def test_rejects_invalid_or_oversized_body(client, data, code):
    response = client.post(
        "/documents/inspect", content=data, headers={"content-type": "image/png"}
    )
    assert response.status_code == code
    assert "detail" in response.json()


@pytest.mark.parametrize(
    "pages,encrypted,code",
    [
        (0, False, 422),
        (3, False, 200),
        (4, False, 413),
        (1, True, 422),
    ],
)
def test_pdf_limits(client, pages, encrypted, code):
    response = client.post("/documents/inspect", content=pdf_bytes(pages, encrypted))
    assert response.status_code == code


def test_rejects_large_image_before_decoding(client):
    output = BytesIO()
    with Image.new("1", (4000, 3001)) as image:
        image.save(output, format="PNG")
    assert (
        client.post("/documents/inspect", content=output.getvalue()).status_code == 413
    )


def test_header_does_not_bypass_byte_limit(client):
    def chunks():
        yield b"x" * LIMIT
        yield b"x"

    response = client.post(
        "/documents/inspect", content=chunks(), headers={"content-length": "1"}
    )
    assert response.status_code == 413


def test_exact_byte_limit_reaches_content_validation(client):
    response = client.post("/documents/inspect", content=b"x" * LIMIT)
    assert response.status_code == 415


def test_accepts_image_ignoring_forged_mime_and_filename(client):
    response = client.post(
        "/documents/inspect",
        content=(EXAMPLES / "receipt.png").read_bytes(),
        headers={
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="../../secret.pdf"',
        },
    )
    assert response.status_code == 200
    assert response.json()["format"] == "png"


def test_stream_stops_at_limit_without_reading_remaining_body():
    messages = iter(
        [
            {"type": "http.request", "body": b"x" * LIMIT, "more_body": True},
            {"type": "http.request", "body": b"x", "more_body": True},
        ]
    )

    async def receive():
        return next(messages)  # A third read would fail this test.

    request = Request({"type": "http", "method": "POST", "path": "/"}, receive)
    with pytest.raises(HTTPException) as error:
        asyncio.run(check_document(request))
    assert error.value.status_code == 413


def test_rejects_truncated_jpeg(client):
    data = (EXAMPLES / "receipt.jpg").read_bytes()[:-100]
    assert client.post("/documents/inspect", content=data).status_code == 422


def test_rejects_animated_png(client):
    output = BytesIO()
    with Image.new("RGB", (10, 10), "red") as first:
        with Image.new("RGB", (10, 10), "blue") as second:
            first.save(output, format="PNG", save_all=True, append_images=[second])
    response = client.post("/documents/inspect", content=output.getvalue())
    assert response.status_code == 422
    assert response.json()["detail"] == "animated_image"
