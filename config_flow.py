"""Config flow for Amaran integration."""
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from .const import DOMAIN, CONF_API_KEY, CONF_HOST, CONF_PORT, DEFAULT_HOST, DEFAULT_PORT

class AmaranConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Amaran."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle user config flow."""
        errors = {}

        if user_input is not None:
            # Test connection
            from .api import AmaranAPI
            api = AmaranAPI(
                user_input[CONF_HOST],
                user_input[CONF_PORT],
                user_input[CONF_API_KEY]
            )

            if await api.connect():
                api.disconnect()
                return self.async_create_entry(
                    title="Amaran Lighting",
                    data=user_input
                )
            else:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY, default=API_KEY if 'API_KEY' in locals() else ""): str,
                vol.Optional(CONF_HOST, default=DEFAULT_HOST): str,
                vol.Optional(CONF_PORT, default=DEFAULT_PORT): int,
            }),
            errors=errors
        )
