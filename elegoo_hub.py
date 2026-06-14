import socket
import json
import random
import time
import threading
import os
import logging
import string
import urllib.request
import urllib.parse
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import paho.mqtt.client as mqtt
import websocket as ws_client_lib

# --- LOGGING CONFIGURATION ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger("ElegooHub")

# --- GLOBAL CONFIGURATION (In-Memory Only) ---
PRINTER_IP = ""      
PRINTER_SN = ""      
PRINTER_PROTO = ""   # Will be dynamically set to "cc1" (WebSocket) or "cc2" (MQTT)

# --- GLOBAL PRINTER STATE ---
printer_state = {
    "connected": False,
    "registered": False,
    "hotend_temp": 0.0,
    "hotend_target": 0.0,
    "bed_temp": 0.0,
    "bed_target": 0.0,
    "progress": 0.0,
    "status": "No printer selected",
    "chamber_light": False
}

client_id = f"1_PC_{random.randint(1000, 9999)}"
register_request_id = f"{client_id}_req"

# Connection client instances
mqtt_client = None
ws_client = None
ws_client_conn = None  # Holds the active websocket connection instance for CC1

# --- 1. AUTOMATIC PRINTER DISCOVERY (UDP Multiscanning) ---
def discover_multiple_printers(timeout_sec=2.0):
    logger.info("Starting UDP search for all CC printers on the network...")
    discovered = []
    
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.5)
        
        payload = json.dumps({"id": 0, "method": 7000}).encode("utf-8")
        s.sendto(payload, ("255.255.255.255", 52700))
        
        start_time = time.time()
        while time.time() - start_time < timeout_sec:
            try:
                data, addr = s.recvfrom(4096)
                resp = json.loads(data.decode("utf-8"))
                result = resp.get("result", {})
                ip = addr[0]
                sn = result.get('sn')
                model = result.get('machine_model', 'Unknown')
                hostname = result.get('host_name', '') 
                
                # Determine protocol based on printer model name
                proto = "cc2" if "2" in str(model) else "cc1"
                
                if not any(p['ip'] == ip for p in discovered) and sn:
                    discovered.append({
                        "ip": ip, 
                        "sn": sn, 
                        "model": model, 
                        "hostname": hostname,
                        "proto": proto
                    })
                    logger.info(f"[Discovery] Printer found: {model} ({hostname}) at IP {ip} (Protocol: {proto})")
            except socket.timeout:
                continue
            except Exception as e:
                logger.error(f"[Discovery] Error during scanning: {e}")
                
    return discovered

# --- 2. MQTT COMMUNICATION (For CC2 Printer) ---
def on_connect_cc2(client, userdata, flags, rc):
    global PRINTER_SN, register_request_id
    if rc == 0:
        logger.info(f"[MQTT CC2] Connected to CC2 printer ({PRINTER_IP}).")
        reg_response_topic = f"elegoo/{PRINTER_SN}/{register_request_id}/register_response"
        client.subscribe(reg_response_topic, qos=0)
        
        reg_topic = f"elegoo/{PRINTER_SN}/api_register"
        payload = json.dumps({"client_id": client_id, "request_id": register_request_id})
        client.publish(reg_topic, payload, qos=0)

def on_message_cc2(client, userdata, msg):
    global printer_state, PRINTER_SN
    try:
        raw_payload = msg.payload.decode("utf-8")
        topic = msg.topic
        logger.debug(f"[MQTT CC2 IN] {topic}: {raw_payload}")
        payload = json.loads(raw_payload)

        if "register_response" in topic:
            if payload.get("error") == "ok":
                logger.info("[MQTT CC2] Registration handshake complete!")
                printer_state["connected"] = True
                printer_state["registered"] = True
                printer_state["status"] = "Connected (CC2)"
                
                client.subscribe(f"elegoo/{PRINTER_SN}/api_status", qos=0)
                client.subscribe(f"elegoo/{PRINTER_SN}/{client_id}/api_response", qos=0)
                
                send_raw_command_cc2(1001)
                send_raw_command_cc2(1002)

        elif "api_status" in topic:
            res = payload.get("result", {})
            if "extruder" in res:
                printer_state["hotend_temp"] = res["extruder"].get("temperature", 0.0)
                printer_state["hotend_target"] = res["extruder"].get("target", 0.0)
            if "heater_bed" in res:
                printer_state["bed_temp"] = res["heater_bed"].get("temperature", 0.0)
                printer_state["bed_target"] = res["heater_bed"].get("target", 0.0)
            if "led" in res:
                printer_state["chamber_light"] = int(res["led"].get("status", 0)) > 0
            if "print_status" in res:
                printer_state["progress"] = res["print_status"].get("progress", 0.0)
            if "machine_status" in res:
                status_code = res["machine_status"].get("status", 1)
                sub_status = res["machine_status"].get("sub_status", 0)
                printer_state["status"] = f"Status: {status_code} (Sub: {sub_status})"

        elif "api_response" in topic:
            if payload.get("type") == "PONG":
                logger.debug("Received PONG.")

    except Exception as e:
        logger.error(f"[MQTT CC2] Error parsing MQTT message: {e}", exc_info=True)

def send_raw_command_cc2(method, params=None):
    global mqtt_client, PRINTER_SN
    if params is None:
        params = {}
    if mqtt_client and printer_state["registered"]:
        req_topic = f"elegoo/{PRINTER_SN}/{client_id}/api_request"
        payload = json.dumps({
            "id": random.randint(1000, 9999),
            "method": method,
            "params": params
        })
        mqtt_client.publish(req_topic, payload, qos=0)

# --- 3. WEBSOCKET COMMUNICATION (For CC1 Printer) ---
def on_ws_open(ws):
    global ws_client_conn, printer_state
    logger.info(f"[WS CC1] Connected to CC1 printer ({PRINTER_IP}). Initializing connection...")
    ws_client_conn = ws
    printer_state["connected"] = True
    printer_state["registered"] = True
    printer_state["status"] = "Connected (CC1)"
    
    send_raw_command_cc1(0)
    send_raw_command_cc1(1)

def on_ws_message(ws, message):
    global printer_state
    try:
        logger.debug(f"[WS CC1 IN] {message}")
        payload = json.loads(message)
        topic = payload.get("Topic", "")

        if "sdcp/status/" in topic:
            status = payload.get("Status", {})
            printer_state["hotend_temp"] = float(status.get("TempOfNozzle", 0.0))
            printer_state["hotend_target"] = float(status.get("TempTargetNozzle", 0.0))
            printer_state["bed_temp"] = float(status.get("TempOfHotbed", 0.0))
            printer_state["bed_target"] = float(status.get("TempTargetHotbed", 0.0))
            
            light_status = status.get("LightStatus", {})
            if light_status:
                printer_state["chamber_light"] = bool(light_status.get("SecondLight", False))
                
            print_info = status.get("PrintInfo", {})
            if print_info:
                printer_state["progress"] = float(print_info.get("Progress", 0.0))
                status_code = print_info.get("Status", 1)
                printer_state["status"] = f"Status: {status_code}"

    except Exception as e:
        logger.error(f"[WS CC1] Error parsing WebSocket message: {e}")

def on_ws_close(ws, *args):
    global printer_state, ws_client_conn
    logger.info("[WS CC1] Connection to CC1 closed.")
    ws_client_conn = None
    printer_state["connected"] = False
    printer_state["registered"] = False
    printer_state["status"] = "Disconnected"

def on_ws_error(ws, error):
    logger.error(f"[WS CC1] Connection error occurred: {error}")

def send_raw_command_cc1(cmd_id, data=None):
    global ws_client_conn
    if data is None:
        data = {}
    if ws_client_conn and printer_state["registered"]:
        req_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=32))
        payload = {
            "Id": "",
            "Data": {
                "Cmd": cmd_id,
                "Data": data,
                "From": 1,
                "MainboardId": "",
                "RequestId": req_id,
                "TimeStamp": int(time.time())
            }
        }
        payload_json = json.dumps(payload)
        logger.info(f"[WS CC1 OUT] Sending SDCP command -> Cmd: {cmd_id} | Data: {data}")
        ws_client_conn.send(payload_json)

def start_ws_cc1_thread():
    global ws_client, PRINTER_IP
    url = f"ws://{PRINTER_IP}:3030/websocket"
    logger.info(f"[WS CC1] Connecting to CC1 WebSocket server at {url}...")
    
    ws_client = ws_client_lib.WebSocketApp(
        url,
        on_open=on_ws_open,
        on_message=on_ws_message,
        on_error=on_ws_error,
        on_close=on_ws_close
    )
    ws_client.run_forever()

# --- SHARED CONNECTION INTERFACE ---
def connect_to_printer(ip, sn, proto):
    global mqtt_client, ws_client, ws_client_conn, PRINTER_IP, PRINTER_SN, PRINTER_PROTO, printer_state
    
    logger.info(f"Connecting to printer at {ip} (SN: {sn} | Protocol: {proto})...")
    PRINTER_IP = ip
    PRINTER_SN = sn
    PRINTER_PROTO = proto
    
    # 1. Stop the previous MQTT client (CC2)
    if mqtt_client:
        logger.info("Disconnecting old MQTT client (CC2)...")
        try:
            mqtt_client.loop_stop()
            mqtt_client.disconnect()
            mqtt_client = None
        except Exception as e:
            logger.error(f"Error disconnecting MQTT: {e}")
            
    # 2. Stop the previous WebSocket client (CC1)
    if ws_client:
        logger.info("Disconnecting old WebSocket client (CC1)...")
        try:
            ws_client.close()
            ws_client = None
            ws_client_conn = None
        except Exception as e:
            logger.error(f"Error disconnecting WebSocket: {e}")

    # Reset printer state
    printer_state["connected"] = False
    printer_state["registered"] = False
    printer_state["status"] = "Connecting..."

    # 3. Start client based on selected printer protocol
    if proto == "cc2":
        mqtt_client = mqtt.Client(client_id=client_id)
        mqtt_client.username_pw_set("elegoo", "")
        mqtt_client.on_connect = on_connect_cc2
        mqtt_client.on_message = on_message_cc2
        mqtt_client.connect(PRINTER_IP, 1883, 60)
        mqtt_client.loop_start()
        logger.info("[Protocol] Started async MQTT loop for CC2.")
        
    elif proto == "cc1":
        threading.Thread(target=start_ws_cc1_thread, daemon=True).start()
        logger.info("[Protocol] Started WebSocket thread for CC1.")

def heartbeat_loop():
    logger.info("Heartbeat loop initialized.")
    while True:
        if printer_state["registered"]:
            try:
                if PRINTER_PROTO == "cc2":
                    send_raw_command_cc2(9999)
                elif PRINTER_PROTO == "cc1" and ws_client_conn:
                    ws_client_conn.send("ping")
                    logger.debug("[Heartbeat] Sent WS PING to CC1.")
            except Exception as e:
                logger.error(f"Error in PING: {e}")
        time.sleep(10)

# --- 4. WEB SERVER (FastAPI) ---
app = FastAPI()

# --- MAIN WEB HUB (Landing Page) ---
@app.get("/", response_class=HTMLResponse)
async def get_hub():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Elegoo CC Family Hub</title>
        <style>
            body {
                background-color: #030712;
                color: #f3f4f6;
                font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
                margin: 0;
                padding: 0;
                display: flex;
                flex-direction: column;
                justify-content: space-between;
                min-height: 100vh;
            }
            .container {
                max-width: 36rem;
                margin: 0 auto;
                padding: 1.5rem;
                width: 100%;
                box-sizing: border-box;
            }
            header {
                text-align: center;
                padding: 1.5rem 0;
                border-bottom: 1px solid #1f2937;
                margin-bottom: 2rem;
            }
            h1 {
                font-size: 1.875rem;
                font-weight: 900;
                color: #2dd4bf;
                margin: 0;
            }
            .subtitle {
                font-size: 0.875rem;
                color: #9ca3af;
                margin-top: 0.5rem;
            }
            .card {
                background-color: #111827;
                padding: 1.5rem;
                border-radius: 0.75rem;
                border: 1px solid #1f2937;
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
                margin-bottom: 1.5rem;
            }
            .card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid #1f2937;
                padding-bottom: 0.75rem;
                margin-bottom: 1rem;
            }
            .btn-scan {
                background-color: #0d9488;
                color: white;
                font-weight: bold;
                padding: 0.5rem 1rem;
                border-radius: 0.5rem;
                font-size: 0.875rem;
                border: none;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .btn-scan:hover {
                background-color: #0f766e;
            }
            .btn-scan:disabled {
                background-color: #115e59;
                cursor: not-allowed;
            }
            .printer-item {
                background-color: #030712;
                padding: 1rem;
                border-radius: 0.5rem;
                border: 1px solid #1f2937;
                display: flex;
                justify-content: space-between;
                align-items: center;
                margin-bottom: 0.75rem;
                transition: border-color 0.2s;
            }
            .printer-item:hover {
                border-color: #115e59;
            }
            .printer-info h3 {
                margin: 0;
                color: #2dd4bf;
                font-size: 1.125rem;
            }
            .printer-info p {
                margin: 0.25rem 0 0 0;
                font-size: 0.75rem;
                font-family: monospace;
                color: #6b7280;
            }
            .btn-connect {
                background-color: #1f2937;
                color: white;
                font-weight: bold;
                padding: 0.5rem 1rem;
                border-radius: 0.5rem;
                font-size: 0.75rem;
                border: none;
                cursor: pointer;
                transition: background-color 0.2s;
            }
            .btn-connect:hover {
                background-color: #0d9488;
            }
            .placeholder {
                color: #6b7280;
                text-align: center;
                padding: 1rem 0;
                font-size: 0.875rem;
                margin: 0;
            }
            .text-input {
                background-color: #030712;
                color: #f3f4f6;
                border: 1px solid #1f2937;
                border-radius: 0.5rem;
                padding: 0.5rem 0.75rem;
                width: 100%;
                box-sizing: border-box;
                font-size: 0.875rem;
                margin-top: 0.25rem;
            }
            .text-input:focus {
                outline: none;
                border-color: #0d9488;
            }
            .form-group {
                margin-bottom: 1rem;
                text-align: left;
            }
            .form-group label {
                font-size: 0.75rem;
                color: #9ca3af;
                font-weight: 600;
                text-transform: uppercase;
            }
            .btn-submit {
                background-color: #0d9488;
                color: white;
                font-weight: bold;
                padding: 0.75rem 1rem;
                border-radius: 0.5rem;
                font-size: 0.875rem;
                border: none;
                cursor: pointer;
                width: 100%;
                transition: background-color 0.2s;
                margin-top: 0.5rem;
            }
            .btn-submit:hover {
                background-color: #0f766e;
            }
            .btn-delete {
                background-color: #ef4444;
                color: white;
                font-weight: bold;
                padding: 0.5rem 0.75rem;
                border-radius: 0.5rem;
                font-size: 0.75rem;
                border: none;
                cursor: pointer;
                transition: background-color 0.2s;
                margin-left: 0.5rem;
            }
            .btn-delete:hover {
                background-color: #dc2626;
            }
            .flex-between {
                display: flex;
                align-items: center;
                justify-content: space-between;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>Elegoo CC Family Hub</h1>
                <p class="subtitle">Network scanning and printer selection for CC1/CC2 series</p>
            </header>

            <!-- Printer List -->
            <div class="card">
                <div class="card-header">
                    <h2 style="font-size: 1.125rem; font-weight: bold; color: #d1d5db; margin: 0;">Discovered Printers</h2>
                    <button onclick="scanNetwork()" id="scan-btn" class="btn-scan">Scan Network</button>
                </div>
                
                <div id="printer-list">
                    <p class="placeholder" id="placeholder">Click "Scan Network" to start searching.</p>
                </div>
            </div>

            <!-- Saved Printers Profile List -->
            <div class="card">
                <div class="card-header">
                    <h2 style="font-size: 1.125rem; font-weight: bold; color: #d1d5db; margin: 0;">My Saved Printers</h2>
                </div>
                
                <div id="saved-printer-list">
                    <p class="placeholder" id="saved-placeholder">No saved printers. Add one using the manual connection form below.</p>
                </div>
            </div>

            <!-- MANUAL CONNECTION CARD -->
            <div class="card">
                <div class="card-header">
                    <h2 style="font-size: 1.125rem; font-weight: bold; color: #d1d5db; margin: 0;">Manual Connection</h2>
                </div>
                
                <div class="form-group">
                    <label for="manual-name">Printer Name (Optional)</label>
                    <input type="text" id="manual-name" placeholder="e.g. My Carbon 2" class="text-input">
                </div>
                
                <div class="form-group">
                    <label for="manual-ip">Printer IP Address</label>
                    <input type="text" id="manual-ip" placeholder="e.g. 192.168.1.150" class="text-input">
                </div>
                
                <div class="form-group">
                    <label for="manual-sn">Printer Serial Number (SN)</label>
                    <input type="text" id="manual-sn" placeholder="e.g. F01XABC123XYZ789" class="text-input">
                </div>
                
                <div class="form-group">
                    <label for="manual-proto">Printer Model / Protocol</label>
                    <select id="manual-proto" class="text-input">
                        <option value="cc2">Centauri Carbon 2 (MQTT)</option>
                        <option value="cc1">Centauri Carbon 1 (WebSocket)</option>
                    </select>
                </div>

                <div class="form-group flex-between" style="margin-top: 1rem;">
                    <label for="save-profile" style="cursor: pointer; font-size: 0.875rem; color: #d1d5db;">Save to My Printers</label>
                    <input type="checkbox" id="save-profile" style="accent-color: #0d9488; cursor: pointer; transform: scale(1.2);">
                </div>
                
                <button onclick="connectManually()" class="btn-submit">Connect Manually</button>
            </div>
        </div>

        <script>
            function getSavedPrinters() {
                const data = localStorage.getItem('elegoo_saved_printers');
                return data ? JSON.parse(data) : [];
            }

            function savePrinterToList(name, ip, sn, proto) {
                let printers = getSavedPrinters();
                if (!printers.some(p => p.ip === ip)) {
                    printers.push({ name, ip, sn, proto });
                    localStorage.setItem('elegoo_saved_printers', JSON.stringify(printers));
                }
            }

            function deleteSavedPrinter(ip) {
                let printers = getSavedPrinters();
                printers = printers.filter(p => p.ip !== ip);
                localStorage.setItem('elegoo_saved_printers', JSON.stringify(printers));
                renderSavedPrinters();
            }

            function renderSavedPrinters() {
                const list = document.getElementById('saved-printer-list');
                const printers = getSavedPrinters();
                list.innerHTML = '';
                
                if (printers.length === 0) {
                    list.innerHTML = '<p class="placeholder">No saved printers. Add one using the manual connection form below.</p>';
                    return;
                }
                
                printers.forEach(p => {
                    const div = document.createElement('div');
                    div.className = 'printer-item';
                    div.innerHTML = `
                        <div class="printer-info">
                            <h3>${p.name} (${p.proto.toUpperCase()})</h3>
                            <p>IP: ${p.ip} | SN: ${p.sn}</p>
                        </div>
                        <div style="display: flex; gap: 0.5rem;">
                            <button onclick="connectAndRedirect('${p.ip}', '${p.sn}', '${p.proto}')" class="btn-connect">Connect</button>
                            <button onclick="deleteSavedPrinter('${p.ip}')" class="btn-delete">Delete</button>
                        </div>
                    `;
                    list.appendChild(div);
                });
            }

            async function scanNetwork() {
                const btn = document.getElementById('scan-btn');
                const list = document.getElementById('printer-list');
                const placeholder = document.getElementById('placeholder');
                
                btn.disabled = true;
                btn.innerText = 'Scanning...';
                if(placeholder) placeholder.innerText = 'Searching for CC printers, please wait...';

                try {
                    const response = await fetch('/api/discover');
                    const printers = await response.json();
                    
                    list.innerHTML = '';
                    if (printers.length === 0) {
                        list.innerHTML = '<p class="placeholder" style="color: #ef4444;">No Elegoo CC family printers found on network.</p>';
                    } else {
                        printers.forEach(p => {
                            const div = document.createElement('div');
                            div.className = 'printer-item';
                            
                            const isDifferent = p.hostname && p.hostname.toLowerCase() !== p.model.toLowerCase();
                            const displayName = isDifferent ? `${p.model} (${p.hostname})` : p.model;
                            
                            div.innerHTML = `
                                <div class="printer-info">
                                    <h3>${displayName}</h3>
                                    <p>IP: ${p.ip} | SN: ${p.sn} | Type: ${p.proto.toUpperCase()}</p>
                                </div>
                                <button onclick="connectAndRedirect('${p.ip}', '${p.sn}', '${p.proto}')" class="btn-connect">Connect</button>
                            `;
                            list.appendChild(div);
                        });
                    }
                } catch (e) {
                    list.innerHTML = '<p class="placeholder" style="color: #ef4444;">Error communicating with server.</p>';
                } finally {
                    btn.disabled = false;
                    btn.innerText = 'Scan Network';
                }
            }

            async function connectAndRedirect(ip, sn, proto) {
                try {
                    const response = await fetch(`/api/connect?ip=${ip}&sn=${sn}&proto=${proto}`, { method: 'POST' });
                    const resData = await response.json();
                    
                    if (resData.success) {
                        const targetUrl = `/index?ip=${ip}&sn=${sn}&lang=en_US`;
                        window.location.href = targetUrl;
                    } else {
                        alert('Connection failed: ' + resData.error);
                    }
                } catch (e) {
                    alert('Error sending connection request.');
                }
            }

            async function connectManually() {
                const ip = document.getElementById('manual-ip').value.trim();
                const sn = document.getElementById('manual-sn').value.trim().toUpperCase();
                const proto = document.getElementById('manual-proto').value;
                const name = document.getElementById('manual-name').value.trim() || 'Elegoo CC';
                const saveProfile = document.getElementById('save-profile').checked;

                if (!ip || !sn) {
                    alert('Please fill in both IP Address and Serial Number.');
                    return;
                }

                try {
                    const response = await fetch(`/api/connect?ip=${ip}&sn=${sn}&proto=${proto}`, { method: 'POST' });
                    const resData = await response.json();
                    
                    if (resData.success) {
                        if (saveProfile) {
                            savePrinterToList(name, ip, sn, proto);
                        }
                        const targetUrl = `/index?ip=${ip}&sn=${sn}&lang=en_US`;
                        window.location.href = targetUrl;
                    } else {
                        alert('Connection failed: ' + resData.error);
                    }
                } catch (e) {
                    alert('Error sending manual connection request.');
                }
            }
            
            window.onload = function() {
                renderSavedPrinters();
                scanNetwork();
            };
        </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/api/discover")
async def api_discover():
    printers = discover_multiple_printers(timeout_sec=2.0)
    return printers

@app.post("/api/connect")
async def api_connect(ip: str, sn: str, proto: str):
    try:
        connect_to_printer(ip, sn, proto)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/api/status")
async def get_status():
    return printer_state

@app.post("/api/command")
async def handle_command(cmd: str):
    logger.info(f"[API] Received dashboard command: '{cmd}'")
    if not printer_state["registered"]:
        raise HTTPException(status_code=503, detail="Printer is not connected")
        
    if PRINTER_PROTO == "cc2":
        if cmd == "pause":
            send_raw_command_cc2(1021)
        elif cmd == "resume":
            send_raw_command_cc2(1023)
        elif cmd == "stop":
            send_raw_command_cc2(1022)
        elif cmd == "led_on":
            send_raw_command_cc2(1029, {"brightness": 255, "power": 1})
        elif cmd == "led_off":
            send_raw_command_cc2(1029, {"brightness": 0, "power": 0})
            
    elif PRINTER_PROTO == "cc1":
        if cmd == "pause":
            send_raw_command_cc1(129)
        elif cmd == "resume":
            send_raw_command_cc1(131)
        elif cmd == "stop":
            send_raw_command_cc1(130)
        elif cmd == "led_on":
            send_raw_command_cc1(403, {"LightStatus": {"SecondLight": True, "RgbLight": [0,0,0]}})
        elif cmd == "led_off":
            send_raw_command_cc1(403, {"LightStatus": {"SecondLight": False, "RgbLight": [0,0,0]}})
            
    return {"success": True}

# --- WEBCAM STREAM PROXY ENDPOINT ---
@app.get("/webcam")
async def webcam_proxy():
    if not PRINTER_IP:
        raise HTTPException(status_code=400, detail="No printer selected/connected")
    
    webcam_url = f"http://{PRINTER_IP}:8080/?action=stream"
    
    try:
        req = urllib.request.Request(webcam_url)
        response = urllib.request.urlopen(req, timeout=5)
        
        content_type = response.headers.get(
            "Content-Type", 
            "multipart/x-mixed-replace; boundary=boundarydonotcross"
        )
        
        def stream_chunks():
            try:
                while True:
                    chunk = response.read(4096)
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                logger.debug(f"[Webcam] Stream disconnected or closed: {e}")
            finally:
                response.close()
                
        return StreamingResponse(stream_chunks(), media_type=content_type)
        
    except Exception as e:
        logger.error(f"[Webcam] Failed to connect to printer webcam at {webcam_url}: {e}")
        raise HTTPException(status_code=502, detail="Printer webcam stream is currently unavailable.")

# --- FILE DOWNLOAD PROXY ENDPOINT ---
@app.get("/download")
async def download_proxy(request: Request):
    if not PRINTER_IP:
        raise HTTPException(status_code=400, detail="No printer selected/connected")
    
    # Forward the exact query string (X-Token and file_name) to the printer
    query_string = request.url.query
    printer_url = f"http://{PRINTER_IP}/download?{query_string}"
    logger.info(f"[Download Proxy] Proxying file download from printer: {printer_url}")
    
    try:
        req = urllib.request.Request(printer_url)
        response = urllib.request.urlopen(req, timeout=15)
        
        # Extract headers from the printer response
        headers = {
            "Content-Disposition": response.headers.get("Content-Disposition", "attachment"),
            "Content-Type": response.headers.get("Content-Type", "application/octet-stream")
        }
        
        def stream_file():
            try:
                while True:
                    chunk = response.read(128 * 1024)  # Read in 128KB chunks
                    if not chunk:
                        break
                    yield chunk
            except Exception as e:
                logger.error(f"[Download Proxy] Error during file stream: {e}")
            finally:
                response.close()
                
        return StreamingResponse(stream_file(), headers=headers)
    except Exception as e:
        logger.error(f"[Download Proxy] Failed to proxy file download from tiskarna: {e}")
        raise HTTPException(status_code=502, detail="Failed to fetch file from printer")

# --- LIVE STATE WEBSOCKET PROXY BRIDGE (Port 9001 -> Port 8484) ---
@app.websocket("/ws-mqtt")
async def websocket_mqtt_proxy(client_ws: WebSocket):
    requested_protocols = client_ws.headers.get("sec-websocket-protocol", "")
    subprotocol = "mqtt" if "mqtt" in requested_protocols else None
    
    await client_ws.accept(subprotocol=subprotocol)
    
    if not PRINTER_IP:
        logger.warning("[WS Proxy] Attempted connection with no active printer selected.")
        await client_ws.close()
        return
        
    printer_ws_url = f"ws://{PRINTER_IP}:9001/"
    logger.info(f"[WS Proxy] Establishing live tunnel from client to printer WS at {printer_ws_url} (Subprotocol: {subprotocol})...")
    
    loop = asyncio.get_running_loop()
    
    try:
        # Increase the connection socket timeout to 10 seconds to detect dead servers
        printer_ws = await loop.run_in_executor(
            None,
            lambda: ws_client_lib.create_connection(
                printer_ws_url, 
                timeout=10, 
                subprotocols=["mqtt"] if subprotocol else None
            )
        )
    except Exception as e:
        logger.error(f"[WS Proxy] Connection to printer WebSocket failed: {e}")
        await client_ws.close()
        return

    # Thread target to safely pull messages from the printer and pipe them back to the client WS
    def receive_from_printer():
        import socket  # Import socket inside thread to capture raw socket exceptions
        try:
            while True:
                try:
                    data = printer_ws.recv()
                    if not data:
                        break
                except (ws_client_lib.WebSocketTimeoutException, socket.timeout):
                    # Safely ignore silence timeouts and loop again to keep the tunnel alive
                    continue
                
                # Securely dispatch the transmission to the active async loop
                if isinstance(data, str):
                    asyncio.run_coroutine_threadsafe(client_ws.send_text(data), loop)
                else:
                    asyncio.run_coroutine_threadsafe(client_ws.send_bytes(data), loop)
        except Exception as e:
            logger.debug(f"[WS Proxy] Printer stream connection closed: {e}")
        finally:
            # Safely shut down the client WS once the printer connection drops
            asyncio.run_coroutine_threadsafe(client_ws.close(), loop)

    # Spawn daemon thread for printer-to-client pipeline
    threading.Thread(target=receive_from_printer, daemon=True).start()

    # Main async loop to receive transmissions from client and pipe them directly to the printer
    try:
        while True:
            data = await client_ws.receive()
            if "text" in data:
                printer_ws.send(data["text"])
            elif "bytes" in data:
                printer_ws.send(data["bytes"])
    except WebSocketDisconnect:
        logger.info("[WS Proxy] Client closed WebSocket connection.")
    except Exception as e:
        logger.error(f"[WS Proxy] Error inside communication loop: {e}")
    finally:
        try:
            printer_ws.close()
            logger.info("[WS Proxy] Closed connection to printer.")
        except Exception:
            pass

# --- SPA ROUTING WITH "BACK TO HUB", WEBCAM, WEBSOCKET, AND DOWNLOAD PATCHERS INJECTION ---
@app.get("/index")
@app.get("/index.html")
async def serve_index_page():
    logger.info("[Server] Received printer web panel request. Serving index.html with injected Back button and Network patches...")
    index_path = "lan_service_web/index.html"
    
    if os.path.exists(index_path):
        try:
            with open(index_path, "r", encoding="utf-8") as f:
                html_content = f.read()
            
            # JAVASCRIPT NETWORK PATCHERS
            # 1. Webcam interceptor (redirects 8080 stream to /webcam)
            # 2. WebSocket interceptor (redirects direct ws://...:9001 to /ws-mqtt on this server)
            # 3. Downloads interceptor (redirects direct http://.../download to /download on this server)
            proxy_injection_script = """
            <!-- NETWORK BYPASS PROXY INTERCEPTORS (WEBCAM, WEBSOCKET & DOWNLOADS) -->
            <script>
            (function() {
                console.log("[Network Proxy] Injecting interceptors...");
                
                // --- 1. WEBCAM INTERCEPTOR ---
                const imgDescriptor = Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, 'src');
                const originalImgSet = imgDescriptor.set;
                
                Object.defineProperty(HTMLImageElement.prototype, 'src', {
                    set: function(value) {
                        if (typeof value === 'string' && (value.includes(':8080/?action=stream') || value.includes('/?action=stream'))) {
                            console.log("[Webcam Proxy] Redirecting direct port 8080 stream to local proxy:", value);
                            value = '/webcam';
                        }
                        originalImgSet.call(this, value);
                    }
                });
                
                // --- 2. WEBSOCKET INTERCEPTOR ---
                const OriginalWebSocket = window.WebSocket;
                window.WebSocket = function(url, protocols) {
                    if (typeof url === 'string' && url.includes(':9001')) {
                        console.log("[WS Proxy] Redirecting direct port 9001 WebSocket to local bridge:", url);
                        const localProto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
                        url = localProto + '//' + window.location.host + '/ws-mqtt';
                    }
                    return new OriginalWebSocket(url, protocols);
                };
                
                window.WebSocket.CONNECTING = OriginalWebSocket.CONNECTING;
                window.WebSocket.OPEN = OriginalWebSocket.OPEN;
                window.WebSocket.CLOSING = OriginalWebSocket.CLOSING;
                window.WebSocket.CLOSED = OriginalWebSocket.CLOSED;
                window.WebSocket.prototype = OriginalWebSocket.prototype;

                // --- 3. DOWNLOADS INTERCEPTOR ---
                // Intercept window.open downloads
                const originalOpen = window.open;
                window.open = function(url, target, features) {
                    if (typeof url === 'string' && url.includes('/download')) {
                        console.log("[Download Proxy] Intercepting window.open download:", url);
                        try {
                            const urlObj = new URL(url, window.location.href);
                            url = '/download' + urlObj.search;
                        } catch(e) {}
                    }
                    return originalOpen.call(window, url, target, features);
                };
                
                // Intercept standard <a> tag download clicks
                document.addEventListener('click', function(e) {
                    let target = e.target;
                    while (target && target.tagName !== 'A') {
                        target = target.parentNode;
                    }
                    if (target && target.href && target.href.includes('/download')) {
                        console.log("[Download Proxy] Intercepting link click download:", target.href);
                        try {
                            const urlObj = new URL(target.href, window.location.href);
                            target.href = '/download' + urlObj.search;
                        } catch(e) {}
                    }
                }, true);
            })();
            </script>
            """
            
            # FLOATING BACK TO WEB HUB BUTTON
            # Positioned on the left side of the screen
            back_button_html = """
            <!-- FLOATING BACK TO WEB HUB BUTTON -->
            <div id="oe-back-button" style="position: fixed; bottom: 20px; left: 20px; z-index: 999999; font-family: sans-serif;">
                <a href="/" style="display: flex; align-items: center; justify-content: center; gap: 8px; background-color: #0d9488; color: white; text-decoration: none; padding: 10px 16px; border-radius: 50px; font-weight: bold; font-size: 14px; box-shadow: 0 4px 15px rgba(0,0,0,0.5); border: 1px solid #2dd4bf; transition: all 0.2s ease-in-out;" 
                   onmouseover="this.style.backgroundColor='#0f766e'; this.style.transform='scale(1.05)';" 
                   onmouseout="this.style.backgroundColor='#0d9488'; this.style.transform='scale(1)';">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" style="display: inline-block; vertical-align: middle;">
                        <line x1="19" y1="12" x2="5" y2="12"></line>
                        <polyline points="12 19 5 12 12 5"></polyline>
                    </svg>
                    Back to Hub
                </a>
            </div>
            """
            
            # Inject Patches into <head>
            if "<head>" in html_content:
                html_content = html_content.replace("<head>", f"<head>{proxy_injection_script}")
            else:
                html_content = proxy_injection_script + html_content
                
            # Inject Back Button HTML right before </body>
            if "</body>" in html_content:
                html_content = html_content.replace("</body>", f"{back_button_html}</body>")
            else:
                html_content += back_button_html
                
            return HTMLResponse(content=html_content)
        except Exception as e:
            logger.error(f"[Server] Error processing index.html for injection: {e}")
            raise HTTPException(status_code=500, detail="Error processing template.")
    else:
        logger.error(f"[Server] Slicer webassets index.html file not found in 'lan_service_web' directory!")
        raise HTTPException(status_code=404, detail="index.html not found.")

# --- 5. MOUNTING OFFICIAL SLICER WEB PANEL ---
if os.path.exists("lan_service_web"):
    app.mount("/", StaticFiles(directory="lan_service_web", html=True), name="static")
    logger.info("Official Elegoo Web Assets found.")
else:
    logger.warning("Folder 'lan_service_web' not found. Please place it in the same directory as this script.")

# --- 6. APPLICATION ENTRY POINT ---
if __name__ == "__main__":
    logger.info("=== Starting Elegoo Family Controller Server ===")
    
    # Start heartbeat ping task in a background daemon thread
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    
    # Spin up web server on localhost (127.0.0.1)
    logger.info("Launching Uvicorn server on port 8484.")
    uvicorn.run(app, host="0.0.0.0", port=8484, log_level="info")
