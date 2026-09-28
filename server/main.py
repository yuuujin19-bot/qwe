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

        elif tool_name == "camera_snapshot":
            if not CAMERA_URL:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": "CAMERA_URL is not configured."}]
                    }
                }
            try:
                with urllib.request.urlopen(f"{CAMERA_URL}/latest.jpg", timeout=10) as response:
                    image_bytes = response.read()
                encoded = base64.b64encode(image_bytes).decode("ascii")
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [
                            {"type": "image", "data": encoded, "mimeType": "image/jpeg"}
                        ]
                    }
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "isError": True,
                        "content": [{"type": "text", "text": f"Camera snapshot failed: {exc}"}]
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
