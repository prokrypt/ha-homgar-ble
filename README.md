# HomGar/RainPoint BLE Thermo-Hygrometer for Home Assistant

Local, cloud-free Home Assistant integration for the Bluetooth-only HomGar / RainPoint / BaldrTherm
**HCS701B** solar thermo-hygrometer (advertises as `HG`).

The sensor broadcasts its readings in BLE advertisements, so temperature and humidity come from passive
listening. Battery status is only sent over a connection, so when the sensor's advertisement says it wants a
sync, the integration connects for a few seconds and does the same handshake as the HomGar app.
No phone app or HomGar cloud is needed.
(The cloud integrations can't help here anyway: readings from Bluetooth-only HomGar sensors stay on the phone.)

## Entities

| Entity | Notes |
|---|---|
| Temperature (°C) | sensor sends °F × 10; converted |
| Humidity (%) | |
| Temperature min / max | sensor's own min/max; disabled by default |
| Humidity min / max | sensor's own min/max; disabled by default |
| Battery (binary sensor) | on = low; updated whenever the sensor asks for a sync |
| Battery status | raw HomGar code (0/1 = normal, higher = low); diagnostic, disabled by default |

The battery entity appears after the first sync. The sensor asks for one after power-on (e.g. after a
battery change) and now and then on its own (not often: twice in one evening, then not for hours), so the
battery state can be hours old; pull the battery for a few seconds to force a fresh sync.

## Requirements

- Home Assistant with the **Bluetooth** integration working, and an adapter in range of the sensor:
  a local adapter, or an [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy.html) near it.
- Battery syncs need a **connectable** adapter or proxy (ESPHome proxies with `active: true` are).
- The handshake identifies the sensor as device slot 1 of its HomGar home, which is right when it's the only
  HomGar Bluetooth device there. With several HomGar BLE devices in one home, please open an issue.
- **Nothing else may stay connected to the sensor.** While the phone app or a tool like nRF Connect
  holds a connection, the sensor stops advertising and Home Assistant gets no updates.

## Install

**HACS:** HACS → ⋮ → *Custom repositories* → add `https://github.com/prokrypt/ha-homgar-ble`, category
*Integration* → install **HomGar/RainPoint BLE Thermo-Hygrometer** → restart Home Assistant.

**Manual:** copy `custom_components/homgar_ble` into your HA `config/custom_components/` and restart.

The sensor should then be discovered automatically (*Settings → Devices & services → Discovered*).
If not, add the integration by hand and choose it from the list.

## Tested with

- HCS701B (firmware 14), Home Assistant 2026.10.1, local USB adapter (BlueZ).

Other HomGar BLE sensors that advertise the same service UUID (`0x01469191`, model code 326) may work.
Reports for other models are welcome; include a few advertisement payloads and the values the app shows.

## Protocol

See [docs/PROTOCOL.md](docs/PROTOCOL.md) for the advertisement format and the GATT authentication,
reverse-engineered from the HomGar Android app.

## Development

The tests use [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component).
They cover the advert and report decoding, the model registry, the GATT sync session against a scripted
fake sensor, the config flows and entry setup. New models in `models.py` are checked automatically.

```sh
pip install -r requirements_test.txt
python script/ha_requirements.py > /tmp/ha_requirements.txt
pip install -r /tmp/ha_requirements.txt -c "$(python script/ha_requirements.py --constraints)"
pytest
```

CI runs them against the minimum Home Assistant version and the one pinned in `requirements_test.txt`.
