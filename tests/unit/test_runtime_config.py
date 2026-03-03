"""Tests for runtime configuration wiring."""

from core.storage.database import create_database

from apps.worker.main import Worker


def test_create_database_uses_explicit_url_over_env(monkeypatch):
    """Explicit URL argument should take precedence over environment."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./env.db")

    db = create_database(database_url="sqlite+aiosqlite:///./explicit.db")

    assert db.database_url == "sqlite+aiosqlite:///./explicit.db"


def test_create_database_uses_env_url(monkeypatch):
    """Environment DATABASE_URL should be used when no argument is passed."""
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./from-env.db")

    db = create_database()

    assert db.database_url == "sqlite+aiosqlite:///./from-env.db"


def test_create_database_falls_back_to_default(monkeypatch):
    """Default local sqlite URL should be used when env is absent."""
    monkeypatch.delenv("DATABASE_URL", raising=False)

    db = create_database()

    assert db.database_url == "sqlite+aiosqlite:///./nexusdev.db"


def test_worker_reads_environment_settings(monkeypatch):
    """Worker polling and concurrency should be configurable via env vars."""
    monkeypatch.setenv("WORKER_POLL_INTERVAL", "9")
    monkeypatch.setenv("WORKER_MAX_CONCURRENT", "2")

    worker = Worker(database=create_database("sqlite+aiosqlite:///./worker-test.db"))

    assert worker._poll_interval == 9
    assert worker._max_concurrent == 2


def test_worker_uses_defaults_for_invalid_settings(monkeypatch):
    """Worker should fall back to defaults when env vars are invalid."""
    monkeypatch.setenv("WORKER_POLL_INTERVAL", "abc")
    monkeypatch.setenv("WORKER_MAX_CONCURRENT", "0")

    worker = Worker(database=create_database("sqlite+aiosqlite:///./worker-test.db"))

    assert worker._poll_interval == 5
    assert worker._max_concurrent == 4
