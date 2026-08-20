#!/bin/bash
# ==============================================================================
# 昕邦智能装备 · 机器人物联网管控平台
# 生产服务器一键安全热升级脚本 (One-Click Safe Update)
# 作用：无损拉取最新代码、自动迁移数据库扩展字段、保留所有自定义图文与历史数据
# ==============================================================================

set -e

echo "======================================================================"
echo "🔄 正在开始更新 昕邦智能装备 · 机器人物联网管控平台..."
echo "======================================================================"

DEPLOY_DIR="/opt/robot-iot"
if [ ! -d "$DEPLOY_DIR" ]; then
    if [ -d "/home/qtz/桌面/robot-iot-standalone/app" ]; then
        DEPLOY_DIR="/home/qtz/桌面/robot-iot-standalone/app"
    elif [ -d "$PWD/static" ]; then
        DEPLOY_DIR="$PWD"
    fi
fi

cd "$DEPLOY_DIR"
echo "📁 当前工作目录: $DEPLOY_DIR"

if [ -f "robot_iot.db" ]; then
    cp robot_iot.db "robot_iot_backup_$(date +%Y%m%d_%H%M%S).db"
    echo "💾 已完成历史数据库自动快照备份"
fi

if [ -d ".git" ]; then
    echo "📥 正在从 GitHub 同步最新代码..."
    git pull origin main || (git fetch --all && git reset --hard origin/main)
else
    echo "📥 正在下载最新核心程序包..."
    wget -qO /tmp/repo.tar.gz https://github.com/shuli6b/-Robot-IoT-Fleet-Management-System-/archive/refs/heads/main.tar.gz
    tar -zxf /tmp/repo.tar.gz --strip-components=1 -C "$DEPLOY_DIR"
    rm -f /tmp/repo.tar.gz
fi

VENV_PYTHON="python3"
if [ -f "$DEPLOY_DIR/venv/bin/python" ]; then
    VENV_PYTHON="$DEPLOY_DIR/venv/bin/python"
    $DEPLOY_DIR/venv/bin/pip install -r requirements.txt || true
elif command -v python3 &> /dev/null; then
    pip3 install -r requirements.txt || true
fi

$VENV_PYTHON -c "from database import init_db, check_db_integrity; init_db(); check_db_integrity()"

if systemctl is-active --quiet robot-iot; then
    sudo systemctl restart robot-iot
    echo "✅ robot-iot 服务已平滑重启！"
elif systemctl is-active --quiet robot_iot; then
    sudo systemctl restart robot_iot
    echo "✅ robot_iot 服务已平滑重启！"
fi

echo "======================================================================"
echo "🎉 生产服务器升级完成！"
echo "🌐 平台访问地址: http://106.55.248.254:8000"
echo "======================================================================"
