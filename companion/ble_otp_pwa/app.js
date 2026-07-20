/**
 * DriveAuth BLE OTP companion (Web Bluetooth PWA).
 *
 * Contract (must match hardware/ble_gatt_server.py):
 *   Service:        6e400001-b5a3-f393-e0a9-e50e24dcca9e
 *   OTP notify:     6e400003-b5a3-f393-e0a9-e50e24dcca9e  (car → phone)
 *   Ack write:      6e400002-b5a3-f393-e0a9-e50e24dcca9e  (phone → car)
 *
 * Payload: {"v":1,"purpose":"driveauth_ladder_otp","code":"…","ttl_s":…}
 * Ack:     {"v":1,"purpose":"driveauth_ladder_otp_ack","code":"…","ok":true}
 */

const SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e";
const OTP_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e";
const ACK_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e";

const otpEl = document.getElementById("otp");
const statusEl = document.getElementById("status");
const connectBtn = document.getElementById("connect");
const disconnectBtn = document.getElementById("disconnect");

let device = null;
let otpChar = null;
let ackChar = null;

function setStatus(text, kind) {
  statusEl.textContent = text;
  statusEl.className = "status" + (kind ? " " + kind : "");
}

function supportsWebBluetooth() {
  return typeof navigator !== "undefined" && !!navigator.bluetooth;
}

async function connect() {
  if (!supportsWebBluetooth()) {
    setStatus("Web Bluetooth not available in this browser", "err");
    return;
  }
  setStatus("Pick DriveAuth-OTP in the chooser…", "warn");
  try {
    device = await navigator.bluetooth.requestDevice({
      filters: [
        { namePrefix: "DriveAuth" },
        { services: [SERVICE_UUID] },
      ],
      optionalServices: [SERVICE_UUID],
    });
    device.addEventListener("gattserverdisconnected", onDisconnected);
    const server = await device.gatt.connect();
    const service = await server.getPrimaryService(SERVICE_UUID);
    otpChar = await service.getCharacteristic(OTP_CHAR_UUID);
    try {
      ackChar = await service.getCharacteristic(ACK_CHAR_UUID);
    } catch (_) {
      ackChar = null;
    }
    await otpChar.startNotifications();
    otpChar.addEventListener("characteristicvaluechanged", onOtpNotify);
    connectBtn.disabled = true;
    disconnectBtn.disabled = false;
    setStatus("Connected — waiting for OTP", "ok");
  } catch (err) {
    setStatus("Connect failed: " + (err && err.message ? err.message : err), "err");
    await disconnect();
  }
}

function onOtpNotify(event) {
  const value = event.target.value;
  const bytes = new Uint8Array(value.buffer);
  const text = new TextDecoder("utf-8").decode(bytes);
  let code = null;
  try {
    const msg = JSON.parse(text);
    if (msg && msg.purpose === "driveauth_ladder_otp" && msg.code) {
      code = String(msg.code);
    }
  } catch (_) {
    // Non-JSON fallback: show raw if it looks like digits.
    if (/^\d{4,8}$/.test(text.trim())) code = text.trim();
  }
  if (!code) {
    setStatus("Received non-OTP payload", "warn");
    return;
  }
  otpEl.textContent = code;
  setStatus("OTP received", "ok");
  void sendAck(code);
}

async function sendAck(code) {
  if (!ackChar) return;
  const payload = JSON.stringify({
    v: 1,
    purpose: "driveauth_ladder_otp_ack",
    code,
    ok: true,
  });
  try {
    const data = new TextEncoder().encode(payload);
    if (ackChar.properties.writeWithoutResponse) {
      await ackChar.writeValueWithoutResponse(data);
    } else {
      await ackChar.writeValue(data);
    }
  } catch (err) {
    setStatus("Ack write failed (OTP still shown)", "warn");
  }
}

function onDisconnected() {
  setStatus("Disconnected", "warn");
  connectBtn.disabled = false;
  disconnectBtn.disabled = true;
  otpChar = null;
  ackChar = null;
}

async function disconnect() {
  try {
    if (otpChar) {
      try {
        await otpChar.stopNotifications();
      } catch (_) {}
      otpChar.removeEventListener("characteristicvaluechanged", onOtpNotify);
    }
    if (device && device.gatt && device.gatt.connected) {
      device.gatt.disconnect();
    }
  } finally {
    device = null;
    onDisconnected();
  }
}

connectBtn.addEventListener("click", () => void connect());
disconnectBtn.addEventListener("click", () => void disconnect());

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

if (!supportsWebBluetooth()) {
  connectBtn.disabled = true;
  setStatus("Use Chrome on Android (Web Bluetooth required)", "err");
}
