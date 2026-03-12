"""Sensor platform for the Aimo Park integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AimoParkCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AimoParkCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AimoParkFreeSpacesSensor(coordinator)])


class AimoParkFreeSpacesSensor(CoordinatorEntity[AimoParkCoordinator], SensorEntity):
    """Number of free spaces in the configured Aimo Park corporate pool."""

    _attr_has_entity_name = True
    _attr_name = "Free spaces"
    _attr_icon = "mdi:parking"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "spaces"

    def __init__(self, coordinator: AimoParkCoordinator) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.pool_id}_free_spaces"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.pool_id)},
            name="Aimo Park Corporate Pool",
            manufacturer="Aimo Park",
            model=self.coordinator.pool_id,
        )

    @property
    def native_value(self) -> int | None:
        if self.coordinator.data:
            return self.coordinator.data.get("free")
        return None

    @property
    def extra_state_attributes(self) -> dict:
        data = self.coordinator.data or {}
        return {
            "pool_id": data.get("pool_id"),
        }
