"""Offline checks: never read local credentials or contact MySQL."""
from importlib import import_module

import pymysql

from app.database_config import DatabaseSettings


def test_engine_creation_is_lazy_and_preserves_special_password(monkeypatch):
    def forbidden_connect(*args, **kwargs):
        raise AssertionError("Engine creation must not connect to MySQL")

    monkeypatch.setattr(pymysql, "connect", forbidden_connect)
    module = import_module("app.database")
    settings = DatabaseSettings("127.0.0.1", 3306, "doctrace", "doctrace_app", "p@ss/#${x}")
    engine = module.create_db_engine(settings)
    try:
        assert engine.url.password == settings.password
        assert settings.password not in repr(engine)
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


def test_driver_connection_arguments_support_unicode_and_bounded_waits():
    module = import_module("app.database")
    settings = DatabaseSettings("127.0.0.1", 3306, "doctrace", "doctrace_app", "dummy")
    engine = module.create_db_engine(settings)
    captured = []

    def intercept(dialect, conn_rec, cargs, cparams):
        captured.append(cparams.copy())
        raise RuntimeError("offline stop")

    from sqlalchemy import event
    import pytest

    event.listen(engine, "do_connect", intercept)
    try:
        with pytest.raises(RuntimeError, match="offline stop"):
            engine.connect()
        params = captured[0]
        assert params["charset"] == "utf8mb4"
        assert 0 < params["connect_timeout"] <= 10
        assert 0 < params["read_timeout"] <= 30
        assert 0 < params["write_timeout"] <= 30
    finally:
        engine.dispose()
