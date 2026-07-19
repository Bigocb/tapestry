"""Tests for OpenWiki wiki viewer routes.

Covers:
- Index page renders HTML listing both brains
- Code brain index lists pages
- Personal brain index handles missing root gracefully
- Raw Markdown page retrieval
- HTML preview format
- Path traversal and invalid paths are rejected
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    """FastAPI test client."""
    return TestClient(app)


def test_wiki_index_renders(client):
    """Wiki index page lists both code and personal brains."""
    response = client.get("/api/wiki")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Code Brain" in response.text
    assert "Personal Brain" in response.text


def test_wiki_code_brain_index(client):
    """Code brain index lists pages from the repo openwiki directory."""
    response = client.get("/api/wiki/code")
    assert response.status_code == 200
    assert "quickstart.md" in response.text
    assert "index.md" in response.text


def test_wiki_personal_brain_index_no_crash(client):
    """Personal brain index returns HTML even if wiki root is empty/missing."""
    response = client.get("/api/wiki/personal")
    assert response.status_code == 200
    assert "Personal Brain" in response.text


def test_wiki_page_markdown(client):
    """Wiki page endpoint returns raw Markdown."""
    response = client.get("/api/wiki/code/pages/quickstart.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "MEMIND Quickstart" in response.text


def test_wiki_page_html_format(client):
    """Wiki page endpoint can render HTML preview."""
    response = client.get("/api/wiki/code/pages/quickstart.md?format=html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "MEMIND Quickstart" in response.text


def test_wiki_page_not_found(client):
    """Missing page returns 404."""
    response = client.get("/api/wiki/code/pages/does-not-exist.md")
    assert response.status_code == 404


def test_wiki_page_traversal_rejected(client):
    """Path traversal attempts are rejected by the route."""
    # Note: HTTP clients typically collapse ".." before sending, so we use a
    # direct unit test below to verify the resolver itself rejects traversal.
    response = client.get("/api/wiki/code/pages/%2E%2E/README.md")
    assert response.status_code in (400, 404)


def test_resolve_page_rejects_traversal():
    """Internal resolver rejects traversal in the path string."""
    from app.routes.wiki import _resolve_page
    from fastapi import HTTPException
    from pathlib import Path

    root = Path("C:/fake/wiki")
    with pytest.raises(HTTPException) as exc_info:
        _resolve_page(root, "../README.md")
    assert exc_info.value.status_code == 400


def test_wiki_unknown_brain(client):
    """Unknown brain returns 400."""
    response = client.get("/api/wiki/unknown")
    assert response.status_code == 400
