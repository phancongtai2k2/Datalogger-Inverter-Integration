"""Minimal client: discover a device, send one (invalid) command, print its acknowledgement.

Same code as section 9 of docs/AI_INTEGRATION_GUIDE.md. Needs MQTT_HOST, MQTT_USER, MQTT_PASSWORD.
"""
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
