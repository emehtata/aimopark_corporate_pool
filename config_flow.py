"""Config flow for the Aimo Park integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    AIMO_CLIENT_ID,
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
    DEFAULT_WINDOW_BUSY_END,
    DEFAULT_WINDOW_BUSY_START,
    DEFAULT_WINDOW_NORMAL_END,
    DOMAIN,
    NORMAL_CACHE_TTL,
    OFFLINE_CACHE_TTL_MAX,
    OFFLINE_CACHE_TTL_MIN,
)
from .coordinator import AimoParkCoordinator

_SETUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_REFRESH_TOKEN): str,
        vol.Optional(CONF_POOL_ID, default=""): str,
        vol.Optional(CONF_COUNTRY_CODE, default="FI"): str,
    }
)


async def _validate_refresh_token(
    hass: HomeAssistant, refresh_token: str
) -> tuple[str | None, str | None]:
    """Exchange the refresh token and return (error key, account sub claim)."""
    session = async_get_clientsession(hass)
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
                return "invalid_auth", None
            j = await resp.json(content_type=None)
            if not j.get("access_token"):
                return "invalid_auth", None
    except aiohttp.ClientError:
        return "cannot_connect", None
    claims = AimoParkCoordinator._decode_jwt_claims(j["access_token"])
    return None, claims.get("sub")


def _time_str(value: str) -> str:
    """Validate and normalise an HH:MM string. Raises ValueError on bad input."""
    try:
        h, m = value.strip().split(":")
        return f"{int(h):02d}:{int(m):02d}"
    except (ValueError, AttributeError) as err:
        raise ValueError("Expected HH:MM format") from err


def _options_schema(current: dict) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(
                CONF_WINDOW_BUSY_START,
                default=current.get(CONF_WINDOW_BUSY_START, DEFAULT_WINDOW_BUSY_START),
            ): str,
            vol.Optional(
                CONF_WINDOW_BUSY_END,
                default=current.get(CONF_WINDOW_BUSY_END, DEFAULT_WINDOW_BUSY_END),
            ): str,
            vol.Optional(
                CONF_WINDOW_NORMAL_END,
                default=current.get(CONF_WINDOW_NORMAL_END, DEFAULT_WINDOW_NORMAL_END),
            ): str,
            vol.Optional(
                CONF_NORMAL_CACHE_TTL,
                default=current.get(CONF_NORMAL_CACHE_TTL, NORMAL_CACHE_TTL),
            ): vol.All(vol.Coerce(int), vol.Range(min=30)),
            vol.Optional(
                CONF_OFFLINE_CACHE_TTL_MIN,
                default=current.get(CONF_OFFLINE_CACHE_TTL_MIN, OFFLINE_CACHE_TTL_MIN),
            ): vol.All(vol.Coerce(int), vol.Range(min=60)),
            vol.Optional(
                CONF_OFFLINE_CACHE_TTL_MAX,
                default=current.get(CONF_OFFLINE_CACHE_TTL_MAX, OFFLINE_CACHE_TTL_MAX),
            ): vol.All(vol.Coerce(int), vol.Range(min=60)),
        }
    )


class AimoParkConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aimo Park."""

    VERSION = 1

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return AimoParkOptionsFlow(config_entry)

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            pool_id = user_input.get(CONF_POOL_ID, "").strip()
            refresh_token = user_input.get(CONF_REFRESH_TOKEN, "").strip()

            if not refresh_token:
                errors[CONF_REFRESH_TOKEN] = "required"

            if not errors:
                token_error, account_id = await _validate_refresh_token(
                    self.hass, refresh_token
                )
                if token_error:
                    errors[CONF_REFRESH_TOKEN] = token_error

            if not errors:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Aimo Park ({pool_id})" if pool_id else "Aimo Park",
                    data={
                        CONF_REFRESH_TOKEN: refresh_token,
                        CONF_POOL_ID: pool_id,
                        CONF_COUNTRY_CODE: user_input.get(CONF_COUNTRY_CODE, "FI"),
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=_SETUP_SCHEMA,
            errors=errors,
        )


class AimoParkOptionsFlow(config_entries.OptionsFlow):
    """Handle options (polling windows & cache TTLs) for Aimo Park."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate and normalise HH:MM fields
            for key in (CONF_WINDOW_BUSY_START, CONF_WINDOW_BUSY_END, CONF_WINDOW_NORMAL_END):
                try:
                    user_input[key] = _time_str(user_input[key])
                except (ValueError, KeyError):
                    errors[key] = "invalid_time"

            if not errors:
                ttl_min = user_input.get(CONF_OFFLINE_CACHE_TTL_MIN, OFFLINE_CACHE_TTL_MIN)
                ttl_max = user_input.get(CONF_OFFLINE_CACHE_TTL_MAX, OFFLINE_CACHE_TTL_MAX)
                if ttl_min >= ttl_max:
                    errors[CONF_OFFLINE_CACHE_TTL_MIN] = "ttl_min_gte_max"

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self._config_entry.options),
            errors=errors,
        )
