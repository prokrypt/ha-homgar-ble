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
| 4 | 1 | Flags (unknown, seen `0x15`) |
| 5 | 4 | Home ID the sensor is bound to |
| 9 | … | HomGar TLV records with the current readings |

A 4-byte payload (device ID only) is a plain beacon with no readings.

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

`pCode` is 0 (that is what the app's advertisement parser uses). Model and did come from the advertisement.
After a valid reply the device sends `52 13 <did:4> <pCode> <model:2> <hw> <sw> <homeId:4> <mac:6, reversed>`
and keeps the connection open. The app then answers
`D2 0C 00 <slot> E0 01 <homeId:LE32> 00 00 00 00` (`slot` is the sub-device index the cloud assigned);
what follows that has not been explored.

```python
import hashlib, struct

def auth_reply(challenge: bytes, model: int, did: int, pcode: int = 0) -> bytes:
    blob = b"\x91\x91" + bytes([pcode]) + struct.pack("<HI", model, did) + challenge
    s = sum(hashlib.md5(blob.hex().upper().encode()).digest())
    return bytes([0xD0, 5, 0]) + struct.pack("<I", s)
```
