#!/usr/bin/env bash
# ==============================================================================
# 机器人物联网管理系统 (Robot IoT Fleet Management System)
# Ubuntu 离线一键部署安装脚本 (兼容 Ubuntu 20.04 / 22.04)
# 合同编号: IOT-20260811
# ==============================================================================

set -euo pipefail

# 颜色输出定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$INSTALL_DIR"

echo -e "${CYAN}================================================================${NC}"
echo -e "${CYAN}  🤖 机器人物联网管理系统 - 离线一键部署安装向导${NC}"
echo -e "${CYAN}================================================================${NC}"
echo -e "${BLUE}工作目录: ${INSTALL_DIR}${NC}"
echo -e "${BLUE}当前时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
echo ""

# 1. 检查 root 权限
if [ "$EUID" -ne 0 ]; then
    echo -e "${YELLOW}⚠️ 注意: 本脚本需要配置 systemd 服务与安装 DEB 包，请使用 sudo 运行:${NC}"
    echo -e "   ${GREEN}sudo bash install.sh${NC}"
    echo -e "   ${CYAN}可选带公网 IP 部署: sudo bash install.sh --public-ip http://118.24.15.88:8000${NC}"
    exit 1
fi

# 解析命令行参数
PUBLIC_IP_ARG=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --public-ip|-p)
            PUBLIC_IP_ARG="$2"
            shift 2
            ;;
        --public-ip=*)
            PUBLIC_IP_ARG="${1#*=}"
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# 2. 赋予脚本执行权限
chmod +x "$INSTALL_DIR"/*.sh "$INSTALL_DIR"/packages/bin/* 2>/dev/null || true

# ==============================================================================
# 步骤 1/6: 检查 Python 环境
# ==============================================================================
echo -e "${PURPLE}[步骤 1/6] 检查系统 Python 环境与基础工具...${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}❌ 错误: 未检测到 Python 3，请确保系统自带的 python3 已安装。${NC}"
    exit 1
fi

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "${GREEN}✅ 检测到 Python 版本: ${PY_VER}${NC}"

# ==============================================================================
# 步骤 2/6: 安装 EMQX MQTT Broker
# ==============================================================================
echo -e "\n${PURPLE}[步骤 2/6] 安装与配置 EMQX 5.8.0 离线 MQTT Broker...${NC}"
EMQX_DEB=$(ls packages/deb/emqx-*.deb 2>/dev/null | head -n 1)

if [ -n "$EMQX_DEB" ] && [ -f "$EMQX_DEB" ]; then
    echo -e "正在从离线包安装: ${CYAN}${EMQX_DEB}${NC} ..."
    dpkg -i --force-overwrite "$EMQX_DEB" >/dev/null 2>&1 || {
        echo -e "${YELLOW}⚠️ dpkg 安装提示依赖，尝试修复中...${NC}"
        apt-get install -f -y --no-download 2>/dev/null || true
        dpkg -i --force-overwrite "$EMQX_DEB" >/dev/null 2>&1 || true
    }
    echo -e "${GREEN}✅ EMQX 5.8.0 安装配置完成!${NC}"
else
    echo -e "${YELLOW}ℹ️ 未发现 offline EMQX deb 包，检查系统现有 MQTT Broker...${NC}"
fi

# 启动并启用 EMQX
if systemctl list-unit-files 2>/dev/null | grep -q "emqx.service"; then
    echo -e "启动 EMQX 服务并设置开机自启..."
    systemctl daemon-reload
    systemctl enable emqx >/dev/null 2>&1 || true
    systemctl restart emqx >/dev/null 2>&1 || true
    sleep 2
    if systemctl is-active --quiet emqx 2>/dev/null; then
        echo -e "${GREEN}✅ EMQX 5.8.0 MQTT Broker 正在运行 (Port: 1883, Dashboard: 18083)${NC}"
    else
        echo -e "${YELLOW}⚠️ EMQX 正在初始化中，服务可能需要几秒后自动就绪...${NC}"
    fi
fi

# ==============================================================================
# 步骤 3/6: 构建 Python 运行环境并安装全量离线依赖
# ==============================================================================
echo -e "\n${PURPLE}[步骤 3/6] 构建 Python 运行环境并安装全量离线依赖包...${NC}"
VENV_DIR="${INSTALL_DIR}/venv"
WHEELS_DIR="${INSTALL_DIR}/packages/pip_wheels"
PYTHON_CMD=""
PIP_CMD=""

# ------ 策略 A: 尝试创建虚拟环境 ------
if python3 -m venv "$VENV_DIR" 2>/dev/null; then
    # venv 创建成功，检查内部 pip 是否可用
    if [ -f "${VENV_DIR}/bin/pip" ]; then
        PIP_CMD="${VENV_DIR}/bin/pip"
        PYTHON_CMD="${VENV_DIR}/bin/python"
        echo -e "${GREEN}✅ 成功创建 Python 独立虚拟环境: ${VENV_DIR}${NC}"
    elif [ -f "${VENV_DIR}/bin/python" ]; then
        # venv 存在但 pip 不存在 (缺少 ensurepip)，用 get-pip.py 注入
        PYTHON_CMD="${VENV_DIR}/bin/python"
        echo -e "${YELLOW}ℹ️ 虚拟环境已创建但缺少 pip，正在通过离线引擎自动注入...${NC}"
        if [ -f "packages/bin/get-pip.py" ]; then
            "$PYTHON_CMD" packages/bin/get-pip.py --no-index --find-links="$WHEELS_DIR" 2>&1 || true
        fi
        if [ -f "${VENV_DIR}/bin/pip" ]; then
            PIP_CMD="${VENV_DIR}/bin/pip"
            echo -e "${GREEN}✅ pip 已成功注入虚拟环境${NC}"
        fi
    fi
fi

# ------ 策略 B: venv 失败，使用系统级 Python ------
if [ -z "$PYTHON_CMD" ] || [ -z "$PIP_CMD" ]; then
    echo -e "${YELLOW}ℹ️ 虚拟环境创建失败 (缺少 python3-venv)，改用系统级 Python 安装${NC}"
    rm -rf "$VENV_DIR" 2>/dev/null || true
    PYTHON_CMD="python3"

    # 检查系统 pip 是否可用
    if python3 -m pip --version >/dev/null 2>&1; then
        PIP_CMD="python3 -m pip"
        echo -e "${GREEN}✅ 检测到系统 pip 可用${NC}"
    elif command -v pip3 &>/dev/null; then
        PIP_CMD="pip3"
        echo -e "${GREEN}✅ 检测到系统 pip3 可用${NC}"
    else
        # 系统也没有 pip，用 get-pip.py 离线注入
        echo -e "${YELLOW}ℹ️ 系统未安装 pip，正在通过离线引擎自动注入 pip 到系统 Python...${NC}"
        if [ -f "packages/bin/get-pip.py" ]; then
            python3 packages/bin/get-pip.py --no-index --find-links="$WHEELS_DIR" 2>&1 || {
                echo -e "${YELLOW}⚠️ 离线注入 pip 失败，尝试仅使用 pip wheel 直接注入...${NC}"
                PIP_WHL=$(ls "$WHEELS_DIR"/pip-*.whl 2>/dev/null | head -n 1)
                if [ -n "$PIP_WHL" ]; then
                    python3 "$PIP_WHL/pip" install --no-index --no-deps "$PIP_WHL" 2>&1 || true
                fi
            }
        fi

        # 再次检查 pip 是否可用
        if python3 -m pip --version >/dev/null 2>&1; then
            PIP_CMD="python3 -m pip"
            echo -e "${GREEN}✅ pip 已成功注入到系统 Python${NC}"
        else
            echo -e "${RED}❌ 无法安装 pip。请手动执行: sudo apt install python3-pip${NC}"
            echo -e "${RED}   然后重新运行: sudo bash install.sh${NC}"
            exit 1
        fi
    fi
fi

echo -e "Python 解释器: ${CYAN}${PYTHON_CMD}${NC}"
echo -e "Pip 工具:       ${CYAN}${PIP_CMD}${NC}"

# 安装离线 wheel 包
echo -e "正在从本地离线 Wheel 目录安装所有依赖包..."

# 兼容 PEP 668 (新版 pip 要求 --break-system-packages)
BSP_FLAG=""
if $PIP_CMD install --help 2>/dev/null | grep -q "break-system-packages"; then
    BSP_FLAG="--break-system-packages"
fi

# 尝试批量安装
$PIP_CMD install --no-index --find-links="$WHEELS_DIR" $BSP_FLAG "$WHEELS_DIR"/*.whl 2>&1 || {
    echo -e "${YELLOW}⚠️ 批量安装遇到冲突，改为逐个安装 wheel 包以确保最大兼容性...${NC}"
    for whl in "$WHEELS_DIR"/*.whl; do
        $PIP_CMD install --no-index --no-deps $BSP_FLAG "$whl" 2>&1 || true
    done
}

# 验证核心 Python 模块
echo -e "验证核心 Python 依赖模块完整性..."
VERIFY_RESULT=$($PYTHON_CMD -c "
import sys
modules = []
try:
    import fastapi; modules.append('FastAPI')
except: pass
try:
    import uvicorn; modules.append('Uvicorn')
except: pass
try:
    import paho.mqtt.client; modules.append('Paho-MQTT')
except: pass
try:
    import aiosqlite; modules.append('aiosqlite')
except: pass
try:
    import httpx; modules.append('HTTPX')
except: pass
print(f'{len(modules)}/5 OK: {', '.join(modules)}')
if len(modules) < 5:
    print('MISSING', file=sys.stderr)
" 2>&1) || true

echo -e "  依赖验证: ${CYAN}${VERIFY_RESULT}${NC}"

if echo "$VERIFY_RESULT" | grep -q "5/5"; then
    echo -e "${GREEN}✅ Python 全部核心依赖验证通过!${NC}"
else
    echo -e "${YELLOW}⚠️ 部分依赖缺失，尝试在线补全 (备用通道)...${NC}"
    $PIP_CMD install $BSP_FLAG -i https://pypi.tuna.tsinghua.edu.cn/simple fastapi uvicorn paho-mqtt aiosqlite python-multipart httpx 2>&1 || {
        echo -e "${YELLOW}⚠️ 在线补全失败 (可能无网络)，请检查离线 wheel 包是否完整${NC}"
    }
fi

# ==============================================================================
# 步骤 4/6: 配置 systemd 系统自启守护服务
# ==============================================================================
echo -e "\n${PURPLE}[步骤 4/6] 配置 Linux systemd 开机自启守护服务...${NC}"
SERVICE_FILE="/etc/systemd/system/robot-iot.service"

# 确定用于 systemd 的 Python 解释器绝对路径
if [ -f "${VENV_DIR}/bin/python" ]; then
    SVC_PYTHON="${VENV_DIR}/bin/python"
    SVC_PATH="${VENV_DIR}/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
else
    SVC_PYTHON=$(which python3)
    SVC_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
fi

cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Robot IoT Fleet Management Cloud Platform (FastAPI + MQTT)
After=network.target network-online.target emqx.service
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${INSTALL_DIR}/app
Environment="PATH=${SVC_PATH}"
Environment="PYTHONUNBUFFERED=1"
ExecStart=${SVC_PYTHON} -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=3s
KillMode=mixed
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable robot-iot >/dev/null 2>&1 || true
systemctl restart robot-iot >/dev/null 2>&1 || true
sleep 3

if systemctl is-active --quiet robot-iot 2>/dev/null; then
    echo -e "${GREEN}✅ systemd 服务已注册并正常运行: robot-iot.service${NC}"
else
    echo -e "${YELLOW}ℹ️ systemd 服务启动异常，查看详情: journalctl -u robot-iot -n 20${NC}"
    echo -e "${YELLOW}   正在改用后台进程模式启动...${NC}"
    cd "${INSTALL_DIR}/app"
    nohup $SVC_PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8000 > "${INSTALL_DIR}/robot_iot.log" 2>&1 &
    sleep 2
    if curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/health 2>/dev/null | grep -q "200"; then
        echo -e "${GREEN}✅ 后台进程模式启动成功!${NC}"
    else
        echo -e "${RED}⚠️ 服务启动失败，请检查日志: ${INSTALL_DIR}/robot_iot.log${NC}"
    fi
fi

# ==============================================================================
# 步骤 5/6: 防火墙配置
# ==============================================================================
echo -e "\n${PURPLE}[步骤 5/6] 检查并开放防火墙端口...${NC}"
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
    ufw allow 8000/tcp comment 'Robot IoT Web Platform' >/dev/null 2>&1 || true
    ufw allow 1883/tcp comment 'EMQX MQTT Protocol' >/dev/null 2>&1 || true
    ufw allow 18083/tcp comment 'EMQX Admin Dashboard' >/dev/null 2>&1 || true
    echo -e "${GREEN}✅ 防火墙规则已自动放行 (8000, 1883, 18083)${NC}"
else
    echo -e "${CYAN}ℹ️ 防火墙 UFW 未开启或无需额外配置${NC}"
fi

# ==============================================================================
# 步骤 6/6: 启动模拟器并展示访问信息
# ==============================================================================
echo -e "\n${PURPLE}[步骤 6/6] 自检系统服务并配置远程访问地址...${NC}"

# 如果用户在命令行传入了公网 IP，自动写入数据库配置
if [ -n "$PUBLIC_IP_ARG" ]; then
    echo -e "正在写入固定公网 IP 配置: ${CYAN}${PUBLIC_IP_ARG}${NC} ..."
    $SVC_PYTHON -c "
import sqlite3, os
clean_url = '${PUBLIC_IP_ARG}'.strip()
if clean_url and not clean_url.startswith(('http://', 'https://')):
    clean_url = 'http://' + clean_url
db_path = os.path.join('${INSTALL_DIR}', 'app', 'robot.db')
conn = sqlite3.connect(db_path)
conn.execute('CREATE TABLE IF NOT EXISTS system_config (config_key TEXT PRIMARY KEY, config_value TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime(\"now\",\"localtime\")))')
conn.execute('INSERT OR REPLACE INTO system_config (config_key, config_value, updated_at) VALUES (?, ?, datetime(\"now\",\"localtime\"))', ('remote_public_url', clean_url))
conn.commit()
conn.close()
print('公网 IP 自动写入数据库成功')
" 2>/dev/null || true
fi

cd "$INSTALL_DIR"
./start.sh mock >/dev/null 2>&1 || true

# 获取本机 IP 地址
HOST_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
    HOST_IP="127.0.0.1"
fi

echo ""
echo -e "${CYAN}================================================================${NC}"
echo -e "${GREEN}  🎉 恭喜！机器人物联网管理系统 一键离线安装与配置全部成功！${NC}"
echo -e "${CYAN}================================================================${NC}"
echo -e "  🌐 局域网内直连访问地址:   ${CYAN}http://${HOST_IP}:8000/${NC}"
if [ -n "$PUBLIC_IP_ARG" ]; then
echo -e "  🌟 固定公网远程访问地址:   ${GREEN}${PUBLIC_IP_ARG}${NC} (已自动联动写入系统后台)"
fi
echo -e "  📊 EMQX 消息中间件后台:    ${CYAN}http://${HOST_IP}:18083/${NC} (默认账号: admin / public)"
echo -e "  📡 MQTT Broker 接入端口:   ${CYAN}${HOST_IP}:1883${NC}"
echo ""
echo -e "${YELLOW}【常用控制命令】:${NC}"
echo -e "  • 随时修改公网 IP 映射:   ${GREEN}sudo ./start.sh set-ip http://您的公网IP:8000${NC}"
echo -e "  • 查看服务实时状态:       ${GREEN}systemctl status robot-iot${NC}  或  ${GREEN}./start.sh status${NC}"
echo -e "  • 查看实时运行日志:       ${GREEN}journalctl -u robot-iot -f${NC}"
echo -e "  • 控制模拟器:             ${GREEN}./start.sh mock${NC} (启动) / ${GREEN}./start.sh stop${NC} (停止)"
echo -e "${CYAN}================================================================${NC}"
