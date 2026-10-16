"""QR fiscal ARCA (ex AFIP) de facturas electrónicas, leído localmente.

Especificación: https://www.arca.gob.ar/fe/qr/documentos/QRespecificaciones.pdf
El QR codifica {URL}?p={JSON en Base64}. Es una segunda fuente estructurada para
contrastar lo que transcribió el modelo; no reemplaza la lectura del documento.
El contenido del QR también es dato no confiable: se valida igual que el resto.
"""

import base64
import binascii
import json
import re
from decimal import Decimal
from io import BytesIO
from typing import Literal
from urllib.parse import parse_qs, urlsplit

import zxingcpp
from PIL import Image
from pydantic import ValidationError

from expense_lens.normalize import cuit_is_valid
from expense_lens.receipts import FieldName, FiscalQr, Receipt

MAX_QR_TEXT = 2048
HOSTS = {"afip.gob.ar", "www.afip.gob.ar", "arca.gob.ar", "www.arca.gob.ar"}
CURRENCIES = {"PES": "ARS", "DOL": "USD", "060": "EUR"}
AUTHORIZATIONS = {"E": "CAE", "A": "CAEA"}
# Tablas del sistema ARCA: código de comprobante → (tipo, letra).
RECEIPT_TYPES = {
    1: ("factura", "A"),
    2: ("nota_debito", "A"),
    3: ("nota_credito", "A"),
    6: ("factura", "B"),
    7: ("nota_debito", "B"),
    8: ("nota_credito", "B"),
    11: ("factura", "C"),
    12: ("nota_debito", "C"),
    13: ("nota_credito", "C"),
    19: ("factura", "E"),
    20: ("nota_debito", "E"),
    21: ("nota_credito", "E"),
    51: ("factura", "M"),
    52: ("nota_debito", "M"),
    53: ("nota_credito", "M"),
    # Factura de Crédito Electrónica MiPyMEs.
    201: ("factura", "A"),
    202: ("nota_debito", "A"),
    203: ("nota_credito", "A"),
    206: ("factura", "B"),
    207: ("nota_debito", "B"),
    208: ("nota_credito", "B"),
    211: ("factura", "C"),
    212: ("nota_debito", "C"),
    213: ("nota_credito", "C"),
}
QrStatus = Literal["found", "not_found", "invalid"]


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Expected integer")
    return value


def _decimal(value: object) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, int | Decimal):
        raise ValueError("Expected number")
    return Decimal(value)


def parse_fiscal_qr(text: str) -> FiscalQr | None:
    """Devuelve el QR normalizado o None si no es un QR fiscal válido."""
    if len(text) > MAX_QR_TEXT:
        return None
    try:
        url = urlsplit(text.strip())
        if url.scheme != "https" or url.hostname not in HOSTS:
            return None
        if url.path.rstrip("/") != "/fe/qr":
            return None
        payload = parse_qs(url.query).get("p", [""])[0]
        payload += "=" * (-len(payload) % 4)
        decoded = base64.b64decode(payload, altchars=b"-_", validate=True)
        data = json.loads(decoded, parse_float=Decimal)
        if not isinstance(data, dict) or data.get("ver") != 1:
            return None
        cuit = str(_integer(data["cuit"]))
        if not cuit_is_valid(cuit):
            return None
        code = _integer(data["tipoCmp"])
        document_type, letter = RECEIPT_TYPES.get(code, (None, None))
        total = _decimal(data["importe"])
        if total < 0 or total != total.quantize(Decimal("0.01")):
            return None
        return FiscalQr.model_validate(
            {
                "issuer_cuit": cuit,
                "date": data["fecha"],
                "point_of_sale": _integer(data["ptoVta"]),
                "number": _integer(data["nroCmp"]),
                "receipt_type_code": code,
                "document_type": document_type,
                "letter": letter,
                "total": str(total),
                "currency": CURRENCIES.get(data["moneda"]),
                "exchange_rate": str(_decimal(data["ctz"])),
                "authorization_type": AUTHORIZATIONS[data["tipoCodAut"]],
                "authorization_code": str(_integer(data["codAut"])),
            }
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        binascii.Error,
        UnicodeDecodeError,
        ValidationError,
    ):
        return None


def find_fiscal_qr(images: list[bytes]) -> tuple[FiscalQr | None, QrStatus]:
    """Busca un QR fiscal en imágenes ya inspeccionadas; no envía nada afuera."""
    seen = False
    for data in images:
        with Image.open(BytesIO(data), formats=["PNG", "JPEG"]) as image:
            barcodes = zxingcpp.read_barcodes(
                image.convert("L"), formats=zxingcpp.BarcodeFormat.QRCode
            )
        for barcode in barcodes:
            seen = True
            qr = parse_fiscal_qr(barcode.text)
            if qr is not None:
                return qr, "found"
    return None, "invalid" if seen else "not_found"


def _number_parts(number: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"\D*(\d{1,5})\s*-\s*(\d{1,8})\D*", number)
    return (int(match[1]), int(match[2])) if match else None


def compare_with_qr(
    receipt: Receipt, qr: FiscalQr
) -> tuple[list[FieldName], set[FieldName]]:
    """Campos en conflicto y campos confirmados. Los vacíos no se completan."""
    expected: dict[FieldName, object] = {
        "issuer_cuit": qr.issuer_cuit,
        "date": qr.date,
        "total": qr.total,
        "currency": qr.currency,
        "document_type": qr.document_type,
        "letter": qr.letter,
    }
    actual: dict[FieldName, object] = {
        field: getattr(receipt, field) for field in expected
    }
    expected["number"] = (qr.point_of_sale, qr.number)
    actual["number"] = receipt.number and _number_parts(receipt.number)
    mismatches: list[FieldName] = []
    verified: set[FieldName] = set()
    for field, value in expected.items():
        if value is None or actual[field] is None:
            continue
        if actual[field] == value:
            verified.add(field)
        else:
            mismatches.append(field)
    return mismatches, verified
