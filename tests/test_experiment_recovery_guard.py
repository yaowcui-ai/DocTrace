import hashlib
import json
import pytest


def test_recovery_checks_algorithm_and_dataset_before_provider_access(tmp_path):
    from scripts.recover_upgrade_retrieval import verify_frozen_inputs
    folder = tmp_path/'evaluation/upgrade_dataset/internal-test-v1'
    folder.mkdir(parents=True)
    (folder/'dataset.json').write_bytes(b'{}')
    (tmp_path/'algorithm.py').write_bytes(b'original')
    freeze = {'dataset_sha256': hashlib.sha256(b'{}').hexdigest(),
              'code_sha256': {'algorithm.py': hashlib.sha256(b'original').hexdigest()}}
    (folder/'freeze.json').write_text(json.dumps(freeze), encoding='utf-8')
    assert verify_frozen_inputs(tmp_path) == freeze['dataset_sha256']
    (tmp_path/'algorithm.py').write_bytes(b'changed')
    with pytest.raises(ValueError, match='algorithm'):
        verify_frozen_inputs(tmp_path)
    (tmp_path/'algorithm.py').write_bytes(b'original')
    (folder/'dataset.json').write_bytes(b'{"changed":true}')
    with pytest.raises(ValueError, match='dataset'):
        verify_frozen_inputs(tmp_path)


def test_timeout_is_not_mislabeled_as_429():
    from scripts.recover_upgrade_retrieval import original_rerank_status
    assert original_rerank_status({'policy': {'whole': {'http_status': 429}}}) == 429
    assert original_rerank_status({'policy': {'whole': {'http_status': None, 'error_kind': 'timeout'}}}) is None
