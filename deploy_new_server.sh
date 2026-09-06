#!/usr/bin/env bash
set -euo pipefail
# Provision credentials, broker ACLs and the verified device registry first.
if [ ! -r /etc/robot-iot/backend.env ] || [ ! -r /etc/robot-iot/bridge.env ]; then
  printf '%s\n' 'Missing protected production environment files; refusing an insecure deployment.' >&2
  exit 1
fi
cd /opt/robot-iot
/opt/robot-iot/venv/bin/python -m pip install -r requirements.txt
/opt/robot-iot/venv/bin/python -m unittest discover -s tests
sudo install -m 644 robot-iot.service /etc/systemd/system/robot-iot.service
sudo systemctl daemon-reload
sudo systemctl enable --now robot-iot.service huashu-bridge.service
