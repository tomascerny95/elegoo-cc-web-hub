# Elegoo CC Web Hub

A lightweight, stateless, and 100% local Web Hub for controlling both **Elegoo Centauri Carbon (CC1)** and **Centauri Carbon 2 (CC2)** 3D printers directly in your web browser. 

This program automatically discovers your printers on the local network, identifies their connection protocol (WebSocket/SDCP for CC1 or MQTT for CC2), and serves the official Elegoo Slicer web panel in English.

## Features

- **Dynamic Network Discovery:** Automatically scans your local network on startup to find any active Elegoo CC printers. No manual IP or Serial Number entry required!
- **Dual-Protocol Support:** Handles both CC1 (SDCP over WebSockets on port 3030) and CC2 (MQTT on port 1883) protocols dynamically.
- **Unification:** Serves the official Elegoo web-assets in English (`&lang=en_US`) seamlessly.
- **Floating "Back to Hub" Button:** Injects a custom floating button into the printer interface so you can easily return to the Hub and switch printers.
- **100% Stateless & Local:** Does not write any configuration files to your disk, making it highly secure and SD-card friendly.

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

> **Note:** To respect copyrights, this repository does not distribute the `lan_service_web` directory. You can easily find and copy this directory from your local Elegoo Slicer or OrcaSlicer installation files (typically under `resources/plugins/elegoolink/web/lan_service_web/`).

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

5. Click **"Scan Network"**, find your printer, and click **"Connect"**!
