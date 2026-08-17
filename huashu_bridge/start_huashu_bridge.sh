#!/usr/bin/env bash
# ==============================================================================
# 华数Ⅲ型工业机器人 (HSC3) -> MQTT 边缘采集网关启动脚本 (Linux)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ROBOT_IP="${1:-}"
MQTT_HOST="${2:-127.0.0.1}"

echo "================================================================"
echo "  🦾 华数Ⅲ型工业机器人 - MQTT 边缘采集桥接器"
echo "================================================================"
echo "工作目录: $SCRIPT_DIR"

# 检查 Python
if ! command -v python3 &>/dev/null; then
    echo "❌ 错误: 未检测到 python3，请先安装 Python 运行环境"
    exit 1
fi

ARGS=""
if [ -n "$ROBOT_IP" ]; then
    ARGS="$ARGS --robot-ip $ROBOT_IP"
fi
if [ -n "$MQTT_HOST" ]; then
    ARGS="$ARGS --mqtt-host $MQTT_HOST"
fi

echo "正在启动采集桥接器 (参数: $ARGS) ..."
python3 huashu_adapter.py $ARGS
