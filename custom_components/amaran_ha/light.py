"""Light platform for Amaran."""
import logging
from typing import Any, Optional
from homeassistant.components.light import (
    LightEntity,
    ColorMode,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amaran lights."""
    api = hass.data[DOMAIN][config_entry.entry_id]

    # Create light entities for all discovered devices
    lights = []
    for device_id, device_data in api.devices.items():
        lights.append(AmaranLight(api, device_id, device_data))

    async_add_entities(lights, True)

class AmaranLight(LightEntity):
    """Representation of an Amaran light."""

    def __init__(self, api, device_id, device_data):
        """Initialize the light."""
        self._api = api
        self._device_id = device_id
        self._attr_unique_id = device_id
        self._attr_name = device_data.get("name", f"Amaran {device_id}")
        self._state = False
        self._brightness = 0
        self._cct = 5500
        self._gm = 0
        self._hue = 0
        self._saturation = 0

        # Set supported features
        self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        self._attr_color_mode = ColorMode.COLOR_TEMP

    async def async_update(self):
        """Update device state."""
        state = await self._api.get_device_state(self._device_id)
        if state:
            self._state = state.get("is_on", False)
            self._brightness = state.get("brightness", 0)
            self._cct = state.get("cct", 5500)
            self._gm = state.get("gm", 0)

            # Check if we're actually in HSI mode by looking at saturation
            # CCT mode returns bogus HSI values with low saturation
            if state.get("mode") == "hsi" or state.get("sat", 0) > 70:
                self._attr_color_mode = ColorMode.HS
                self._hue = state.get("hue", 0)
                self._saturation = state.get("sat", 0)
            else:
                # In CCT mode - don't use the bogus HSI values
                self._attr_color_mode = ColorMode.COLOR_TEMP
                self._hue = 0
                self._saturation = 0

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state

    @property
    def brightness(self) -> Optional[int]:
        """Return brightness."""
        return int(self._brightness * 2.55)  # Convert 0-100 to 0-255

    @property
    def hs_color(self) -> Optional[tuple]:
        """Return HS color."""
        if self._attr_color_mode == ColorMode.HS:
            return (self._hue, self._saturation)
        return None

    @property
    def color_temp_kelvin(self) -> Optional[int]:
        """Return color temperature in Kelvin."""
        if self._attr_color_mode == ColorMode.COLOR_TEMP:
            return self._cct
        return None

    @property
    def min_color_temp_kelvin(self) -> int:
        """Return minimum color temp."""
        return 2000

    @property
    def max_color_temp_kelvin(self) -> int:
        """Return maximum color temp."""
        return 10000

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light."""
        await self._api.set_power(self._device_id, True)

        if ATTR_BRIGHTNESS in kwargs:
            brightness = int(kwargs[ATTR_BRIGHTNESS] / 2.55)
            await self._api.set_brightness(self._device_id, brightness)

        if ATTR_HS_COLOR in kwargs:
            hue, saturation = kwargs[ATTR_HS_COLOR]
            self._attr_color_mode = ColorMode.HS
            self._hue = hue
            self._saturation = saturation
            # Use current brightness, not saturation for intensity
            current_brightness = self._brightness if self._brightness > 0 else 100
            await self._api.set_hsi(self._device_id, int(hue), int(saturation), int(current_brightness * 10))

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            await self._api.set_cct(self._device_id, kwargs[ATTR_COLOR_TEMP_KELVIN])

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        await self._api.set_power(self._device_id, False)
