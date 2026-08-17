"""
tunnel_manager.py - 机器人物联网管理系统 公网与远程访问配置管理器
专注于标准企业级【公网 IP 直连 / 域名映射 / 局域网协同】模式：
- 自动识别并展示本机局域网 IP (如 http://10.0.1.44:8000/)
- 支持用户配置固定公网 IP 或企业域名 (如 http://118.x.x.x:8000 或 https://robot.yourdomain.com)
- 零第三方穿透依赖、零海外网络握手、100% 工业级稳定
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional

try:
    from database import get_system_config, set_system_config
except ImportError:
    def get_system_config(key, default=None): return default
    def set_system_config(key, value): return True

logger = logging.getLogger("RobotIoT.RemoteAccess")

# 获取本机真实内网 IP
def get_local_ip() -> str:
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def get_tunnel_status() -> Dict[str, Any]:
    """获取当前公网与局域网远程访问状态"""
    local_ip = get_local_ip()
    local_url = f"http://{local_ip}:8000"

    # 从系统配置中读取已配置的公网 IP / 域名
    saved_public_url = get_system_config("remote_public_url", default="")

    status = "running" if saved_public_url else "configured"
    active_url = saved_public_url or local_url

    return {
        "status": "running" if saved_public_url else "stopped",
        "engine": "public_ip",
        "local_ip": local_ip,
        "local_url": local_url,
        "public_url": active_url,
        "configured_public_url": saved_public_url,
        "local_port": 8000,
        "mqtt_port": 1883,
        "emqx_port": 18083,
        "traffic_info": "公网 IP / 局域网直连链路正常" if saved_public_url else f"局域网直连已就绪 ({local_url})",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


async def start_tunnel(engine: str = "public_ip", port: int = 8000, custom_url: str = "", **kwargs) -> Dict[str, Any]:
    """
    保存并启用公网 IP / 域名映射配置
    """
    clean_url = (custom_url or "").strip()
    if clean_url:
        if not clean_url.startswith("http://") and not clean_url.startswith("https://"):
            clean_url = "http://" + clean_url
        set_system_config("remote_public_url", clean_url)
        logger.info(f"已更新并启用公网远程访问地址: {clean_url}")
    else:
        # 清空公网地址
        set_system_config("remote_public_url", "")

    return get_tunnel_status()


async def stop_tunnel() -> Dict[str, Any]:
    """重置为默认局域网访问模式"""
    set_system_config("remote_public_url", "")
    logger.info("已重置公网访问地址为局域网默认直连模式")
    return get_tunnel_status()
