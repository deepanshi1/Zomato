from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.main import cors_origins

FRONTEND = "https://zomatoreco.vercel.app"


def test_cors_origins_parses_comma_list(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", f" {FRONTEND}/ , http://localhost:3000,, ")
    assert cors_origins() == [FRONTEND, "http://localhost:3000"]


def test_cors_origins_empty_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert cors_origins() == []


def test_preflight_allows_only_configured_origin(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", FRONTEND)
    app = FastAPI()
    app.add_middleware(CORSMiddleware, allow_origins=cors_origins(),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.post("/recommendations")
    def recommendations():
        return {}

    client = TestClient(app)
    headers = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    ok = client.options("/recommendations", headers={"Origin": FRONTEND, **headers})
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == FRONTEND
    denied = client.options("/recommendations", headers={"Origin": "https://evil.example", **headers})
    assert "access-control-allow-origin" not in denied.headers
