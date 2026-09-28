from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import time
import os
import json
import uuid

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
    action: str = "set"
    vibrate: int = 0
    suction: int = 0
    duration: Optional[float] = None


class BridgeHeartbeat(BaseModel):
    device_name: Optional[str] = None
    connected: bool = False


# === MCP Protocol (Streamable HTTP) ===

MCP_TOOLS = [
    {
        "name": "toy_set",
        "description": "Set toy vibration and/or suction intensity. vibrate: 0-20, suction: 0-10. duration in seconds (0 or null = until stopped).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vibrate": {"type": "integer", "description": "Vibration intensity 0-20", "minimum": 0, "maximum": 20},
                "suction": {"type": "integer", "description": "Suction intensity 0-10", "minimum": 0, "maximum": 10},
                "duration": {"type": "number", "description": "Duration in seconds. 0 or omit = until stopped.", "minimum": 0}
            }
        }
    },
    {
        "name": "toy_stop",
        "description": "Immediately stop all toy output.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "toy_status",
        "description": "Check if the BLE bridge is online and what command is active.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]


def handle_mcp_request(body: dict) -> dict:
    method = body.get("method", "")
    req_id = body.get("id")
    params = body.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "sx765b-toy", "version": "1.0.0"}
            }
        }

    elif method == "notifications/initialized":
        return None  # no response for notifications

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": MCP_TOOLS
            }
        }

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name == "toy_set":
            vib = max(0, min(20, int(arguments.get("vibrate", 0))))
            suc = max(0, min(10, int(arguments.get("suction", 0))))
            dur = arguments.get("duration")
            if dur is not None:
                dur = float(dur)
                if dur == 0:
                    dur = None

            current_command["action"] = "set"
            current_command["vibrate"] = vib
            current_command["suction"] = suc
            current_command["duration"] = dur
            current_command["timestamp"] = time.time()

            text = f"Set vibrate={vib}/20, suction={suc}/10"
            if dur:
                text += f", duration={dur}s"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}]
                }
            }

        elif tool_name == "toy_stop":
            current_command["action"] = "stop"
            current_command["vibrate"] = 0
            current_command["suction"] = 0
            current_command["duration"] = None
            current_command["timestamp"] = time.time()
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": "Stopped all output."}]
                }
            }

        elif tool_name == "toy_status":
            online = (time.time() - bridge_status["last_poll"]) < 5
            text = f"Bridge online: {online}"
            if bridge_status["device_name"]:
                text += f", device: {bridge_status['device_name']}"
            text += f", current: vib={current_command['vibrate']} suc={current_command['suction']}"
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": text}]
                }
            }

        else:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }

    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"}
        }


@app.post("/mcp")
async def mcp_endpoint(request: Request):
    body = await request.json()
    response = handle_mcp_request(body)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(content=response)


# === REST Endpoints (still work for manual testing) ===

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


# === Bridge Endpoints ===

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
