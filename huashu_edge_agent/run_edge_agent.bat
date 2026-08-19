@echo off
chcp 65001 >nul
title 华数机器人端侧边缘采集与远程互联客户端

echo ======================================================================
echo  🏭 华数Ⅲ型机器人端侧数据采集与云端长连接客户端
echo ======================================================================
echo.

if not exist venv (
    echo [INFO] 首次运行，正在创建 Python 虚拟环境...
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
) else (
    call venv\Scripts\activate.bat
)

echo [INFO] 正在启动端侧采集程序...
python huashu_edge_collector.py

pause
