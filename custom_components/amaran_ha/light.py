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
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Amaran lights."""
    api = hass.data[DOMAIN][config_entry.entry_id]

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

        # State attributes
        self._attr_is_on = False
        self._attr_brightness = 0
        self._attr_color_temp_kelvin = 5500
        self._attr_hs_color = None
        self._gm = 100
        self._available = True

        # Track last set mode to ignore device's fake HSI values
        self._last_set_mode = ColorMode.COLOR_TEMP

        # Color mode tracking
        self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        self._attr_color_mode = ColorMode.COLOR_TEMP

        # Temperature bounds
        self._attr_min_color_temp_kelvin = 2000
        self._attr_max_color_temp_kelvin = 10000

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self._available and self._api.connected

    async def async_update(self):
        """Update device state."""
        try:
            state = await self._api.get_device_state(self._device_id)
            _LOGGER.debug(f"Raw state from API: {state}")

            if state:
                self._available = True
                self._attr_is_on = state.get("is_on", False)

                # Update brightness (convert from 0-100 to 0-255)
                brightness_percent = state.get("brightness", 0)
                self._attr_brightness = int(brightness_percent * 2.55)

                # Store raw values
                cct = state.get("cct", 5500)
                hue = state.get("hue", 0)
                sat = state.get("sat", 0)
                self._gm = state.get("gm", 100)

                # Use last explicitly set mode, don't trust device's HSI values in CCT mode
                if self._last_set_mode == ColorMode.COLOR_TEMP:
                    self._attr_color_mode = ColorMode.COLOR_TEMP
                    self._attr_color_temp_kelvin = cct
                    self._attr_hs_color = None
                else:
                    # Only switch to HS mode if we explicitly set it or saturation is very high
                    if sat > 85:  # High saturation definitely means HSI mode
                        self._attr_color_mode = ColorMode.HS
                        self._attr_hs_color = (hue, sat)
                        self._attr_color_temp_kelvin = None
                        self._last_set_mode = ColorMode.HS
                    else:
                        # Low/medium saturation - keep current mode
                        if self._attr_color_mode == ColorMode.COLOR_TEMP:
                            self._attr_color_temp_kelvin = cct
                            self._attr_hs_color = None
                        else:
                            self._attr_hs_color = (hue, sat)
                            self._attr_color_temp_kelvin = None

                _LOGGER.debug(
                    f"Updated state - Mode: {self._attr_color_mode}, "
                    f"CCT: {self._attr_color_temp_kelvin}, "
                    f"HS: {self._attr_hs_color}, "
                    f"Brightness: {brightness_percent}%"
                )
            else:
                self._available = False

        except Exception as e:
            _LOGGER.error(f"Error updating {self._device_id}: {e}")
            self._available = False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on light with proper dual mode handling."""
        _LOGGER.debug(f"async_turn_on called with kwargs: {kwargs}")

        try:
            if not await self._api.ensure_connected():
                raise HomeAssistantError(f"Cannot connect to Amaran light {self._device_id}")

            # Turn on if not already on
            if not self._attr_is_on:
                result = await self._api.set_power(self._device_id, True)
                if result is None:
                    raise HomeAssistantError(f"Failed to turn on {self._device_id}")
                self._attr_is_on = True

            # Handle color temperature changes
            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
                _LOGGER.debug(f"Setting CCT: {kelvin}K")

                result = await self._api.set_cct(self._device_id, kelvin)
                if result is None:
                    _LOGGER.warning(f"Failed to set color temperature for {self._device_id}")
                else:
                    # Update state for COLOR_TEMP mode
                    self._last_set_mode = ColorMode.COLOR_TEMP
                    self._attr_color_mode = ColorMode.COLOR_TEMP
                    self._attr_color_temp_kelvin = kelvin
                    self._attr_hs_color = None

            # Handle HSI color changes
            elif ATTR_HS_COLOR in kwargs:
                hue, saturation = kwargs[ATTR_HS_COLOR]
                _LOGGER.debug(f"Setting HSI: H={hue}, S={saturation}")

                # Calculate intensity from current brightness
                brightness_percent = int(self._attr_brightness / 2.55) if self._attr_brightness else 100
                intensity = int(brightness_percent * 10)

                result = await self._api.set_hsi(self._device_id, int(hue), int(saturation), intensity)
                if result is None:
                    _LOGGER.warning(f"Failed to set HSI color for {self._device_id}")
                else:
                    # Update state for HS mode
                    self._last_set_mode = ColorMode.HS
                    self._attr_color_mode = ColorMode.HS
                    self._attr_hs_color = (hue, saturation)
                    self._attr_color_temp_kelvin = None

            # Handle brightness changes (independent of color mode)
            if ATTR_BRIGHTNESS in kwargs:
                brightness = kwargs[ATTR_BRIGHTNESS]
                brightness_percent = int(brightness / 2.55)

                result = await self._api.set_brightness(self._device_id, brightness_percent)
                if result is None:
                    _LOGGER.warning(f"Failed to set brightness for {self._device_id}")
                else:
                    self._attr_brightness = brightness

            # Notify Home Assistant of state changes
            self.async_write_ha_state()
            self._available = True

        except Exception as e:
            _LOGGER.error(f"Failed to turn on light {self._device_id}: {e}")
            self._available = False
            raise HomeAssistantError(f"Failed to control Amaran light: {str(e)}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        try:
            if not await self._api.ensure_connected():
                raise HomeAssistantError(f"Cannot connect to Amaran light {self._device_id}")

            result = await self._api.set_power(self._device_id, False)
            if result is None:
                raise HomeAssistantError(f"Failed to turn off {self._device_id}")

            self._attr_is_on = False
            self.async_write_ha_state()
            self._available = True

        except Exception as e:
            _LOGGER.error(f"Failed to turn off light {self._device_id}: {e}")
            self._available = False
            raise HomeAssistantError(f"Failed to control Amaran light: {str(e)}")
