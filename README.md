# Elegoo CC Web Hub

A lightweight, stateless, and local Web Hub for controlling both **Elegoo Centauri Carbon (CC1)** and **Centauri Carbon 2 (CC2)** 3D printers directly in your web browser. 

This program automatically discovers your printers on the local network, identifies their connection protocol (WebSocket/SDCP for CC1 or MQTT for CC2), and serves the official Elegoo Slicer web panel in English.

## Features

- **Dynamic Network Discovery:** Automatically scans your local network on startup to find active Elegoo CC printers. No manual IP or Serial Number entry required for discovered devices.
- **Dual-Protocol Support:** Handles both CC1 (SDCP over WebSockets on port 3030) and CC2 (MQTT on port 1883) protocols dynamically.
- **Unification:** Serves the official Elegoo web-assets in English (`&lang=en_US`) seamlessly.
- **Floating "Back to Hub" Button:** Injects a custom floating button into the printer interface so you can return to the Hub dashboard and switch printers easily.
- **My Saved Printers (New):** Save your printers directly in your browser using HTML5 LocalStorage. This keeps the backend server lightweight and stateless, as your printer profiles are preserved client-side.
- **Manual Connection Bypass (New):** Manually connect to printers using their IP address and Serial Number. This is useful if UDP broadcast discovery is blocked on your network, or if your printers reside on different subnets or VLANs.
- **Profile Management (New):** Assign custom names to manual printer setups and delete saved configurations from your list when they are no longer needed.
- **Enhanced Hostname Recognition (New):** Displays custom printer hostnames alongside their model names in the discovery list for easier identification.

## Python Installation Guide (For Beginners)

Before running this script, you must have Python 3 and `pip` (Python package manager) installed on your system.

### 1. On Raspberry Pi / Linux (Recommended)
Python 3 is usually pre-installed on Raspberry Pi OS. You can verify, install, or update it by running the following commands in your terminal:
```bash
sudo apt update
sudo apt install python3 python3-pip -y
```

### 2. On Windows
1. Download the official Python 3 installer: [python.org/downloads/windows](https://www.python.org/downloads/windows/).
2. Run the downloaded installer.
3. **CRITICAL STEP:** At the bottom of the installation window, check the box that says **"Add Python.exe to PATH"**. If you skip this step, the `python` command will not work in your command prompt!
4. Click **"Install Now"** and wait for it to complete.

### 3. On macOS
1. Download the latest macOS installer: [python.org/downloads/macos](https://www.python.org/downloads/macos/).
2. Open the downloaded `.pkg` file and follow the standard installation wizard.
3. Alternatively, if you use Homebrew, you can install it via the terminal:
   ```bash
   brew install python
   ```

### 4. Verify your Installation
To ensure Python and `pip` are installed correctly, open your terminal (Linux/macOS) or Command Prompt (Windows) and type:
```bash
python --version   # or: python3 --version
pip --version      # or: pip3 --version
```
If you see version numbers (e.g., `Python 3.11.x`), you are ready to proceed!

## File Structure

Arrange your project folder on your device (e.g., Raspberry Pi) as follows:

```text
elegoo-cc-web-hub/
├── elegoo_hub.py               <-- The Python script from this repository
└── lan_service_web/            <-- Copied from your Elegoo/OrcaSlicer installation
    ├── index.html
    ├── favicon.ico
    └── (all other folders/assets...)
```

> **Note:** To respect copyrights, this repository does not distribute the `lan_service_web` directory. You can find and copy this directory from your local Elegoo Slicer or OrcaSlicer installation files (typically under `resources/plugins/elegoolink/web/lan_service_web/`).

## Installation & Running

1. Install the required Python dependencies:
   ```bash
   pip install fastapi uvicorn paho-mqtt websocket-client --break-system-packages
   ```

2. Place your `lan_service_web` folder next to `elegoo_hub.py`.

3. Run the application:
   ```bash
   python elegoo_hub.py
   ```

4. Open your web browser on any device in the same network and navigate to:
   `http://<YOUR_RASPBERRY_PI_IP>:8484`

5. From the main dashboard:
   - Click **"Scan Network"** to discover nearby printers, or 
   - Fill out the **"Manual Connection"** form to connect and save custom profiles directly into your browser's persistent storage.
