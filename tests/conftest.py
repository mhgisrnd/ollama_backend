import pytest


@pytest.fixture(autouse=True)
def isolated_registry(tmp_path, monkeypatch):
    """Never write test registrations into the user's local registry."""
    monkeypatch.setenv("LLM_SERVER_REGISTRY_DATABASE_PATH", str(tmp_path / "registry.sqlite3"))
