"""Trusted-proxy client resolution: X-Forwarded-For is honored only when the
direct peer is inside TRUSTED_PROXY_CIDRS. Default configuration trusts nobody."""
import asyncio
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from src import web
from src.core.login_limiter import LoginLimiter
from src.web_security import TrustedProxyHeaders, forwarded_client_address, trusted_proxy_networks

LOGIN_BODY = b'{"username":"admin","password":"wrong-password"}'


def http_scope(headers=(), client=('10.0.0.9', 4444), path='/api/auth/login'):
    return {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
            'method': 'POST', 'path': path, 'raw_path': path.encode(), 'root_path': '',
            'scheme': 'http', 'query_string': b'', 'client': client, 'server': ('test', 80),
            'headers': [(b'host', b'test'), (b'content-type', b'application/json'),
                        (b'content-length', str(len(LOGIN_BODY)).encode()),
                        (b'x-requested-with', b'Booksmith'), *headers]}


def post_login(scope, monkeypatch, limiter=None):
    """Run one raw login request through the full app and return (status, limiter source)."""
    if limiter is None:
        limiter = Mock()
        limiter.consume = Mock(return_value=None)
    monkeypatch.setattr(web, 'login_limiter', limiter)
    monkeypatch.setattr(web, 'verify_password', Mock(return_value=False))
    calls = {'n': 0}
    async def receive():
        calls['n'] += 1
        body = LOGIN_BODY if calls['n'] == 1 else b''
        return {'type': 'http.request', 'body': body, 'more_body': False}
    send = AsyncMock()
    asyncio.run(web.app(scope, receive, send))
    status = next(call.args[0]['status'] for call in send.await_args_list
                  if call.args[0]['type'] == 'http.response.start')
    return status, limiter.consume.call_args.args[0]


def test_trusted_peer_uses_forwarded_client(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', b'203.0.113.7')])
    status, source = post_login(scope, monkeypatch)
    assert status == 401
    assert source == '203.0.113.7'


def test_untrusted_peer_ignores_forwarded_for(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', b'203.0.113.7')], client=('192.0.2.1', 1234))
    _, source = post_login(scope, monkeypatch)
    assert source == '192.0.2.1'


def test_no_trust_by_default_ignores_forwarded_for(monkeypatch):
    monkeypatch.delenv('TRUSTED_PROXY_CIDRS', raising=False)
    scope = http_scope(headers=[(b'x-forwarded-for', b'203.0.113.7')])
    _, source = post_login(scope, monkeypatch)
    assert source == '10.0.0.9'


def test_non_ip_peer_is_never_trusted_even_with_allow_all_cidr(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '0.0.0.0/0')
    monkeypatch.setattr(web, 'login_limiter', Mock(consume=Mock(return_value=None)))
    monkeypatch.setattr(web, 'verify_password', Mock(return_value=False))
    client = TestClient(web.app, headers={'X-Requested-With': 'Booksmith'})
    response = client.post('/api/auth/login', json={'username': 'admin', 'password': 'wrong'},
                           headers={'X-Forwarded-For': '203.0.113.7'})
    assert response.status_code == 401
    assert web.login_limiter.consume.call_args.args[0] == 'testclient'


def test_forwarded_chain_skips_trusted_proxies_from_the_right(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', b'198.51.100.7, 10.0.0.9')])
    _, source = post_login(scope, monkeypatch)
    assert source == '198.51.100.7'


def test_all_trusted_forwarded_chain_uses_leftmost_entry(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', b'10.0.0.5, 10.0.0.9')])
    _, source = post_login(scope, monkeypatch)
    assert source == '10.0.0.5'


@pytest.mark.parametrize('forwarded', ['not-an-ip', '203.0.113.7:8080', '[2001:db8::1]:443',
                                       '203.0.113.7, bogus'])
def test_malformed_forwarded_header_fails_closed(monkeypatch, forwarded):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', forwarded.encode())])
    _, source = post_login(scope, monkeypatch)
    assert source == '10.0.0.9'


def test_duplicate_forwarded_headers_are_ignored(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    scope = http_scope(headers=[(b'x-forwarded-for', b'203.0.113.7'),
                                (b'x-forwarded-for', b'203.0.113.8')])
    _, source = post_login(scope, monkeypatch)
    assert source == '10.0.0.9'


def test_overlong_forwarded_chain_is_ignored(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    chain = ','.join(f'203.0.113.{i}' for i in range(17))
    scope = http_scope(headers=[(b'x-forwarded-for', chain.encode())])
    _, source = post_login(scope, monkeypatch)
    assert source == '10.0.0.9'


def test_rotating_forwarded_sources_share_the_global_account_lockout(monkeypatch):
    """Behind a trusted proxy, spoofed/rotating XFF cannot multiply the per-account allowance."""
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', '10.0.0.0/8')
    real_limiter = LoginLimiter(account_limit=2, source_limit=100)
    limiter = Mock()
    limiter.consume = Mock(side_effect=real_limiter.consume)
    for i, expected in ((1, 401), (2, 401), (3, 429)):
        scope = http_scope(headers=[(b'x-forwarded-for', f'203.0.113.{i}'.encode())])
        status, source = post_login(scope, monkeypatch, limiter=limiter)
        assert status == expected
        assert source == f'203.0.113.{i}'


def test_trusted_proxy_networks_parsing():
    assert trusted_proxy_networks('') == []
    assert trusted_proxy_networks('  ') == []
    networks = trusted_proxy_networks('10.0.0.0/8, 127.0.0.1/32,2001:db8::/32')
    assert len(networks) == 3
    # Host bits are tolerated (strict=False), like uvicorn's forwarded-allow-ips.
    assert str(trusted_proxy_networks('10.0.0.1')[0]) == '10.0.0.1/32'
    for bad in ('bogus', '10.0.0.0/33', '10.0.0.0/8, nope'):
        with pytest.raises(ValueError, match='TRUSTED_PROXY_CIDRS'):
            trusted_proxy_networks(bad)


def test_forwarded_client_address_unit():
    networks = trusted_proxy_networks('10.0.0.0/8')
    assert forwarded_client_address('203.0.113.7', networks) == '203.0.113.7'
    assert forwarded_client_address('203.0.113.7, 10.0.0.9', networks) == '203.0.113.7'
    assert forwarded_client_address('10.0.0.5, 10.0.0.9', networks) == '10.0.0.5'
    assert forwarded_client_address('garbage', networks) is None
    assert forwarded_client_address('203.0.113.7:80', networks) is None
    assert forwarded_client_address(','.join(['203.0.113.1'] * 17), networks) is None
    assert forwarded_client_address('', networks) is None


def test_invalid_trusted_proxy_cidrs_stop_startup(monkeypatch):
    monkeypatch.setenv('TRUSTED_PROXY_CIDRS', 'bogus')
    with pytest.raises(ValueError, match='TRUSTED_PROXY_CIDRS'):
        asyncio.run(web.startup_event())


def test_middleware_passes_non_http_scopes_through():
    downstream = AsyncMock()
    middleware = TrustedProxyHeaders(downstream, networks=lambda: trusted_proxy_networks('10.0.0.0/8'))
    scope = {'type': 'lifespan'}
    asyncio.run(middleware(scope, AsyncMock(), AsyncMock()))
    downstream.assert_awaited_once()
