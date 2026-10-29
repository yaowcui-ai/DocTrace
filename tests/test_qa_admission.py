import pytest


def test_paid_pipeline_admission_is_bounded_per_owner_and_released():
    from app.security_limits import QAAdmission
    from app.lightrag_client import UpstreamError
    gate = QAAdmission(max_concurrent=2, max_per_owner=1)
    with gate.slot('alice'):
        with pytest.raises(UpstreamError) as error:
            with gate.slot('alice'):
                pass
        assert error.value.status_code == 429
        with gate.slot('bob'):
            with pytest.raises(UpstreamError):
                with gate.slot('charlie'):
                    pass
    with gate.slot('alice'):
        pass


def test_admission_release_on_upstream_failure():
    from app.security_limits import QAAdmission
    gate = QAAdmission(max_concurrent=1)
    with pytest.raises(RuntimeError):
        with gate.slot('alice'):
            raise RuntimeError('fixture upstream failure')
    with gate.slot('bob'):
        pass
