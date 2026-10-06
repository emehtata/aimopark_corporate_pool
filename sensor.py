"""Sensor platform for the Aimo Park integration."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
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
    known: set[str] = set()

    @callback
    def _add_new_pools() -> None:
        new = set(coordinator.data["pools"]) - known
        known.update(new)
        async_add_entities(
            [AimoParkFreeSpacesSensor(coordinator, uid) for uid in sorted(new)]
        )

    _add_new_pools()
    entry.async_on_unload(coordinator.async_add_listener(_add_new_pools))


class AimoParkFreeSpacesSensor(CoordinatorEntity[AimoParkCoordinator], SensorEntity):
    """Number of free spaces in one Aimo Park pooling group."""

    _attr_has_entity_name = True
    _attr_name = "Free spaces"
    _attr_icon = "mdi:parking"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "spaces"

    def __init__(self, coordinator: AimoParkCoordinator, pool_id: str) -> None:
        super().__init__(coordinator)
        self._pool_id = pool_id
        self._attr_unique_id = f"{pool_id}_free_spaces"

    @property
    def _pool(self) -> dict | None:
        return (self.coordinator.data or {}).get("pools", {}).get(self._pool_id)

    @property
    def available(self) -> bool:
        return super().available and self._pool is not None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._pool_id)},
            name=(self._pool or {}).get("name") or "Aimo Park Corporate Pool",
            manufacturer="Aimo Park",
            model=self._pool_id,
        )

    @property
    def native_value(self) -> int | None:
        return (self._pool or {}).get("free")

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "pool_id": self._pool_id,
            "pool_size": (self._pool or {}).get("size"),
        }
