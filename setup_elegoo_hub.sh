#!/usr/bin/env bash
set -e

# Resolve absolute path to the git repository directory
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_SCRIPT="$REPO_DIR/elegoo_hub.py"

# Ensure script is executed with root/sudo privileges
if [ "$EUID" -ne 0 ]; then
  echo "[!] Please run this script with root privileges: sudo bash ./setup_elegoo_hub.sh"
  exit 1
fi

# Fully automatic detection of regular system user (UID >= 1000)
TARGET_USER="${SUDO_USER:-$(awk -F: '$3 >= 1000 && $3 < 60000 {print $1; exit}' /etc/passwd)}"

if [ -z "$TARGET_USER" ]; then
  echo "[!] Error: Failed to detect a valid system user!"
  exit 1
fi

echo "=========================================================="
echo "  Elegoo CC Web Hub Setup & Auto-Updater"
echo "  Running in-place from : $REPO_DIR"
echo "  Target User           : $TARGET_USER"
echo "=========================================================="

echo "=== [1/5] Stopping existing service (Safe Update) ==="
if systemctl is-active --quiet elegoo_hub.service 2>/dev/null; then
    echo "-> Stopping elegoo_hub.service..."
    systemctl stop elegoo_hub.service
fi

echo "=== [2/5] Pulling latest code from Git ==="
if [ -d "$REPO_DIR/.git" ]; then
    echo "-> Checking for updates on GitHub..."
    sudo -u "$TARGET_USER" git -C "$REPO_DIR" pull || echo "-> Note: Local changes present or already up to date."
fi

# Verify main python script presence
if [ ! -f "$PYTHON_SCRIPT" ]; then
  echo "[!] Error: elegoo_hub.py not found in $REPO_DIR!"
  exit 1
fi

echo "=== [3/5] Installing dependencies & virtual environment ==="
apt update
apt install -y python3 python3-pip python3-venv git curl

# Setup a clean Python venv inside the repo (PEP 668 compliant)
VENV_DIR="$REPO_DIR/venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "-> Creating Python virtual environment in $VENV_DIR..."
    sudo -u "$TARGET_USER" python3 -m venv "$VENV_DIR"
fi

echo "-> Installing / updating required Python libraries in venv..."
sudo -u "$TARGET_USER" "$VENV_DIR/bin/pip" install --upgrade \
    fastapi \
    uvicorn \
    paho-mqtt \
    websocket-client \
    websockets

# Check for lan_service_web folder
if [ ! -d "$REPO_DIR/lan_service_web" ]; then
    echo ""
    echo "[!] WARNING: Directory 'lan_service_web' not found in $REPO_DIR!"
    echo "    Make sure to copy it from your Elegoo Slicer / OrcaSlicer installation."
    echo ""
fi

# Set proper ownership
chmod +x "$PYTHON_SCRIPT"
chown -R "${TARGET_USER}:${TARGET_USER}" "$REPO_DIR"

echo "=== [4/5] Configuring systemd service ==="
cat << EOF > /etc/systemd/system/elegoo_hub.service
[Unit]
Description=Elegoo CC Web Hub ($TARGET_USER)
After=network.target

[Service]
Type=simple
User=$TARGET_USER
Group=$TARGET_USER
WorkingDirectory=$REPO_DIR
ExecStart=$VENV_DIR/bin/python $PYTHON_SCRIPT
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

echo "=== [5/5] Enabling and starting service ==="
systemctl daemon-reload
systemctl enable elegoo_hub.service
systemctl restart elegoo_hub.service

IP_ADDR=$(hostname -I | awk '{print $1}')

echo ""
echo "=========================================================="
echo " Setup complete! Elegoo CC Web Hub is ONLINE."
echo "=========================================================="
echo " Web Dashboard : http://${IP_ADDR}:8484"
echo " (Also accessible via Tailscale IP or <hostname>.local:8484)"
echo " Service Status: sudo systemctl status elegoo_hub"
echo " View Logs     : journalctl -u elegoo_hub -f"
echo "=========================================================="
