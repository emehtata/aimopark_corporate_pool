"""DataUpdateCoordinator for the Aimo Park integration.

Handles:
- Azure B2C refresh-token grant (token rotation included)
- Time-windowed caching (fast / normal / offline) matching Helsinki timezone
- Force-refresh flag for on-demand bypasses
"""
from __future__ import annotations

import base64
import datetime
import json
import logging
import random
import time
from zoneinfo import ZoneInfo

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .auth import AimoAuthError, async_password_login
from .const import (
    AIMO_BFF_URL,
    AIMO_CLIENT_ID,
    AIMO_READ_PERMITS_QUERY,
    AIMO_TOKEN_URL,
    CONF_COUNTRY_CODE,
    CONF_NORMAL_CACHE_TTL,
    CONF_OFFLINE_CACHE_TTL_MAX,
    CONF_OFFLINE_CACHE_TTL_MIN,
    CONF_POOL_ID,
    CONF_REFRESH_TOKEN,
    CONF_WINDOW_BUSY_END,
    CONF_WINDOW_BUSY_START,
    CONF_WINDOW_NORMAL_END,
    COORDINATOR_POLL_INTERVAL,
    DOMAIN,
    HELSINKI_TZ,
    NORMAL_CACHE_TTL,
    OFFLINE_CACHE_TTL_MAX,
    OFFLINE_CACHE_TTL_MIN,
    WINDOW_FAST_END,
    WINDOW_FAST_START,
    WINDOW_NORMAL_END,
)

_LOGGER = logging.getLogger(__name__)
_HELSINKI = ZoneInfo(HELSINKI_TZ)


class AimoParkCoordinator(DataUpdateCoordinator[dict]):
    """Coordinator that polls the Aimo Park BFF respecting time-based windows."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._entry = entry

        # In-memory access token cache (reset on HA restart)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

        # Result cache shared across all windows
        self._result_cache: dict | None = None
        self._result_fetched_at: float = 0.0
        self._offline_ttl: int = OFFLINE_CACHE_TTL_MIN

        # Set to True to skip cache on the next _async_update_data call
        self._force_next: bool = False
        self._auth_retry_at: float = 0.0

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=datetime.timedelta(seconds=COORDINATOR_POLL_INTERVAL),
        )

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    @property
    def pool_filter(self) -> str | None:
        """Optional pool ID restricting discovery to a single pool."""
        return self._entry.data.get(CONF_POOL_ID) or None

    @property
    def country_code(self) -> str:
        return self._entry.data.get(CONF_COUNTRY_CODE, "FI")

    def request_force_refresh(self) -> None:
        """Mark the next scheduled (or manual) refresh as a forced cache bypass."""
        self._force_next = True

    # ------------------------------------------------------------------
    # HA DataUpdateCoordinator interface
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict:
        """Return pool capacity data, respecting the time-window cache."""
        force = self._force_next
        self._force_next = False

        window = self._poll_window()
        age = time.monotonic() - self._result_fetched_at

        if not force and self._result_cache:
            if window is None and age < self._offline_ttl:
                _LOGGER.debug(
                    "Aimo Park: offline window, serving cache (age=%.0fs / ttl=%ds)",
                    age,
                    self._offline_ttl,
                )
                return self._result_cache
            normal_ttl = self._entry.options.get(CONF_NORMAL_CACHE_TTL, NORMAL_CACHE_TTL)
            if window == "normal" and age < normal_ttl:
                _LOGGER.debug(
                    "Aimo Park: normal window, serving cache (age=%.0fs)", age
                )
                return self._result_cache
            # "fast" window — always fall through and fetch

        _LOGGER.info(
            "Aimo Park: fetching from BFF (window=%s, force=%s)",
            window,
            force,
        )
        result = await self._fetch_pools()

        # Store to cache
        self._result_cache = result
        self._result_fetched_at = time.monotonic()
        ttl_min = self._entry.options.get(CONF_OFFLINE_CACHE_TTL_MIN, OFFLINE_CACHE_TTL_MIN)
        ttl_max = self._entry.options.get(CONF_OFFLINE_CACHE_TTL_MAX, OFFLINE_CACHE_TTL_MAX)
        self._offline_ttl = random.randint(ttl_min, ttl_max)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_window_time(self, option_key: str, default: datetime.time) -> datetime.time:
        """Parse a HH:MM string from entry options, falling back to default."""
        val = self._entry.options.get(option_key)
        if val:
            try:
                h, m = str(val).split(":", 1)
                return datetime.time(int(h), int(m))
            except (ValueError, AttributeError):
                pass
        return default

    def _poll_window(self) -> str | None:
        """Return "fast", "normal", or None based on Helsinki local time."""
        now = datetime.datetime.now(_HELSINKI)
        if now.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return None
        t = now.time()
        busy_start = self._get_window_time(CONF_WINDOW_BUSY_START, WINDOW_FAST_START)
        busy_end   = self._get_window_time(CONF_WINDOW_BUSY_END, WINDOW_FAST_END)
        normal_end = self._get_window_time(CONF_WINDOW_NORMAL_END, WINDOW_NORMAL_END)
        if busy_start <= t < busy_end:
            return "fast"
        if busy_end <= t < normal_end:
            return "normal"
        return None

    @staticmethod
    def _decode_jwt_claims(token: str) -> dict:
        try:
            payload_b64 = token.split(".")[1]
            payload_b64 += "=" * (-len(payload_b64) % 4)
            return json.loads(base64.urlsafe_b64decode(payload_b64))
        except Exception:  # noqa: BLE001
            return {}

    async def _request_refresh_grant(self, refresh_token: str) -> dict | None:
        """Exchange a refresh token; returns the token response or None on failure."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                AIMO_TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "client_id": AIMO_CLIENT_ID,
                    "scope": AIMO_CLIENT_ID,
                    "refresh_token": refresh_token,
                },
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    _LOGGER.warning(
                        "Aimo Park: token refresh returned %s: %s", resp.status, text
                    )
                    return None
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            _LOGGER.error("Aimo Park: token refresh request failed: %s", err)
            return None

    async def _refresh_access_token(self) -> str | None:
        """Get a new access token via the refresh token, else via username/password."""
        if time.monotonic() < self._auth_retry_at:
            raise ConfigEntryAuthFailed("Aimo Park authentication requires re-authentication")

        refresh_token = self._entry.data.get(CONF_REFRESH_TOKEN)
        j = await self._request_refresh_grant(refresh_token) if refresh_token else None

        username = self._entry.data.get(CONF_USERNAME)
        stored_password = self._entry.data.get(CONF_PASSWORD, "")
        password = self._decode_password(stored_password)
        if password and not stored_password.startswith("base64:"):
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={
                    **self._entry.data,
                    CONF_PASSWORD: self._encode_password(password),
                },
            )
        if not (j and j.get("access_token")) and username and password:
            _LOGGER.info("Aimo Park: logging in with username and password")
            try:
                j = await async_password_login(username, password)
            except AimoAuthError as err:
                _LOGGER.error("Aimo Park: login failed: %s", err.key)
                self._auth_retry_at = time.monotonic() + 900
                raise ConfigEntryAuthFailed(
                    "Aimo Park username/password authentication failed"
                ) from err

        if not j or not j.get("access_token"):
            self._auth_retry_at = time.monotonic() + 900
            raise ConfigEntryAuthFailed("Aimo Park authentication requires re-authentication")

        access_token = j["access_token"]
        self._access_token = access_token
        self._token_expires_at = (
            time.monotonic() + j.get("expires_in", 3600) - 60
        )

        # Persist the refresh token whenever the server issued a new one
        new_rt = j.get("refresh_token")
        if new_rt and new_rt != refresh_token:
            self.hass.config_entries.async_update_entry(
                self._entry,
                data={**self._entry.data, CONF_REFRESH_TOKEN: new_rt},
            )
            _LOGGER.debug("Aimo Park: refresh token rotated")

        claims = self._decode_jwt_claims(access_token)
        _LOGGER.info(
            "Aimo Park: access token refreshed — sub=%s exp=%s",
            claims.get("sub"),
            claims.get("exp"),
        )
        return access_token

    @staticmethod
    def _decode_password(value: str) -> str:
        """Decode the current base64 form and support pre-0.2.0 entries."""
        if not value.startswith("base64:"):
            return value
        try:
            return base64.b64decode(value[7:]).decode()
        except (ValueError, UnicodeDecodeError):
            return ""

    @staticmethod
    def _encode_password(value: str) -> str:
        """Encode a password for storage without changing its value."""
        return f"base64:{base64.b64encode(value.encode()).decode()}"

    async def _get_access_token(self) -> str | None:
        """Return a cached access token, refreshing it if expired or missing."""
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token
        return await self._refresh_access_token()

    async def _fetch_pools(self) -> dict:
        """Query the Aimo BFF and return {"pools": {uid: {"name", "free", "size"}}}."""
        token = await self._get_access_token()
        if not token:
            raise UpdateFailed("Failed to obtain Aimo Park access token")

        payload = {
            "operationName": "ReadUnifyPermits",
            "variables": {},
            "query": AIMO_READ_PERMITS_QUERY,
        }
        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": token,
            "X-Country-Code": self.country_code,
        }

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                AIMO_BFF_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 401:
                    # Invalidate so the next call forces a fresh token
                    self._access_token = None
                    self._token_expires_at = 0.0
                    text = await resp.text()
                    raise UpdateFailed(
                        f"Aimo BFF 401 Unauthorized — token rejected. Detail: {text[:200]}"
                    )
                if resp.status != 200:
                    text = await resp.text()
                    raise UpdateFailed(
                        f"Aimo BFF returned HTTP {resp.status}: {text[:200]}"
                    )
                j = await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Aimo BFF request failed: {err}") from err

        errors = j.get("errors")
        if errors:
            codes = [e.get("extensions", {}).get("code") for e in errors]
            if "UNAUTHENTICATED" in codes:
                self._access_token = None
                self._token_expires_at = 0.0
            raise UpdateFailed(f"Aimo BFF GraphQL errors: {errors}")

        try:
            permits = j["data"]["readUnifyPermits"]
        except (KeyError, TypeError) as err:
            raise UpdateFailed(
                f"Unexpected Aimo BFF response shape: {j}"
            ) from err

        # A pool can appear under several permits, so key by uid
        pools: dict[str, dict] = {}
        for permit in permits or []:
            for pool in permit.get("accessPermitPoolingGroupInfo") or []:
                uid = pool.get("uid")
                if not uid or (self.pool_filter and uid != self.pool_filter):
                    continue
                pools[uid] = {
                    "name": pool.get("name"),
                    "free": pool.get("freePoolingSpots"),
                    "size": pool.get("poolSize"),
                }

        if not pools:
            _LOGGER.warning(
                "Aimo Park: no pooling groups found%s",
                f" matching pool_id {self.pool_filter}" if self.pool_filter else "",
            )
        return {"pools": pools}
