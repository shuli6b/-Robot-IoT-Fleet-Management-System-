#!/bin/bash
# ==============================================================================
# 华数Ⅲ型机器人端侧边缘采集与远程互联客户端 (Linux 运行脚本)
# ==============================================================================

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "[INFO] 首次运行，正在创建 Python 虚拟环境..."
    python3 -m venv venv
    ./venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
fi

echo "[INFO] 正在启动端侧采集程序..."
./venv/bin/python huashu_edge_collector.py
