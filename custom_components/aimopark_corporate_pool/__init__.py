"""Aimo Park integration for Home Assistant.

Provides a sensor for the number of free spaces in an employer's
Aimo Park corporate pool, with time-windowed caching and a
force-refresh service.
"""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN
from .coordinator import AimoParkCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_FORCE_REFRESH = "force_refresh"
SERVICE_SCHEMA = vol.Schema(
    {vol.Optional("entry_id"): cv.string}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aimo Park from a config entry."""
    coordinator = AimoParkCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register service only once (when the first entry is loaded)
    if not hass.services.has_service(DOMAIN, SERVICE_FORCE_REFRESH):

        async def _handle_force_refresh(call: ServiceCall) -> None:
            """Mark next refresh as forced for the specified (or all) entry/entries."""
            target_entry_id = call.data.get("entry_id")
            for eid, coord in hass.data.get(DOMAIN, {}).items():
                if target_entry_id is None or eid == target_entry_id:
                    coord.request_force_refresh()
                    await coord.async_refresh()

        hass.services.async_register(
            DOMAIN,
            SERVICE_FORCE_REFRESH,
            _handle_force_refresh,
            schema=SERVICE_SCHEMA,
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Remove service when no entries remain
    if not hass.data.get(DOMAIN):
        hass.services.async_remove(DOMAIN, SERVICE_FORCE_REFRESH)

    return unload_ok
