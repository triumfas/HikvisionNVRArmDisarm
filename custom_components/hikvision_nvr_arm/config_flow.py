"""Config flow for Hikvision NVR Arm/Disarm."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from . import selected_triggers
from .api import HikAuthError, HikNvrClient, HikNvrError, HikPermissionError, Trigger
from .const import CONF_TRIGGERS, DEFAULT_PORT, DOMAIN

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _trigger_options(triggers: list[Trigger]) -> dict[str, str]:
    return {t.id: f"Channel {t.channel} - {t.event_type} ({t.id})" for t in triggers}


class HikNvrArmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for NVR credentials, then which events Hik-Connect push should follow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._triggers: list[Trigger] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return HikNvrArmOptionsFlow()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = HikNvrClient(
                async_get_clientsession(self.hass),
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_USERNAME],
                user_input[CONF_PASSWORD],
            )
            try:
                info = await client.device_info()
                self._triggers = await client.list_triggers()
            except HikAuthError:
                errors["base"] = "invalid_auth"
            except HikPermissionError:
                errors["base"] = "no_permission"
            except HikNvrError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured()
                self._data = {**user_input, **info}
                return await self.async_step_triggers()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(USER_SCHEMA, user_input),
            errors=errors,
        )

    async def async_step_triggers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title=self._data["name"],
                data={**self._data, CONF_TRIGGERS: user_input[CONF_TRIGGERS]},
            )
        armed_now = [t.id for t in self._triggers if t.armed]
        return self.async_show_form(
            step_id="triggers",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRIGGERS, default=armed_now): cv.multi_select(
                        _trigger_options(self._triggers)
                    )
                }
            ),
        )


class HikNvrArmOptionsFlow(OptionsFlow):
    """Change which events are armed/disarmed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_TRIGGERS: user_input[CONF_TRIGGERS]})
        data = self.config_entry.data
        client = HikNvrClient(
            async_get_clientsession(self.hass),
            data[CONF_HOST],
            data[CONF_PORT],
            data[CONF_USERNAME],
            data[CONF_PASSWORD],
        )
        try:
            triggers = await client.list_triggers()
        except HikNvrError:
            return self.async_abort(reason="cannot_connect")
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TRIGGERS, default=selected_triggers(self.config_entry)
                    ): cv.multi_select(_trigger_options(triggers))
                }
            ),
        )
