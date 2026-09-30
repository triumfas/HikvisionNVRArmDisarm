"""Arm/disarm Hik-Connect notifications on a Hikvision NVR."""

from __future__ import annotations

from datetime import timedelta
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import HikAuthError, HikNvrClient, HikNvrError, HikPermissionError, Trigger
from .const import CONF_TRIGGERS, DOMAIN, SCAN_INTERVAL_SECONDS

_LOGGER = logging.getLogger(__name__)
PLATFORMS = [Platform.SWITCH]


def selected_triggers(entry: ConfigEntry) -> list[str]:
    """Trigger ids this entry controls (options override the initial selection)."""
    return list(entry.options.get(CONF_TRIGGERS, entry.data[CONF_TRIGGERS]))


class NvrCoordinator(DataUpdateCoordinator[dict[str, Trigger]]):
    """Polls which of the selected triggers currently notify the surveillance center."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: HikNvrClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.client = client
        self.entry = entry

    async def _async_update_data(self) -> dict[str, Trigger]:
        try:
            triggers = await self.client.list_triggers()
        except (HikAuthError, HikPermissionError) as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except HikNvrError as err:
            raise UpdateFailed(str(err)) from err
        wanted = set(selected_triggers(self.entry))
        return {t.id: t for t in triggers if t.id in wanted}


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    client = HikNvrClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.data[CONF_USERNAME],
        entry.data[CONF_PASSWORD],
    )
    coordinator = NvrCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_reload_on_options))
    return True


async def _reload_on_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if unloaded := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)
    return unloaded
