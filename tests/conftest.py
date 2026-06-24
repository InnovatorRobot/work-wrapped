"""Shared pytest fixtures.

Sets up an isolated SQLite DB and a safe config BEFORE the app is imported, and
isolates the JSON data directory per test so tests never touch real data.
"""

import os
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

# Isolated DB + safe config must be set before importing config/main.
_TMPDB = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_TMPDB.close()
os.environ["DATABASE_URL"] = "sqlite:///" + _TMPDB.name
os.environ.setdefault("SECRET_KEY", "test-secret-key-aaaaaaaaaaaaaaaaaaaaaaaaaaaa")
os.environ["DEMO_MODE"] = "true"
os.environ["ALLOW_INSECURE_SECRET"] = "true"

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def isolate_storage(tmp_path, monkeypatch):
    """Point JSON storage at a fresh temp dir for each test."""
    import storage

    monkeypatch.setattr(storage, "_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture
def client():
    from starlette.testclient import TestClient
    from main import app

    with TestClient(app) as c:  # entering context runs startup (init_db)
        yield c


@pytest.fixture
def demo_client(client):
    """A client already logged in via demo mode."""
    client.get("/demo", follow_redirects=True)
    return client
