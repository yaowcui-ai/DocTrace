"""Console and bounded UTF-8 files for the local single-process server."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from .console_logging import BufferedConsoleHandler, protect_server_console

DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


class QuietRotatingFileHandler(RotatingFileHandler):
    def handleError(self, record):
        # Console remains an independent sink if disk writes fail.
        pass


def configure_qa_logging(log_dir: Path | None = None) -> None:
    protect_server_console()
    logger = logging.getLogger("doctrace.qa")
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(handler.name == "doctrace_qa_console" for handler in logger.handlers):
        handler = BufferedConsoleHandler()
        handler.set_name("doctrace_qa_console")
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)

    if not any(handler.name == "doctrace_qa_file" for handler in logger.handlers):
        try:
            directory = DEFAULT_LOG_DIR if log_dir is None else Path(log_dir)
            directory.mkdir(parents=True, exist_ok=True)
            handler = QuietRotatingFileHandler(directory / "doctrace-qa.jsonl",
                maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
            handler.set_name("doctrace_qa_file")
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        except OSError as error:
            from .qa_logging import log_qa_event
            log_qa_event("logging_file_unavailable", None, error_type=type(error).__name__)
