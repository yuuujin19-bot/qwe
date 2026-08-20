from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
import time
import os

app = FastAPI()

SECRET = os.environ.get("BRIDGE_SECRET", "sx765b-secret")

# Command queue (in-memory, single user)
current_command = {
    "action": "idle",
    "vibrate": 0,
    "suction": 0,
    "timestamp": 0
}

bridge_status = {
    "connected": False,
    "last_poll": 0,
    "device_name": None
}


def check_secret(authorization: Optional[str] = Header(None)):
    if authorization != f"Bearer {SECRET}":
        raise HTTPException(status_code=401, detail="Unauthorized")


class ToyCommand(BaseModel):
    action: str = "set"  # set, stop, pulse
    vibrate: int = 0  # 0-20
    suction: int = 0  # 0-10
    duration: Optional[float] = None  # seconds, None = until stopped


class BridgeHeartbeat(BaseModel):
    device_name: Optional[str] = None
    connected: bool = False


# === MCP Tool Endpoints (called by AI) ===

@app.post("/toy/command")
async def send_command(cmd: ToyCommand, authorization: Optional[str] = Header(None)):
    check_secret(authorization)
    current_command["action"] = cmd.action
    current_command["vibrate"] = max(0, min(20, cmd.vibrate))
    current_command["suction"] = max(0, min(10, cmd.suction))
    current_command["duration"] = cmd.duration
    current_command["timestamp"] = time.time()
    return {"status": "ok", "command": current_command}


@app.post("/toy/stop")
async def stop_toy(authorization: Optional[str] = Header(None)):
    check_secret(authorization)
    current_command["action"] = "stop"
    current_command["vibrate"] = 0
    current_command["suction"] = 0
    current_command["duration"] = None
    current_command["timestamp"] = time.time()
    return {"status": "stopped"}


@app.get("/toy/status")
async def toy_status(authorization: Optional[str] = Header(None)):
    check_secret(authorization)
    online = (time.time() - bridge_status["last_poll"]) < 5
    return {
        "bridge_online": online,
        "device": bridge_status["device_name"],
        "current_command": current_command
    }


# === Bridge Endpoints (called by local Python script) ===

@app.get("/bridge/poll")
async def bridge_poll(authorization: Optional[str] = Header(None)):
    check_secret(authorization)
    bridge_status["last_poll"] = time.time()
    return current_command


@app.post("/bridge/heartbeat")
async def bridge_heartbeat(hb: BridgeHeartbeat, authorization: Optional[str] = Header(None)):
    check_secret(authorization)
    bridge_status["connected"] = hb.connected
    bridge_status["device_name"] = hb.device_name
    bridge_status["last_poll"] = time.time()
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "bridge_online": (time.time() - bridge_status["last_poll"]) < 5}
