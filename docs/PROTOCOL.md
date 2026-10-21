# HomGar BLE protocol notes (HCS701B)

Reverse-engineered from the HomGar Android app (`com.baldr.homgar`) and checked against a real HCS701B.
Multi-byte integers are little-endian throughout.

## Advertisement

- Local name `HG`.
- Service data, AD type `0x20` (32-bit UUID), UUID `0x01469191`. On air the UUID is `91 91 | 46 01`:
  the `0x9191` HomGar marker followed by the model code (326 = HCS701B).

Service data payload:

| Offset | Size | Meaning |
|---|---|---|
| 0 | 4 | Device ID (`did`), as used by the app and the cloud |
| 4 | 1 | Flags, see below |
| 5 | 4 | Home ID the sensor is bound to |
| 9 | … | HomGar TLV records with the current readings |

A 4-byte payload (device ID only) is what a sensor sends before it has been paired with a home
(see [Pairing](#pairing)): no flags, no readings.

### Flags

As the HomGar app's advert parser reads them:

| Bits | Meaning |
|---|---|
| `0x01` | home ID follows |
| `0x02` | sensor wants a sync (seen `0x03`/`0x17` after power-on, `0x15` otherwise) |
| `0x04` | records have no dpId prefix |
| `0x30` | battery status, `(flags & 0x30) >> 4`: 0/1 normal, higher low. The app adds it as a `DC <bat>` record |
| `0x08`, `0x40` | unknown |
| `0x80` | another flags byte follows (not seen on the HCS701B) |

### TLV records

Same encoding as the HomGar cloud `statusParam` (see
[homeassistant-homgar](https://github.com/brettmeyerowitz/homeassistant-homgar) `decoder.py`):

- `h < 0x80`: one-byte record, code `(h >> 4) & 7`.
- `h >= 0x80`: code `((h >> 2) & 31) + 8`, followed by `(h & 3) + 1` value bytes. Code 39 means the code is in the next byte (+39).

| Header | Code | Field | Value |
|---|---|---|---|
| `85` | 9 TEM | temperature | S16, °F × 10 |
| `88` | 10 RH | humidity | U8, % |
| `b8` | 22 TREND | trend | U8 |
| `e7` | 33 MAX_TEM | temperature min/max | 2 × S16, °F × 10 |
| `e9` | 34 MAX_RH | humidity min/max | 2 × U8, % |

Example: `… 85 18 03 88 28 b8 05 e7 0f 03 1b 03 e9 27 2e` = 79.2 °F, 40 %, trend 5, 78.3–79.5 °F, 39–46 %.

## GATT

Service `4f68a200-b458-c812-9999-43686f75717a`:

- `4f68a302-…` (notify, read): device → host
- `4f68a301-…` (write without response): host → device

Frames are `[opcode][length][payload]`. Replies from the host set bit 7 of the opcode (`0x50` → `0xD0`).
Opcodes: `0x50` auth, `0x52` request connection, `0x54`/`0x55` report state, `0x57` read DP data,
`0x5C` send control, `0x60` report device stats, `0x64` read history.

### Authentication

On subscribe the device sends `50 04 <challenge:4>` about once a second, and drops the link after
about 5 s without a valid answer.

```
blob  = 91 91 | pCode(1) | model(LE16) | did(LE32) | challenge(4)     # 13 bytes
text  = blob as upper-case hex string
sum   = sum of the 16 bytes of MD5(text), as unsigned values
reply = D0 05 00 | sum(LE32)                                          # write to a301
```

```python
import hashlib, struct

def auth_reply(challenge: bytes, model: int, did: int, pcode: int = 0) -> bytes:
    blob = b"\x91\x91" + bytes([pcode]) + struct.pack("<HI", model, did) + challenge
    s = sum(hashlib.md5(blob.hex().upper().encode()).digest())
    return bytes([0xD0, 5, 0]) + struct.pack("<I", s)
```

`pCode` is 0 (that is what the app's advertisement parser uses). Model and did come from the advertisement.
The device only offers the challenge while its advert has the "wants sync" flag set; after a completed
session it accepts connections but stays silent until it wants another sync.

### Sync session

| Device sends | Host answers |
|---|---|
| `52 13 <did:4> <pCode> <model:2> <hw> <sw> <homeId:4> <mac:6, reversed>` | `D2 0C 00 <slot> E0 01 <homeId:LE32> 00 00 00 00` |
| `59 01 02` (sometimes: asks for dpId 2, the clock) | `D9 06 00 02 <T4:LE32>` |
| `55 <len> <stateVer> <TLV records>` (or `54` with a dpId byte before each record) | `D5 02 00 <stateVer>` (or `D4 …`) |

- `slot` is the sub-device index the HomGar cloud assigned (1 for the only BLE device in a home); `E0 01` (480)
  is a constant in the app; `homeId` is echoed from the `0x52` frame.
- T4 time, local time of the home: `sec | min<<6 | hour<<12 | day<<17 | month<<22 | (year-2020)<<26`.
- The report holds the same TLV records as the advert plus `DC <bat>` (battery status, same as the flags bits).
  Example: `55 12 01 dc 01 85 31 03 88 2a b8 0d e7 26 03 31 03 e9 2a 34`.
- The device disconnects a few seconds after the report is acknowledged.
- `0x59` with other dpIds asks for settings (calibration, units, alert thresholds); those are not answered here.

### Pairing

A sensor that was never paired only advertises its device ID, but unlike a paired one it offers the
auth challenge on every connection, without a "wants sync" flag. After the auth its `0x52` frame carries
home ID 0. Answering it with a non-zero home ID pairs the sensor with that home:

```
device: 52 13 1f7d0049 49 4601 00 0a 00000000 2c7f775223dc     # home ID 0
host:   D2 0C 00 02 E0 01 7ea10400 00000000                    # home ID 0x0004a17e
device: 55 12 01 dc 01 85 0f 03 88 28 b8 0d e7 0f 03 10 03 e9 28 2e
host:   D5 02 00 01
```

Straight afterwards the advert has flags `0x15`, the new home ID and readings. Seen on an HCS701B
(firmware 10) on 2026-10-20. The app's own pairing also registers the sensor with the HomGar cloud
and offers firmware updates; the integration does only the Bluetooth part, with a random home ID.
