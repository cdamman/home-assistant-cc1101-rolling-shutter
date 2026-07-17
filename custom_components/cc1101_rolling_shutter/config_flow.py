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
)


class CC1101ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Initial configuration: the serial port and its baud rate."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
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
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

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
            # Prevent two entries from pointing at the same port.
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

    async def async_step_add_shutter(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a shutter (ID + name)."""
        errors: dict[str, str] = {}
        shutters: list[dict[str, str]] = list(
            self.config_entry.options.get(CONF_SHUTTERS, [])
        )

        if user_input is not None:
            new_id = str(user_input[CONF_SHUTTER_ID]).strip()
            if any(s[CONF_SHUTTER_ID] == new_id for s in shutters):
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

        schema = vol.Schema(
            {
                vol.Required(CONF_SHUTTER_ID): str,
                vol.Required(CONF_NAME): str,
            }
        )
        return self.async_show_form(
            step_id="add_shutter", data_schema=schema, errors=errors
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
            remaining = [
                s for s in shutters if s[CONF_SHUTTER_ID] not in to_remove
            ]
            return self.async_create_entry(title="", data={CONF_SHUTTERS: remaining})

        if not shutters:
            # Nothing to remove: go back to the menu.
            return self.async_abort(reason="no_shutters")

        choices = {
            s[CONF_SHUTTER_ID]: f"{s[CONF_NAME]} (id {s[CONF_SHUTTER_ID]})"
            for s in shutters
        }
        schema = vol.Schema(
            {vol.Optional("to_remove", default=[]): cv.multi_select(choices)}
        )
        return self.async_show_form(step_id="remove_shutter", data_schema=schema)
