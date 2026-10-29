"""Offline checks of load-report accounting; no servers, databases or providers."""
import pytest

from scripts.upgrade_load import percentile, summarize, parse_args, request_inputs


def test_percentile_documents_small_sample_interpolation():
    assert percentile([], 95) is None
    assert percentile([0.4], 95) == 0.4
    assert percentile([0.4, 0.1, 0.3, 0.2], 50) == pytest.approx(0.25)
    assert percentile([0.4, 0.1, 0.3, 0.2], 95) == pytest.approx(0.385)


def test_summary_keeps_rejections_transport_errors_and_unconfirmed_200():
    rows = [
        {'status_code': 200, 'completed': True, 'elapsed_seconds': .2},
        {'status_code': 429, 'completed': False, 'elapsed_seconds': .02},
        {'status_code': None, 'completed': False, 'elapsed_seconds': .5},
        {'status_code': 200, 'completed': False, 'elapsed_seconds': .1},
    ]
    result = summarize(rows, wall_seconds=2)
    assert result['attempted'] == 4
    assert result['http_successes'] == 2
    assert result['completed'] == 1
    assert result['failures'] == 3
    assert result['failure_rate'] == .75
    assert result['http_status_counts'] == {'200': 2, '429': 1, 'transport_error': 1}
    assert result['attempted_requests_per_second'] == 2
    assert result['completed_requests_per_second'] == .5
    assert result['completed_latency_seconds']['p95'] == .2


def test_all_failed_latency_is_unavailable_instead_of_zero():
    result = summarize([{'status_code': 503, 'completed': False, 'elapsed_seconds': .1}], wall_seconds=1)
    assert result['completed_latency_seconds']['p50'] is None
    assert result['completed_latency_seconds']['p95'] is None


def test_request_plan_is_bounded_and_requires_explicit_execute():
    args = parse_args([])
    assert args.execute is False
    assert args.requests_per_level == 20
    for invalid in ('0', '21'):
        with pytest.raises(SystemExit):
            parse_args(['--requests-per-level', invalid])


def test_each_concurrent_operation_has_its_own_conversation_and_unique_key():
    rows = request_inputs(['conversation-a', 'conversation-b'], concurrency=5, run_id='synthetic-run')
    assert len(rows) == 2
    assert len({r['idempotency_key'] for r in rows}) == 2
    assert len({r['conversation_id'] for r in rows}) == 2
    assert all(r['body']['knowledge_base'] == 'frozen' and r['body']['mode'] == 'naive' for r in rows)
    assert all(r['body']['question'].startswith('[SYNTHETIC LOAD') for r in rows)
