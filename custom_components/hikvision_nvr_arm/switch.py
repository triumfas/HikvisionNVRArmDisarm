"""Switch: on = Hik-Connect notifications armed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NvrCoordinator, selected_triggers
from .api import HikNvrError
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ArmSwitch(hass.data[DOMAIN][entry.entry_id], entry)])


class ArmSwitch(CoordinatorEntity[NvrCoordinator], SwitchEntity):
    """Armed = every selected event notifies the surveillance center (Hik-Connect push)."""

    _attr_has_entity_name = True
    _attr_translation_key = "notifications"
    _attr_icon = "mdi:shield-home"

    def __init__(self, coordinator: NvrCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._pending: bool | None = None  # target state while a change is being applied
        self._attr_unique_id = f"{entry.unique_id}_hikconnect_notifications"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.unique_id)},
            name=entry.data.get("name", "NVR"),
            manufacturer="Hikvision",
            model=entry.data.get("model"),
            sw_version=entry.data.get("firmware"),
        )

    @property
    def is_on(self) -> bool | None:
        """True if all armed, False if all disarmed, None (unknown) if mixed."""
        if self._pending is not None:
            return self._pending
        states = {t.armed for t in self.coordinator.data.values()}
        if len(states) == 1:
            return states.pop()
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        return {
            "armed_events": sorted(t.id for t in data.values() if t.armed),
            "disarmed_events": sorted(t.id for t in data.values() if not t.armed),
            "partial": len({t.armed for t in data.values()}) > 1,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    async def _set(self, armed: bool) -> None:
        self._pending = armed  # show the requested state right away, applying takes seconds
        self.async_write_ha_state()
        try:
            failed = await self.coordinator.client.set_armed(selected_triggers(self._entry), armed)
            # Verify from the NVR, not from what we think we wrote.
            await self.coordinator.async_refresh()
        except HikNvrError as err:
            raise HomeAssistantError(f"NVR error: {err}") from err
        finally:
            self._pending = None
            self.async_write_ha_state()
        wrong = [t.id for t in self.coordinator.data.values() if t.armed != armed]
        if failed or wrong:
            raise HomeAssistantError(
                f"{'Arm' if armed else 'Disarm'} failed for: {', '.join(sorted(set(failed) | set(wrong)))}"
            )
