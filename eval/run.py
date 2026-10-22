"""Corrida real acotada sobre el dataset sintético: una llamada por caso.

Requiere --allow-provider (envía imágenes ficticias a Groq), no reintenta y nunca
reutiliza un directorio de salida. --pause-seconds espacia los casos sin
reintentar. Puntuar con eval/score.py, sin red.
"""

import argparse
import hashlib
import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

from groq import APIStatusError

from expense_lens import extraction
from expense_lens.documents import DocumentError

DATASET = Path(__file__).resolve().parent / "dataset"


def build_plan(manifest: dict, dataset: Path) -> dict:
    cases = []
    for entry in manifest["cases"]:
        digest = hashlib.sha256((dataset / entry["file"]).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            raise ValueError(f"dataset_hash_mismatch: {entry['id']}")
        cases.append(
            {
                "id": entry["id"],
                "file": entry["file"],
                "sha256": digest,
                "expected": entry["expected"],
            }
        )
    return {
        "model": extraction.MODEL,
        "max_calls": len(cases),
        "retries": 0,
        "prompt_sha256": hashlib.sha256(extraction.PROMPT.encode()).hexdigest(),
        "cases": cases,
        "limits": "Dataset sintetico pequeno; no mide generalizacion.",
    }


def run(output: Path, dataset: Path = DATASET, pause_seconds: float = 0.0) -> None:
    manifest = json.loads((dataset / "manifest.json").read_text())
    plan = build_plan(manifest, dataset)
    plan["pause_seconds"] = pause_seconds
    output.mkdir(parents=True, exist_ok=False)
    original_factory = extraction.configured_client
    (output / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
    with (output / "attempts.jsonl").open("x") as attempts:
        for index, case in enumerate(plan["cases"]):
            if index and pause_seconds:
                # Espacia llamadas para respetar el límite por minuto; no reintenta.
                time.sleep(pause_seconds)
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
                        try:
                            # Transcripción cruda: permite re-medir reglas nuevas.
                            output = json.loads(completion.choices[0].message.content)
                        except (IndexError, TypeError, ValueError):
                            output = None
                        captured.update(
                            model_output=output if isinstance(output, dict) else None,
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
            record: dict[str, Any] = {"case": case["id"]}
            try:
                with patch.object(extraction, "configured_client", factory):
                    result = extraction.extract_document_receipt(
                        (dataset / case["file"]).read_bytes()
                    )
                record["result"] = result.model_dump(mode="json")
            except (extraction.ExtractionError, DocumentError) as exc:
                record.update(error=exc.detail, status=exc.status_code)
            except Exception as exc:
                # Solo el tipo: el mensaje podría contener datos del proveedor.
                record.update(error=type(exc).__name__, status=None)
            finally:
                record.update(
                    captured,
                    calls=len(calls),
                    elapsed_seconds=round(time.monotonic() - started, 3),
                )
                attempts.write(json.dumps(record) + "\n")
                attempts.flush()
            print(case["id"], "ok" if "result" in record else record["error"])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-provider", action="store_true", required=True)
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0.0,
        help="Pausa entre casos para no exceder el límite del proveedor.",
    )
    args = parser.parse_args(argv)
    if args.pause_seconds < 0:
        parser.error("--pause-seconds no puede ser negativo")
    run(args.output, pause_seconds=args.pause_seconds)


if __name__ == "__main__":
    main()
