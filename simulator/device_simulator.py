"""Datalogger simulator: behaves like one device on the MQTT broker, so the app can be built
and tested without hardware. It follows docs/AI_INTEGRATION_GUIDE.md.

    pip install "paho-mqtt>=2.0"
    export MQTT_HOST=... MQTT_USER=... MQTT_PASSWORD=...      (see .env.example)
    python simulator/device_simulator.py                     # tenant "dev", serial SIM-0001
    python simulator/device_simulator.py --sn SIM-0002 --locked --update 1.0.99

  --locked   the "inverter" refuses pv_priority load / grid (as a real unit does while its
             password is not entered): those commands get code 500 "Biến tần từ chối ..."
  --update   announce this firmware version as available, so the upgrade flow can be tested

It publishes under solar/{tenant}/inverter/{sn}/... Keep the tenant different from the one used
by real devices (default here: "dev").
"""
import argparse
import hashlib
import json
import math
import os
import random
import ssl
import threading
import time

import paho.mqtt.client as mqtt

GRID_MODES = ["on_grid", "limit_ups_load", "limit_home_load", "ac_coupling"]
PV_PRIORITIES = ["load", "charging", "grid"]
BATTERY_MODES = ["standby", "ups_load", "home_load", "grid_sell"]
MAX_COMMAND_AGE_S = 300


def valid_time(v):
    try:
        h, m = str(v).split(":")
        return len(m) == 2 and 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except ValueError:
        return False


def norm_time(v):
    h, m = str(v).split(":")
    return "%02d:%02d" % (int(h), int(m))


class Simulator:
    def __init__(self, a):
        self.a = a
        self.sn = a.sn
        self.base = "solar/%s/inverter/%s/" % (a.tenant, a.sn)
        self.fw = "1.0.16"
        self.latest = a.update or self.fw
        self.fw_state, self.fw_progress, self.fw_result = "idle", 0, "up to date"
        self.last_check = int(time.time())
        self.soc = 62.0
        self.acks = {}  # cmd_id -> (payload hash, ack json)
        self.lock = threading.Lock()
        self.cfg = {
            "grid_mode": "limit_ups_load", "pv_priority": "charging", "battery_mode": "ups_load",
            "grid_charging": [True, True, True], "export_w": 20, "schedule_enabled": False,
            "charge_current_a": 60, "reserve_soc": 10,
            "periods": [{"start_time": "00:00", "end_time": "00:00", "charge_power_w": 3300, "stop_soc": 100} for _ in range(3)],
        }
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sim-" + a.sn)
        if os.environ.get("MQTT_USER"):
            c.username_pw_set(os.environ["MQTT_USER"], os.environ.get("MQTT_PASSWORD", ""))
        if a.port == 8883:
            c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
        c.will_set(self.base + "up/status", json.dumps(self.offline("connection_lost"), separators=(",", ":")), qos=1, retain=True)
        c.on_connect = self.on_connect
        c.on_message = self.on_message
        self.c = c

    # ------------------------------------------------------------------ publishing
    def pub(self, suffix, obj, retain=False):
        self.c.publish(self.base + suffix, json.dumps(obj, ensure_ascii=False, separators=(",", ":")), retain=retain)

    def offline(self, reason):
        return {"sn": self.sn, "state": "offline", "ts": int(time.time()), "reason": reason}

    def status(self):
        return {"sn": self.sn, "state": "online", "ts": int(time.time()), "model": "SRNE Hybrid Inverter M39",
                "fw_ver": "V2.85", "ip_addr": "192.168.1.50", "signal_rssi": -40 - random.randint(0, 8),
                "logger_fw": self.fw, "inverter_comm": "ok"}

    def config_state(self):
        c = self.cfg
        zero = c["grid_mode"] in ("limit_ups_load", "limit_home_load")
        mode = ("battery_priority" if c["pv_priority"] == "charging" else "self_consumption" if zero
                else "grid_connected" if c["grid_mode"] == "on_grid" else "ac_coupling")
        periods = [dict(period=i + 1, grid_charge=c["grid_charging"][i], **p) for i, p in enumerate(c["periods"])]
        first = periods[0]
        return {"sn": self.sn, "ts": int(time.time()), "work_mode": mode, "grid_mode": c["grid_mode"],
                "pv_priority": c["pv_priority"], "battery_mode": c["battery_mode"], "grid_charging": c["grid_charging"],
                "zero_export": {"enabled": zero, "limit_export_w": c["export_w"]},
                "charge_schedule": {"enabled": c["schedule_enabled"], "start_time": first["start_time"],
                                    "end_time": first["end_time"], "charge_current_limit_a": c["charge_current_a"],
                                    "charge_power_w": first["charge_power_w"], "stop_soc": first["stop_soc"],
                                    "grid_charge": first["grid_charge"], "periods": periods},
                "battery_reserve_soc": c["reserve_soc"]}

    def firmware(self):
        newer = tuple(map(int, self.latest.split("."))) > tuple(map(int, self.fw.split(".")))
        return {"sn": self.sn, "current_version": self.fw, "latest_version": self.latest, "update_available": newer,
                "state": self.fw_state, "progress": self.fw_progress, "last_check": self.last_check,
                "last_result": self.fw_result, "ts": int(time.time())}

    def telemetry(self):
        t = time.time()
        sun = max(0.0, math.sin((t % 600) / 600 * math.pi))  # a "day" every 10 minutes
        p1, p2 = round(2400 * sun), round(1900 * sun)
        load = 900 + round(400 * math.sin(t / 37)) + random.randint(-20, 20)
        bat = round(min(1500, max(-1500, load - p1 - p2)) * 0.6, 1)  # >0 discharging, <0 charging
        grid = round(load - p1 - p2 - bat)                           # >0 import, <0 export
        if self.cfg["grid_mode"] in ("limit_ups_load", "limit_home_load"):
            grid = max(grid, -self.cfg["export_w"])
        self.soc = min(100.0, max(self.cfg["reserve_soc"], self.soc - bat / 20000.0))
        self.bat_w = bat
        return {"sn": self.sn, "ts": int(t), "inv_status": 2, "inv_temp": round(35 + 8 * sun, 1),
                "pv": {"v_pv1": round(340 * (0.4 + 0.6 * sun), 1), "i_pv1": round(p1 / 340, 1), "p_pv1": p1,
                       "v_pv2": round(338 * (0.4 + 0.6 * sun), 1), "i_pv2": round(p2 / 338, 1), "p_pv2": p2, "p_total": p1 + p2},
                "grid": {"v_ac": round(229 + random.random() * 3, 1), "i_ac": round(abs(grid) / 230, 1),
                         "freq": round(50 + random.uniform(-0.05, 0.05), 2), "p_active": grid,
                         "p_direction": "export" if grid < 0 else "import" if grid > 0 else "idle"},
                "load": {"v_out": 230.0, "i_out": round(load / 230, 1), "p_active": load, "freq": 50.0},
                "battery": {"p_flow": bat, "p_direction": "charging" if bat < -10 else "discharging" if bat > 10 else "idle",
                            "soc": round(self.soc)},
                "energy": {"yield_today_kwh": round((t % 86400) / 86400 * 18, 1), "yield_total_kwh": 4520.8,
                           "load_today_kwh": round((t % 86400) / 86400 * 14, 1), "grid_export_today_kwh": 2.1}}

    def battery(self):
        v, i = 51.2, round(getattr(self, "bat_w", 0) / 51.2, 1)
        st = "charging" if i < -0.5 else "discharging" if i > 0.5 else "standby"
        msg = {"sn": self.sn, "bms_sn": "BAT-%s-01" % self.sn, "ts": int(time.time()), "model": "Battery",
               "soc": round(self.soc), "soh": 98, "voltage": v, "current": i, "power_w": round(v * abs(i), 1), "status": st,
               "temp_cells_avg": 31.5, "temp_bms": 34.0, "cycle_count": 142,
               "capacity_ah_remaining": round(self.soc), "capacity_ah_nominal": 100}
        if st == "charging":
            msg["est_time_remaining_min"] = round((100 - self.soc) / abs(i) * 60)
        elif st == "discharging":
            msg["est_time_remaining_min"] = round(max(0, self.soc - self.cfg["reserve_soc"]) / i * 60)
        else:
            msg["est_time_remaining_min"] = 0
        return msg

    # ------------------------------------------------------------------ commands
    def ack(self, cmd_id, action, code, message, digest=None):
        a = {"cmd_id": cmd_id, "sn": self.sn, "action": action, "ts": int(time.time()), "success": code == 200,
             "code": code, "message": message}
        if cmd_id:
            self.acks[cmd_id] = (digest, a)
        self.pub("up/command/ack", a)
        print("  ack %s %s -> %d %s" % (cmd_id, action, code, message))

    def on_message(self, c, u, m):
        digest = hashlib.sha1(m.payload).hexdigest()
        try:
            body = json.loads(m.payload)
            assert isinstance(body, dict)
        except Exception:
            return self.ack("", "", 400, "JSON không hợp lệ")
        cmd_id, action, p = str(body.get("cmd_id", "")), str(body.get("action", "")), body.get("params") or {}
        if cmd_id in self.acks and self.acks[cmd_id][0] == digest:  # redelivery: answer again, do not re-run
            return self.pub("up/command/ack", self.acks[cmd_id][1])
        fail = lambda code, msg: self.ack(cmd_id, action, code, msg, digest)
        if not cmd_id or len(cmd_id) > 64:
            return fail(400, "cmd_id là bắt buộc (tối đa 64 ký tự)")
        ts = body.get("ts")
        if isinstance(ts, int) and ts + MAX_COMMAND_AGE_S < time.time():
            return fail(408, "Lệnh đã hết hạn (gửi cách đây %d giây)" % (time.time() - ts))
        with self.lock:
            handler = {"SET_WORK_MODE": self.set_work_mode, "SET_CHARGE_SCHEDULE": self.set_charge_schedule,
                       "SET_GRID_PARAMETERS": self.set_grid, "FIRMWARE_CHECK": self.fw_check,
                       "FIRMWARE_UPGRADE": self.fw_upgrade}.get(action)
            if not handler:
                return fail(400, "action không được hỗ trợ: '%s'" % action)
            result = handler(p, cmd_id, digest)
            if result is None:  # the handler answers later (firmware upgrade)
                return
            code, msg = result
            self.ack(cmd_id, action, code, msg, digest)
            if code == 200 and action.startswith("SET_"):
                self.pub("up/config/state", self.config_state(), retain=True)

    def set_work_mode(self, p, *_):
        legacy = {"self_consumption": {"grid_mode": "limit_home_load", "pv_priority": "load"},
                  "grid_connected": {"grid_mode": "on_grid", "pv_priority": "grid"}, "battery_priority": {"pv_priority": "charging"}}
        if "mode" in p:
            if p["mode"] not in legacy:
                return 400, "params.mode không hợp lệ: '%s'" % p["mode"]
            p = legacy[p["mode"]]
        new = {}
        for key, allowed in (("grid_mode", GRID_MODES), ("pv_priority", PV_PRIORITIES), ("battery_mode", BATTERY_MODES)):
            if key in p:
                if p[key] not in allowed:
                    return 400, "params.%s không hợp lệ: '%s' (%s)" % (key, p[key], " | ".join(allowed))
                new[key] = p[key]
        if "grid_charging" in p:
            g = p["grid_charging"]
            if isinstance(g, bool):
                g = [g, g, g]
            if not (isinstance(g, list) and len(g) == 3 and all(isinstance(x, bool) for x in g)):
                return 400, "params.grid_charging phải là true/false hoặc mảng 3 giá trị [khung1, khung2, khung3]"
            new["grid_charging"] = g
        if not new:
            return 400, "Cần ít nhất một trong: grid_mode, pv_priority, battery_mode, grid_charging (hoặc mode)"
        if self.a.locked and new.get("pv_priority") in ("load", "grid") and new["pv_priority"] != self.cfg["pv_priority"]:
            return 500, "Biến tần từ chối ghi: cần mật khẩu biến tần (chưa cấu hình trên datalogger) (mã 0x0B) (bước 1/1)"
        self.cfg.update(new)
        return 200, "Đã cập nhật chế độ: " + ", ".join("%s = %s" % kv for kv in new.items()) + "."

    def set_charge_schedule(self, p, *_):
        if not isinstance(p.get("enabled"), bool):
            return 400, "params.enabled (true/false) là bắt buộc"
        entries = p.get("periods")
        if entries is None:
            entries = [dict({k: p[k] for k in ("start_time", "end_time", "charge_power_w", "stop_soc") if k in p}, period=1)]
            if len(entries[0]) == 1:
                entries = []
        elif not (isinstance(entries, list) and 1 <= len(entries) <= 3):
            return 400, "params.periods phải là mảng 1..3 khung giờ"
        changes, seen, any_time = [], set(), False
        for pos, e in enumerate(entries):
            n = e.get("period", pos + 1)
            if n not in (1, 2, 3) or n in seen:
                return 400, "period phải là 1, 2 hoặc 3 và không lặp lại"
            seen.add(n)
            if ("start_time" in e) != ("end_time" in e):
                return 400, "khung %d: cần cả start_time và end_time" % n
            if "start_time" in e:
                if not (valid_time(e["start_time"]) and valid_time(e["end_time"])):
                    return 400, "khung %d: giờ phải có dạng HH:MM (00:00..23:59)" % n
                any_time = True
            w, soc = e.get("charge_power_w"), e.get("stop_soc")
            if w is not None and not (isinstance(w, (int, float)) and 0 <= w <= 12000):
                return 400, "khung %d: charge_power_w phải trong khoảng 0..12000 W" % n
            if soc is not None and not (isinstance(soc, (int, float)) and 0 <= soc <= 100):
                return 400, "khung %d: stop_soc phải trong khoảng 0..100 %%" % n
            if "grid_charging" in e and not isinstance(e["grid_charging"], bool):
                return 400, "khung %d: grid_charging phải là true/false" % n
            changes.append((n, e))
        if p["enabled"] and not any_time:
            return 400, "Bật lịch sạc cần ít nhất một khung có start_time và end_time"
        cur = p.get("charge_current_a")
        if cur is not None and not (isinstance(cur, (int, float)) and 0 < cur <= 400):
            return 400, "params.charge_current_a phải trong khoảng (0, 400] A"
        for n, e in changes:
            slot = self.cfg["periods"][n - 1]
            if "start_time" in e:
                slot["start_time"], slot["end_time"] = norm_time(e["start_time"]), norm_time(e["end_time"])
            if "charge_power_w" in e:
                slot["charge_power_w"] = round(e["charge_power_w"])
            if "stop_soc" in e:
                slot["stop_soc"] = round(e["stop_soc"])
            if "grid_charging" in e:
                self.cfg["grid_charging"][n - 1] = e["grid_charging"]
            elif p["enabled"] and "start_time" in e:
                self.cfg["grid_charging"][n - 1] = True
        if cur is not None:
            self.cfg["charge_current_a"] = cur
        self.cfg["schedule_enabled"] = p["enabled"]
        return 200, "Đã bật lịch sạc từ lưới." if p["enabled"] else "Đã tắt lịch sạc."

    def set_grid(self, p, *_):
        if "zero_export_enabled" not in p and "max_export_power_w" not in p:
            return 400, "Cần params.zero_export_enabled và/hoặc params.max_export_power_w"
        w = p.get("max_export_power_w")
        if w is not None and not (isinstance(w, (int, float)) and 0 <= w <= 500):
            return 400, "params.max_export_power_w phải trong khoảng 0..500 W"
        if "zero_export_enabled" in p:
            if not isinstance(p["zero_export_enabled"], bool):
                return 400, "params.zero_export_enabled phải là true/false"
            where = p.get("zero_export_mode", "home_load")
            if where not in ("home_load", "ups_load"):
                return 400, "params.zero_export_mode phải là home_load hoặc ups_load"
            self.cfg["grid_mode"] = ("limit_" + where) if p["zero_export_enabled"] else "on_grid"
        if w is not None:
            self.cfg["export_w"] = round(w)
        return 200, "Đã cập nhật thông số lưới."

    def fw_check(self, *_):
        self.last_check = int(time.time())
        newer = self.firmware()["update_available"]
        self.fw_result = ("update available: %s -> %s (waiting for confirmation)" % (self.fw, self.latest)) if newer \
            else "up to date (%s, server %s)" % (self.fw, self.latest)
        self.pub("up/firmware", self.firmware(), retain=True)
        return 200, "Đang kiểm tra phiên bản mới, kết quả ở up/firmware"

    def fw_upgrade(self, p, cmd_id, digest):
        ver = str(p.get("version", ""))
        try:
            want = tuple(map(int, ver.split(".")))
            assert len(want) == 3
        except Exception:
            return 400, "version phải có dạng MAJOR.MINOR.PATCH"
        if want <= tuple(map(int, self.fw.split("."))):
            return 400, "Thiết bị đang chạy %s, không nâng cấp lên %s" % (self.fw, ver)
        if self.fw_state != "idle":
            return 409, "Đang có một lần nâng cấp khác"
        if ver != self.latest:
            return 409, "Server đang cung cấp phiên bản %s, không phải %s" % (self.latest, ver)
        threading.Thread(target=self.run_upgrade, args=(ver, cmd_id, digest), daemon=True).start()
        return None

    def run_upgrade(self, ver, cmd_id, digest):
        self.fw_state = "downloading"
        for pct in range(0, 101, 10):
            self.fw_progress = pct
            self.pub("up/firmware", self.firmware(), retain=True)
            time.sleep(1)
        self.fw_state, self.fw_progress, self.fw_result = "rebooting", 0, "installed %s, rebooting" % ver
        self.pub("up/firmware", self.firmware(), retain=True)
        self.ack(cmd_id, "FIRMWARE_UPGRADE", 200, "Đã cài phiên bản %s, thiết bị đang khởi động lại." % ver, digest)
        self.pub("up/status", self.offline("connection_lost"), retain=True)
        time.sleep(4)
        self.fw, self.fw_state = ver, "verifying"
        self.pub("up/status", self.status(), retain=True)
        self.pub("up/firmware", self.firmware(), retain=True)
        time.sleep(10)
        self.fw_state, self.fw_result = "idle", "updated to %s, health check passed" % ver
        self.pub("up/firmware", self.firmware(), retain=True)

    # ------------------------------------------------------------------ main loop
    def on_connect(self, c, u, flags, rc, props=None):
        c.subscribe(self.base + "down/command", qos=1)
        self.pub("up/status", self.status(), retain=True)
        self.pub("up/config/state", self.config_state(), retain=True)
        self.fw_check()
        print("simulator online: %sup/#   (commands on %sdown/command)" % (self.base, self.base))

    def run(self):
        self.c.connect(os.environ["MQTT_HOST"], self.a.port, 30)
        self.c.loop_start()
        tick = 0
        try:
            while True:
                time.sleep(5)
                tick += 1
                with self.lock:
                    self.pub("up/telemetry", self.telemetry())
                    if tick % 4 == 0:
                        self.pub("up/battery", self.battery())
        except KeyboardInterrupt:
            self.pub("up/status", self.offline("connection_lost"), retain=True)
            time.sleep(0.5)
            self.c.loop_stop()
            print("stopped (status left as offline)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tenant", default=os.environ.get("MQTT_TENANT", "dev"))
    ap.add_argument("--sn", default="SIM-0001")
    ap.add_argument("--port", type=int, default=8883)
    ap.add_argument("--locked", action="store_true", help="refuse pv_priority load/grid like a locked inverter")
    ap.add_argument("--update", default="", help="firmware version to announce as available, e.g. 1.0.99")
    Simulator(ap.parse_args()).run()
