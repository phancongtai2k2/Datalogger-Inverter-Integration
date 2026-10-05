# AI Integration Guide — SRNE Inverter Datalogger (MQTT + HTTP)

You are integrating an application (web app, backend service, or mobile backend) with a
solar-inverter datalogger. This file is the complete contract. You do not need the firmware
source, and you must not modify the device firmware.

Applies to datalogger firmware **1.0.16 or later**. The running version is reported in
`up/status` (`logger_fw`) and `up/firmware` (`current_version`).

## 1. What the device is

An ESP32-S3 datalogger wired to one SRNE hybrid inverter over RS485. It:

- reads the inverter every few seconds and publishes JSON to an MQTT broker,
- accepts JSON commands over MQTT and writes the corresponding settings to the inverter,
- reads each written setting back from the inverter and republishes the configuration.

One datalogger serves exactly one inverter. The inverter serial number identifies the pair.

## 2. Connection

| | |
|---|---|
| Protocol | MQTT 3.1.1 over TLS |
| Port | 8883 |
| Credentials | Read from the environment: `MQTT_HOST`, `MQTT_USER`, `MQTT_PASSWORD`. Never hard-code them and never write them into source files, logs, or documentation. |
| Tenant | Read from `MQTT_TENANT`; default `ggp` |
| Payloads | UTF-8 JSON, minified |
| Time | `ts` is a Unix timestamp in seconds, UTC |

Use a unique MQTT client ID for your application. Do not reuse the device's client ID: the
broker would disconnect the device.

## 3. Topics

```
solar/{tenant}/inverter/{sn}/up/...     device -> you
solar/{tenant}/inverter/{sn}/down/...   you -> device
```

`{sn}` is the inverter serial number, for example `INV-EXAMPLE-0001`.

**Discover devices; never hard-code `{sn}`.** Subscribe to
`solar/{tenant}/inverter/+/up/#` and take `sn` from each payload. A datalogger that has not
yet read its inverter publishes under its own device ID (for example `datalogger_01`) and moves
to the inverter serial as soon as it reads it. When that happens it publishes
`{"state":"offline","reason":"sn_changed"}` on the old `up/status` and starts publishing under
the new `{sn}`. Treat the new `sn` as the same physical device only if your own records link them.

| Topic suffix | Direction | Retained | Sent |
|---|---|---|---|
| `up/status` | device → you | yes | On connect, when inverter identity or link state changes, and `offline` on connection loss |
| `up/telemetry` | device → you | no | Every 5 s while the inverter answers |
| `up/battery` | device → you | no | Every 20 s |
| `up/alarm` | device → you | no | When an inverter fault code appears or disappears |
| `up/config/state` | device → you | yes | After connect and after every command that changes settings |
| `up/firmware` | device → you | yes | When firmware / update state changes |
| `up/command/ack` | device → you | no | One per command |
| `down/command` | you → device | — | Your commands |

Retained topics deliver the latest message immediately when you subscribe. Use them to render
current state without waiting.

## 4. Messages from the device

A field the device could not read is **absent** from the payload. Never treat a missing field
as zero; show it as unknown.

### 4.1 `up/status`

```json
{"sn":"INV-EXAMPLE-0001","state":"online","ts":1790935526,"model":"SRNE Hybrid Inverter M39","fw_ver":"V2.85","ip_addr":"192.168.1.50","signal_rssi":-32,"logger_fw":"1.0.14","inverter_comm":"ok"}
```
```json
{"sn":"INV-EXAMPLE-0001","state":"offline","ts":1790935526,"reason":"connection_lost"}
```

| Field | Type | Meaning |
|---|---|---|
| `state` | string | `online` or `offline` |
| `ts` | int | For `offline` with `connection_lost`: the time of the device's last connect, **not** the time the connection dropped. Record your own receive time. |
| `reason` | string | Only when offline: `connection_lost`, `sn_changed`, `reconfigure` |
| `model`, `fw_ver` | string | Inverter model and inverter firmware. Absent until read. |
| `logger_fw` | string | Datalogger firmware version |
| `inverter_comm` | string | `ok` = inverter is answering; `no_response` = datalogger is online but the inverter is not answering on RS485 |
| `ip_addr`, `signal_rssi` | string, int | Datalogger LAN address and WiFi signal in dBm |

When `inverter_comm` is `no_response`, no telemetry is published and setting commands fail with code 500.

### 4.2 `up/telemetry`

```json
{"sn":"INV-EXAMPLE-0001","ts":1790936027,"inv_status":1,"inv_temp":34.1,
 "pv":{"v_pv1":340.5,"i_pv1":6.8,"p_pv1":2315,"v_pv2":338.2,"i_pv2":5.6,"p_pv2":1894,"p_total":4209},
 "grid":{"v_ac":224.5,"i_ac":2.2,"freq":50.02,"p_active":-500,"p_direction":"export"},
 "load":{"v_out":220,"i_out":11.4,"p_active":2500,"freq":50},
 "battery":{"p_flow":-1198.1,"p_direction":"charging","soc":76},
 "energy":{"yield_today_kwh":18.4,"yield_total_kwh":4520.8,"load_today_kwh":14.2,"grid_import_today_kwh":3.1,"grid_export_today_kwh":7.3}}
```

| Field | Unit | Notes |
|---|---|---|
| `inv_status` | — | 0 initialising, 1 standby, 2 running on grid, 3 running on inverter |
| `inv_temp` | °C | Heat-sink temperature |
| `pv.v_pv1`, `pv.v_pv2` | V | |
| `pv.i_pv1`, `pv.i_pv2` | A | |
| `pv.p_pv1`, `pv.p_pv2`, `pv.p_total` | W | |
| `grid.v_ac`, `grid.i_ac`, `grid.freq` | V, A, Hz | |
| `grid.p_active` | W | **Negative = exporting to the grid, positive = importing from the grid** |
| `grid.p_direction` | — | `export`, `import`, `idle` |
| `load.v_out`, `load.i_out`, `load.p_active`, `load.freq` | V, A, W, Hz | |
| `battery.p_flow` | W | **Negative = charging, positive = discharging** |
| `battery.p_direction` | — | `charging` (below −10 W), `discharging` (above 10 W), `idle` |
| `battery.soc` | % | |
| `energy.yield_today_kwh`, `energy.yield_total_kwh` | kWh | PV production today / lifetime |
| `energy.load_today_kwh` | kWh | |
| `energy.grid_export_today_kwh` | kWh | |
| `energy.grid_import_today_kwh` | kWh | Not available on some inverter models: expect it to be absent |

### 4.3 `up/battery`

```json
{"sn":"INV-EXAMPLE-0001","bms_sn":"BAT-INV-EXAMPLE-0001-01","ts":1790936022,"model":"Battery","soc":76,"soh":98,"voltage":51.2,"current":-23.4,"power_w":1198.1,"status":"charging","est_time_remaining_min":62,"temp_cells_avg":32.5,"temp_bms":36,"cycle_count":142,"capacity_ah_remaining":76,"capacity_ah_nominal":100}
```

| Field | Unit | Notes |
|---|---|---|
| `soc`, `soh` | % | |
| `voltage` | V | |
| `current` | A | **Negative = charging, positive = discharging** |
| `power_w` | W | Always positive: voltage × abs(current) |
| `status` | — | `charging` (below −0.5 A), `discharging` (above 0.5 A), `standby` |
| `est_time_remaining_min` | min | Estimated time to full (charging) or to the reserve level (discharging). Present only when the nominal capacity is known. |
| `temp_cells_avg`, `temp_bms` | °C | |
| `cycle_count` | — | |
| `capacity_ah_remaining`, `capacity_ah_nominal` | Ah | |

With no battery connected the inverter reports near-zero voltage and nonsense temperatures
(for example −35). Treat `voltage` below about 10 V as "no battery" in the UI.

### 4.4 `up/alarm`

```json
{"alarm_id":"ALM-20260926-004","sn":"INV-EXAMPLE-0001","ts":1790413164,"event_state":"triggered","error_code":"F024","severity":"critical","title":"Mất kết nối lưới điện","description":"Inverter chuyển sang cấp điện từ pin.","data_snapshot":{"grid_v":224.5,"battery_soc":76,"load_w":2500}}
```

| Field | Notes |
|---|---|
| `event_state` | `triggered` when a fault appears, `cleared` when it disappears. One message per event. |
| `error_code` | `F` plus the three-digit inverter fault code. Pair `triggered` and `cleared` by `error_code` + `sn`. |
| `severity` | `critical`, `warning`, `info` |
| `title`, `description` | Vietnamese text. Unknown codes get a generic title containing the code. |
| `alarm_id` | Unique per event (`ALM-YYYYMMDD-NNN`) |
| `data_snapshot` | Grid voltage, battery SOC and load power at the moment of the event |

Alarms are not retained. An alarm raised while your client was disconnected is not replayed, so
persist alarms on your side.

### 4.5 `up/config/state`

```json
{"sn":"INV-EXAMPLE-0001","ts":1790935920,"work_mode":"self_consumption",
 "grid_mode":"limit_ups_load","pv_priority":"load","battery_mode":"ups_load","grid_charging":[true,true,true],
 "zero_export":{"enabled":true,"limit_export_w":20},
 "charge_schedule":{"enabled":false,"start_time":"00:00","end_time":"00:00","charge_current_limit_a":60,"charge_power_w":3300,"stop_soc":100,"grid_charge":true,
   "periods":[{"period":1,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true},
              {"period":2,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true},
              {"period":3,"start_time":"00:00","end_time":"00:00","charge_power_w":3300,"stop_soc":100,"grid_charge":true}]},
 "battery_reserve_soc":10}
```

| Field | Values | Inverter screen |
|---|---|---|
| `grid_mode` | `on_grid`, `limit_ups_load`, `limit_home_load`, `ac_coupling` | Hybrid grid mode |
| `pv_priority` | `load`, `charging`, `grid` | PV energy manage |
| `battery_mode` | `standby`, `ups_load`, `home_load`, `grid_sell` | Battery energy manage |
| `grid_charging` | array of three booleans: periods 1, 2, 3 | Grid charging enable |
| `work_mode` | `self_consumption`, `grid_connected`, `battery_priority`, `off_grid`, `ac_coupling` | Coarse summary kept for older clients. Prefer the four fields above. |
| `zero_export.enabled` | bool | True when `grid_mode` is `limit_ups_load` or `limit_home_load` |
| `zero_export.limit_export_w` | W, 0–500 | Anti-backflow power margin |
| `charge_schedule.enabled` | bool | Timed charging on/off (applies to all periods) |
| `charge_schedule.periods[]` | three objects | `period` 1–3, `start_time`, `end_time` (`HH:MM`), `charge_power_w`, `stop_soc`, `grid_charge` |
| `charge_schedule.charge_current_limit_a` | A | Grid charging current limit, shared by all periods |
| `charge_schedule.start_time`, `end_time`, `charge_power_w`, `stop_soc`, `grid_charge` | — | Copy of period 1 |
| `battery_reserve_soc` | % | Battery stops discharging below this level |

A period whose `start_time` and `end_time` are both `00:00` is unused.

This message is the device's read-back from the inverter. It is the source of truth for settings.

### 4.6 `up/firmware`

```json
{"sn":"INV-EXAMPLE-0001","current_version":"1.0.14","latest_version":"1.0.15","update_available":true,"state":"idle","progress":0,"last_check":1790935492,"last_result":"update available: 1.0.14 -> 1.0.15 (waiting for confirmation)","ts":1790935522}
```

| Field | Notes |
|---|---|
| `current_version`, `latest_version` | `latest_version` is absent until the device has checked once |
| `update_available` | True when a newer version exists. The device never installs it on its own. |
| `state` | `idle`, `checking`, `installing`, `downloading`, `rebooting`, `verifying` |
| `progress` | 0–100 while downloading, in steps of 10 |
| `last_result` | English diagnostic text for the last check or install |
| `failed_version` | Present when an update was installed, failed its health check, and was rolled back |

### 4.7 `up/command/ack`

```json
{"cmd_id":"3f2b6c1e-...","sn":"INV-EXAMPLE-0001","action":"SET_WORK_MODE","ts":1790936003,"success":true,"code":200,"message":"Đã cập nhật chế độ: PV energy manage = charging."}
```

See section 6.

## 5. Commands to the device

Publish to `solar/{tenant}/inverter/{sn}/down/command` with QoS 1, not retained.

```json
{"cmd_id":"<unique>","action":"<ACTION>","ts":<now, unix seconds>,"params":{...}}
```

| Field | Required | Rules |
|---|---|---|
| `cmd_id` | yes | Up to 64 characters. Generate a new UUID for every command. |
| `action` | yes | One of the actions below |
| `ts` | recommended | The device rejects commands older than 300 s with code 408 |
| `params` | per action | |

### 5.1 `SET_WORK_MODE`

Send any subset of the four fields.

```json
{"cmd_id":"...","action":"SET_WORK_MODE","ts":1790936000,"params":{"grid_mode":"limit_home_load","pv_priority":"charging","battery_mode":"home_load","grid_charging":[true,false,true]}}
```

| Param | Values |
|---|---|
| `grid_mode` | `on_grid`, `limit_ups_load`, `limit_home_load`, `ac_coupling` |
| `pv_priority` | `load`, `charging`, `grid` |
| `battery_mode` | `standby`, `ups_load`, `home_load`, `grid_sell` |
| `grid_charging` | `true` / `false` for all three periods, or an array of exactly three booleans |

Legacy form, still accepted: `{"mode":"self_consumption"}`, `{"mode":"grid_connected"}`,
`{"mode":"battery_priority"}`. Do not use it in new code.

`on_grid`, `ac_coupling` and `grid_sell` allow the inverter to feed power into the public grid.

### 5.2 `SET_CHARGE_SCHEDULE`

Period 1 only:
```json
{"cmd_id":"...","action":"SET_CHARGE_SCHEDULE","ts":1790936000,"params":{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":3000,"stop_soc":100,"charge_current_a":30}}
```
Several periods:
```json
{"cmd_id":"...","action":"SET_CHARGE_SCHEDULE","ts":1790936000,"params":{"enabled":true,"periods":[
  {"start_time":"22:00","end_time":"04:00","charge_power_w":3000,"stop_soc":90},
  {"start_time":"12:00","end_time":"14:00","charge_power_w":1500,"grid_charging":false},
  {"period":3,"start_time":"00:00","end_time":"00:00"}]}}
```

| Param | Required | Range | Notes |
|---|---|---|---|
| `enabled` | yes | bool | Timed charging on/off |
| `start_time`, `end_time` | when enabling | `HH:MM`, 00:00–23:59 | Send both or neither. `00:00`–`00:00` clears a period. |
| `charge_power_w` | no | 0–12000 | Maximum charging power for the period |
| `stop_soc` | no | 0–100 | Stop charging at this SOC |
| `grid_charging` (inside a period) | no | bool | Default: switched on for every period that has times when `enabled` is true |
| `charge_current_a` | no | above 0, up to 400 | Grid charging current limit, shared |
| `periods` | no | 1–3 objects | Array position is the period number unless the object has `"period": 1..3`. Periods you do not send keep their settings. |

To switch the schedule off without changing the periods: `{"enabled":false}`.

### 5.3 `SET_GRID_PARAMETERS`

```json
{"cmd_id":"...","action":"SET_GRID_PARAMETERS","ts":1790936000,"params":{"zero_export_enabled":true,"max_export_power_w":20}}
```

| Param | Notes |
|---|---|
| `zero_export_enabled` | `true` selects anti-backflow on the home load (`"zero_export_mode":"ups_load"` selects the UPS load instead). `false` sets `grid_mode` to `on_grid`, which allows export. |
| `max_export_power_w` | 0–500 |

At least one of the two is required.

### 5.4 `FIRMWARE_CHECK` and `FIRMWARE_UPGRADE`

```json
{"cmd_id":"...","action":"FIRMWARE_CHECK","ts":1790936000,"params":{}}
{"cmd_id":"...","action":"FIRMWARE_UPGRADE","ts":1790936000,"params":{"version":"1.0.15"}}
```

`version` must equal `latest_version` from the current `up/firmware` message.

## 6. Acknowledgements

Every command gets exactly one message on `up/command/ack` with the same `cmd_id`.

| `code` | Meaning | What to do |
|---|---|---|
| 200 | Done. For setting commands the values are written to the inverter. | Wait for the next `up/config/state` and render from it |
| 400 | Invalid parameter, unknown action, or invalid / older firmware version | Show `message`; do not retry unchanged |
| 408 | Command older than 300 s | Resend with a fresh `ts` and a new `cmd_id` |
| 409 | Device busy, or the server no longer offers that firmware version | Retry later; for firmware, re-read `up/firmware` first |
| 422 | Firmware image rejected | Report to the device vendor |
| 500 | The inverter did not answer (`message` contains `TIMEOUT`): retrying can help. Or the inverter answered and refused the value (`message` starts with `Biến tần từ chối`): the inverter does not allow that change in its current state, so do not retry automatically. Or a network error during a firmware download. | Show `message` |
| 503 | Command queue full | Retry after a few seconds |

`message` is Vietnamese and suitable for showing to the end user.

Timeouts to use while waiting for the acknowledgement:

- Setting commands: **15 s**. Typical response is under 2 s.
- `FIRMWARE_UPGRADE`: **5 minutes**. The acknowledgement is sent only when the install has
  finished (about 30 s on a normal link) or failed.

A command that writes several settings applies them in order and stops at the first failure.
The acknowledgement then has code 500 and `up/config/state` shows what was actually applied.

## 7. Rules you must follow

1. **Generate a new `cmd_id` for every command.** The device answers a repeated message (same
   `cmd_id` and identical payload) with the stored acknowledgement and does not execute it
   again. Reusing an ID therefore returns a stale result.
2. **Send the current `ts`.** The broker can deliver a queued command long after it was
   published; `ts` lets the device drop it instead of changing settings late.
3. **After code 200, read the result from `up/config/state`.** Do not update your UI from the
   values you sent. The device reads the settings back from the inverter and that is what is
   actually in effect.
4. **Match acknowledgements by `cmd_id`,** not by order or by `action`. Other clients may send
   commands to the same device.
5. **Expect the inverter to refuse some valid values.** The inverter applies its own rules: on a
   real unit `pv_priority: "load"` was refused (code 500, `Biến tần từ chối ...`) while other
   values were accepted. Offer every documented value, show the refusal message, and keep the
   UI on the value from `up/config/state`. Some settings need the inverter's user password;
   the datalogger enters it by itself when it has been configured on the datalogger. If the
   refusal message mentions `mật khẩu biến tần`, tell the user to set or correct that password
   on the datalogger (web UI, Modbus tab). Never ask for it in your app or send it over MQTT.
6. **Handle absent fields.** Models differ; a field that is missing is unknown, not zero.
7. **Ask the user before enabling grid export.** `grid_mode: on_grid`, `grid_mode: ac_coupling`,
   `battery_mode: grid_sell` and `zero_export_enabled: false` let the inverter feed the public
   grid, which may be illegal or unsafe at the installation site.
8. **Send `FIRMWARE_UPGRADE` only after the user confirms,** and only with the `latest_version`
   currently shown in `up/firmware`. The device restarts during the upgrade.
9. **Never hard-code `sn`, tenant, host or credentials.** Discover `sn` from the broker; take
   the rest from configuration.
10. **Do not publish to `up/...` topics and do not publish retained messages to `down/command`.**
   A retained command would be re-executed every time the device reconnects.
11. **Do not poll.** Subscribe once and react to messages; retained topics give you current state.

## 8. Reference flows

**Change a setting**
1. Render current values from `up/config/state`.
2. On user input, publish the command with a new `cmd_id` and the current `ts`.
3. Wait up to 15 s for the acknowledgement with that `cmd_id`.
4. Code 200: wait for the next `up/config/state` (arrives within seconds) and render it.
   Any other code: show `message` and keep the previous values on screen.

**Upgrade firmware**
1. `up/firmware.update_available` is true → offer "Upgrade to `latest_version`".
2. User confirms → publish `FIRMWARE_UPGRADE` with that version.
3. Show `up/firmware.progress` while `state` is `downloading`.
4. Acknowledgement 200 → the device restarts. `up/status` may show `offline` then `online`.
5. `up/firmware.current_version` equals the new version. About one minute later `last_result`
   contains `health check passed`. If `failed_version` appears instead, the new version was
   rolled back and the device is running the previous one.

**Device offline**
`up/status.state` is `offline`. Commands published now are held by the broker and delivered
when the device reconnects; anything older than 300 s is then rejected with 408. Disable
controls in the UI while the device is offline rather than queuing commands.

## 9. Minimal clients

Both examples connect, discover a device, send one command and wait for its acknowledgement.
The command uses an invalid value on purpose, so it is rejected with code 400 and changes nothing.

### Python (paho-mqtt 2.x)

```python
import json, os, ssl, threading, time, uuid
import paho.mqtt.client as mqtt

TENANT = os.environ.get("MQTT_TENANT", "ggp")
acks, devices = {}, {}
cv = threading.Condition()

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload)
    except ValueError:
        return
    parts = msg.topic.split("/")          # solar/{tenant}/inverter/{sn}/up/...
    sn, suffix = parts[3], "/".join(parts[4:])
    with cv:
        if suffix == "up/status":
            devices[sn] = data
        elif suffix == "up/command/ack":
            acks[data.get("cmd_id")] = data
        cv.notify_all()

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="app-" + uuid.uuid4().hex[:8])
client.username_pw_set(os.environ["MQTT_USER"], os.environ["MQTT_PASSWORD"])
client.tls_set(cert_reqs=ssl.CERT_REQUIRED)
client.on_message = on_message
client.connect(os.environ["MQTT_HOST"], 8883, keepalive=30)
client.subscribe(f"solar/{TENANT}/inverter/+/up/#", qos=1)
client.loop_start()

def send_command(sn, action, params, timeout=15):
    """Publish one command and return its acknowledgement, or None on timeout."""
    cmd_id = str(uuid.uuid4())
    body = {"cmd_id": cmd_id, "action": action, "ts": int(time.time()), "params": params}
    client.publish(f"solar/{TENANT}/inverter/{sn}/down/command", json.dumps(body), qos=1)
    deadline = time.time() + timeout
    with cv:
        while cmd_id not in acks:
            left = deadline - time.time()
            if left <= 0:
                return None
            cv.wait(left)
        return acks.pop(cmd_id)

with cv:                                   # wait for a device that is online
    cv.wait_for(lambda: any(d.get("state") == "online" for d in devices.values()), timeout=10)
online = [sn for sn, d in devices.items() if d.get("state") == "online"]
if not online:
    raise SystemExit("no device online")

ack = send_command(online[0], "SET_WORK_MODE", {"grid_mode": "not_a_mode"})
print(online[0], "->", ack)                # expect code 400
client.loop_stop()
```

### JavaScript (Node.js, `mqtt` package)

```javascript
const mqtt = require("mqtt");
const { randomUUID } = require("crypto");

const TENANT = process.env.MQTT_TENANT || "ggp";
const client = mqtt.connect(`mqtts://${process.env.MQTT_HOST}:8883`, {
  username: process.env.MQTT_USER,
  password: process.env.MQTT_PASSWORD,
  clientId: "app-" + randomUUID().slice(0, 8),
});

const pending = new Map();   // cmd_id -> resolve
const devices = new Map();   // sn -> last status

client.on("connect", () => client.subscribe(`solar/${TENANT}/inverter/+/up/#`, { qos: 1 }));

client.on("message", (topic, payload) => {
  let data;
  try { data = JSON.parse(payload.toString()); } catch { return; }
  const parts = topic.split("/");                 // solar/{tenant}/inverter/{sn}/up/...
  const sn = parts[3], suffix = parts.slice(4).join("/");
  if (suffix === "up/status") devices.set(sn, data);
  if (suffix === "up/command/ack" && pending.has(data.cmd_id)) {
    pending.get(data.cmd_id)(data);
    pending.delete(data.cmd_id);
  }
});

// Publish one command; resolves with its acknowledgement, or null on timeout.
function sendCommand(sn, action, params, timeoutMs = 15000) {
  const cmd_id = randomUUID();
  const body = { cmd_id, action, ts: Math.floor(Date.now() / 1000), params };
  return new Promise((resolve) => {
    const timer = setTimeout(() => { pending.delete(cmd_id); resolve(null); }, timeoutMs);
    pending.set(cmd_id, (ack) => { clearTimeout(timer); resolve(ack); });
    client.publish(`solar/${TENANT}/inverter/${sn}/down/command`, JSON.stringify(body), { qos: 1 });
  });
}

setTimeout(async () => {
  const online = [...devices].filter(([, d]) => d.state === "online").map(([sn]) => sn);
  if (!online.length) { console.error("no device online"); return client.end(); }
  const ack = await sendCommand(online[0], "SET_WORK_MODE", { grid_mode: "not_a_mode" });
  console.log(online[0], "->", ack);              // expect code 400
  client.end();
}, 5000);
```

## 10. Local HTTP API (optional, same LAN only)

The datalogger also serves HTTP on port 80 at `ip_addr` from `up/status`. There is no
authentication, so use it only for on-site tools, never from a public backend.

| Method and path | Purpose |
|---|---|
| `GET /api/system` | Datalogger status: firmware, WiFi, MQTT, Modbus counters |
| `GET /api/data` | Current raw registers and the read result of every polled block |
| `GET /api/config` | Datalogger configuration (passwords masked as `********`) |
| `POST /api/config` | Change datalogger configuration. Changing `network` restarts the device. |
| `GET /api/firmware` | Same content as `up/firmware` |
| `POST /api/firmware/check` | Check for a new version now |
| `POST /api/firmware/upgrade` | Body `{"version":"x.y.z"}`; returns 202 when accepted |

Every `POST` must carry the header `Content-Type: application/json`. Without it the device
answers 400 `missing JSON body`.

Inverter settings (work mode, charge schedule, grid parameters) are available over MQTT only.

## 11. Self-test checklist

Run these against a real device before shipping. The first group changes nothing on the inverter.

**Read path**
- [ ] `up/status` arrives on subscribe with `state: online` and `inverter_comm: ok`.
- [ ] `up/telemetry` arrives about every 5 s; `up/battery` about every 20 s.
- [ ] `up/config/state` and `up/firmware` arrive on subscribe (retained).

**Rejections (no change on the inverter)**

| Command | Expected acknowledgement |
|---|---|
| `SET_WORK_MODE` `{"grid_mode":"not_a_mode"}` | 400 |
| `SET_WORK_MODE` `{"grid_charging":[true]}` | 400 |
| `SET_CHARGE_SCHEDULE` `{"enabled":true,"start_time":"25:00","end_time":"04:00"}` | 400 |
| `SET_CHARGE_SCHEDULE` `{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":13000}` | 400 |
| `SET_GRID_PARAMETERS` `{"max_export_power_w":900}` | 400 |
| Unknown `action` | 400 |
| Any valid command with `ts` one hour in the past | 408 |
| `FIRMWARE_UPGRADE` `{"version":"1.0.1"}` | 400 |
| The same message published twice | Two identical acknowledgements, executed once |

**Round trip (changes a setting, then restores it)**
1. Record `charge_schedule` from `up/config/state`.
2. Send `SET_GRID_PARAMETERS` with `max_export_power_w` set to the recorded
   `zero_export.limit_export_w`. Expect 200 and an unchanged `up/config/state`.
3. Send `SET_CHARGE_SCHEDULE` `{"enabled":true,"start_time":"22:00","end_time":"04:00","charge_power_w":3000}`.
   Expect 200 and `up/config/state` showing period 1 as 22:00–04:00, 3000 W, enabled.
4. Restore the recorded values with another `SET_CHARGE_SCHEDULE` and confirm `up/config/state`
   matches step 1.

## 12. Known limitations

- Device-to-cloud messages are published at QoS 0. The offline status (last will) and command
  delivery use QoS 1. Do not assume every telemetry sample arrives.
- `grid_import_today_kwh` and detailed BMS data are absent on some inverter models.
- Fault descriptions exist for codes F001, F004, F014, F024 and F058; other codes carry a
  generic title.
- `up/status.ts` on an unexpected disconnect is the last connect time (see 4.1).
- The device checks for new firmware at start-up and once per night; use `FIRMWARE_CHECK` to
  check immediately.
