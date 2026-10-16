from fastapi.testclient import TestClient

from expense_lens.main import app


def test_health_returns_service_status():
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"status": "ok", "service": "expense-lens"}
