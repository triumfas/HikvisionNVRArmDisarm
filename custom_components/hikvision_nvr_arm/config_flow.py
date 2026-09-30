"""Config flow for Hikvision NVR Arm/Disarm."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import (
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SSL,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from . import client_from_data, selected_triggers
from .api import (
    HikAuthError,
    HikNvrError,
    HikPermissionError,
    HikSslError,
    Trigger,
)
from .const import CONF_TRIGGERS, DEFAULT_PORT, DOMAIN, EVENT_NAMES


def _connection_schema() -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_HOST): str,
            vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
            vol.Required(CONF_SSL, default=False): bool,
            vol.Required(CONF_VERIFY_SSL, default=True): bool,
            vol.Required(CONF_USERNAME): str,
            vol.Required(CONF_PASSWORD): str,
        }
    )


def _camera(channel: int | None, names: Mapping[int, str]) -> str:
    return names.get(channel, f"Channel {channel}")


def _trigger_options(triggers: list[Trigger], names: Mapping[int, str]) -> dict[str, str]:
    """Checkbox labels like "Intrusion - Iejimas", grouped by event type."""
    ordered = sorted(triggers, key=lambda t: (EVENT_NAMES.get(t.event_type, t.event_type), t.channel or 0))
    return {t.id: f"{EVENT_NAMES.get(t.event_type, t.event_type)} - {_camera(t.channel, names)}" for t in ordered}


def _summary(triggers: list[Trigger], names: Mapping[int, str]) -> str:
    """Markdown list: one line per event type with the cameras it covers."""
    by_type: dict[str, list[str]] = {}
    for t in sorted(triggers, key=lambda t: t.channel or 0):
        by_type.setdefault(EVENT_NAMES.get(t.event_type, t.event_type), []).append(_camera(t.channel, names))
    lines = [f"- **{event}**: {', '.join(cams)}" for event, cams in sorted(by_type.items())]
    return "\n".join(lines)


class HikNvrArmConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for NVR credentials, then which events Hik-Connect push should follow."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._triggers: list[Trigger] = []
        self._names: dict[int, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return HikNvrArmOptionsFlow()

    async def _try_connect(
        self, hass_data: Mapping[str, Any]
    ) -> tuple[dict[str, str] | None, list[Trigger], dict[str, str]]:
        """Return (device info, triggers, errors)."""
        client = client_from_data(self.hass, hass_data)
        try:
            info = await client.device_info()
            triggers = await client.list_triggers()
        except HikAuthError:
            return None, [], {"base": "invalid_auth"}
        except HikPermissionError:
            return None, [], {"base": "no_permission"}
        except HikSslError:
            return None, [], {"base": "ssl_error"}
        except HikNvrError:
            return None, [], {"base": "cannot_connect"}
        return info, triggers, {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            info, triggers, errors = await self._try_connect(user_input)
            if info:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_configured()
                self._triggers = triggers
                self._names = await client_from_data(self.hass, user_input).channel_names()
                self._data = {**user_input, **info}
                return await self.async_step_review()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(_connection_schema(), user_input),
            errors=errors,
        )

    def _create(self, trigger_ids: list[str]) -> ConfigFlowResult:
        return self.async_create_entry(
            title=self._data["name"], data={**self._data, CONF_TRIGGERS: trigger_ids}
        )

    async def async_step_review(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the events that are armed on the NVR right now (the usual choice)."""
        armed = [t for t in self._triggers if t.armed]
        if not armed:  # nothing to summarise, go straight to the manual list
            return await self.async_step_triggers()
        if user_input is not None:
            if user_input["customize"]:
                return await self.async_step_triggers()
            return self._create([t.id for t in armed])
        return self.async_show_form(
            step_id="review",
            data_schema=vol.Schema({vol.Required("customize", default=False): bool}),
            description_placeholders={"summary": _summary(armed, self._names)},
        )

    async def async_step_triggers(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self._create(user_input[CONF_TRIGGERS])
        armed_now = [t.id for t in self._triggers if t.armed]
        return self.async_show_form(
            step_id="triggers",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_TRIGGERS, default=armed_now): cv.multi_select(
                        _trigger_options(self._triggers, self._names)
                    )
                }
            ),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change host, port, SSL settings or credentials of an existing NVR."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            info, _, errors = await self._try_connect(user_input)
            if info:
                await self.async_set_unique_id(info["serial"])
                self._abort_if_unique_id_mismatch(reason="wrong_device")
                self.hass.config_entries.async_update_entry(entry, data={**entry.data, **user_input})
                return self.async_abort(reason="reconfigure_successful")
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema(), user_input or entry.data
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            info, _, errors = await self._try_connect(data)
            if info:
                self.hass.config_entries.async_update_entry(entry, data=data)
                return self.async_abort(reason="reauth_successful")
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )


class HikNvrArmOptionsFlow(OptionsFlow):
    """Change which events are armed/disarmed."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_TRIGGERS: user_input[CONF_TRIGGERS]})
        client = client_from_data(self.hass, self.config_entry.data)
        try:
            triggers = await client.list_triggers()
        except HikNvrError:
            return self.async_abort(reason="cannot_connect")
        names = await client.channel_names()
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TRIGGERS, default=selected_triggers(self.config_entry)
                    ): cv.multi_select(_trigger_options(triggers, names))
                }
            ),
        )
