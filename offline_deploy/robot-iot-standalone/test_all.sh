#!/usr/bin/env bash
# ==============================================================================
# 机器人物联网管理系统 - 一键全链路自动化离线验收测试脚本
# ==============================================================================

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

if [ -f "$DIR/venv/bin/python" ]; then
    PYTHON="$DIR/venv/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
else
    PYTHON="python"
fi

echo -e "${CYAN}=====================================================${NC}"
echo -e "${CYAN}  🧪 机器人物联网管理系统 - 自动化功能与接口验收测试${NC}"
echo -e "${CYAN}=====================================================${NC}"

$PYTHON - << 'EOF'
import sys, urllib.request, json, time

base = "http://127.0.0.1:8000"
endpoints = [
    ("系统健康状态", "/api/health"),
    ("全局统计大屏", "/api/system/overview"),
    ("设备档案列表", "/api/devices"),
    ("运营分析与OEE", "/api/analytics/operational"),
    ("大模型配置接口", "/api/ai/config"),
    ("公网穿透管理器", "/api/tunnel/status"),
]

passed = 0
total = len(endpoints)

print("\n--- 1. 核心 RESTful API 接口冒烟测试 ---")
for name, p in endpoints:
    try:
        r = urllib.request.urlopen(base + p, timeout=5)
        d = json.loads(r.read().decode())
        code = d.get("code", 0)
        if code == 200:
            print(f"  \033[0;32m[PASS]\033[0m {name:16} -> GET {p:25} (HTTP 200 OK)")
            passed += 1
        else:
            print(f"  \033[0;31m[FAIL]\033[0m {name:16} -> GET {p:25} (Code: {code})")
    except Exception as e:
        print(f"  \033[0;31m[FAIL]\033[0m {name:16} -> GET {p:25} (Error: {e})")

# 2. AI 多轮对话与全域智能中枢测试
print("\n--- 2. AI 智能运维多轮对话接口测试 ---")
total += 1
try:
    req_body = json.dumps({
        "messages": [
            {"role": "user", "content": "华数机械臂和珞石AMR当前工况正常吗？"},
            {"role": "assistant", "content": "华数机械臂与珞石AMR当前处于在线监测中，各关节及底盘参数正常。"},
            {"role": "user", "content": "请评估500小时润滑维保倒计时"}
        ]
    }).encode("utf-8")
    req = urllib.request.Request(base + "/api/ai/chat", data=req_body, headers={"Content-Type": "application/json"})
    r = urllib.request.urlopen(req, timeout=10)
    d = json.loads(r.read().decode())
    if d.get("code") == 200:
        reply = d.get("data", {}).get("reply", "")
        mode = d.get("data", {}).get("mode", "unknown")
        print(f"  \033[0;32m[PASS]\033[0m AI 多轮连续对话中枢 -> POST /api/ai/chat (模式: {mode})")
        print(f"         回复摘要: {reply[:80]}...")
        passed += 1
    else:
        print(f"  \033[0;31m[FAIL]\033[0m AI 对话接口异常: {d}")
except Exception as e:
    print(f"  \033[0;31m[FAIL]\033[0m AI 对话接口调用失败: {e}")

print("\n-------------------------------------------")
print(f"验收测试结果: {passed}/{total} 接口通过")
if passed == total:
    print("\033[0;32m🎉 系统功能全部健康，满足合同全部交付与部署要求！\033[0m")
else:
    print("\033[1;33m⚠️ 部分接口未通过，请检查服务是否已启动 (运行 ./start.sh all)\033[0m")
EOF
