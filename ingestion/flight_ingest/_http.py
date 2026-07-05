"""Thin HTTP helpers shared by the source modules.

Centralizes the ``verify`` toggle (corporate-proxy escape hatch) and a simple
exponential-backoff retry so each source module stays focused on its schema.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import Settings

log = logging.getLogger("flight_ingest.http")


def make_client(settings: Settings, **kwargs: Any) -> httpx.Client:
    """Create an httpx client honoring the SSL-verify toggle and timeout."""
    headers = {"User-Agent": settings.user_agent}
    headers.update(kwargs.pop("headers", {}) or {})
    return httpx.Client(
        verify=settings.ssl_verify,
        timeout=settings.http_timeout,
        headers=headers,
        follow_redirects=True,
        **kwargs,
    )


def _retry_after_seconds(resp: httpx.Response | None) -> float | None:
    """Parse a Retry-After header (delta-seconds form) if present."""
    if resp is None:
        return None
    raw = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None  # HTTP-date form is rare here; fall back to backoff


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    max_retries: int,
    pause: float,
    max_backoff: float = 60.0,
    **kwargs: Any,
) -> httpx.Response:
    """GET ``url`` with exponential backoff on transport/5xx/429 errors.

    4xx (except 429) fail fast — they will not improve on retry. On 429 the
    server's ``Retry-After`` header is honored when present; otherwise an
    exponential backoff capped at ``max_backoff`` is used (so a daily-quota 429
    waits meaningfully instead of busy-looping every few seconds).
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            resp = client.get(url, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"retryable status {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if attempt > max_retries:
                raise
            resp = getattr(exc, "response", None)
            retry_after = _retry_after_seconds(resp)
            backoff = (
                retry_after
                if retry_after is not None
                else min(max_backoff, pause * (2 ** (attempt - 1)))
            )
            log.warning(
                "GET %s failed (attempt %d/%d): %s — retrying in %.1fs%s",
                url,
                attempt,
                max_retries,
                exc,
                backoff,
                " (Retry-After)" if retry_after is not None else "",
            )
            time.sleep(backoff)
