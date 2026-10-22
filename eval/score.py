"""Puntuador determinista y offline de un directorio de resultados de eval/run.py.

Uso: python eval/score.py <results-dir>. Escribe metrics.json y report.md.
Con --replay-rules reaplica las reglas actuales a las transcripciones guardadas
(sin red) y escribe metrics-replay.json y report-replay.md; no toca la corrida.
Un error del proveedor o una salida inválida nunca cuenta como acierto: se informa
aparte y queda fuera de los denominadores de exactitud.
"""

import argparse
import json
import statistics
from collections import Counter
from decimal import Decimal
from pathlib import Path

from expense_lens.receipts import CategorySuggestion, FiscalQr, RawReceipt
from expense_lens.rules import review_receipt

FIELDS = (
    "issuer",
    "issuer_cuit",
    "date",
    "number",
    "document_type",
    "letter",
    "currency",
    "subtotal",
    "tax",
    "total",
)
AMOUNTS = {"subtotal", "tax", "total"}
UNTRUSTED = {"conflict", "missing"}


def same(field: str, expected, predicted) -> bool:
    if expected is None or predicted is None:
        return expected is predicted
    if field in AMOUNTS:
        return Decimal(expected) == Decimal(predicted)
    return expected == predicted


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def load(results: Path) -> tuple[dict, list[dict]]:
    plan = json.loads((results / "plan.json").read_text())
    attempts = [
        json.loads(line)
        for line in (results / "attempts.jsonl").read_text().splitlines()
        if line.strip()
    ]
    return plan, attempts


def score(plan: dict, attempts: list[dict]) -> dict:
    expected_by_case = {case["id"]: case["expected"] for case in plan["cases"]}
    by_case = {attempt["case"]: attempt for attempt in attempts}
    correct = Counter()
    evaluated_cases = []
    hallucinated = []
    truth_null = 0
    wrong = []
    detected = 0
    false_verified = []
    expected_flags = detected_flags = 0
    review_cases = 0
    qr_status_correct = 0
    failures = []
    category_cases = category_model = category_rules = 0
    for case_id, expected in expected_by_case.items():
        attempt = by_case.get(case_id)
        if attempt is None or "result" not in attempt:
            failures.append(
                {
                    "case": case_id,
                    "error": attempt.get("error") if attempt else "not_run",
                    "http_status": attempt.get("http_status") if attempt else None,
                }
            )
            continue
        evaluated_cases.append(case_id)
        result = attempt["result"]
        status = result["field_status"]
        for field in FIELDS:
            truth = expected["receipt"].get(field)
            predicted = result["receipt"].get(field)
            truth_null += truth is None
            if same(field, truth, predicted):
                correct[field] += 1
                continue
            wrong.append({"case": case_id, "field": field})
            if truth is None:
                hallucinated.append({"case": case_id, "field": field})
            if status[field] in UNTRUSTED:
                detected += 1
            if status[field] == "verified":
                false_verified.append({"case": case_id, "field": field})
        for field in expected["flagged_fields"]:
            expected_flags += 1
            detected_flags += status[field] in UNTRUSTED
        review_cases += any(value in UNTRUSTED for value in status.values())
        suggestion = result.get("category_suggestion")
        if "category" in expected and suggestion is not None:
            # Mismos casos para ambas fuentes; null esperado exige null predicho.
            category_cases += 1
            category_model += suggestion["model"] == expected["category"]
            category_rules += suggestion["rules"] == expected["category"]
        qr_status_correct += result["fiscal_qr_status"] == expected["fiscal_qr_status"]
    count = len(evaluated_cases)
    latencies = [a["elapsed_seconds"] for a in attempts if "elapsed_seconds" in a]
    usages = [a["usage"] for a in attempts if a.get("usage")]
    errors = Counter(
        f"http_{f['http_status']}" if f["http_status"] else f["error"] for f in failures
    )
    return {
        "model": plan.get("model"),
        "prompt_sha256": plan.get("prompt_sha256"),
        "cases_total": len(expected_by_case),
        "cases_evaluated": count,
        "cases_failed": len(failures),
        "failures": failures,
        "failures_by_kind": dict(sorted(errors.items())),
        "field_accuracy": {field: ratio(correct[field], count) for field in FIELDS},
        "overall_field_accuracy": ratio(sum(correct.values()), count * len(FIELDS)),
        "wrong_fields": len(wrong),
        "hallucinated_fields": hallucinated,
        "hallucination_rate": ratio(len(hallucinated), truth_null),
        "detection_recall": ratio(detected, len(wrong)),
        "false_verified": false_verified,
        "false_verified_count": len(false_verified),
        "expected_flag_recall": ratio(detected_flags, expected_flags),
        "review_rate": ratio(review_cases, count),
        "fiscal_qr_status_accuracy": ratio(qr_status_correct, count),
        "category_accuracy": {
            "cases": category_cases,
            "model": ratio(category_model, category_cases),
            "rules": ratio(category_rules, category_cases),
        },
        "latency_seconds": {
            "attempts": len(latencies),
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "median": round(statistics.median(latencies), 3) if latencies else None,
            "max": max(latencies) if latencies else None,
        },
        "tokens": {
            "attempts_with_usage": len(usages),
            "attempts_without_usage": len(attempts) - len(usages),
            "prompt": sum(u.get("prompt_tokens") or 0 for u in usages),
            "completion": sum(u.get("completion_tokens") or 0 for u in usages),
        },
    }


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def report(metrics: dict) -> str:
    lines = ["# Reporte de evaluación", ""]
    lines.append(f"Modelo: `{metrics['model']}`. Dataset sintético ficticio.")
    lines.append("")
    if metrics["false_verified_count"]:
        lines.append(
            f"> **⚠ FALSOS VERIFICADOS: {metrics['false_verified_count']}** — "
            "campos con estado `verified` pero erróneos: "
            + ", ".join(f"{f['case']}.{f['field']}" for f in metrics["false_verified"])
        )
    else:
        lines.append("> Falsos verificados: 0")
    lines += [
        "",
        f"- Casos evaluados: {metrics['cases_evaluated']} de {metrics['cases_total']}",
        f"- Fallos del proveedor o salida inválida (no cuentan como acierto): "
        f"{metrics['cases_failed']} {metrics['failures_by_kind']}",
        f"- Exactitud global por campo: {percent(metrics['overall_field_accuracy'])}",
        f"- Campos inventados: {len(metrics['hallucinated_fields'])} "
        f"(tasa {percent(metrics['hallucination_rate'])})",
        f"- Recall de detección (erróneos en conflict/missing): "
        f"{percent(metrics['detection_recall'])} de {metrics['wrong_fields']}",
        f"- Recall de campos marcados esperados: "
        f"{percent(metrics['expected_flag_recall'])}",
        f"- Tasa de revisión (casos con campo no confiable): "
        f"{percent(metrics['review_rate'])}",
        f"- Estado del QR fiscal correcto: "
        f"{percent(metrics['fiscal_qr_status_accuracy'])}",
        f"- Exactitud de categoría: modelo "
        f"{percent(metrics['category_accuracy']['model'])}, reglas "
        f"{percent(metrics['category_accuracy']['rules'])} "
        f"({metrics['category_accuracy']['cases']} casos)",
        f"- Latencia (s): media {metrics['latency_seconds']['mean']}, "
        f"mediana {metrics['latency_seconds']['median']}, "
        f"máx {metrics['latency_seconds']['max']}",
        f"- Tokens: {metrics['tokens']['prompt']} de entrada y "
        f"{metrics['tokens']['completion']} de salida "
        f"({metrics['tokens']['attempts_without_usage']} intentos sin uso informado)",
        "",
        "| Campo | Exactitud |",
        "|---|---|",
    ]
    lines += [
        f"| {field} | {percent(value)} |"
        for field, value in metrics["field_accuracy"].items()
    ]
    lines += [
        "",
        "Muestra pequeña y sintética: no es una estimación para facturas reales.",
        "",
    ]
    return "\n".join(lines)


def replay_rules(attempts: list[dict]) -> list[dict]:
    """Reaplica normalización y reglas actuales; los valores canónicos no cambian."""
    replayed = []
    for attempt in attempts:
        if "result" not in attempt:
            replayed.append(attempt)
            continue
        old = attempt["result"]
        # Preferir la transcripción cruda: el resultado guardado ya perdió los
        # valores que las reglas viejas dejaron en null (como "1.234").
        source = attempt.get("model_output") or old["receipt"]
        raw = RawReceipt.model_validate(
            {
                k: None if source.get(k) is None else str(source[k])
                for k in RawReceipt.model_fields
            }
        )
        qr = FiscalQr.model_validate(old["fiscal_qr"]) if old["fiscal_qr"] else None
        result = review_receipt(raw, qr)
        result.fiscal_qr_status = old["fiscal_qr_status"]
        stored = old.get("category_suggestion")
        if stored is None:
            result.category_suggestion = None  # corrida anterior a la categoría
        else:
            # El modelo ya respondió; solo las reglas se reaplican.
            assert result.category_suggestion is not None
            result.category_suggestion = CategorySuggestion.of(
                stored["model"], result.category_suggestion.rules
            )
        replayed.append({**attempt, "result": result.model_dump(mode="json")})
    return replayed


def main(argv: list[str] | None = None) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--replay-rules", action="store_true")
    args = parser.parse_args(argv)
    plan, attempts = load(args.results)
    suffix = ""
    if args.replay_rules:
        attempts, suffix = replay_rules(attempts), "-replay"
    metrics = score(plan, attempts)
    (args.results / f"metrics{suffix}.json").write_text(
        json.dumps(metrics, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    )
    text = report(metrics)
    if args.replay_rules:
        text = text.replace(
            "\n\n",
            "\n\nReglas reaplicadas offline sobre las transcripciones guardadas;"
            " el modelo no se volvió a llamar.\n\n",
            1,
        )
    (args.results / f"report{suffix}.md").write_text(text)
    return metrics


if __name__ == "__main__":
    main()
