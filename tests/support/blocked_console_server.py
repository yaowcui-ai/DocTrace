"""Real Uvicorn with permanently blocked console sinks, no DB or providers."""
import sys
from pathlib import Path
from threading import Event

import uvicorn

from app import database_config, logging_config
from app.config import ConfigurationError


class FrozenConsole:
    def write(self, message):
        Event().wait()  # Deliberately never returns; process terminated by harness.

    def flush(self):
        pass

    def isatty(self):
        return False


def unavailable_database():
    raise ConfigurationError('Database disabled in console-blocking fixture')


if __name__ == '__main__':
    stream=FrozenConsole()
    database_config.load_database_settings=unavailable_database
    logging_config.DEFAULT_LOG_DIR=Path(sys.argv[2])
    sys.stderr=stream
    sys.stdout=stream
    # Normal Uvicorn logging configuration + string app import, exactly like
    # `python -m uvicorn app.main:app`; no pre-wrapping or alternate lifespan.
    uvicorn.run('app.main:app',host='127.0.0.1',port=int(sys.argv[1]),access_log=True)
