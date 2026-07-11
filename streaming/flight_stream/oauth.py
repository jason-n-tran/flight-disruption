"""OAuth2 token caching for sustained OpenSky polling.

``flight_ingest`` already implements the client-credentials exchange (and the
anonymous fallback). For a one-shot snapshot it fetches a fresh token each call,
which is fine. The continuous producer, however, polls for hours — so we cache
the token and refresh it shortly BEFORE it expires rather than per request.

This wrapper does NOT duplicate the token exchange; it delegates to
``flight_ingest.opensky.get_access_token`` and only adds expiry bookkeeping.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from flight_ingest.config import Settings
from flight_ingest.opensky import get_access_token as _ingest_get_token

log = logging.getLogger("flight_stream.oauth")

# OpenSky access tokens last ~30 min; refresh with a safety margin before expiry.
DEFAULT_TOKEN_TTL_SECONDS = 1800
DEFAULT_REFRESH_MARGIN_SECONDS = 60


class TokenCache:
    """Caches an OpenSky bearer token and refreshes it before expiry.

    Anonymous mode (no creds) yields ``None`` tokens; we cache that decision too
    so we do not spam the token endpoint when running unauthenticated.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
        refresh_margin_seconds: int = DEFAULT_REFRESH_MARGIN_SECONDS,
        fetcher: Callable[[Settings], str | None] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        self._ttl = ttl_seconds
        self._margin = refresh_margin_seconds
        self._fetch = fetcher or _ingest_get_token
        self._clock = clock
        self._token: str | None = None
        self._expires_at: float = 0.0
        self._has_creds = bool(
            settings.opensky_client_id and settings.opensky_client_secret
        )
        self._fetched_once = False

    @property
    def authenticated(self) -> bool:
        return self._has_creds

    def _expired(self) -> bool:
        return self._clock() >= (self._expires_at - self._margin)

    def get_token(self, *, force_refresh: bool = False) -> str | None:
        """Return a valid bearer token (or None in anonymous mode).

        Refreshes when the cached token is missing/near-expiry. In anonymous
        mode the first call records the (None) decision and subsequent calls
        short-circuit without hitting the network.
        """
        if not self._has_creds:
            if not self._fetched_once:
                # Logs the anonymous-fallback warning exactly once, via ingest.
                self._token = self._fetch(self._settings)
                self._fetched_once = True
            return self._token

        if force_refresh or self._token is None or self._expired():
            token = self._fetch(self._settings)
            self._fetched_once = True
            if token is None:
                # Creds present but exchange failed: degrade to anonymous for
                # this cycle, retry next cycle (don't crash the producer loop).
                log.warning("Token refresh returned no token; using anonymous this cycle.")
                self._token = None
                self._expires_at = self._clock() + self._margin
            else:
                self._token = token
                self._expires_at = self._clock() + self._ttl
                log.info("Refreshed OpenSky access token (valid ~%ds).", self._ttl)
        return self._token
