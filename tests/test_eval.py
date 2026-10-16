import base64
import hashlib
import importlib.util
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from groq import Groq

from expense_lens import extraction
from expense_lens.fiscal_qr import find_fiscal_qr
from expense_lens.pdf_render import render_pdf
from expense_lens.receipts import RawReceipt, Receipt
from expense_lens.rules import review_receipt

EVAL = Path(__file__).parents[1] / "eval"


def load_module(name: str):
    spec = importlib.util.spec_from_file_location(f"eval_{name}", EVAL / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


generate_dataset = load_module("generate_dataset")
run_module = load_module("run")
score_module = load_module("score")
MANIFEST = json.loads((EVAL / "dataset/manifest.json").read_text())
CASES = MANIFEST["cases"]
UNTRUSTED = {"conflict", "missing"}


def page_images(entry) -> list[bytes]:
    data = (EVAL / "dataset" / entry["file"]).read_bytes()
    if entry["file"].endswith(".pdf"):
        return [base64.b64decode(url.partition(",")[2]) for url in render_pdf(data)]
    return [data]


# --- dataset ---------------------------------------------------------------


def test_dataset_has_twelve_fictitious_cases_with_valid_truth():
    assert len(CASES) == 12
    assert len({entry["id"] for entry in CASES}) == 12
    for entry in CASES:
        data = (EVAL / "dataset" / entry["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry["sha256"], entry["id"]
        truth = entry["expected"]["receipt"]
        assert Receipt.model_validate(truth).model_dump(mode="json") == truth
        assert set(entry["expected"]["flagged_fields"]) <= set(truth)


def test_generator_reproduces_committed_dataset_byte_for_byte(tmp_path):
    generate_dataset.generate(tmp_path)
    committed = {path.name for path in (EVAL / "dataset").iterdir()}
    assert {path.name for path in tmp_path.iterdir()} == committed
    for name in committed:
        assert (tmp_path / name).read_bytes() == (EVAL / "dataset" / name).read_bytes()


@pytest.mark.parametrize("entry", CASES, ids=[entry["id"] for entry in CASES])
def test_every_case_qr_decodes_as_declared(entry):
    qr, status = find_fiscal_qr(page_images(entry))
    assert status == entry["expected"]["fiscal_qr_status"]
    assert (qr is not None) == (status == "found")
    if qr is not None:
        truth = entry["expected"]["receipt"]
        assert qr.issuer_cuit == truth["issuer_cuit"]
        assert qr.document_type == truth["document_type"]
        same_total = qr.total == Decimal(truth["total"])
        # Solo el caso de contradicción declara un total distinto al visible.
        assert same_total != ("total" in entry["expected"]["flagged_fields"])


def test_multipage_pdf_has_two_pages_and_no_qr():
    entry = next(e for e in CASES if e["id"] == "pdf_texto_multipagina")
    assert len(page_images(entry)) == 2
    assert entry["expected"]["fiscal_qr_status"] == "not_found"


@pytest.mark.parametrize("entry", CASES, ids=[entry["id"] for entry in CASES])
def test_pipeline_flags_exactly_the_declared_fields(entry):
    truth = dict(entry["expected"]["receipt"])
    if entry["id"] == "importe_ambiguo":
        truth["total"] = "1.234"  # lo que transcribiría el modelo
    qr, _ = find_fiscal_qr(page_images(entry))
    result = review_receipt(RawReceipt.model_validate(truth), qr, date(2026, 10, 16))
    untrusted = {f for f, s in result.field_status.items() if s in UNTRUSTED}
    flagged = set(entry["expected"]["flagged_fields"])
    assert flagged <= untrusted
    if entry["id"] != "no_es_comprobante":
        assert untrusted == flagged
    assert result.movement == entry["expected"]["movement"]


# --- runner ----------------------------------------------------------------


def completion(content: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "test",
            "model": extraction.MODEL,
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": json.dumps(content)},
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        },
    )


@pytest.fixture
def provider(monkeypatch):
    """Transporte simulado: el caso n responde con su verdad, o falla con `status`."""
    monkeypatch.setenv("GROQ_API_KEY", "sk-test-SECRET-VALUE")
    calls = []
    state = {"status": 200}

    def handler(request):
        calls.append(request)
        if state["status"] != 200:
            return httpx.Response(
                state["status"], json={"error": {"message": "PRIVATE-ERROR"}}
            )
        return completion(CASES[len(calls) - 1]["expected"]["receipt"])

    monkeypatch.setattr(
        extraction,
        "configured_client",
        lambda: Groq(
            api_key="sk-test-SECRET-VALUE",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )
    return calls, state


def read_attempts(directory: Path) -> list[dict]:
    lines = (directory / "attempts.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def test_runner_requires_explicit_provider_authorization(tmp_path, provider):
    calls, _ = provider
    with pytest.raises(SystemExit):
        run_module.main([str(tmp_path / "out")])
    assert calls == []
    assert not (tmp_path / "out").exists()


def test_runner_makes_one_call_per_case_and_refuses_replay(tmp_path, provider):
    calls, _ = provider
    out = tmp_path / "out"
    run_module.main([str(out), "--allow-provider"])
    attempts = read_attempts(out)
    assert len(calls) == len(attempts) == len(CASES)
    assert [a["case"] for a in attempts] == [e["id"] for e in CASES]
    assert all(a["calls"] == 1 and "result" in a for a in attempts)
    plan = json.loads((out / "plan.json").read_text())
    assert plan["retries"] == 0 and plan["max_calls"] == len(CASES)
    assert (
        plan["prompt_sha256"] == hashlib.sha256(extraction.PROMPT.encode()).hexdigest()
    )
    assert [c["sha256"] for c in plan["cases"]] == [e["sha256"] for e in CASES]
    assert [c["expected"] for c in plan["cases"]] == [e["expected"] for e in CASES]
    with pytest.raises(FileExistsError):
        run_module.main([str(out), "--allow-provider"])
    assert len(calls) == len(CASES)


def test_runner_output_scores_perfectly_when_model_echoes_truth(tmp_path, provider):
    out = tmp_path / "out"
    run_module.main([str(out), "--allow-provider"])
    metrics = score_module.main([str(out)])
    assert metrics["cases_evaluated"] == len(CASES)
    assert metrics["overall_field_accuracy"] == 1.0
    assert metrics["false_verified_count"] == 0
    assert metrics["hallucinated_fields"] == []
    assert (out / "metrics.json").exists() and (out / "report.md").exists()


def test_runner_does_not_retry_errors_nor_leak_secrets(tmp_path, provider):
    calls, state = provider
    state["status"] = 429
    out = tmp_path / "out"
    run_module.main([str(out), "--allow-provider"])
    attempts = read_attempts(out)
    assert len(calls) == len(attempts) == len(CASES)
    assert all(a["http_status"] == 429 and a["calls"] == 1 for a in attempts)
    assert all(a["error"] == "provider_rate_limited" for a in attempts)
    for path in out.iterdir():
        text = path.read_text()
        assert "PRIVATE-ERROR" not in text
        assert "sk-test-SECRET-VALUE" not in text
    metrics = score_module.main([str(out)])
    assert metrics["cases_evaluated"] == 0
    assert metrics["failures_by_kind"] == {"http_429": len(CASES)}
    assert metrics["overall_field_accuracy"] is None


# --- scorer ----------------------------------------------------------------


def expected_case(case_id, receipt, qr="not_found", flagged=()):
    return {
        "id": case_id,
        "expected": {
            "receipt": receipt,
            "fiscal_qr_status": qr,
            "flagged_fields": list(flagged),
            "movement": "expense",
        },
    }


def predicted(receipt, status, qr="not_found", **latency):
    fields = score_module.FIELDS
    return {
        "result": {
            "receipt": {f: receipt.get(f) for f in fields},
            "field_status": {f: status.get(f, "empty") for f in fields},
            "fiscal_qr_status": qr,
        },
        "calls": 1,
        **latency,
    }


@pytest.fixture
def results(tmp_path):
    plan = {
        "model": "test-model",
        "prompt_sha256": "abc",
        "cases": [
            expected_case(
                "a",
                {"issuer": "X", "date": "2026-10-01", "total": "100.00"},
                qr="found",
            ),
            expected_case("b", {"issuer": "Y", "total": "200.00"}, "found", ["total"]),
            expected_case("c", {"issuer": "Z", "total": "300.00"}),
            expected_case("d", {"issuer": "Z"}, flagged=["total"]),
        ],
    }
    attempts = [
        {
            "case": "a",
            **predicted(
                {"issuer": "X", "date": "2026-10-01", "total": "100"},
                {"issuer": "unverified", "date": "verified", "total": "verified"},
                qr="found",
                elapsed_seconds=1.0,
                usage={"prompt_tokens": 100, "completion_tokens": 10},
            ),
        },
        {
            # Total erróneo pero verified (falso verificado) e impuesto inventado.
            "case": "b",
            **predicted(
                {"issuer": "Y", "total": "20.00", "tax": "42.00"},
                {"issuer": "unverified", "total": "verified", "tax": "conflict"},
                qr="found",
                elapsed_seconds=3.0,
                usage={"prompt_tokens": 200, "completion_tokens": 20},
            ),
        },
        {
            "case": "c",
            "error": "provider_rate_limited",
            "status": 503,
            "http_status": 429,
            "calls": 1,
            "elapsed_seconds": 0.5,
        },
        {
            "case": "d",
            **predicted(
                {"issuer": "W"},
                {"issuer": "unverified", "total": "conflict"},
                elapsed_seconds=1.5,
            ),
        },
    ]
    (tmp_path / "plan.json").write_text(json.dumps(plan))
    (tmp_path / "attempts.jsonl").write_text(
        "".join(json.dumps(a) + "\n" for a in attempts)
    )
    return tmp_path


def test_scorer_exact_metric_math(results):
    metrics = score_module.main([str(results)])
    assert (metrics["cases_total"], metrics["cases_evaluated"]) == (4, 3)
    assert metrics["cases_failed"] == 1
    assert metrics["failures_by_kind"] == {"http_429": 1}
    assert metrics["failures"] == [
        {"case": "c", "error": "provider_rate_limited", "http_status": 429}
    ]
    accuracy = metrics["field_accuracy"]
    assert accuracy["issuer"] == accuracy["total"] == accuracy["tax"] == 0.6667
    assert accuracy["date"] == accuracy["letter"] == 1.0
    assert metrics["overall_field_accuracy"] == 0.9  # 27 de 30
    assert metrics["wrong_fields"] == 3
    assert metrics["hallucinated_fields"] == [{"case": "b", "field": "tax"}]
    assert metrics["hallucination_rate"] == 0.0417  # 1 de 24 verdades null
    assert metrics["detection_recall"] == 0.3333  # solo b.tax de 3 erróneos
    assert metrics["false_verified"] == [{"case": "b", "field": "total"}]
    assert metrics["false_verified_count"] == 1
    assert metrics["expected_flag_recall"] == 0.5  # d.total sí, b.total no
    assert metrics["review_rate"] == 0.6667
    assert metrics["fiscal_qr_status_accuracy"] == 1.0
    assert metrics["latency_seconds"] == {
        "attempts": 4,
        "mean": 1.5,
        "median": 1.25,
        "max": 3.0,
    }
    assert metrics["tokens"] == {
        "attempts_with_usage": 2,
        "attempts_without_usage": 2,
        "prompt": 300,
        "completion": 30,
    }


def test_scorer_report_highlights_false_verified_and_is_deterministic(results):
    score_module.main([str(results)])
    first = (results / "metrics.json").read_text(), (results / "report.md").read_text()
    score_module.main([str(results)])
    assert first == (
        (results / "metrics.json").read_text(),
        (results / "report.md").read_text(),
    )
    assert "FALSOS VERIFICADOS: 1" in first[1]
    assert "b.total" in first[1]
    assert "http_429" in first[1]


def test_runner_paces_cases_without_retrying(tmp_path, provider, monkeypatch):
    calls, _ = provider
    sleeps = []
    monkeypatch.setattr(run_module.time, "sleep", sleeps.append)
    out = tmp_path / "out"
    run_module.main([str(out), "--allow-provider", "--pause-seconds", "15"])
    assert sleeps == [15.0] * (len(CASES) - 1)
    assert len(calls) == len(CASES)
    plan = json.loads((out / "plan.json").read_text())
    assert plan["pause_seconds"] == 15.0 and plan["retries"] == 0


def test_runner_rejects_negative_pause(tmp_path, provider):
    calls, _ = provider
    with pytest.raises(SystemExit):
        run_module.main(
            [str(tmp_path / "out"), "--allow-provider", "--pause-seconds", "-1"]
        )
    assert calls == []
