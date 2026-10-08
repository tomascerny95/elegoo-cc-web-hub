# Elegoo CC Web Hub

A lightweight, stateless, and local Web Hub for controlling both **Elegoo Centauri Carbon (CC1)** and **Centauri Carbon 2 (CC2)** 3D printers directly in your web browser.

This program automatically discovers your printers on the local network, identifies their connection protocol, and serves the official Elegoo Slicer web panel in English.

---

## ✨ Features
- **Dynamic Network Discovery:** Automatically scans your local network on startup to find active Elegoo CC printers. No manual IP or Serial Number entry required for discovered devices.
- **Dual-Protocol Support:** Handles both CC1 (SDCP over WebSockets on port 3030) and CC2 (MQTT on port 1883) protocols dynamically.
- **Unification:** Serves the official Elegoo web-assets in English (`&lang=en_US`) seamlessly.
- **My Saved Printers:** Save your printers directly in your browser using HTML5 LocalStorage. This keeps the backend server lightweight and stateless.
- **Manual Connection Bypass:** Manually connect to printers using their IP address and Serial Number if UDP discovery is blocked or across VLANs.
- **Webcam Stream Proxying:** Intercepts and routes printer camera streams through port 8484 (`/webcam`), bypassing mixed-content (HTTP/HTTPS) and CORS blocks.
- **WebSocket Bridge:** Transparently tunnels live status MQTT WebSocket traffic through port 8484 (`/ws-mqtt`).
- **File & Timelapse Downloads:** Proxies g-code and timelapse MP4 downloads through port 8484 (`/download`).
- **Tailscale & VPN Optimized:** Single-port proxying (port **8484**) enables safe remote monitoring from anywhere without router port forwarding.
- **Floating "Back to Hub" Button:** Injects a custom floating button to switch between printers easily.

---

## 📁 File Structure

Arrange your project folder on your device as follows:

```text
elegoo-cc-web-hub/
├── elegoo_hub.py          <-- Python script from this repository
├── setup_elegoo_hub.sh    <-- Automated installer & updater
└── lan_service_web/       <-- Copied from your Elegoo/OrcaSlicer installation
    ├── index.html
    ├── favicon.ico
    └── (assets...)
```

> **Note:** To respect copyrights, this repository does not distribute the `lan_service_web` directory. You can find and copy this directory from your local Elegoo Slicer or OrcaSlicer installation files (typically under `resources/plugins/elegoolink/web/lan_service_web/`).

---

## 🚀 Quick Start on Raspberry Pi / Linux

### Automated In-Place Installation (Recommended)

```bash
# 1. Clone the repository
cd ~
git clone https://github.com/tomascerny95/elegoo-cc-web-hub.git

# 2. Enter directory, make script executable, and run installer
cd elegoo-cc-web-hub
chmod +x setup_elegoo_hub.sh
sudo bash ./setup_elegoo_hub.sh
```

The script will automatically:
- Detect your active system user.
- Stop any existing background instance.
- Pull the latest commits from GitHub.
- Create an isolated Python virtual environment (`venv`) and install all dependencies safely without `--break-system-packages`.
- Register and launch the `elegoo_hub.service` systemd unit.

---

## 🌐 Accessing the Hub

Open your web browser and navigate to:
```text
http://<DEVICE_IP>:8484
```
*(Also accessible via your Tailscale IP or `http://<hostname>.local:8484`).*

---

## 🔄 Updating to the Latest Version

To update the hub to the latest version at any time:

```bash
cd ~/elegoo-cc-web-hub
git fetch origin && git reset --hard origin/main && chmod +x setup_elegoo_hub.sh && sudo bash ./setup_elegoo_hub.sh
```

---

## 🖥️ Running on Windows

1. Clone or download the repository.
2. Install Python 3.8+ and dependencies:
   ```bash
   pip install fastapi uvicorn paho-mqtt websocket-client websockets
   ```
3. Copy your `lan_service_web` folder next to `elegoo_hub.py`.
4. Run the application:
   ```bash
   python elegoo_hub.py
   ```
5. Open `http://localhost:8484` in your browser.

---

## 🛠️ Service Management (systemd on Linux)

```bash
# Check service status
sudo systemctl status elegoo_hub

# Restart service
sudo systemctl restart elegoo_hub

# View live application logs
journalctl -u elegoo_hub -f
```

---

## 📄 License
This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details.
