"""Centralised HTTP client for all API calls (not downloads).

Every outgoing HTTP request in v2/app/ goes through this module, except
for file downloads (those go through download_scheduler.py which does its
own streaming).

Responsibilities:
  - Single point for all API calls
  - Retry with exponential backoff on transient errors (timeout, 5xx)
  - Logging every call (url, method, status, duration, caller)
  - Rate limiting (optional, per-domain)
  - Queryable stats (total calls, errors, avg duration)

Usage:
    from v2.app.core.http_client import http

    # Simple GET
    data = http.get_json("https://civitai.com/api/v1/models/12345",
                         headers={"Authorization": "Bearer xxx"},
                         caller="civitai_client.get_model")

    # With params
    data = http.get_json("https://civitai.com/api/v1/images",
                         params={"modelId": 12345, "limit": 200},
                         caller="civitai_client.get_images_rest")
"""

import threading
import time
from collections import deque
from dataclasses import dataclass, field

import httpx


# ── Call log entry ───────────────────────────────────────────────────────────

@dataclass
class CallRecord:
    """Record of a single HTTP call, kept in the ring buffer."""
    timestamp: float        # time.time()
    method: str             # GET, POST
    url: str                # full URL (truncated for display)
    status: int             # HTTP status code (0 if network error)
    duration_ms: int        # round-trip time in milliseconds
    caller: str             # who made the call (e.g. "civitai_client.get_model")
    error: str | None       # error message if failed, None if ok
    response_bytes: int     # response body size


# ── Stats ────────────────────────────────────────────────────────────────────

@dataclass
class Stats:
    """Aggregate statistics, computed from the log."""
    total_calls: int = 0
    total_errors: int = 0
    total_bytes: int = 0
    avg_duration_ms: float = 0.0
    calls_by_caller: dict = field(default_factory=dict)
    errors_by_caller: dict = field(default_factory=dict)


# ── HTTP Client ──────────────────────────────────────────────────────────────

class HttpClient:
    """Centralised HTTP client with logging, retry, and rate limiting.

    One global instance (`http`) is created at module level.
    All API calls in the application go through it.

    Does NOT handle file downloads — those go through download_scheduler.py
    which needs streaming and Range headers for resume.
    """

    # Ring buffer size for call log
    _LOG_SIZE = 500

    # Default settings
    _DEFAULT_TIMEOUT = 20       # seconds
    _DEFAULT_MAX_RETRIES = 2    # 0 = no retry, 2 = up to 3 attempts
    _DEFAULT_BACKOFF = 1.0      # seconds, multiplied by attempt number

    def __init__(self):
        """Create a new HTTP client with empty log and counters."""
        self._log: deque[CallRecord] = deque(maxlen=self._LOG_SIZE)
        self._lock = threading.Lock()

        # Rate limiting: per-domain minimum interval between requests.
        # None = no limit. Set with set_rate_limit().
        self._rate_limits: dict[str, float] = {}       # domain → min seconds between calls
        self._last_call: dict[str, float] = {}          # domain → timestamp of last call

        # Aggregate counters (thread-safe via _lock)
        self._total_calls = 0
        self._total_errors = 0
        self._total_bytes = 0
        self._total_duration_ms = 0

    # ── Rate limiting ────────────────────────────────────────────────────

    def set_rate_limit(self, domain: str, min_interval: float):
        """Set minimum interval between requests to a domain.

        Args:
            domain: Domain name (e.g. "civitai.com").
            min_interval: Minimum seconds between requests. 0 = no limit.
        """
        if min_interval <= 0:
            self._rate_limits.pop(domain, None)
        else:
            self._rate_limits[domain] = min_interval

    def _wait_for_rate_limit(self, url: str):
        """Sleep if needed to respect rate limits for this URL's domain."""
        from urllib.parse import urlparse
        domain = urlparse(url).hostname or ""
        limit = self._rate_limits.get(domain)
        if not limit:
            return
        last = self._last_call.get(domain, 0)
        elapsed = time.time() - last
        if elapsed < limit:
            time.sleep(limit - elapsed)
        self._last_call[domain] = time.time()

    # ── Core request method ──────────────────────────────────────────────

    def request(
        self,
        method: str,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        json_body: dict | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        caller: str = "",
    ) -> httpx.Response:
        """Make an HTTP request with retry, logging, and rate limiting.

        This is the low-level method. Prefer get_json() for typical API calls.

        Args:
            method: HTTP method (GET, POST, etc.)
            url: Full URL.
            params: Query parameters.
            headers: HTTP headers.
            json_body: JSON body for POST requests.
            timeout: Override default timeout (seconds).
            max_retries: Override default retry count.
            caller: Identifier for who's making this call (for logging).

        Returns:
            httpx.Response object.

        Raises:
            httpx.HTTPStatusError: On 4xx after retries (4xx is not retried).
            httpx.RequestError: On network errors after retries.
        """
        t = timeout or self._DEFAULT_TIMEOUT
        retries = max_retries if max_retries is not None else self._DEFAULT_MAX_RETRIES
        last_error = None

        for attempt in range(retries + 1):
            self._wait_for_rate_limit(url)
            start = time.time()
            status = 0
            error_msg = None
            response_bytes = 0

            try:
                r = httpx.request(
                    method, url,
                    params=params,
                    headers=headers,
                    json=json_body,
                    timeout=t,
                    follow_redirects=True,
                )
                status = r.status_code
                response_bytes = len(r.content)
                r.raise_for_status()

                # Success — log and return
                duration = int((time.time() - start) * 1000)
                self._record(method, url, status, duration, caller, None, response_bytes)
                return r

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                error_msg = f"HTTP {status}"
                last_error = e

                # Don't retry 4xx — it's a client error, retrying won't help
                if status < 500:
                    duration = int((time.time() - start) * 1000)
                    self._record(method, url, status, duration, caller, error_msg, response_bytes)
                    raise

                # 5xx — retry
                if attempt < retries:
                    time.sleep(self._DEFAULT_BACKOFF * (attempt + 1))
                    continue

                duration = int((time.time() - start) * 1000)
                self._record(method, url, status, duration, caller, error_msg, response_bytes)
                raise

            except (httpx.TimeoutException, httpx.RequestError) as e:
                error_msg = str(e)[:200]
                last_error = e
                duration = int((time.time() - start) * 1000)

                if attempt < retries:
                    time.sleep(self._DEFAULT_BACKOFF * (attempt + 1))
                    continue

                self._record(method, url, status, duration, caller, error_msg, 0)
                raise

    def get_json(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int | None = None,
        caller: str = "",
    ) -> dict:
        """GET request, return parsed JSON.

        The most common call pattern for API endpoints.

        Args:
            url: Full URL.
            params: Query parameters.
            headers: HTTP headers.
            timeout: Override default timeout.
            caller: Who's making this call.

        Returns:
            Parsed JSON response as dict.
        """
        r = self.request("GET", url, params=params, headers=headers,
                         timeout=timeout, caller=caller)
        return r.json()

    def post_json(
        self,
        url: str,
        json_body: dict | None = None,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: int | None = None,
        caller: str = "",
    ) -> dict:
        """POST request with JSON body, return parsed JSON.

        Args:
            url: Full URL.
            json_body: JSON body.
            params: Query parameters.
            headers: HTTP headers.
            timeout: Override default timeout.
            caller: Who's making this call.

        Returns:
            Parsed JSON response as dict.
        """
        r = self.request("POST", url, params=params, headers=headers,
                         json_body=json_body, timeout=timeout, caller=caller)
        return r.json()

    # ── Logging ──────────────────────────────────────────────────────────

    def _record(self, method: str, url: str, status: int, duration_ms: int,
                caller: str, error: str | None, response_bytes: int):
        """Record a call in the ring buffer and update counters."""
        record = CallRecord(
            timestamp=time.time(),
            method=method,
            url=url[:200],  # truncate long URLs
            status=status,
            duration_ms=duration_ms,
            caller=caller,
            error=error,
            response_bytes=response_bytes,
        )
        with self._lock:
            self._log.append(record)
            self._total_calls += 1
            self._total_bytes += response_bytes
            self._total_duration_ms += duration_ms
            if error:
                self._total_errors += 1

    # ── Stats and log access ─────────────────────────────────────────────

    def get_stats(self) -> Stats:
        """Get aggregate statistics.

        Returns:
            Stats dataclass with totals and per-caller breakdown.
        """
        with self._lock:
            stats = Stats(
                total_calls=self._total_calls,
                total_errors=self._total_errors,
                total_bytes=self._total_bytes,
                avg_duration_ms=(
                    self._total_duration_ms / self._total_calls
                    if self._total_calls > 0 else 0.0
                ),
            )
            # Per-caller breakdown from ring buffer
            for r in self._log:
                stats.calls_by_caller[r.caller] = stats.calls_by_caller.get(r.caller, 0) + 1
                if r.error:
                    stats.errors_by_caller[r.caller] = stats.errors_by_caller.get(r.caller, 0) + 1
            return stats

    def get_log(self, limit: int = 50, caller: str | None = None) -> list[CallRecord]:
        """Get recent call log entries.

        Args:
            limit: Max entries to return (newest first).
            caller: Filter by caller name (optional).

        Returns:
            List of CallRecord, newest first.
        """
        with self._lock:
            entries = list(self._log)
        if caller:
            entries = [e for e in entries if e.caller == caller]
        entries.reverse()  # newest first
        return entries[:limit]

    def clear_stats(self):
        """Reset all counters and clear the log."""
        with self._lock:
            self._log.clear()
            self._total_calls = 0
            self._total_errors = 0
            self._total_bytes = 0
            self._total_duration_ms = 0


# ── Global instance ──────────────────────────────────────────────────────────
# All modules import and use this single instance.

http = HttpClient()
