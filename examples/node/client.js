// Minimal client: discover a device, send one (invalid) command, print its acknowledgement.
// Same code as section 9 of docs/AI_INTEGRATION_GUIDE.md. Needs MQTT_HOST, MQTT_USER, MQTT_PASSWORD.
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
