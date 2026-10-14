# HomGar/RainPoint BLE Thermo-Hygrometer for Home Assistant

Local, cloud-free Home Assistant integration for the Bluetooth-only HomGar / RainPoint / BaldrTherm
**HCS701B** solar thermo-hygrometer (advertises as `HG`).

The sensor broadcasts its readings in BLE advertisements, so this integration only listens:
it never connects to or writes to the sensor, and it does not need the phone app or the HomGar cloud.
(The cloud integrations can't help here anyway: readings from Bluetooth-only HomGar sensors stay on the phone.)

## Entities

| Entity | Notes |
|---|---|
| Temperature (°C) | sensor sends °F × 10; converted |
| Humidity (%) | |
| Temperature min / max | sensor's own min/max; disabled by default |
| Humidity min / max | sensor's own min/max; disabled by default |

Battery level is not included in the advertisements, so it isn't available yet.

## Requirements

- Home Assistant with the **Bluetooth** integration working, and an adapter in range of the sensor:
  a local adapter, or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) near it.
- **Nothing else may stay connected to the sensor.** While the phone app or a tool like nRF Connect
  holds a connection, the sensor stops advertising and Home Assistant gets no updates.

## Install

**HACS:** HACS → ⋮ → *Custom repositories* → add `https://github.com/prokrypt/ha-homgar-ble`, category
*Integration* → install **HomGar/RainPoint BLE Thermo-Hygrometer** → restart Home Assistant.

**Manual:** copy `custom_components/homgar_ble` into your HA `config/custom_components/` and restart.

The sensor should then be discovered automatically (*Settings → Devices & services → Discovered*).
If not, add the integration by hand and choose it from the list.

## Tested with

- HCS701B, Home Assistant 2026.10.1, local USB adapter (BlueZ).

Other HomGar BLE sensors that advertise the same service UUID (`0x01469191`, model code 326) may work.
Reports for other models are welcome; include a few advertisement payloads and the values the app shows.

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the advertisement format and the GATT authentication,
reverse-engineered from the HomGar Android app.
