"""Proceso PDFium de vida corta: stdin PDF, stdout JSON; nunca llama al proveedor."""

import base64
import json
import math
import sys
from io import BytesIO

import pypdfium2 as pdfium

from expense_lens.documents import MAX_BYTES, MAX_PAGES, DocumentError


def render(data: bytes) -> list[str]:
    images = []
    total_bytes = 0
    with pdfium.PdfDocument(data) as document:
        if not 1 <= len(document) <= MAX_PAGES:
            raise DocumentError(422, "invalid_pdf_render")
        for index in range(len(document)):
            page = document[index]
            try:
                width, height = page.get_size()
                if not all(
                    math.isfinite(v) and 0 < v <= 20_000 for v in (width, height)
                ):
                    raise DocumentError(413, "pdf_page_too_large")
                scale = min(2.0, 1400 / width, 1400 / height)
                if math.ceil(width * scale) * math.ceil(height * scale) > 2_000_000:
                    raise DocumentError(413, "pdf_page_too_large")
                bitmap = page.render(scale=scale, may_draw_forms=False)
                try:
                    with bitmap.to_pil() as raster:
                        with raster.convert("RGB") as image:
                            output = BytesIO()
                            image.save(output, format="JPEG", quality=85)
                    encoded = output.getvalue()
                finally:
                    bitmap.close()
                total_bytes += len(encoded)
                if total_bytes > MAX_BYTES:
                    raise DocumentError(413, "rendered_pdf_too_large")
                images.append(
                    "data:image/jpeg;base64," + base64.b64encode(encoded).decode()
                )
            finally:
                page.close()
    return images


def main() -> None:
    data = sys.stdin.buffer.read(MAX_BYTES + 1)
    try:
        if len(data) > MAX_BYTES:
            raise DocumentError(413, "document_too_large")
        result = {"images": render(data)}
    except DocumentError as exc:
        result = {"error": exc.detail, "status": exc.status_code}
    except Exception:
        result = {"error": "invalid_pdf_render", "status": 422}
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
