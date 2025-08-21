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
        self._available = True

        # Set supported features
        self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        self._attr_color_mode = ColorMode.COLOR_TEMP

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
            else:
                self._available = False

            _LOGGER.debug(f"HA hue: {self._hue}, sat: {self._saturation}, brightness: {self._brightness}")

        except Exception as e:
            _LOGGER.error(f"Error updating {self._device_id}: {e}")
            self._available = False

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._state

    @property
    def brightness(self) -> Optional[int]:
        """Return brightness."""
        return int(self._brightness * 2.55)  # Convert 0-100 to 0-255

    @property
    def hs_color(self):
        """Return the HS color."""
        # Always return HSI values if we have them
        if self._hue is not None and self._saturation is not None:
            return (self._hue, self._saturation)
        return None

@property
def color_mode(self):
    """Return current color mode."""
    # Check actual saturation value to determine mode
    if self._saturation is not None and self._saturation > 10:  # Lowered threshold
        return ColorMode.HS
    return ColorMode.COLOR_TEMP

@property
def color_temp_kelvin(self) -> Optional[int]:
    """Return color temperature in Kelvin."""
    # Always return CCT if we're not in a saturated color mode
    if self._saturation is None or self._saturation <= 10:
        return self._cct
    return None

async def async_update(self):
    """Update device state."""
    try:
        state = await self._api.get_device_state(self._device_id)
        _LOGGER.debug(f"Raw state from API: {state}")

        if state:
            self._available = True
            self._state = state.get("is_on", False)
            self._brightness = state.get("brightness", 0)
            self._cct = state.get("cct", 5500)
            self._gm = state.get("gm", 0)

            # Always store the HSI values
            self._hue = state.get("hue", 0)
            self._saturation = state.get("sat", 0)

            # Determine color mode based on saturation
            if self._saturation > 10:  # Low saturation means CCT mode
                self._attr_color_mode = ColorMode.HS
            else:
                self._attr_color_mode = ColorMode.COLOR_TEMP
        else:
            self._available = False

        _LOGGER.debug(f"HA mode: {self._attr_color_mode}, hue: {self._hue}, sat: {self._saturation}, cct: {self._cct}, brightness: {self._brightness}")

    except Exception as e:
        _LOGGER.error(f"Error updating {self._device_id}: {e}")
        self._available = False

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
        _LOGGER.debug(f"async_turn_on called with kwargs: {kwargs}")

        try:
            # Ensure we're connected before sending commands
            if not await self._api.ensure_connected():
                raise HomeAssistantError(f"Cannot connect to Amaran light {self._device_id}")

            # Turn on the light
            result = await self._api.set_power(self._device_id, True)
            if result is None:
                raise HomeAssistantError(f"Failed to turn on {self._device_id}")

            # Set brightness if specified
            if ATTR_BRIGHTNESS in kwargs:
                brightness = int(kwargs[ATTR_BRIGHTNESS] / 2.55)
                result = await self._api.set_brightness(self._device_id, brightness)
                if result is None:
                    _LOGGER.warning(f"Failed to set brightness for {self._device_id}")

            # Set HSI color if specified
            if ATTR_HS_COLOR in kwargs:
                hue, saturation = kwargs[ATTR_HS_COLOR]
                _LOGGER.debug(f"Setting HSI: H={hue}, S={saturation}")
                self._attr_color_mode = ColorMode.HS
                self._hue = hue
                self._saturation = saturation
                current_brightness = self._brightness if self._brightness > 0 else 100
                result = await self._api.set_hsi(self._device_id, int(hue), int(saturation), int(current_brightness * 10))
                if result is None:
                    _LOGGER.warning(f"Failed to set HSI color for {self._device_id}")

            # Set color temperature if specified
            if ATTR_COLOR_TEMP_KELVIN in kwargs:
                _LOGGER.debug(f"Setting CCT: {kwargs[ATTR_COLOR_TEMP_KELVIN]}K")
                self._attr_color_mode = ColorMode.COLOR_TEMP
                result = await self._api.set_cct(self._device_id, kwargs[ATTR_COLOR_TEMP_KELVIN])
                if result is None:
                    _LOGGER.warning(f"Failed to set color temperature for {self._device_id}")

            self._available = True

        except Exception as e:
            _LOGGER.error(f"Failed to turn on light {self._device_id}: {e}")
            self._available = False
            raise HomeAssistantError(f"Failed to control Amaran light: {str(e)}")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off light."""
        try:
            # Ensure we're connected before sending commands
            if not await self._api.ensure_connected():
                raise HomeAssistantError(f"Cannot connect to Amaran light {self._device_id}")

            result = await self._api.set_power(self._device_id, False)
            if result is None:
                raise HomeAssistantError(f"Failed to turn off {self._device_id}")

            self._available = True

        except Exception as e:
            _LOGGER.error(f"Failed to turn off light {self._device_id}: {e}")
            self._available = False
            raise HomeAssistantError(f"Failed to control Amaran light: {str(e)}")
