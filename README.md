# 工业机器人物联网管控平台 (Robot IoT Fleet Management System)

基于 **FastAPI + EMQX (MQTT) + SQLite** 构建的工业机器人设备监控与远程指令调度管理系统。

---

## 📋 功能特点

- **多设备数据接入**：基于 MQTT 异步消息机制，支持机械臂、AMR 移动机器人、四足巡检机器狗等设备的运行状态与传感器数据上报。
- **统一界面架构与一键明暗模式切换**：
  - 默认采用极简浅白风格（纯线条 SVG 矢量图标、清晰留白），适合日常管理与移动端巡检。
  - 界面右上角配备轻量化图标按钮（☀️ / 🌙），一键无缝切换暗黑工业深色模式，自动持久化存储偏好，所有功能完全一致。
- **综合工况大屏**：包含 5 项核心指标概览、实时流式遥测与传感器数据吞吐曲线、广州番禺与南沙节点智造地图。
- **设备台账与 3D 姿态控制**：支持卡片与紧凑列表切换、六轴机械臂关节角度解析、末端空间坐标（XYZ）展示与华数指令控制。
- **AI 自然语言指令解析**：支持输入中文口语化指令，解析为标准控制指令标识与 JSON 参数。
- **远程指令调度**：支持通过 Web 界面向现场设备下发启动、暂停、复位、急停等控制指令。
- **在线时长与状态检测**：后台定时扫描设备上报时间，超时未上报自动标记为离线状态。
- **设备智能诊断**：支持配置大模型 API（通义千问、DeepSeek、OpenAI、Ollama 等兼容接口），辅助分析设备运行状态。

---

## 🌐 界面访问

| 界面 | 访问路径 | 说明 |
| :--- | :--- | :--- |
| **管控大屏主界面** | `http://<服务器IP>:8000/` | 默认极简浅色，支持右上角图标一键切换暗黑模式 |
| **系统登录页面** | `http://<服务器IP>:8000/login` | 矢量地图与系统登录/注册界面，支持一键切换明暗模式 |
| **MQTT 中间件控制台** | `http://<服务器IP>:18083` | EMQX 节点与连接管理 |

> **默认账号**：超级管理员 `admin` / `admin888`，普通操作员 `user` / `123456`

---

## 🏗️ 系统架构

```text
[ 现场设备端 ]                                  [ 服务器端 (Ubuntu / Windows) ]
+-------------------------+                      +---------------------------------------+
| 华数机械臂 / AMR / 机器狗 |                      |            EMQX 消息中间件             |
| (现场设备或模拟器)        | ===== MQTT 报文 =====> |      (端口: 1883 TCP, 18083 Dashboard) |
+-------------------------+ (robot/{type}/{id}/#) +---------------------------------------+
                                                                     ▲
                                                                     │ MQTT 订阅 / 发布 (cmd/#)
                                                                     ▼
                                                  +---------------------------------------+
                                                  |         FastAPI 后端服务              |
                                                  |  - 数据清洗与 SQLite 存储             |
                                                  |  - RESTful API 与设备状态检测         |
                                                  |  - 指令下发与鉴权校验                 |
                                                  +---------------------------------------+
                                                                     ▲
                                                                     │ HTTP 接口与静态页面
                                                                     ▼
                                                  +---------------------------------------+
                                                  |            Web 管理界面               |
                                                  |   (http://服务器IP:8000)              |
                                                  +---------------------------------------+
```

---

## 📂 项目结构

```text
├── main.py                     # FastAPI 后端服务主程序（MQTT监听、REST API、静态托管）
├── database.py                 # SQLite 数据库访问层
├── mock_robot.py               # 机器人设备多节点模拟器
├── run_broker.py               # 本地测试用微型 MQTT 服务
├── requirements.txt            # Python 依赖清单
├── robot-iot.service           # Linux Systemd 服务配置
├── start.sh / stop.sh          # Linux 启动与停止脚本
├── static/                     # 前端静态资源
│   ├── index.html              # 暗黑版监控界面
│   ├── index_next.html         # 极简浅色版监控界面
│   └── login.html              # 极简浅色登录界面
├── huashu_sdk/                 # 华数二次开发接口文件
└── README.md                   # 说明文档
```

---

## 🚀 部署与运行全流程 (从 GitHub 到服务器/本地运行)

### 第一步：获取源码与安装依赖

```bash
# 1. 克隆代码仓库
git clone https://github.com/shuli6b/-Robot-IoT-Fleet-Management-System-.git
cd -Robot-IoT-Fleet-Management-System-

# 2. 创建并激活 Python 虚拟环境 (推荐 Python 3.8+)
python3 -m venv venv
source venv/bin/activate       # Linux / macOS
# .\venv\Scripts\activate      # Windows

# 3. 安装依赖包
pip install -r requirements.txt
```

---

### 第二步：启动运行服务（两种模式任选其一）

#### 选项 A：Linux 服务器生产部署 (Ubuntu 22.04 LTS)

适用于云服务器或局域网工控服务器长期稳定运行：

```bash
# 1. 安装并启动 EMQX 消息中间件
wget https://www.emqx.com/en/downloads/broker/v5.8.0/emqx-5.8.0-ubuntu22.04-amd64.deb
sudo dpkg -i emqx-5.8.0-ubuntu22.04-amd64.deb
sudo systemctl enable emqx --now

# 2. 配置并启动系统后台守护进程
sudo cp robot-iot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable robot-iot --now

# 3. 开放防火墙端口
sudo ufw allow 8000/tcp    # Web 控制台与 API
sudo ufw allow 1883/tcp    # MQTT 设备通信端口
sudo ufw allow 18083/tcp   # EMQX Dashboard (可选)
sudo ufw reload
```

#### 选项 B：本地开发与单机测试 (Windows / Linux)

适用于个人电脑本地开发或快速功能验证，无需安装复杂外部服务：

```bash
# 1. 终端一：启动系统内置微型 MQTT 服务 (监听 1883 端口)
python run_broker.py

# 2. 终端二：启动 FastAPI 后端服务 (监听 8000 端口)
python main.py
```

---

### 第三步：启动模拟设备上报测试数据（可选）

如现场暂无物理机器人连入，可启动内置多设备模拟器：

```bash
# 启动 10 台并发模拟设备 (包含机械臂、AMR 与机器狗)
python mock_robot.py --num-devices 10
```

---

### 第四步：浏览器访问与使用

在浏览器中打开对应地址即可进入系统：

- **管控大屏主界面**：`http://<服务器IP或127.0.0.1>:8000/`（默认浅色，右上角图标一键切换暗黑模式）
- **独立登录页面**：`http://<服务器IP或127.0.0.1>:8000/login`（支持一键切换明暗模式）

---

## 📡 报文对接格式

### 1. 设备遥测数据上报 (Device -> Server)
- **主题格式**：`robot/{device_type}/{device_id}/{data_type}`
  - `device_type`：`huashu_arm` / `luxshare_amr` / `robot_dog`
  - `data_type`：`state`（状态）/ `sensor`（传感器）/ `alarm`（告警）
- **Payload 示例**：
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

### 2. 控制指令下发 (Server -> Device)
- **主题格式**：`robot/{device_type}/{device_id}/cmd`
- **Payload 示例**：
```json
{
  "cmd_id": "cmd_1723880000",
  "action": "start_cycle",
  "params": {
    "speed": 80
  },
  "timestamp": "2026-08-17T16:00:05Z"
}
```

---

## 🔍 API 接口速查

| 方法 | 路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/system/overview` | 获取系统概览统计与连接状态 |
| `GET` | `/api/devices` | 获取设备列表与最新在线状态 |
| `GET` | `/api/history` | 查询历史遥测报文记录 |
| `POST` | `/api/device/{id}/cmd` | 向指定设备下发控制指令 |
| `POST` | `/api/ai/parse_command` | 自然语言指令解析 |
| `POST` | `/api/ai/chat` | AI 智能诊断对话 |
