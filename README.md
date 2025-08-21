# Amaran Home Assistant Integration

Control Amaran/Aputure lights through Home Assistant via WebSocket API.

## Features

- 🔌 Auto-discovery of all Amaran lights
- 💡 On/off control
- 🔆 Brightness adjustment (0-100%)
- 🌡️ Color temperature (2000-10000K)
- 🎨 HSI color control
- 🔄 Real-time state updates
- 📍 Home Assistant area support

## Supported Devices

- Amaran 150c/300c/600c series
- Amaran PT1c/PT2c/PT4c series
- Amaran Ace series
- All devices compatible with Sidus Link Control Box

## Requirements

- Home Assistant 2024.1+
- Sidus Link Control Box running on network
- API key from Control Box

## Installation

1. Copy `amaran` folder to `config/custom_components/`
2. Restart Home Assistant
3. Go to Settings → Devices & Services → Add Integration
4. Search for "Amaran Lighting"
5. Enter:
   - API Key (Base64 encoded)
   - Host IP (default: 10.0.0.57)
   - Port (default: 12345)

## Configuration

The integration auto-discovers all lights after setup. Each light appears as a separate entity with full control capabilities.

### API Key

Get your API key from the Amaran Desktop settings. The key should be Base64 encoded.

Example: `dWI2aHenaeNnDCVrFeVveGFyNXieeHZ1J2NxeW94eGs=`

## Usage

Control lights through:
- Home Assistant UI
- Automations
- Scripts
- Voice assistants (Alexa/Google Home via HA)

### Service Examples

```yaml
# Turn on light at 50% brightness
service: light.turn_on
target:
  entity_id: light.amaran_pt2c_1
data:
  brightness_pct: 50

# Set color temperature
service: light.turn_on
target:
  entity_id: light.amaran_150c_1
data:
  kelvin: 5600

# Set HSI color
service: light.turn_on
target:
  entity_id: light.amaran_ace_25c_1
data:
  hs_color: [180, 75]
```

## Troubleshooting

### Lights not discovered
- Check if lights are connected in desktop app
- Verify API key is correct
- Ensure port 12345 is accessible

### Connection drops
- Check network stability
- Verify no firewall blocking WebSocket

### Enable debug logging
```yaml
logger:
  default: info
  logs:
    custom_components.amaran: debug
```

## Protocol

Uses Sidus Link WebSocket protocol v2 with AES-256-GCM token authentication.

## License

MIT

## Support

Report issues at: https://github.com/jlxq0/amaran-ha
