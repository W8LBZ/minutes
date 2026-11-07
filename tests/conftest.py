import os
import tempfile
from pathlib import Path

# Importing the web app opens an archive and a login database; keep both away from real data.
os.environ["W8LBZ_DATA"] = tempfile.mkdtemp(prefix="w8lbz-test-")
os.environ["W8LBZ_CONFIG"] = str(Path(__file__).parent / "fixtures" / "test-club.yaml")

import pytest


@pytest.fixture(autouse=True)
def fresh_business(tmp_path, monkeypatch):
    """Each test starts with no tracked business items (business.json would otherwise be shared)."""
    from w8lbz_minutes import business
    d = tmp_path / "business-data"
    d.mkdir()
    monkeypatch.setattr(business, "DATA", d)


@pytest.fixture(autouse=True)
def no_update_check(monkeypatch):
    """Pages for admins in admin mode check GitHub for a new release; never from the tests."""
    from w8lbz_minutes import updates
    monkeypatch.setattr(updates, "latest", lambda *a, **k: None)
