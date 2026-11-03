"""One bounded retry policy for remote calls, excluding local processing."""
import asyncio
from collections.abc import Mapping
from datetime import timezone
from email.utils import parsedate_to_datetime
import logging
import math
import random
import time

import httpx
from src.core.process_runner import setting

logger = logging.getLogger(__name__)


class APINetworkError(RuntimeError):
    pass


class APIBudgetExceeded(TimeoutError):
    pass


class APIResponseError(ValueError):
    def __init__(self, status_code, headers=None, provider='API'):
        super().__init__(f'{provider} API Error: Status {status_code}')
        self.status_code = status_code
        self.headers = headers if isinstance(headers, Mapping) else {}


def error_status(error):
    for obj in (error, getattr(error, 'response', None), getattr(error, 'raw_response', None)):
        status = getattr(obj, 'status_code', None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
    return None


def retry_after(error):
    for obj in (error, getattr(error, 'response', None), getattr(error, 'raw_response', None)):
        headers = getattr(obj, 'headers', None)
        if not isinstance(headers, Mapping):
            continue
        value = next((v for k, v in headers.items() if str(k).lower() == 'retry-after'), None)
        if not isinstance(value, str):
            continue
        try:
            seconds = float(value)
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = max(0.0, date.timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
                continue
        if math.isfinite(seconds) and seconds >= 0:
            return seconds
    return None


def validate_retry_settings():
    return (setting('API_REQUEST_TIMEOUT_SECONDS', 60),
            setting('API_RETRY_BUDGET_SECONDS', 180),
            setting('API_RETRY_MAX_DELAY_SECONDS', 60))


async def call_api(operation, attempts=3):
    if not isinstance(attempts, int) or attempts < 1:
        raise ValueError('API attempt count must be a positive integer')
    request_timeout, total_budget, max_delay = validate_retry_settings()
    deadline = time.monotonic() + total_budget
    for attempt in range(attempts):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise APIBudgetExceeded('API retry budget exhausted')
        try:
            return await asyncio.wait_for(operation(), min(request_timeout, remaining))
        except Exception as error:
            if time.monotonic() >= deadline:
                raise APIBudgetExceeded('API retry budget exhausted') from None
            status = error_status(error)
            transient = status in (408, 429) or (status is not None and 500 <= status <= 599)
            if status is None:
                transient = isinstance(error, (httpx.TransportError, TimeoutError, ConnectionError))
            hint = retry_after(error)
            if not transient or attempt == attempts - 1 or (hint is not None and hint > max_delay):
                if status is not None:
                    if isinstance(error, APIResponseError):
                        raise
                    raise APIResponseError(status) from None
                if transient:
                    raise APINetworkError(f'API request failed ({type(error).__name__})') from None
                raise
            multiplier = 15 if status == 429 and hint is None else 1
            base = min(max_delay, multiplier * 2 ** min(attempt, 20))
            delay = min(max_delay, max(base, hint or 0) + random.uniform(0, min(1, base * 0.25)))
            remaining = deadline - time.monotonic()
            if delay >= remaining:
                raise APIBudgetExceeded('API retry delay exceeds remaining budget') from None
            logger.warning('Retrying API attempt %s/%s after %.2fs (status=%s, type=%s)',
                           attempt + 1, attempts, delay, status, type(error).__name__)
            await asyncio.sleep(delay)
