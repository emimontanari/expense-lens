import base64
import json
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image
from pypdf import PdfWriter

from expense_lens.documents import DocumentError
from expense_lens.pdf_render import render_pdf

EXAMPLES = Path(__file__).parents[1] / "examples" / "synthetic"


@pytest.mark.parametrize("name", ["receipt-scanned.pdf", "receipt-text.pdf"])
def test_renders_scanned_and_text_pdf_to_bounded_jpeg(name):
    pages = render_pdf((EXAMPLES / name).read_bytes())
    assert len(pages) == 1
    assert pages[0].startswith("data:image/jpeg;base64,")
    with Image.open(BytesIO(base64.b64decode(pages[0].split(",", 1)[1]))) as image:
        assert max(image.size) <= 1400
        assert image.width * image.height <= 2_000_000
        with image.convert("L") as grayscale:
            assert sum(grayscale.histogram()[:100]) > 0


def test_renders_three_pages_in_order():
    writer = PdfWriter()
    for width in [200, 300, 400]:
        writer.add_blank_page(width=width, height=600)
    output = BytesIO()
    writer.write(output)
    pages = render_pdf(output.getvalue())
    widths = []
    for page in pages:
        with Image.open(BytesIO(base64.b64decode(page.split(",", 1)[1]))) as image:
            widths.append(image.width)
    assert len(widths) == 3
    assert widths == sorted(set(widths))


def test_child_timeout_is_sanitized_and_does_not_receive_secrets(monkeypatch):
    def run(*args, **kwargs):
        assert kwargs["timeout"] == 10
        assert "GROQ_API_KEY" not in kwargs["env"]
        assert "EXPENSE_LENS_ENABLE_GROQ" not in kwargs["env"]
        assert "PYTHONPATH" not in kwargs["env"]
        raise subprocess.TimeoutExpired(args[0], 10)

    monkeypatch.setenv("GROQ_API_KEY", "test-not-real")
    monkeypatch.setattr(subprocess, "run", run)
    with pytest.raises(DocumentError) as error:
        render_pdf((EXAMPLES / "receipt-scanned.pdf").read_bytes())
    assert error.value.detail == "pdf_render_timeout"


@pytest.mark.parametrize(
    "returncode,stdout",
    [
        (1, b"SENSITIVE"),
        (0, b"not-json"),
        (0, json.dumps({"error": "pdf_page_too_large", "status": 413}).encode()),
    ],
)
def test_child_failure_is_sanitized(monkeypatch, returncode, stdout):
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: subprocess.CompletedProcess(a[0], returncode, stdout),
    )
    with pytest.raises(DocumentError) as error:
        render_pdf((EXAMPLES / "receipt-scanned.pdf").read_bytes())
    assert "SENSITIVE" not in error.value.detail
    assert error.value.status_code in [413, 422]


def test_rejects_oversized_page_geometry():
    writer = PdfWriter()
    writer.add_blank_page(width=30_000, height=30_000)
    output = BytesIO()
    writer.write(output)
    with pytest.raises(DocumentError) as error:
        render_pdf(output.getvalue())
    assert error.value.status_code == 413
