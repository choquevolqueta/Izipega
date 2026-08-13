from fastapi.testclient import TestClient

from server import app

client = TestClient(app)


def test_ping_responde_ok():
    r = client.get("/ping")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "historial_total" in body
    assert "ia_disponible" in body
