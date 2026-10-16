import json
import runpy
import sys
from pathlib import Path

import httpx
import pytest
from groq import Groq

from expense_lens import extraction


@pytest.mark.parametrize("status", [200, 429])
def test_capture_is_bounded_and_refuses_replay(tmp_path, monkeypatch, status):
    script = runpy.run_path(str(Path(__file__).parents[1] / "eval/smoke.py"))
    calls = []

    def handler(request):
        calls.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"message": "PRIVATE-ERROR"}})
        return httpx.Response(
            200,
            json={
                "id": "test",
                "model": extraction.MODEL,
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(script["EXPECTED"]),
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr(
        extraction,
        "configured_client",
        lambda: Groq(
            api_key="test-not-real",
            max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        ),
    )
    destination = tmp_path / "capture"
    monkeypatch.setattr(sys, "argv", ["smoke", str(destination), "--allow-provider"])
    script["main"]()
    records = [
        json.loads(line)
        for line in (destination / "attempts.jsonl").read_text().splitlines()
    ]
    assert len(records) == len(calls) == 4
    assert all(record["calls"] == 1 for record in records)
    assert "PRIVATE-ERROR" not in (destination / "attempts.jsonl").read_text()
    if status == 200:
        assert all(all(record["field_matches"].values()) for record in records)
    else:
        assert all(record["http_status"] == 429 for record in records)
    with pytest.raises(FileExistsError):
        script["main"]()
    assert len(calls) == 4
