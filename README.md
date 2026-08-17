# 智能机器人管理系统 (Robot IoT Fleet Management System)

基于 **FastAPI + EMQX (MQTT) + SQLite + 原生轻量化前端** 构建的高性能、工业级机器人集群监控与远程调度管理平台。

---

## 🌟 系统核心特性

- 🚀 **高并发数据接入**：基于 MQTT (paho-mqtt) 异步消息架构，支持海量异构机器人（机械臂、AMR、四足巡检狗）毫秒级遥测数据并发上报。
- 📊 **现代化工业监控大屏**：单文件原生响应式前端，支持 10+ 台设备实时卡片渲染、六轴机械臂关节角度解析、末端空间坐标（XYZ）展示与原始 JSON 报文实时追踪。
- 🎮 **双向远程指令调度**：支持通过 Web 界面向指定设备秒级下发 `start`（启动）、`stop`（停机）、`reset`（复位）、`emergency_stop`（急停）等控制指令（QoS=1）。
- ⏱️ **智能心跳与容灾状态机**：内置后台异步设备心跳扫描与自动离线判定（超时 15 秒自动置灰标记为 `offline`），支持网络抖动自动重连与本地降级入库。
- 🤖 **工业智能诊断中心**：支持接入多大模型服务（通义千问、DeepSeek、OpenAI、Ollama 等），实现设备故障与遥测指标的智能分析诊断。

---

## 🏗️ 系统架构设计

```text
[ 工业现场端 ]                              [ 远端/云端服务器 (Ubuntu 22.04) ]
+---------------------+                      +---------------------------------------+
| 华数机械臂 / AMR / 狗 |                      |            EMQX 消息中间件             |
| (物理设备或模拟集群)  | ===== MQTT 报文 =====> |      (端口: 1883 TCP, 18083 Dashboard) |
+---------------------+ (robot/{type}/{id}/#) +---------------------------------------+
                                                                 ▲
                                                                 │ MQTT 订阅 / 发布 (cmd/#)
                                                                 ▼
                                              +---------------------------------------+
                                              |         FastAPI 核心后台服务           |
                                              |  - 数据清洗与 WAL 高频入库 (SQLite)    |
                                              |  - RESTful API & 自动化心跳扫描        |
                                              |  - 指令下发路由与鉴权校验               |
                                              +---------------------------------------+
                                                                 ▲
                                                                 │ HTTP / JSON 轮询
                                                                 ▼
                                              +---------------------------------------+
                                              |        原生轻量化 Web 管理大屏        |
                                              |   (http://服务器IP:8000 / index.html)   |
                                              +---------------------------------------+
```

---

## 📂 项目目录结构

```text
机器人管理系统/
├── main.py                     # FastAPI 后端核心主程序（MQTT监听、REST API、静态托管）
├── database.py                 # SQLite 数据库访问层（WAL高并发模式、线程安全）
├── mock_robot.py               # 工业机器人多设备并发模拟器（支持10+台多型号动态生成）
├── run_broker.py               # 本地测试用微型 MQTT 中间件服务
├── requirements.txt            # Python 核心依赖清单
├── robot-iot.service           # Linux Systemd 守护进程服务配置文件
├── start.sh / stop.sh          # Linux 一键启动与安全停止脚本
├── static/                     # 前端静态资源目录
│   └── index.html              # 现代化单文件监控调度前端（HTML5 + Tailwind CSS + JS）
├── huashu_sdk/                 # 华数机器人官方二次开发接口库
├── huashu_bridge/              # 华数现场转接桥接程序组件
└── README.md                   # 本部署与测试说明文档
```

---

## 🚀 快速开始与本地测试 (Windows / Linux)

### 1. 环境准备
确保已安装 **Python 3.8+** 及 **Git**。

```bash
# 克隆仓库代码
git clone <您的GitHub仓库地址>
cd 机器人管理系统

# 安装核心依赖
pip install -r requirements.txt
```

### 2. 本地快速启动（3 步完成全闭环测试）

为方便开发与功能验证，系统内置了本地轻量化微型 MQTT Broker，无需安装大型中间件即可在本地一键运行：

```bash
# 步骤 1：启动本地微型 MQTT 服务 (监听 0.0.0.0:1883)
python run_broker.py

# 步骤 2：新建终端，启动 FastAPI 后台管理服务 (监听 0.0.0.0:8000)
python main.py

# 步骤 3：新建终端，启动 10 台并发模拟机器人
python mock_robot.py --num-devices 10
```

### 3. 访问监控大屏
打开浏览器访问：👉 **http://127.0.0.1:8000**
- 顶部概览将显示 **总设备数：10**、**在线设备：10**。
- 右上角 MQTT 状态将显示绿灯 **「已连接」**。
- 可点击任意设备卡片查看动态更新的轴角度、坐标位置与原始报文，并在右下角测试下发任务控制指令。

---

## 🐧 生产环境部署指南 (Ubuntu 22.04 LTS)

### 1. 基础环境安装
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ufw
```

### 2. 安装与配置 EMQX 消息中间件
```bash
# 下载并安装 EMQX
wget https://www.emqx.com/en/downloads/broker/v5.8.0/emqx-5.8.0-ubuntu22.04-amd64.deb
sudo dpkg -i emqx-5.8.0-ubuntu22.04-amd64.deb
sudo systemctl enable emqx --now

# 配置安全认证账户 (禁用匿名登录)
sudo emqx ctl users add robot_server robot_server_pass
```

### 3. 部署后台应用
```bash
# 进入项目目录并创建 Python 虚拟环境
cd /home/ubuntu/机器人管理系统
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 配置 Systemd 系统守护进程
sudo cp robot-iot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable robot-iot --now
```

### 4. 开放防火墙端口
```bash
sudo ufw allow 8000/tcp    # Web 大屏及 REST API 端口
sudo ufw allow 1883/tcp    # MQTT 工业协议接入端口
sudo ufw allow 18083/tcp   # EMQX 后台管理 Dashboard 端口 (可选)
sudo ufw reload
```

---

## 📡 工业设备对接协议规范

### 1. MQTT 报文规范

#### ① 设备遥测数据上报 (Device -> Server)
- **主题格式**：`robot/{device_type}/{device_id}/{data_type}`
  - `device_type`：`huashu_arm`（机械臂）/ `luxshare_amr`（移动机器人）/ `robot_dog`（四足巡检狗）
  - `data_type`：`state`（状态运行）/ `sensor`（传感器指标）/ `alarm`（告警）
- **Payload 示例 (华数机械臂)**：
```json
{
  "timestamp": "2026-08-17T16:00:00Z",
  "status": "running",
  "battery": 88.5,
  "joint_angles": [12.5, -45.2, 88.1, 0.0, 90.0, -15.3],
  "tcp_position": [350.2, -120.5, 450.8],
  "temperature": 42.1,
  "err_code": 0
}
```

#### ② 远程控制指令下发 (Server -> Device)
- **主题格式**：`cmd/{device_type}/{device_id}`
- **Payload 示例**：
```json
{
  "cmd_id": "cmd_1723880000",
  "action": "emergency_stop",
  "params": {},
  "timestamp": "2026-08-17T16:00:05Z"
}
```

---

## 🔍 RESTful API 核心接口速查

| 请求方法 | 接口路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/system/overview` | 获取系统整体概览指标、MQTT连接状态与设备总数 |
| `GET` | `/api/devices` | 获取所有接入设备的最新在线状态与基础属性 |
| `GET` | `/api/devices/{type}/{id}/latest` | 获取指定设备的完整遥测历史与最新传感器读数 |
| `POST` | `/api/control/dispatch` | 向指定设备下发控制指令并同步记录审计日志 |
| `POST` | `/api/ai/chat` | 工业智能故障诊断与数据分析交互接口 |

---

## 📄 开源许可证与协议
本项目严格遵循工程规范开发，供工业机器人集群调度及智能化管理场景使用。
