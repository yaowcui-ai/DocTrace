"""A paused console must never hold a request thread or the event loop."""
from io import StringIO
import logging
from threading import Event, Thread

from app import logging_config


class PausedConsole:
    def __init__(self):
        self.entered = Event()
        self.resume = Event()

    def write(self, value):
        self.entered.set()
        self.resume.wait(5)

    def flush(self):
        pass


def test_qa_file_and_producer_continue_when_console_is_paused(monkeypatch, tmp_path):
    stream = PausedConsole()
    logger = logging.Logger('paused_console', level=logging.INFO)
    original_get = logging.getLogger
    monkeypatch.setattr(logging_config.logging, 'getLogger', lambda name=None: logger if name == 'doctrace.qa' else original_get(name))
    monkeypatch.setattr('sys.stderr', stream)
    logging_config.configure_qa_logging(tmp_path)
    done = Event()
    producer = Thread(target=lambda: (logger.info('{"event":"probe"}'), done.set()), daemon=True)
    try:
        producer.start()
        assert stream.entered.wait(1)
        assert done.wait(0.5), 'Console I/O blocked the business thread'
        assert 'probe' in (tmp_path/'doctrace-qa.jsonl').read_text(encoding='utf-8')
    finally:
        stream.resume.set()
        producer.join(2)
        for handler in logger.handlers:
            handler.close()


def test_queue_is_bounded_and_full_queue_never_blocks():
    from app.console_logging import BufferedConsoleHandler
    stream=PausedConsole()
    handler=BufferedConsoleHandler(stream, capacity=2)
    record=logging.LogRecord('test',logging.INFO,'',0,'message',(),None)
    try:
        handler.handle(record)
        assert stream.entered.wait(1)
        for _ in range(30):
            handler.handle(record)
        assert handler.pending_count <= 2
        assert handler.dropped_count > 0
        assert not handler.wait_for_idle(0.01)
    finally:
        stream.resume.set()
        assert handler.wait_for_idle(2)
        handler.close()


def test_server_console_handlers_are_wrapped_once(monkeypatch):
    from app.console_logging import BufferedConsoleHandler, protect_server_console
    logger=logging.Logger('uvicorn_test',level=logging.INFO)
    stream=StringIO()
    original=logging.StreamHandler(stream)
    original.setFormatter(logging.Formatter('server:%(message)s'))
    logger.addHandler(original)
    original_get=logging.getLogger
    monkeypatch.setattr(logging,'getLogger',lambda name=None:logger if name in ('uvicorn','uvicorn.error','uvicorn.access') else original_get(name))
    protect_server_console()
    protect_server_console()
    assert len(logger.handlers)==1
    handler=logger.handlers[0]
    assert isinstance(handler,BufferedConsoleHandler)
    logger.info('probe')
    assert handler.wait_for_idle(1)
    assert stream.getvalue()=='server:probe\n'
    handler.close()


def test_console_close_does_not_wait_for_a_frozen_terminal():
    from app.console_logging import BufferedConsoleHandler
    stream=PausedConsole()
    handler=BufferedConsoleHandler(stream)
    done=Event()
    try:
        handler.handle(logging.LogRecord('test',logging.INFO,'',0,'probe',(),None))
        assert stream.entered.wait(1)
        closer=Thread(target=lambda:(handler.close(),done.set()),daemon=True)
        closer.start()
        assert done.wait(0.5)
    finally:
        stream.resume.set()
        handler.wait_for_idle(2)


def test_broken_console_is_silent_and_later_messages_still_work():
    from app.console_logging import BufferedConsoleHandler
    class Broken:
        def write(self,value):raise OSError('private-console-error')
    handler=BufferedConsoleHandler(Broken())
    record=logging.LogRecord('test',logging.INFO,'',0,'probe',(),None)
    handler.handle(record)
    assert handler.wait_for_idle(1)
    output=StringIO()
    handler.setStream(output)
    handler.handle(record)
    assert handler.wait_for_idle(1)
    assert output.getvalue()=='probe\n'
    handler.close()
