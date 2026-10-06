"""Config flow for the Aimo Park integration."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .auth import AimoAuthError, async_password_login
from .const import (
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


_SETUP_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Optional(CONF_POOL_ID, default=""): str,
        vol.Optional(CONF_COUNTRY_CODE, default="FI"): str,
    }
).extend(_options_schema({}).schema)

_OPTION_KEYS = tuple(_options_schema({}).schema)


def _validate_options(user_input: dict) -> dict[str, str]:
    """Normalise the HH:MM fields in place and return any errors by field."""
    errors: dict[str, str] = {}
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
    return errors


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
            username = user_input.get(CONF_USERNAME, "").strip()
            password = user_input.get(CONF_PASSWORD, "")

            if not username:
                errors[CONF_USERNAME] = "required"
            if not password:
                errors[CONF_PASSWORD] = "required"
            errors.update(_validate_options(user_input))

            tokens: dict = {}
            if not errors:
                try:
                    tokens = await async_password_login(username, password)
                except AimoAuthError as err:
                    errors["base"] = err.key

            if not errors:
                await self.async_set_unique_id(username.lower())
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"Aimo Park ({pool_id})" if pool_id else "Aimo Park",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_REFRESH_TOKEN: tokens.get("refresh_token"),
                        CONF_POOL_ID: pool_id,
                        CONF_COUNTRY_CODE: user_input.get(CONF_COUNTRY_CODE, "FI"),
                    },
                    options={k: user_input[k] for k in _OPTION_KEYS if k in user_input},
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
            errors = _validate_options(user_input)

            if not errors:
                return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(self._config_entry.options),
            errors=errors,
        )
