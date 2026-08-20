import asyncio
import time
import json
from bleak import BleakScanner, BleakClient

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

# === CONFIGURATION ===
DEVICE_NAME = "SX765B"
WRITE_HANDLE = 8
BRIDGE_URL = ""  # Fill in your Railway URL
BRIDGE_SECRET = "sx765b-secret"  # Must match server
POLL_INTERVAL = 0.3  # seconds
KEEPALIVE_INTERVAL = 1.5  # seconds

# === STATE ===
last_vib = 0
last_suc = 0
last_send_time = 0
last_command_ts = 0
duration_start = 0
duration_limit = None


def make_vib_cmd(intensity):
    if intensity == 0:
        return bytes([0x55, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00])
    return bytes([0x55, 0x03, 0x00, 0x00, 0x01, intensity, 0x00])


def make_suc_cmd(intensity):
    if intensity == 0:
        return bytes([0x55, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00])
    return bytes([0x55, 0x09, 0x00, 0x00, 0x01, intensity, 0x00])


def poll_server():
    if not BRIDGE_URL:
        return None
    try:
        req = urllib.request.Request(
            f"{BRIDGE_URL}/bridge/poll",
            headers={"Authorization": f"Bearer {BRIDGE_SECRET}"}
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return None


def send_heartbeat(device_name, connected):
    if not BRIDGE_URL:
        return
    try:
        data = json.dumps({"device_name": device_name, "connected": connected}).encode()
        req = urllib.request.Request(
            f"{BRIDGE_URL}/bridge/heartbeat",
            data=data,
            headers={
                "Authorization": f"Bearer {BRIDGE_SECRET}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=3)
    except Exception:
        pass


async def main():
    global last_vib, last_suc, last_send_time, last_command_ts
    global duration_start, duration_limit

    print("=== SX765B BLE Bridge ===")
    print(f"Server: {BRIDGE_URL or '(not configured - local only)'}")
    print()

    print("Scanning for SX765B...")
    device = None
    devices = await BleakScanner.discover(timeout=10.0)
    for d in devices:
        if d.name and DEVICE_NAME in d.name:
            device = d
            break

    if not device:
        print("ERROR: SX765B not found. Make sure toy is on.")
        return

    print(f"Found: {device.name} ({device.address})")

    async with BleakClient(device.address) as client:
        print("Connected!")
        print("Bridge running. Polling for commands...\n")

        send_heartbeat(device.name, True)
        heartbeat_time = time.time()

        try:
            while True:
                now = time.time()

                cmd = poll_server()
                if cmd and cmd.get("timestamp", 0) != last_command_ts:
                    last_command_ts = cmd["timestamp"]
                    action = cmd.get("action", "idle")

                    if action == "stop":
                        last_vib = 0
                        last_suc = 0
                        duration_limit = None
                        await client.write_gatt_char(WRITE_HANDLE, make_vib_cmd(0), response=False)
                        await client.write_gatt_char(WRITE_HANDLE, make_suc_cmd(0), response=False)
                        print(f"[{time.strftime('%H:%M:%S')}] STOP")

                    elif action in ("set", "pulse"):
                        new_vib = cmd.get("vibrate", 0)
                        new_suc = cmd.get("suction", 0)
                        last_vib = max(0, min(20, new_vib))
                        last_suc = max(0, min(10, new_suc))
                        duration_limit = cmd.get("duration")
                        duration_start = now

                        await client.write_gatt_char(WRITE_HANDLE, make_vib_cmd(last_vib), response=False)
                        await client.write_gatt_char(WRITE_HANDLE, make_suc_cmd(last_suc), response=False)
                        last_send_time = now
                        print(f"[{time.strftime('%H:%M:%S')}] SET vib={last_vib} suc={last_suc} dur={duration_limit}")

                if duration_limit and (now - duration_start) >= duration_limit:
                    last_vib = 0
                    last_suc = 0
                    duration_limit = None
                    await client.write_gatt_char(WRITE_HANDLE, make_vib_cmd(0), response=False)
                    await client.write_gatt_char(WRITE_HANDLE, make_suc_cmd(0), response=False)
                    print(f"[{time.strftime('%H:%M:%S')}] Duration ended, stopped.")

                if (last_vib > 0 or last_suc > 0) and (now - last_send_time) >= KEEPALIVE_INTERVAL:
                    await client.write_gatt_char(WRITE_HANDLE, make_vib_cmd(last_vib), response=False)
                    await client.write_gatt_char(WRITE_HANDLE, make_suc_cmd(last_suc), response=False)
                    last_send_time = now

                if (now - heartbeat_time) >= 3.0:
                    send_heartbeat(device.name, True)
                    heartbeat_time = now

                await asyncio.sleep(POLL_INTERVAL)

        except KeyboardInterrupt:
            print("\nStopping...")
            await client.write_gatt_char(WRITE_HANDLE, make_vib_cmd(0), response=False)
            await client.write_gatt_char(WRITE_HANDLE, make_suc_cmd(0), response=False)
            send_heartbeat(device.name, False)
            print("Bye!")


if __name__ == "__main__":
    asyncio.run(main())
