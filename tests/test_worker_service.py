import pytest


def test_worker_requires_explicit_once_or_service_mode():
    from app.knowledge.worker import parse_arguments
    assert parse_arguments(['--once']).once is True
    assert parse_arguments(['--serve']).serve is True
    with pytest.raises(SystemExit):
        parse_arguments([])
    with pytest.raises(SystemExit):
        parse_arguments(['--serve', '--poll-seconds', '0'])


def test_service_stops_without_claiming_more_jobs():
    from app.knowledge.worker import run_service
    from threading import Event
    event = Event()
    event.set()
    class Forbidden:
        def acquire(self, *args):
            raise AssertionError('No job after shutdown')
    assert run_service(Forbidden(), None, event, poll_seconds=2) == 0
