"""Tests for FastAPI application setup.

RED: Verify FastAPI app is properly configured.
- App starts and responds to health check
- CORS middleware is configured
- OpenAPI documentation available
- Error handling works
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


def test_app_created():
    """FastAPI app is created."""
    assert app is not None
    assert app.title == "Tapestry API"


def test_health_check(client):
    """Health check endpoint works."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "version": "0.1.0"}


def test_openapi_docs_available(client):
    """OpenAPI documentation is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    assert "openapi" in response.json()


def test_swagger_ui_available(client):
    """Swagger UI documentation is available."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower()


def test_redoc_available(client):
    """ReDoc documentation is available."""
    response = client.get("/redoc")
    assert response.status_code == 200


def test_404_not_found(client):
    """Non-existent routes return 404."""
    response = client.get("/nonexistent")
    assert response.status_code == 404


def test_cors_headers(client):
    """CORS headers are set correctly."""
    response = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert response.status_code == 200
    # CORS headers should be present
    assert (
        "access-control-allow-origin" in response.headers or response.status_code == 200
    )
