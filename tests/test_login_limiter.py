from concurrent.futures import ThreadPoolExecutor
import logging
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


def test_sources_have_independent_buckets_but_the_account_bucket_is_global(clock):
    limiter = LoginLimiter()
    for _ in range(5):
        assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-a', 'admin') == 300
    assert limiter.consume('source-a', 'another-account') is None
    # The global per-account bucket blocks the same account from other sources.
    assert limiter.consume('source-b', 'admin') == 300
    assert limiter.consume('source-b', 'another-account') is None


def test_rotating_source_addresses_cannot_multiply_the_account_allowance(clock):
    limiter = LoginLimiter(account_limit=3)
    for i in range(3):
        assert limiter.consume(f'10.0.0.{i}', 'admin') is None
    assert limiter.consume('10.0.0.99', 'admin') == 300
    assert limiter.consume('10.0.0.99', 'another-user') is None


def test_capacity_fails_closed_without_evicting_limits(clock):
    limiter = LoginLimiter(max_entries=5)
    assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-b', 'admin') is None
    for i in range(20):
        assert limiter.consume(f'rotating-{i}', f'user-{i}') == 300
    assert len(limiter._entries) == 5
    clock.return_value = 1300
    assert limiter.consume('new-source', 'admin') is None
    assert len(limiter._entries) == 3


def test_full_table_of_locked_out_sources_does_not_block_new_sources(clock):
    limiter = LoginLimiter(max_entries=8, source_limit=2, account_limit=5)
    # source-a reaches its source limit and is locked out; its per-source
    # account entries are redundant but still occupy table space.
    assert limiter.consume('source-a', 'user-1') is None
    assert limiter.consume('source-a', 'user-2') is None
    assert limiter.consume('source-a', 'user-3') == 300
    assert len(limiter._entries) == 5  # source + 2 per-source accounts + 2 global accounts
    # Fill the rest of the table with a second locked-out source.
    assert limiter.consume('source-b', 'user-1') is None
    assert limiter.consume('source-b', 'user-2') is None
    assert len(limiter._entries) == 8
    # A brand-new source is still admitted by evicting redundant account entries.
    assert limiter.consume('new-source', 'admin') is None
    assert len(limiter._entries) <= 8
    # The locked-out sources stay locked out; their limits were not reset.
    assert limiter.consume('source-a', 'user-9') == 300
    assert limiter.consume('source-b', 'user-9') == 300


def test_capacity_still_blocks_when_no_redundant_entries_exist(clock):
    limiter = LoginLimiter(max_entries=3, source_limit=20)
    assert limiter.consume('source-a', 'admin') is None
    assert limiter.consume('source-b', 'admin') == 300
    assert len(limiter._entries) == 3
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


def test_failed_login_is_logged_with_source_but_never_the_password(monkeypatch, caplog):
    monkeypatch.setattr(web, 'verify_password', Mock(return_value=False))
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    with caplog.at_level(logging.INFO, logger='booksmith.auth'):
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'super-secret-value'})
    assert response.status_code == 401
    failures = [r for r in caplog.records if 'Login failed' in r.getMessage()]
    assert len(failures) == 1
    assert 'admin' in failures[0].getMessage()
    assert 'super-secret-value' not in caplog.text


def test_successful_login_and_lockout_are_logged_without_passwords(monkeypatch, caplog):
    monkeypatch.setattr(web, 'login_limiter', LoginLimiter(account_limit=1))
    monkeypatch.setattr(web, 'active_sessions', {})
    monkeypatch.setattr(web, 'verify_password', Mock(return_value=True))
    monkeypatch.setattr(web, 'APP_USERNAME', 'admin')
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    with caplog.at_level(logging.INFO, logger='booksmith.auth'):
        assert client.post('/api/auth/login', json={'username': 'admin', 'password': 'first-secret-1'}).status_code == 200
        response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'second-secret'})
    assert response.status_code == 429
    messages = [r.getMessage() for r in caplog.records]
    assert any('Login successful' in message and 'admin' in message for message in messages)
    assert any('rate-limited' in message for message in messages)
    assert 'first-secret-1' not in caplog.text
    assert 'second-secret' not in caplog.text
