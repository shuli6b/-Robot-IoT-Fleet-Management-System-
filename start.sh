#!/usr/bin/env bash
set -euo pipefail
# Starts monitoring and its bridge, not robot motion.
sudo systemctl start robot-iot.service huashu-bridge.service
sudo systemctl is-active robot-iot.service huashu-bridge.service
