"""Firmas de QR fiscales ligadas a un secreto conocido solo por el servidor."""

import hashlib
import hmac
import json
import os
import secrets

from expense_lens.receipts import FiscalQr

_secret: bytes | None = None


def _get_secret() -> bytes:
    global _secret
    if _secret is None:
        configured = os.environ.get("EXPENSE_LENS_SECRET", "")
        _secret = configured.encode("utf-8") if configured else secrets.token_bytes(32)
    return _secret


def sign_qr(qr: FiscalQr) -> str:
    canonical = json.dumps(
        qr.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(_get_secret(), canonical, hashlib.sha256).hexdigest()


def verify_qr(qr: FiscalQr, signature: str | None) -> bool:
    if not isinstance(signature, str):
        return False
    # Bytes, no texto: compare_digest lanza TypeError con texto no ASCII.
    return hmac.compare_digest(sign_qr(qr).encode(), signature.encode())
