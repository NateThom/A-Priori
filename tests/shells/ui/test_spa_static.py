"""Tests for bundled frontend SPA assets served by apriori.ui server.

AC traceability:
- AC-1: Opening server URL loads SPA and default graph view shell.
- Technical constraints: assets live under src/apriori/shells/ui/static and are self-contained.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apriori.config import Config
from apriori.shells.ui.server import create_app
from tests.shells.ui.test_api import _TestStore


STATIC_DIR = Path("src/apriori/shells/ui/static")


def test_static_bundle_files_exist() -> None:
    """Bundled frontend assets are present in package static directory."""
    required = [
        "index.html",
        "app.css",
        "app.js",
        "vendor/react.production.min.js",
        "vendor/react-dom.production.min.js",
        "vendor/cytoscape.min.js",
    ]
    for relative_path in required:
        assert (STATIC_DIR / relative_path).is_file(), relative_path


def test_root_serves_spa_index_with_graph_default_shell() -> None:
    """GET / serves bundled SPA and graph view is default visible section."""
    app = create_app(_TestStore(), Config())
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    html = response.text
    assert "<title>A-Priori Human Audit UI</title>" in html
    assert 'id="graph-view"' in html
    assert 'data-default-view="graph"' in html


def test_static_assets_are_served_from_root() -> None:
    """Static JS and CSS are served by FastAPI app without external CDNs."""
    app = create_app(_TestStore(), Config())
    client = TestClient(app)

    css = client.get("/app.css")
    js = client.get("/app.js")

    assert css.status_code == 200
    assert "text/css" in css.headers["content-type"]
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]
