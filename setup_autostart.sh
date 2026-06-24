#!/bin/bash

# Cesta k projektu (upravte pokud se lisi)
PROJECT_DIR="$(pwd)"
PYTHON_PATH="$(which python3)"
SERVICE_FILE="/etc/systemd/system/elegoo_hub.service"

echo "Nastavuji automaticke spousteni pro Elegoo CC Web Hub..."

# Vytvoreni service souboru
sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=Elegoo CC Web Hub
After=network.target

[Service]
ExecStart=$PYTHON_PATH $PROJECT_DIR/elegoo_hub.py
WorkingDirectory=$PROJECT_DIR
StandardOutput=inherit
StandardError=inherit
Restart=always
User=$USER

[Install]
WantedBy=multi-user.target
EOF

# Reload a aktivace
sudo systemctl daemon-reload
sudo systemctl enable elegoo_hub.service
sudo systemctl start elegoo_hub.service

echo "Hotovo! Sluzba byla vytvorena a spustena."
sudo systemctl status elegoo_hub.service --no-pager
