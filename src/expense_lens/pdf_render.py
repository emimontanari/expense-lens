"""Renderizador acotado en subproceso, sin heredar credenciales del servidor."""

import json
import os
import subprocess
import sys

from expense_lens.documents import MAX_BYTES, MAX_PAGES, DocumentError, inspect_document


def render_pdf(data: bytes) -> list[str]:
    if inspect_document(data).format != "pdf":
        raise DocumentError(415, "pdf_required")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "expense_lens.pdf_worker"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env={"PATH": os.defpath},
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise DocumentError(422, "pdf_render_timeout") from exc
    except OSError as exc:
        raise DocumentError(422, "pdf_render_failed") from exc
    if result.returncode != 0 or len(result.stdout) > MAX_BYTES * 2:
        raise DocumentError(422, "pdf_render_failed")
    try:
        payload = json.loads(result.stdout)
        error = payload.get("error")
        if error in {"pdf_page_too_large", "rendered_pdf_too_large"}:
            raise DocumentError(413, error)
        images = payload["images"]
        if not isinstance(images, list) or not 1 <= len(images) <= MAX_PAGES:
            raise ValueError("Invalid page count")
        if not all(
            isinstance(v, str) and v.startswith("data:image/jpeg;base64,")
            for v in images
        ):
            raise ValueError("Invalid image data")
        return images
    except (KeyError, AttributeError, TypeError, ValueError) as exc:
        if isinstance(exc, DocumentError):
            raise
        raise DocumentError(422, "pdf_render_failed") from exc
