from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from src.core.login_limiter import LoginLimiter
from src import web


@pytest.fixture
def clock(monkeypatch):
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr('src.core.login_limiter.time.monotonic', clock)
    return clock


def test_account_limit_expiry_and_no_extension_on_rejection(clock):
    limiter = LoginLimiter()
    for _ in range(5):
        assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-a', 'admin') == 300
    clock.return_value = 1299.1
    assert limiter.consume('source-a', 'admin') == 1
    clock.return_value = 1300
    assert limiter.consume('source-a', 'admin') is None


def test_source_limit_cannot_be_bypassed_by_changing_username(clock):
    limiter = LoginLimiter()
    for i in range(20):
        assert limiter.consume('source-a', f'user-{i}') is None
    assert limiter.consume('source-a', 'another-user') == 300
    assert limiter.consume('source-b', 'another-user') is None


def test_accounts_and_sources_have_independent_buckets(clock):
    limiter = LoginLimiter()
    for _ in range(5):
        assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-a', 'admin') == 300
    assert limiter.consume('source-a', 'another-account') is None
    assert limiter.consume('source-b', 'admin') is None


def test_capacity_fails_closed_without_evicting_limits(clock):
    limiter = LoginLimiter(max_entries=4)
    assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-b', 'admin') is None
    for i in range(20):
        assert limiter.consume(f'rotating-{i}', f'user-{i}') == 300
    assert len(limiter._entries) == 4
    clock.return_value = 1300
    assert limiter.consume('new-source', 'admin') is None
    assert len(limiter._entries) == 2


def test_full_table_of_locked_out_sources_does_not_block_new_sources(clock):
    limiter = LoginLimiter(max_entries=5, source_limit=2, account_limit=5)
    # source-a reaches its source limit and is locked out; its account entries
    # are redundant but still occupy table space.
    assert limiter.consume('source-a', 'user-1') is None
    assert limiter.consume('source-a', 'user-2') is None
    assert limiter.consume('source-a', 'user-3') == 300
    assert len(limiter._entries) == 3  # source + 2 account entries
    # Fill the rest of the table with a second locked-out source.
    assert limiter.consume('source-b', 'user-1') is None
    assert limiter.consume('source-b', 'user-2') is None
    assert len(limiter._entries) == 5
    # A brand-new source is still admitted by evicting redundant account entries.
    assert limiter.consume('new-source', 'admin') is None
    assert len(limiter._entries) <= 5
    # The locked-out sources stay locked out; their limits were not reset.
    assert limiter.consume('source-a', 'user-9') == 300
    assert limiter.consume('source-b', 'user-9') == 300


def test_capacity_still_blocks_when_no_redundant_entries_exist(clock):
    limiter = LoginLimiter(max_entries=2, source_limit=20)
    assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-b', 'admin') == 300
    assert len(limiter._entries) == 2
    clock.return_value = 1300
    assert limiter.consume('source-c', 'admin') is None


def test_parallel_requests_cannot_exceed_limit():
    limiter = LoginLimiter()
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda _: limiter.consume('source-a', 'admin'), range(30)))
    assert results.count(None) == 5


def test_endpoint_limits_before_hashing_and_ignores_forwarded_headers(monkeypatch):
    limiter = LoginLimiter(account_limit=2)
    monkeypatch.setattr(web, 'login_limiter', limiter)
    verify = Mock(return_value=False)
    monkeypatch.setattr(web, 'verify_password', verify)
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    for i in range(2):
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'},
                               headers={'X-Forwarded-For': f'192.0.2.{i}'})
        assert response.status_code == 401
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'},
                           headers={'X-Forwarded-For': '203.0.113.99', 'Forwarded': 'for=203.0.113.99'})
    assert response.status_code == 429
    assert 1 <= int(response.headers['Retry-After']) <= 300
    assert verify.call_count == 2
    assert 'set-cookie' not in response.headers


def test_successful_logins_also_consume_allowance(monkeypatch):
    monkeypatch.setattr(web, 'login_limiter', LoginLimiter(account_limit=2))
    monkeypatch.setattr(web, 'active_sessions', {})
    monkeypatch.setattr(web, 'verify_password', Mock(return_value=True))
    monkeypatch.setattr(web, 'APP_USERNAME', 'test-user')
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    payload = {'username': 'test-user', 'password': 'test-only-password'}
    assert client.post('/api/auth/login', json=payload).status_code == 200
    assert client.post('/api/auth/login', json=payload).status_code == 200
    assert client.post('/api/auth/login', json=payload).status_code == 429
    assert len(web.active_sessions) == 2
