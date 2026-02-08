# Exaviz PoE Management

Monitor and control Power over Ethernet ports on Exaviz hardware platforms directly from Home Assistant.

![Exaviz Logo](logo.png)

## Features

- **Real-time Monitoring**: View PoE port status, power consumption, voltage, and current
- **Port Control**: Enable/disable PoE power on individual ports with a single click
- **Device Identification**: Automatic detection of connected devices (IP, MAC, Manufacturer)
- **Beautiful UI**: Custom Lovelace card with Exaviz branding and modern design
- **Multi-language**: Support for 10 languages (EN, ES, DE, FR, IT, JA, ZH, KO, PT, NL)
- **Local Polling**: No cloud dependency, all data stays local

## Supported Hardware

### Cruiser Carrier Board
- 4 or 8 built-in 1GbE PoE ports
- Direct hardware control via `/proc` filesystem
- Perfect for small to medium deployments

### Interceptor PoE Board
- 8 PoE+ ports at 100MbE per add-on board
- Support for up to 2 add-on boards (16 ports total)
- Ideal for high-density camera installations

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Go to "Integrations"
3. Click "Explore & Download Repositories"
4. Search for "Exaviz PoE Management"
5. Click "Download"
6. Restart Home Assistant

### Post-Installation Setup (CRITICAL)

After installation, you **must** configure sudo access for port control:

```bash
sudo nano /etc/sudoers.d/homeassistant-poe
```

Add the following:

```sudoers
homeassistant ALL=(ALL) NOPASSWD: /usr/sbin/ip link set poe* up
homeassistant ALL=(ALL) NOPASSWD: /usr/sbin/ip link set poe* down
```

Set permissions:

```bash
sudo chmod 0440 /etc/sudoers.d/homeassistant-poe
sudo visudo -c  # Validate syntax
```

See [Setup Guide](https://exa-pedia.com/docs/home-assistant/installation/) for detailed instructions.

## Configuration

The integration auto-detects your Exaviz hardware on first run:

1. Go to **Settings** → **Devices & Services**
2. Click **+ Add Integration**
3. Search for "Exaviz PoE Management"
4. Click to add
5. Integration will detect your board and create entities

## Using the Lovelace Card

Add the custom card to your dashboard:

```yaml
type: custom:exaviz-poe-card
poe_set: exaviz_onboard
name: PoE Ports
show_header: true
show_summary: true
show_details: true
layout: auto
```

### Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `poe_set` | string | `exaviz_onboard` | Which PoE system (`exaviz_onboard`, `exaviz_addon_0`, `exaviz_addon_1`) |
| `name` | string | `"PoE Ports"` | Card title |
| `show_header` | boolean | `true` | Show/hide card header with logo |
| `show_summary` | boolean | `true` | Show/hide summary statistics |
| `show_details` | boolean | `true` | Show/hide detailed port info |
| `layout` | string | `"auto"` | Layout mode (`auto`, `compact`, `detailed`) |

## Entities Created

### Sensors (per port)

- `sensor.exaviz_poe_port_N_status` - Power status (on/off)
- `sensor.exaviz_poe_port_N_voltage` - Port voltage (V)
- `sensor.exaviz_poe_port_N_current` - Port current (mA)
- `sensor.exaviz_poe_port_N_device_ip` - Connected device IP
- `sensor.exaviz_poe_port_N_device_mac` - Connected device MAC
- `sensor.exaviz_poe_port_N_device_type` - Device manufacturer

### Switches (per port)

- `switch.exaviz_poe_port_N_enable` - Enable/disable PoE power

## Automation Examples

### Turn off unused ports at night

```yaml
automation:
  - alias: "PoE Night Mode"
    trigger:
      - platform: time
        at: "23:00:00"
    action:
      - service: switch.turn_off
        target:
          entity_id:
            - switch.exaviz_poe_port_4_enable
            - switch.exaviz_poe_port_5_enable
```

### Alert on new device connection

```yaml
automation:
  - alias: "PoE Device Connected"
    trigger:
      - platform: state
        entity_id: sensor.exaviz_poe_port_0_device_name
        from: "No Device"
    action:
      - service: notify.mobile_app
        data:
          message: "New device on port 0: {{ states('sensor.exaviz_poe_port_0_device_name') }}"
```

## Known Issues

### Add-on Board Port Control (Interceptor)

**Status:** ⚠️ Known Issue - Hardware Team Investigation

**Issue:** Port enable/disable on add-on boards (Interceptor) may not reliably control PoE power. The network interface control works, but PoE power may remain on.

**Affected:** Interceptor PoE Board (add-on) ports only  
**Not Affected:** Cruiser onboard ports (work correctly)

**Tracking:** See [GitHub Issues](https://github.com/exavizco/ha-poe-plugin/issues)

**Expected Fix:** Awaiting hardware team input on proper kernel module API for add-on board control.

## Documentation

- **[Documentation](https://exa-pedia.com/docs/home-assistant/)** - Complete installation and configuration guide
- **[Troubleshooting](https://exa-pedia.com/docs/home-assistant/troubleshooting/)** - Common issues and solutions

## Support

- **Issues:** [GitHub Issues](https://github.com/exavizco/ha-poe-plugin/issues)
- **Email:** support@exaviz.com
- **Documentation:** [exa-pedia.com](https://exa-pedia.com/docs/home-assistant/)

## License

Copyright © 2024-2025 Axzez LLC

Licensed under MIT with Commons Clause. See [LICENSE](https://github.com/exavizco/ha-poe-plugin/blob/main/LICENSE) for details.

## About Exaviz

Exaviz develops innovative IoT, AI, and video solutions for smart infrastructure. Our PoE management platform provides reliable, high-performance power and data delivery for connected devices.

**Exaviz** is a product of **Axzez LLC**.

Learn more: https://exaviz.com

