#!/bin/bash
# ==============================================================================
# 机器人物联网管理系统 (Robot IoT Management System) - 一键启动脚本
# 适用系统: Ubuntu 22.04 LTS / Linux / macOS
# ==============================================================================

set -e

# 获取脚本所在目录的绝对路径
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "======================================================================"
echo "🤖 机器人物联网管理系统 (Robot IoT Platform)"
echo "   工作目录: $SCRIPT_DIR"
echo "======================================================================"

# 1. 检查并创建 Python 虚拟环境 (venv)
if [ ! -d "venv" ]; then
    echo "[INFO] 正在创建 Python 虚拟环境 (venv)..."
    python3 -m venv venv || {
        echo "[ERROR] 创建虚拟环境失败，请先安装 python3-venv: sudo apt install -y python3-venv"
        exit 1
    }
fi

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 安装或更新 Python 依赖
echo "[INFO] 正在检查并安装依赖 (requirements.txt)..."
pip install -r requirements.txt -q

# 4. 检查 SQLite 数据库并自动初始化
echo "[INFO] 正在校验 SQLite 数据库环境..."
python3 -c "from database import init_db, check_db_integrity; init_db(); check_db_integrity()"

# 5. 获取本机内网 IP 地址
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
    HOST_IP="127.0.0.1"
fi

echo "======================================================================"
echo "✅ 服务准备就绪，正在启动 FastAPI 后端与 MQTT 监听引擎..."
echo "🌐 Web 前端管理后台: http://${HOST_IP}:8000"
echo "📚 API 交互式文档:   http://${HOST_IP}:8000/docs"
echo "🩺 系统健康检查接口: http://${HOST_IP}:8000/api/health"
echo "📝 系统运行日志文件: $SCRIPT_DIR/robot_iot.log"
echo "======================================================================"
echo "[INFO] 按 Ctrl+C 可优雅停止服务..."

# 6. 启动 Uvicorn 服务
exec python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
