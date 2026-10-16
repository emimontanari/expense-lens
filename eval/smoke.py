"""Captura manual acotada: cuatro formatos del mismo recibo, no un benchmark."""

import argparse
import hashlib
import json
import time
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

from groq import APIStatusError

from expense_lens import extraction
from expense_lens.documents import DocumentError

ROOT = Path(__file__).resolve().parents[1]
FILES = ("receipt.png", "receipt.jpg", "receipt-text.pdf", "receipt-scanned.pdf")
EXPECTED = {
    "issuer": "Comercio ficticio",
    "date": "2026-10-15",
    "number": "0001-00000001",
    "currency": "ARS",
    "subtotal": "100.00",
    "tax": "21.00",
    "total": "121.00",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-provider", action="store_true", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    original_factory = extraction.configured_client
    plan = {
        "model": extraction.MODEL,
        "max_calls": 4,
        "retries": 0,
        "prompt_sha256": hashlib.sha256(extraction.PROMPT.encode()).hexdigest(),
        "inputs": {
            name: hashlib.sha256(
                (ROOT / "examples/synthetic" / name).read_bytes()
            ).hexdigest()
            for name in FILES
        },
        "expected": EXPECTED,
        "limits": "Mismo recibo en cuatro formatos; no mide generalización.",
    }
    (args.output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    with (args.output / "attempts.jsonl").open("x") as output:
        for name in FILES:
            captured: dict[str, Any] = {}
            calls = []

            @contextmanager
            def factory():
                with original_factory() as client:
                    create = client.chat.completions.create

                    def capture(**kwargs):
                        calls.append(1)
                        try:
                            completion = create(**kwargs)
                        except APIStatusError as exc:
                            captured["http_status"] = exc.status_code
                            raise
                        captured.update(
                            model=completion.model,
                            response_id=completion.id,
                            usage=completion.usage.model_dump()
                            if completion.usage
                            else None,
                        )
                        return completion

                    with patch.object(client.chat.completions, "create", capture):
                        yield client

            started = time.monotonic()
            record: dict[str, Any] = {"file": name}
            try:
                with patch.object(extraction, "configured_client", factory):
                    result = extraction.extract_document_receipt(
                        (ROOT / "examples/synthetic" / name).read_bytes()
                    )
                receipt = result.receipt.model_dump(mode="json")
                matches = {
                    field: (
                        Decimal(receipt[field]) == Decimal(expected)
                        if field in {"subtotal", "tax", "total"}
                        and receipt[field] is not None
                        else receipt[field] == expected
                    )
                    for field, expected in EXPECTED.items()
                }
                record.update(
                    result=result.model_dump(mode="json"), field_matches=matches
                )
            except (extraction.ExtractionError, DocumentError) as exc:
                record.update(error=exc.detail, status=exc.status_code)
            finally:
                record.update(
                    captured,
                    calls=len(calls),
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                output.write(json.dumps(record) + "\n")
                output.flush()
            print(
                name,
                "ok" if "result" in record else record.get("error", "unexpected_error"),
                flush=True,
            )


if __name__ == "__main__":
    main()
