from fastapi import FastAPI
from fastapi.testclient import TestClient

from banorte_agent.api.auth import require_bearer


def test_optional_bearer_allows_request_when_key_missing():
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = require_bearer(None)):
        return {"ok": True}

    assert TestClient(app).get("/protected").status_code == 200


def test_bearer_rejects_wrong_key():
    app = FastAPI()

    @app.get("/protected")
    def protected(_: None = require_bearer("secret")):
        return {"ok": True}

    response = TestClient(app).get("/protected", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401
