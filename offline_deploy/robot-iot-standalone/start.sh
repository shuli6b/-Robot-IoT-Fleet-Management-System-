#!/usr/bin/env bash
# ==============================================================================
# 机器人物联网管理系统 - 一键启动与多模式运行控制脚本
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# 查找 Python 解释器
if [ -f "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

MODE="${1:-all}"

show_status() {
    echo -e "${CYAN}--- 系统当前运行状态 ---${NC}"
    if pgrep -f "uvicorn main:app" > /dev/null; then
        U_PID=$(pgrep -f "uvicorn main:app" | head -n 1)
        echo -e "  FastAPI 服务:       ${GREEN}● 运行中 (PID: $U_PID)${NC} -> http://0.0.0.0:8000"
    else
        echo -e "  FastAPI 服务:       ${RED}○ 未运行${NC}"
    fi

    if pgrep -f "mock_robot.py" > /dev/null; then
        M_PID=$(pgrep -f "mock_robot.py" | head -n 1)
        echo -e "  机器人模拟器:       ${GREEN}● 运行中 (PID: $M_PID)${NC}"
    else
        echo -e "  机器人模拟器:       ${YELLOW}○ 未运行${NC}"
    fi

    if command -v systemctl &>/dev/null && systemctl is-active --quiet emqx 2>/dev/null; then
        echo -e "  EMQX MQTT Broker:   ${GREEN}● 运行中 (Port: 1883)${NC}"
    fi
    echo -e "${CYAN}------------------------${NC}"
}

stop_all() {
    echo -e "${YELLOW}正在停止所有系统服务与模拟器...${NC}"
    pkill -f "mock_robot.py" 2>/dev/null || true
    pkill -f "uvicorn main:app" 2>/dev/null || true
    if command -v systemctl &>/dev/null && systemctl is-active --quiet robot-iot 2>/dev/null; then
        systemctl stop robot-iot 2>/dev/null || true
    fi
    echo -e "${GREEN}✅ 已全部停止。${NC}"
}

case "$MODE" in
    stop)
        stop_all
        exit 0
        ;;
    status)
        show_status
        exit 0
        ;;
    mock)
        echo -e "${CYAN}正在启动 3 台机器人全真遥测模拟器 (华数臂/AMR/机器狗)...${NC}"
        cd "$DIR/app"
        nohup $PYTHON mock_robot.py --interval 2.0 > "$DIR/mock_robot.log" 2>&1 &
        sleep 1
        echo -e "${GREEN}✅ 模拟器已在后台启动 (PID: $!)，日志: mock_robot.log${NC}"
        exit 0
        ;;
    set-ip)
        NEW_IP="$2"
        if [ -z "$NEW_IP" ]; then
            echo -e "${YELLOW}当前配置的公网远程访问地址:${NC}"
            $PYTHON -c "
import sqlite3, os
db_path = os.path.join('$DIR', 'app', 'robot.db')
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute('SELECT config_value FROM system_config WHERE config_key=\"remote_public_url\"')
    row = cur.fetchone()
    print('  -> ' + (row[0] if row and row[0] else '未配置 (当前为局域网直连模式)'))
    conn.close()
" 2>/dev/null || true
            echo -e "\n${CYAN}用法: sudo ./start.sh set-ip http://您的公网IP:8000${NC}"
            exit 0
        fi
        clean_url="$NEW_IP"
        if [[ ! "$clean_url" =~ ^https?:// ]]; then
            clean_url="http://$clean_url"
        fi
        $PYTHON -c "
import sqlite3, os
db_path = os.path.join('$DIR', 'app', 'robot.db')
conn = sqlite3.connect(db_path)
conn.execute('INSERT OR REPLACE INTO system_config (config_key, config_value, updated_at) VALUES (?, ?, datetime(\"now\",\"localtime\"))', ('remote_public_url', '$clean_url'))
conn.commit()
conn.close()
" 2>/dev/null || true
        echo -e "${GREEN}✅ 固定公网远程访问地址已成功更新为: ${CYAN}${clean_url}${NC}"
        echo -e "   网页后台与大屏已同步更新生效。"
        exit 0
        ;;
    app)
        echo -e "${CYAN}正在前台启动 FastAPI 核心服务 (按 Ctrl+C 退出)...${NC}"
        cd "$DIR/app"
        exec $PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8000
        ;;
    all|*)
        echo -e "${CYAN}=====================================================${NC}"
        echo -e "${CYAN}  🚀 正在一键启动机器人物联网管理平台 (含服务+模拟器)${NC}"
        echo -e "${CYAN}=====================================================${NC}"
        
        # 1. 检查并启动 FastAPI 服务
        if ! pgrep -f "uvicorn main:app" > /dev/null; then
            if command -v systemctl &>/dev/null && systemctl list-unit-files | grep -q "robot-iot.service"; then
                echo -e "通过 systemd 启动 robot-iot 服务..."
                systemctl start robot-iot || true
            else
                echo -e "在后台启动 uvicorn 服务..."
                cd "$DIR/app"
                nohup $PYTHON -m uvicorn main:app --host 0.0.0.0 --port 8000 > "$DIR/robot_iot.log" 2>&1 &
            fi
            sleep 2
        fi

        # 2. 启动机器人模拟器
        if ! pgrep -f "mock_robot.py" > /dev/null; then
            echo -e "启动 3 台机器人工业遥测数据上报模拟器..."
            cd "$DIR/app"
            nohup $PYTHON mock_robot.py --interval 2.0 > "$DIR/mock_robot.log" 2>&1 &
            sleep 1
        fi

        echo ""
        show_status
        echo ""
        echo -e "${GREEN}🎉 启动完成！请在浏览器打开: http://localhost:8000/ 或 http://服务器IP:8000/${NC}"
        ;;
esac
