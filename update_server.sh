#!/usr/bin/env bash
set -euo pipefail
cd /opt/robot-iot
if [ -n "$(git status --porcelain)" ]; then
  printf '%s\n' 'Uncommitted changes present; refusing to overwrite.' >&2
  exit 1
fi
set -a
source /etc/robot-iot/backend.env
set +a
/opt/robot-iot/venv/bin/python backup_service.py --database "$DB_PATH"
git pull --ff-only
/opt/robot-iot/venv/bin/python -m unittest discover -s tests
sudo systemctl restart robot-iot.service huashu-bridge.service
