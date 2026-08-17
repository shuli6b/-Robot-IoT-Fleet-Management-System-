# 🚀 机器人物联网管理系统 - Ubuntu 22.04 LTS 纯离线开箱即用部署说明书

> **交付合同编号**: IOT-20260811  
> **包类型**: 100% 纯离线独立全量安装包 (Zero-Network Dependency Standalone Package)  
> **适用系统**: Ubuntu 22.04 LTS (x86_64 / amd64)

---

## 📦 本离线包内包含的完整组件清单

本安装包已将所有依赖库、二进制安装包、前端资源全部打包，**目标 Ubuntu 服务器无需连接互联网**：

1. **`app/` (核心业务代码)**:
   - `main.py`: FastAPI 异步核心服务 + MQTT 双向通信客户端
   - `database.py`: SQLite 工业数据库引擎 (WAL 高并发锁优化 + 连接池安全)
   - `mock_robot.py`: 华数机械臂、珞石 AMR 复合机器人、南沙四足机器狗全真遥测模拟器
   - `static/`: 现代化大屏前端 (含离线 `tailwindcss.js` 引擎与 AI Copilot 连续对话中枢)
   - `requirements.txt`: 生产依赖清单
2. **`packages/` (全部离线依赖库)**:
   - `deb/emqx-5.8.0-ubuntu22.04-amd64.deb`: 官方 EMQX 5.8.0 离线 MQTT Broker 安装包 (43.5 MB)
   - `pip_wheels/*.whl`: 26 个针对 Linux x86_64 / Python 3.10 的离线依赖 Wheel 包 (FastAPI, Uvicorn, Pydantic-Core, Uvloop 等)
3. **自动化脚本**:
   - `install.sh`: **【一键全自动离线部署脚本】** (自动装 EMQX、配置 Python 虚拟环境、离线装依赖、注册 systemd 开机自启、放行防火墙)
   - `start.sh`: 一键启动脚本 (`./start.sh all` 启动服务+模拟器)
   - `stop.sh`: 一键安全停止脚本
   - `test_all.sh`: 一键全链路功能自动化验收测试脚本

---

## ⚡ 纯离线实机部署 3 步极简指南

### 第 1 步：将压缩包上传到 Ubuntu 服务器并解压

在您的 Windows 本地终端使用 `scp` 或 WinSCP / FileZilla 上传压缩包：

```bash
# 上传压缩包到服务器 /opt 目录 (或任意目录)
scp robot-iot-standalone-ubuntu22.04.tar.gz user@您的服务器IP:/opt/
```

登录 Ubuntu 服务器终端并解压：

```bash
cd /opt
sudo tar -zxvf robot-iot-standalone-ubuntu22.04.tar.gz
cd robot-iot-standalone
```

---

### 第 2 步：运行一键离线部署脚本

执行一键安装脚本（自动完成所有环境与服务的离线配置，耗时仅需约 15 秒）：

```bash
sudo chmod +x *.sh
sudo ./install.sh
```

> **脚本自动完成的操作**：
> 1. 安装离线 `emqx-5.8.0` MQTT Broker 并启动服务
> 2. 创建 Python 3.10 隔离虚拟环境 `venv`
> 3. 从本地 `packages/pip_wheels/` 离线安装所有 Python 依赖
> 4. 生成并启动 `/etc/systemd/system/robot-iot.service` 开机自启服务
> 5. 自动配置 UFW 防火墙放行 `8000` (Web), `1883` (MQTT), `18083` (EMQX) 端口

---

### 第 3 步：启动机器人数据模拟器与验收测试

安装完成后，运行一键启动命令启动华数臂、AMR 与机器狗的遥测模拟上报：

```bash
./start.sh mock
```

运行自动化接口验收测试：

```bash
./test_all.sh
```

---

## 🌐 访问大屏管理平台

打开任意电脑的浏览器，访问：

- **🖥️ 机器人物联网管理大屏**: `http://<您的Ubuntu服务器IP>:8000/`
- **📊 EMQX MQTT 消息中间件后台**: `http://<您的Ubuntu服务器IP>:18083/` *(默认账号: `admin` / 密码: `public`)*
- **📡 设备 MQTT 上报接入地址**: `mqtt://<您的Ubuntu服务器IP>:1883`

---

## 🛠️ 常用管理命令速查表

| 功能 | 终端命令 |
| :--- | :--- |
| **一键启动全部组件** | `./start.sh all` |
| **一键停止全部组件** | `./stop.sh` |
| **查看系统组件运行状态** | `./start.sh status` |
| **查看服务实时运行日志** | `sudo journalctl -u robot-iot -f` |
| **重启后台系统服务** | `sudo systemctl restart robot-iot` |
| **运行全自动功能测试** | `./test_all.sh` |
