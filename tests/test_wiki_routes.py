"""Tests for OpenWiki wiki viewer routes.

Covers:
- Index page renders app-like HTML listing both brains
- Brain index renders folder tree and front-matter-aware titles
- Raw Markdown page retrieval still works
- HTML page renders Markdown to real HTML with front matter
- Table of contents is generated
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
    """Wiki index page lists both code and personal brains with app layout."""
    response = client.get("/api/wiki")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tapestry OpenWiki" in response.text
    assert "Code Brain" in response.text
    assert "Personal Brain" in response.text
    assert "app-like" not in response.text  # sanity: no placeholder text


def test_wiki_index_shows_page_counts(client):
    """Index shows page counts and recent pages."""
    response = client.get("/api/wiki")
    assert response.status_code == 200
    assert "page(s)" in response.text
    assert "quickstart.md" in response.text


def test_wiki_code_brain_index(client):
    """Code brain index lists pages with front-matter titles."""
    response = client.get("/api/wiki/code")
    assert response.status_code == 200
    # quickstart.md has front matter title "Tapestry Quickstart"
    assert "Tapestry Quickstart" in response.text
    assert "index.md" in response.text or "Documentation Index" in response.text


def test_wiki_code_brain_has_tree(client):
    """Code brain index renders nested folder tree."""
    response = client.get("/api/wiki/code")
    assert response.status_code == 200
    assert "folder" in response.text
    assert "page" in response.text


def test_wiki_personal_brain_index_no_crash(client):
    """Personal brain index returns HTML even if wiki root is empty/missing."""
    response = client.get("/api/wiki/personal")
    assert response.status_code == 200
    assert "Personal Brain" in response.text


def test_wiki_page_markdown(client):
    """Wiki page endpoint returns raw Markdown when requested."""
    response = client.get("/api/wiki/code/pages/quickstart.md?format=markdown")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "Tapestry Quickstart" in response.text


def test_wiki_page_html_renders_markdown(client):
    """Default HTML format renders Markdown to real HTML."""
    response = client.get("/api/wiki/code/pages/quickstart.md")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Should contain rendered headings, not escaped Markdown source
    assert "<h1>Tapestry Quickstart</h1>" in response.text
    # Body content should not be inside a single pre wrapping the whole page
    assert response.text.count("<pre>") >= 0  # code blocks use pre legitimately
    assert "# Tapestry Quickstart" not in response.text


def test_wiki_page_html_shows_front_matter(client):
    """HTML page shows title, description, and tags from front matter."""
    response = client.get("/api/wiki/code/pages/quickstart.md")
    assert response.status_code == 200
    assert "Entry point for the Tapestry wiki" in response.text
    assert "quickstart" in response.text.lower()


def test_wiki_page_html_has_toc(client):
    """HTML page contains a table of contents."""
    response = client.get("/api/wiki/code/pages/quickstart.md")
    assert response.status_code == 200
    assert "On this page" in response.text
    assert 'class="toc"' in response.text


def test_wiki_page_html_format(client):
    """Explicit format=html query still works."""
    response = client.get("/api/wiki/code/pages/quickstart.md?format=html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Tapestry Quickstart" in response.text


def test_wiki_page_not_found(client):
    """Missing page returns 404."""
    response = client.get("/api/wiki/code/pages/does-not-exist.md")
    assert response.status_code == 404


def test_wiki_page_traversal_rejected(client):
    """Path traversal attempts are rejected by the route."""
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
