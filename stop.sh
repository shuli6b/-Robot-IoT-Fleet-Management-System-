#!/usr/bin/env bash
set -euo pipefail
# Stopping software is NOT an emergency stop of the physical robot.
case "${1:-all}" in
  mock) sudo systemctl stop robot-mock.service ;;
  bridge) sudo systemctl stop huashu-bridge.service ;;
  server) sudo systemctl stop robot-iot.service ;;
  all) sudo systemctl stop robot-mock.service huashu-bridge.service robot-iot.service ;;
  *) printf '%s\n' 'Usage: stop.sh [mock|bridge|server|all]' >&2; exit 2 ;;
esac
