"""Application Engine lifecycle; no MySQL or model network calls."""
import asyncio
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app import main
from app.config import ConfigurationError


def test_one_engine_is_shared_and_disposed_on_shutdown(monkeypatch):
    engine = Mock()
    factory = Mock(return_value=engine)
    monkeypatch.setattr(main, "create_db_engine", factory, raising=False)

    with TestClient(main.app) as client:
        assert main.app.state.db_engine is engine
        assert client.get("/health").status_code == 200
        assert client.get("/health").status_code == 200
        factory.assert_called_once()
        engine.connect.assert_not_called()
        engine.dispose.assert_not_called()

    engine.dispose.assert_called_once()
    assert main.app.state.db_engine is None


def test_lifespan_releases_engine_even_when_body_raises(monkeypatch):
    engine = Mock()
    monkeypatch.setattr(main, "create_db_engine", lambda settings: engine, raising=False)

    async def exercise():
        async with main.lifespan(main.app):
            assert main.app.state.db_engine is engine
            raise RuntimeError("simulated body error")

    with pytest.raises(RuntimeError, match="simulated body error"):
        asyncio.run(exercise())
    engine.dispose.assert_called_once()
    assert main.app.state.db_engine is None


def test_missing_database_configuration_keeps_liveness_available(monkeypatch):
    def missing():
        raise ConfigurationError("MYSQL_PASSWORD secret-value")

    factory = Mock()
    monkeypatch.setattr(main, "load_database_settings", missing)
    monkeypatch.setattr(main, "create_db_engine", factory, raising=False)

    with TestClient(main.app) as client:
        assert main.app.state.db_engine is None
        response = client.get("/health")
        assert response.json() == {"status": "ok", "service": "DocTrace"}
        assert "secret-value" not in response.text
    factory.assert_not_called()
