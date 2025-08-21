"""The Amaran integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform
from .const import DOMAIN
from .api import AmaranAPI

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.LIGHT]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Amaran from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Create API instance
    api = AmaranAPI(
        entry.data["host"],
        entry.data["port"],
        entry.data["api_key"]
    )

    # Connect to WebSocket
    if not await api.connect():
        return False

    hass.data[DOMAIN][entry.entry_id] = api

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        api = hass.data[DOMAIN].pop(entry.entry_id)
        api.disconnect()

    return unload_ok
