#!/usr/bin/env bash
# ==============================================================================
# 机器人物联网管理系统 - 安全停止脚本
# ==============================================================================
# 用法:
#   ./stop.sh mock       -> 仅停止机器人遥测模拟器 (保持主服务大屏正常运行)
#   ./stop.sh bridge     -> 仅停止华数机械臂采集网关
#   ./stop.sh server     -> 仅停止 Web 大屏与后端服务
#   ./stop.sh            -> 停止全部组件与服务
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

TARGET="${1:-all}"

case "$TARGET" in
    mock)
        echo -e "${YELLOW}🛑 正在仅停止机器人遥测模拟器...${NC}"
        if pgrep -f "mock_robot.py" > /dev/null; then
            pkill -9 -f "mock_robot.py" 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止机器人遥测模拟器 (Web 主服务仍正常运行)${NC}"
        else
            echo -e "${CYAN}ℹ️ 机器人模拟器当前未在运行${NC}"
        fi
        ;;
    bridge)
        echo -e "${YELLOW}🛑 正在仅停止华数机械臂采集网关...${NC}"
        if pgrep -f "huashu_adapter.py" > /dev/null; then
            pkill -9 -f "huashu_adapter.py" 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止华数机械臂采集网关${NC}"
        else
            echo -e "${CYAN}ℹ️ 华数采集网关当前未在运行${NC}"
        fi
        ;;
    server)
        echo -e "${YELLOW}🛑 正在停止 Web 主服务与后台 API...${NC}"
        pkill -9 -f "uvicorn main:app" 2>/dev/null || true
        pkill -9 -f "main:app" 2>/dev/null || true
        if command -v systemctl &>/dev/null && systemctl is-active --quiet robot-iot 2>/dev/null; then
            sudo systemctl stop robot-iot 2>/dev/null || true
        fi
        echo -e "${GREEN}✅ 已停止 Web 主服务${NC}"
        ;;
    all|*)
        echo -e "${YELLOW}🛑 正在安全停止机器人物联网管理系统所有组件...${NC}"
        
        # 1. 停止模拟器
        if pgrep -f "mock_robot.py" > /dev/null; then
            pkill -9 -f "mock_robot.py" 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止机器人遥测模拟器${NC}"
        fi

        # 2. 停止华数采集网关
        if pgrep -f "huashu_adapter.py" > /dev/null; then
            pkill -9 -f "huashu_adapter.py" 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止华数机械臂采集网关${NC}"
        fi

        # 3. 停止 FastAPI 服务
        if pgrep -f "uvicorn main:app" > /dev/null; then
            pkill -9 -f "uvicorn main:app" 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止 FastAPI 进程${NC}"
        fi

        # 4. 停止 systemd 服务
        if command -v systemctl &>/dev/null && systemctl is-active --quiet robot-iot 2>/dev/null; then
            sudo systemctl stop robot-iot 2>/dev/null || true
            echo -e "${GREEN}✅ 已停止 systemd robot-iot 服务${NC}"
        fi

        echo -e "${GREEN}🎉 系统所有服务已完全安全关闭。${NC}"
        ;;
esac
