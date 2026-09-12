"""One HTTP session for all sources: browser-like UA, timeouts, retries."""

import logging
import time
from typing import Any, Dict, Optional

import requests

logger = logging.getLogger(__name__)

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')

DEFAULT_TIMEOUT = 30
RETRY_STATUSES = {429, 500, 502, 503, 504}


def get(url: str, params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None, timeout: int = DEFAULT_TIMEOUT,
        retries: int = 3) -> requests.Response:
    """GET with a small exponential backoff on transient failures."""
    merged = {'User-Agent': USER_AGENT}
    if headers:
        merged.update(headers)

    last_error: Optional[Exception] = None
    for attempt in range(retries):
        try:
            response = requests.get(url, params=params, headers=merged, timeout=timeout)
            if response.status_code in RETRY_STATUSES and attempt < retries - 1:
                wait = 2 ** attempt
                logger.warning(f"{url} -> {response.status_code}; retrying in {wait}s")
                time.sleep(wait)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as e:
            last_error = e
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    raise last_error  # type: ignore[misc]
