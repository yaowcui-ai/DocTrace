from sqlalchemy import URL, Engine, create_engine

from .database_config import DatabaseSettings


def create_db_engine(settings: DatabaseSettings) -> Engine:
    url = URL.create(
        drivername="mysql+pymysql",
        username=settings.user,
        password=settings.password,
        host=settings.host,
        port=settings.port,
        database=settings.database,
        query={"charset": "utf8mb4"},
    )

    return create_engine(
        url,
        pool_pre_ping=True,
        echo=False,
        hide_parameters=True,
        connect_args={
            "connect_timeout": 5,
            "read_timeout": 10,
            "write_timeout": 10,
        },
    )