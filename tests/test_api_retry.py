import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from mistralai.client import errors

from src.api import retry
from src.api.retry import APIResponseError, APIBudgetExceeded, call_api
from src.api.openai_client import OpenAITTSClient
from src.api.mistral_client import MistralTTSClient


@pytest.fixture
def deterministic(monkeypatch):
    monkeypatch.setattr(retry.random, 'uniform', lambda low, high: 0)
    clock = Mock(return_value=1000.0)
    monkeypatch.setattr(retry.time, 'monotonic', clock)
    async def sleep(seconds):
        clock.return_value += seconds
    sleeper = AsyncMock(side_effect=sleep)
    monkeypatch.setattr(retry.asyncio, 'sleep', sleeper)
    return clock, sleeper


@pytest.mark.parametrize('status', [400, 401, 403, 404, 409, 422])
def test_permanent_http_errors_are_not_retried(deterministic, status):
    operation = AsyncMock(side_effect=APIResponseError(status))
    with pytest.raises(APIResponseError):
        asyncio.run(call_api(operation))
    assert operation.await_count == 1
    deterministic[1].assert_not_called()


@pytest.mark.parametrize('error', [APIResponseError(429), APIResponseError(503),
                                   httpx.ConnectError('offline'), httpx.ReadTimeout('timeout')])
def test_transient_errors_retry_with_backoff(deterministic, error):
    operation = AsyncMock(side_effect=[error, error, 'ok'])
    assert asyncio.run(call_api(operation)) == 'ok'
    assert [call.args[0] for call in deterministic[1].call_args_list] == ([15, 30] if isinstance(error, APIResponseError) and error.status_code == 429 else [1, 2])


def test_sdk_status_and_headers_are_structured_and_error_body_not_logged(deterministic, caplog):
    response = httpx.Response(429, headers={'Retry-After': '7'}, text='secret-error-body')
    error = errors.SDKError('rate limited', response)
    operation = AsyncMock(side_effect=[error, 'ok'])
    assert asyncio.run(call_api(operation)) == 'ok'
    deterministic[1].assert_awaited_once_with(7)
    assert 'secret-error-body' not in caplog.text


def test_retry_after_http_date(deterministic, monkeypatch):
    monkeypatch.setattr(retry.time, 'time', lambda: 1000)
    header = format_datetime(datetime.fromtimestamp(1010, timezone.utc), usegmt=True)
    operation = AsyncMock(side_effect=[APIResponseError(503, {'Retry-After': header}), 'ok'])
    assert asyncio.run(call_api(operation)) == 'ok'
    deterministic[1].assert_awaited_once_with(10)


@pytest.mark.parametrize('header', ['broken', '-1', 'nan', 'inf'])
def test_invalid_retry_after_falls_back_to_backoff(deterministic, header):
    operation = AsyncMock(side_effect=[APIResponseError(429, {'Retry-After': header}), 'ok'])
    assert asyncio.run(call_api(operation)) == 'ok'
    deterministic[1].assert_awaited_once_with(15)


def test_long_retry_after_does_not_trigger_early_retry(deterministic):
    operation = AsyncMock(side_effect=APIResponseError(429, {'Retry-After': '120'}))
    with pytest.raises(APIResponseError):
        asyncio.run(call_api(operation))
    assert operation.await_count == 1
    deterministic[1].assert_not_called()


def test_retry_budget_includes_waits(deterministic, monkeypatch):
    monkeypatch.setenv('API_RETRY_BUDGET_SECONDS', '2')
    operation = AsyncMock(side_effect=APIResponseError(503))
    with pytest.raises(APIBudgetExceeded):
        asyncio.run(call_api(operation, attempts=10))
    assert operation.await_count == 2
    deterministic[1].assert_awaited_once_with(1)


def test_jitter_is_applied(monkeypatch):
    monkeypatch.setattr(retry.random, 'uniform', lambda low, high: high)
    sleep = AsyncMock()
    monkeypatch.setattr(retry.asyncio, 'sleep', sleep)
    operation = AsyncMock(side_effect=[APIResponseError(500), 'ok'])
    assert asyncio.run(call_api(operation)) == 'ok'
    sleep.assert_awaited_once_with(1.25)


def test_attempt_timeout_and_cancellation_close_operation(monkeypatch):
    monkeypatch.setenv('API_REQUEST_TIMEOUT_SECONDS', '0.02')
    monkeypatch.setenv('API_RETRY_BUDGET_SECONDS', '0.02')
    closed = []
    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    with pytest.raises(APIBudgetExceeded):
        asyncio.run(call_api(operation))
    assert closed == [True]


def test_cancellation_never_retries():
    operation = AsyncMock(side_effect=asyncio.CancelledError)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(call_api(operation))
    operation.assert_awaited_once()


@pytest.mark.parametrize('failure', [PermissionError('disk'), ValueError('invalid data'), RuntimeError('local error')])
def test_unclassified_errors_are_not_retried(deterministic, failure):
    operation = AsyncMock(side_effect=failure)
    with pytest.raises(type(failure)):
        asyncio.run(call_api(operation))
    operation.assert_awaited_once()


@pytest.mark.parametrize('provider', ['mistral', 'openai'])
def test_invalid_audio_does_not_repeat_paid_request(tmp_path, monkeypatch, provider):
    if provider == 'mistral':
        client = MistralTTSClient('fake')
        client.set_voice_id('voice')
        operation = AsyncMock(return_value=Mock(audio_data=None, audio=b'small'))
        client.client = Mock(audio=Mock(speech=Mock(complete_async=operation)))
    else:
        client = OpenAITTSClient('fake')
        operation = AsyncMock(return_value=Mock(status_code=200, content=b'small'))
        monkeypatch.setattr(httpx.AsyncClient, 'post', operation)
    with pytest.raises(RuntimeError, match='too small'):
        asyncio.run(client.generate_audio('text', tmp_path / 'out.mp3'))
    operation.assert_awaited_once()


def test_mistral_sdk_nested_retries_are_disabled():
    client = MistralTTSClient('fake')
    assert client.client.sdk_configuration.retry_config is None


def test_disk_error_does_not_repeat_mistral_tts(tmp_path, monkeypatch):
    from pathlib import Path
    client = MistralTTSClient('fake')
    client.set_voice_id('voice')
    operation = AsyncMock(return_value=Mock(audio_data=None, audio=b'x' * 200))
    client.client = Mock(audio=Mock(speech=Mock(complete_async=operation)))
    monkeypatch.setattr(Path, 'write_bytes', Mock(side_effect=PermissionError('disk')))
    with pytest.raises(PermissionError):
        asyncio.run(client.generate_audio('text', tmp_path / 'out.mp3'))
    operation.assert_awaited_once()


def test_truncated_text_response_is_not_repeated():
    client = MistralTTSClient('fake')
    response = Mock(choices=[Mock(message=Mock(content='partial'), finish_reason='length')])
    operation = AsyncMock(return_value=response)
    client.client = Mock(chat=Mock(complete_async=operation))
    with pytest.raises(RuntimeError, match='capacity'):
        asyncio.run(client.translate_text('text', 'English', 'Polish'))
    operation.assert_awaited_once()


def test_sdk_permanent_error_is_sanitized(deterministic):
    failure = errors.SDKError('failed', httpx.Response(401, text='secret body'))
    operation = AsyncMock(side_effect=failure)
    with pytest.raises(APIResponseError) as caught:
        asyncio.run(call_api(operation))
    assert 'secret body' not in str(caught.value)
    operation.assert_awaited_once()
