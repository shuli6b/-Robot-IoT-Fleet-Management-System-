#!/bin/bash
# ==============================================================================
# 机器人物联网管控平台 (Robot IoT Fleet Management System)
# 全新 Ubuntu 22.04 LTS 生产服务器一键全自动部署脚本 (One-Click Auto Deploy)
# ==============================================================================

set -e

echo "======================================================================"
echo "🚀 正在开始全自动部署 昕邦智能装备 · 机器人物联网管控平台..."
echo "======================================================================"

# 1. 基础系统依赖与 Python3 环境安装
echo "[1/6] 安装系统依赖与 Python 环境..."
apt-get update -y
apt-get install -y python3 python3-pip python3-venv curl wget git net-tools

# 2. 安装 EMQX 5.8 工业物联网 Broker
echo "[2/6] 安装与启动 EMQX 5.8.0 物联网消息中间件..."
if ! command -v emqx &> /dev/null; then
    curl -s https://assets.emqx.com/scripts/install-emqx-deb.sh | bash || true
    apt-get install -y emqx || {
        cd /tmp
        wget -q https://www.emqx.com/zh/downloads/broker/v5.8.0/emqx-5.8.0-ubuntu22.04-amd64.deb
        dpkg -i emqx-5.8.0-ubuntu22.04-amd64.deb
    }
fi
systemctl daemon-reload
systemctl enable --now emqx
systemctl restart emqx

# 3. 创建标准部署目录与虚拟环境
echo "[3/6] 初始化应用目录 /opt/robot-iot 与 Python 虚拟环境..."
mkdir -p /opt/robot-iot/static/assets
cd /opt/robot-iot

if [ ! -d "/opt/robot-iot/venv" ]; then
    python3 -m venv /opt/robot-iot/venv
fi

/opt/robot-iot/venv/bin/pip install --upgrade pip
/opt/robot-iot/venv/bin/pip install -r requirements.txt

# 4. 初始化数据库与表结构
echo "[4/6] 初始化持久化数据库与资产配置..."
/opt/robot-iot/venv/bin/python -c "from database import init_db, check_db_integrity; init_db(); check_db_integrity()"

# 5. 配置并启动 robot-iot 系统守护服务
echo "[5/6] 注册并启动 systemd 后台守护服务 (robot-iot)..."
cat << 'EOF' > /etc/systemd/system/robot-iot.service
[Unit]
Description=Robot IoT Fleet Management Cloud Platform (FastAPI + MQTT)
After=network.target emqx.service
Wants=emqx.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/robot-iot
ExecStart=/opt/robot-iot/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=3s
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now robot-iot
systemctl restart robot-iot

# 6. 配置 FRP 客户端穿透 (可选)
FRPS_HOST="${FRPS_SERVER_IP:-127.0.0.1}"
FRPS_AUTH_TOKEN="${FRPS_AUTH_TOKEN:-YOUR_AUTH_TOKEN}"

echo "[6/6] 配置 FRP 穿透客户端 (frpc)..."
mkdir -p /usr/local/frp
cat << EOF > /usr/local/frp/frpc.toml
serverAddr = "$FRPS_HOST"
serverPort = 7000
auth.token = "$FRPS_AUTH_TOKEN"

[[proxies]]
name = "iot-web"
type = "tcp"
localIP = "127.0.0.1"
localPort = 8000
remotePort = 8000

[[proxies]]
name = "iot-mqtt"
type = "tcp"
localIP = "127.0.0.1"
localPort = 1883
remotePort = 1883

[[proxies]]
name = "emqx-dashboard"
type = "tcp"
localIP = "127.0.0.1"
localPort = 18083
remotePort = 18083

[[proxies]]
name = "local-ssh"
type = "tcp"
localIP = "127.0.0.1"
localPort = 22
remotePort = 2222
EOF

if [ ! -f "/usr/local/frp/frpc" ]; then
    cd /tmp
    wget -q https://github.com/fatedier/frp/releases/download/v0.58.1/frp_0.58.1_linux_amd64.tar.gz || true
    if [ -f "frp_0.58.1_linux_amd64.tar.gz" ]; then
        tar -zxf frp_0.58.1_linux_amd64.tar.gz
        cp frp_0.58.1_linux_amd64/frpc /usr/local/frp/frpc
        chmod +x /usr/local/frp/frpc
    fi
fi

cat << 'EOF' > /etc/systemd/system/frpc.service
[Unit]
Description=FRP Client Service (Robot IoT Intranet Bridge)
After=network.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/frp/frpc -c /usr/local/frp/frpc.toml
Restart=always
RestartSec=5s

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now frpc
systemctl restart frpc || true

echo "======================================================================"
echo "✅ 部署全部成功！"
echo "🌐 本地管控大屏: http://127.0.0.1:8000"
echo "======================================================================"
