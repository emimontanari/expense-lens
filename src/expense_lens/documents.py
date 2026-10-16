"""Inspección local de contenido; no almacena archivos ni extrae datos del recibo."""

from io import BytesIO
from typing import Literal

from PIL import Image
from pydantic import BaseModel
from pypdf import PdfReader

MAX_BYTES = 5 * 1024 * 1024
MAX_PIXELS = 12_000_000
MAX_PAGES = 3


class DocumentError(ValueError):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class DocumentInspection(BaseModel):
    format: Literal["jpeg", "png", "pdf"]
    size_bytes: int
    pages: int | None = None
    requires_human_review: Literal[True] = True


def inspect_document(data: bytes) -> DocumentInspection:
    """Verifica estructura básica. No es antivirus, sandbox ni validación fiscal."""
    if len(data) > MAX_BYTES:
        raise DocumentError(413, "document_too_large")
    if not data:
        raise DocumentError(422, "empty_document")
    if data.startswith(b"%PDF-"):
        try:
            reader = PdfReader(BytesIO(data), strict=True)
            if reader.is_encrypted:
                raise DocumentError(422, "encrypted_pdf")
            pages = len(reader.pages)
            if pages > MAX_PAGES:
                raise DocumentError(413, "too_many_pages")
            if pages == 0:
                raise DocumentError(422, "empty_pdf")
        except DocumentError:
            raise
        except Exception as exc:
            # Errores heterogéneos del parser: no devolver detalles del documento.
            raise DocumentError(422, "invalid_pdf") from exc
        return DocumentInspection(format="pdf", size_bytes=len(data), pages=pages)
    if not (data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8")):
        raise DocumentError(415, "unsupported_document")
    try:
        with Image.open(BytesIO(data), formats=["PNG", "JPEG"]) as image:
            if image.width * image.height > MAX_PIXELS:
                raise DocumentError(413, "too_many_pixels")
            if getattr(image, "n_frames", 1) != 1:
                raise DocumentError(422, "animated_image")
            kind = "png" if image.format == "PNG" else "jpeg"
            image.verify()
        with Image.open(BytesIO(data), formats=["PNG", "JPEG"]) as image:
            image.load()
    except DocumentError:
        raise
    except Image.DecompressionBombError as exc:
        raise DocumentError(413, "too_many_pixels") from exc
    except Exception as exc:
        raise DocumentError(422, "invalid_image") from exc
    return DocumentInspection(format=kind, size_bytes=len(data))
