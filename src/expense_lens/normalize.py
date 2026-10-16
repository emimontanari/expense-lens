"""Normalización determinista de valores transcritos de comprobantes argentinos.

El modelo transcribe lo que ve; este módulo convierte a formatos canónicos.
Ante ambigüedad devuelve None y un código de advertencia: nunca adivina.
"""

import re
from datetime import date

CURRENCY_TOKENS = re.compile(r"US\$|U\$S|U\$D|USD|AR\$|\$AR|ARS|EUR|€|\$", re.I)
MAX_INTEGER_DIGITS = 10
CUIT_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)

ARS = {"ARS", "PES", "PESO", "PESOS", "AR$", "$AR"}
USD = {"USD", "US$", "U$S", "U$D", "DOL", "DOLAR", "DOLARES", "DÓLAR", "DÓLARES"}
EUR = {"EUR", "€", "EURO", "EUROS", "060"}


def _grouped(value: str, thousands: str) -> str | None:
    """Devuelve los dígitos si el agrupamiento de miles es válido."""
    sep = re.escape(thousands)
    if re.fullmatch(rf"\d{{1,3}}({sep}\d{{3}})+", value) is None:
        return None
    return value.replace(thousands, "")


def normalize_amount(raw: str | None) -> tuple[str | None, str | None]:
    """Convierte "1.234,56" o "1,234.56" a "1234.56". El signo lo da el tipo."""
    if raw is None or not raw.strip():
        return None, None
    value = CURRENCY_TOKENS.sub("", raw).replace(" ", "").strip()
    if value.startswith("(") and value.endswith(")"):
        value = value[1:-1]
    value = value.removeprefix("-")
    integer, decimals = None, ""
    if re.fullmatch(r"\d+", value):
        integer = value
    elif "." in value and "," in value:
        decimal_sep = "." if value.rfind(".") > value.rfind(",") else ","
        thousands = "," if decimal_sep == "." else "."
        head, _, tail = value.rpartition(decimal_sep)
        if re.fullmatch(r"\d{1,2}", tail):
            integer, decimals = _grouped(head, thousands), tail
    else:
        sep = "," if "," in value else "."
        if re.fullmatch(rf"\d+{re.escape(sep)}\d{{1,2}}", value):
            integer, _, decimals = value.partition(sep)
        elif re.fullmatch(rf"\d{{1,3}}{re.escape(sep)}\d{{3}}", value):
            # "1.234" puede ser mil doscientos o uno con decimales: no se adivina.
            return None, "ambiguous_amount"
        else:
            integer = _grouped(value, sep)
    if integer is None or len(integer.lstrip("0") or "0") > MAX_INTEGER_DIGITS:
        return None, "unparseable_amount"
    return integer + (f".{decimals}" if decimals else ""), None


def normalize_date(raw: str | None) -> tuple[date | None, str | None]:
    """Acepta ISO y el formato argentino día/mes/año."""
    if raw is None or not raw.strip():
        return None, None
    value = raw.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            return date.fromisoformat(value), None
        match = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", value)
        if match:
            day, month, year = (int(part) for part in match.groups())
            return date(year, month, day), None
    except ValueError:
        pass
    return None, "invalid_date"


def normalize_currency(raw: str | None) -> tuple[str | None, str | None]:
    """Identifica la moneda emitida; nunca convierte importes entre monedas."""
    if raw is None or not raw.strip():
        return None, None
    value = raw.strip().upper()
    if value == "$":
        # En Argentina "$" es pesos, pero se informa que fue una inferencia.
        return "ARS", "currency_inferred_from_symbol"
    for code, aliases in (("ARS", ARS), ("USD", USD), ("EUR", EUR)):
        if value in aliases:
            return code, None
    return None, "unknown_currency"


def cuit_is_valid(digits: str) -> bool:
    """Dígito verificador módulo 11 con los pesos oficiales."""
    if re.fullmatch(r"\d{11}", digits) is None:
        return False
    total = sum(int(d) * w for d, w in zip(digits[:10], CUIT_WEIGHTS, strict=True))
    check = 11 - total % 11
    check = 0 if check == 11 else check
    return check != 10 and check == int(digits[10])


def normalize_cuit(raw: str | None) -> tuple[str | None, str | None]:
    if raw is None or not raw.strip():
        return None, None
    digits = re.sub(r"[\s.-]", "", raw)
    if not cuit_is_valid(digits):
        return None, "invalid_cuit"
    return digits, None
