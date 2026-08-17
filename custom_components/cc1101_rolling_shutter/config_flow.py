"""Configuration UI (config and options flows) for the integration."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv

from .const import (
    CONF_BAUDRATE,
    CONF_NAME,
    CONF_PORT,
    CONF_SHUTTER_ID,
    CONF_SHUTTERS,
    DEFAULT_BAUDRATE,
    DEFAULT_PORT,
    DOMAIN,
    cover_key,
    normalise_shutter_id,
)

CONF_DISCOVERED = "discovered"


class CC1101ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configuration of the CC1101 serial hub."""

    # Version 2 addresses shutters by their 4-byte radio ID instead of the
    # index that used to be hardcoded in the firmware.
    VERSION = 2

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Serial port + baud rate."""
        errors: dict[str, str] = {}
        if user_input is not None:
            # A serial port can only be configured once.
            await self.async_set_unique_id(user_input[CONF_PORT])
            self._abort_if_unique_id_configured()
            return self.async_create_entry(
                title=f"CC1101 ({user_input[CONF_PORT]})",
                data={
                    CONF_PORT: user_input[CONF_PORT],
                    CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                },
                options={CONF_SHUTTERS: []},
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=DEFAULT_PORT): str,
                vol.Required(CONF_BAUDRATE, default=DEFAULT_BAUDRATE): cv.positive_int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change the serial port / baud rate without recreating the devices.

        The devices are identified from the ``entry_id`` (stable), not from the
        port: changing the port therefore keeps every shutter and its room.
        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            new_port = user_input[CONF_PORT].strip()
            if any(
                other.entry_id != entry.entry_id
                and other.data.get(CONF_PORT) == new_port
                for other in self._async_current_entries()
            ):
                errors["base"] = "already_configured"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=new_port,
                    title=f"CC1101 ({new_port})",
                    data_updates={
                        CONF_PORT: new_port,
                        CONF_BAUDRATE: user_input[CONF_BAUDRATE],
                    },
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): str,
                vol.Required(
                    CONF_BAUDRATE,
                    default=entry.data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE),
                ): cv.positive_int,
            }
        )
        return self.async_show_form(
            step_id="reconfigure", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow handler."""
        return CC1101OptionsFlow()


class CC1101OptionsFlow(OptionsFlow):
    """Options: adding and removing shutters."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the add/remove menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["add_shutter", "remove_shutter"],
        )

    def _discovery_choices(self) -> dict[str, str]:
        """Shutters heard on the air that are not configured yet.

        Empty when the entry is not loaded — the options flow must still work
        if the serial port could not be opened.
        """
        hub = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        if hub is None:
            return {}
        choices: dict[str, str] = {}
        for shutter in hub.available_discoveries():
            label = shutter.shutter_id
            if shutter.last_command:
                label = f"{label} (heard: {shutter.last_command})"
            choices[shutter.shutter_id] = label
        return choices

    async def async_step_add_shutter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a shutter, either discovered on the air or typed in."""
        errors: dict[str, str] = {}
        shutters: list[dict[str, str]] = list(
            self.config_entry.options.get(CONF_SHUTTERS, [])
        )
        choices = self._discovery_choices()

        if user_input is not None:
            typed = str(user_input.get(CONF_SHUTTER_ID, "")).strip()
            raw_id = typed or user_input.get(CONF_DISCOVERED, "")
            if not raw_id:
                errors["base"] = "id_required"
            else:
                try:
                    new_id = normalise_shutter_id(raw_id)
                except ValueError:
                    errors["base"] = "invalid_id"
                else:
                    if any(cover_key(s) == new_id for s in shutters):
                        errors["base"] = "already_exists"
                    else:
                        shutters.append(
                            {
                                CONF_SHUTTER_ID: new_id,
                                CONF_NAME: user_input[CONF_NAME].strip(),
                            }
                        )
                        return self.async_create_entry(
                            title="", data={CONF_SHUTTERS: shutters}
                        )

        fields: dict[Any, Any] = {}
        if choices:
            fields[vol.Optional(CONF_DISCOVERED)] = vol.In(choices)
        fields[vol.Optional(CONF_SHUTTER_ID, default="")] = str
        fields[vol.Required(CONF_NAME)] = str

        return self.async_show_form(
            step_id="add_shutter",
            data_schema=vol.Schema(fields),
            errors=errors,
            description_placeholders={"discovered": str(len(choices))},
        )

    async def async_step_remove_shutter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Remove one or more shutters."""
        shutters: list[dict[str, str]] = list(
            self.config_entry.options.get(CONF_SHUTTERS, [])
        )

        if user_input is not None:
            to_remove = set(user_input.get("to_remove", []))
            remaining = [s for s in shutters if cover_key(s) not in to_remove]
            return self.async_create_entry(title="", data={CONF_SHUTTERS: remaining})

        if not shutters:
            return self.async_abort(reason="no_shutters")

        choices = {
            cover_key(s): f"{s[CONF_NAME]} ({cover_key(s)})" for s in shutters
        }
        schema = vol.Schema(
            {vol.Optional("to_remove", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_shutter", data_schema=schema)
