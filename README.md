# 工业机器人物联网管控平台 (Robot IoT Fleet Management System)

基于 **FastAPI + EMQX (MQTT) + SQLite** 构建的工业机器人设备监控与远程指令调度管理系统。

---

## 📋 功能特点

- **多设备数据接入**：基于 MQTT 异步消息机制，支持机械臂、AMR 移动机器人、四足巡检机器狗等设备的运行状态与传感器数据上报。
- **双版本界面**：
  - **暗黑工业版**（路径：`/` 或 `/dark`）：深色界面，适合车间工控屏与中控室监控大屏。
  - **极简浅色版**（路径：`/light` 或 `/login` 或 `/v2`）：浅色界面与矢量线条图标，适合日常管理与移动端查看。
- **设备工况监控**：支持设备台账展示、六轴机械臂关节角度解析、末端空间坐标（XYZ）展示与原始报文查看。
- **AI 自然语言指令解析**：支持输入中文口语化指令，解析为标准控制指令标识与 JSON 参数。
- **远程指令调度**：支持通过 Web 界面向现场设备下发启动、暂停、复位、急停等控制指令。
- **设备心跳检测**：后台定时扫描设备上报时间，超时未上报自动标记为离线状态。
- **设备智能诊断**：支持配置大模型 API（通义千问、DeepSeek、OpenAI、Ollama 等兼容接口），辅助分析设备运行状态。

---

## 🌐 界面访问路径

| 界面版本 | 访问路径 | 说明 |
| :--- | :--- | :--- |
| **极简浅色版** | `http://<服务器IP>:8000/light` 或 `/v2` | 浅色管理后台，支持卡片与列表切换 |
| **独立登录页** | `http://<服务器IP>:8000/login` | 矢量地图与系统登录/注册界面 |
| **暗黑工业版** | `http://<服务器IP>:8000/` 或 `/dark` | 经典深色界面 |
| **MQTT 中间件控制台** | `http://<服务器IP>:18083` | EMQX 节点与连接管理 |

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

## 🚀 本地运行与测试 (Windows / Linux)

### 1. 环境准备
需要安装 **Python 3.8+**。

```bash
git clone https://github.com/shuli6b/-Robot-IoT-Fleet-Management-System-.git
cd -Robot-IoT-Fleet-Management-System-

pip install -r requirements.txt
```

### 2. 本地启动
```bash
# 1. 启动微型 MQTT 服务
python run_broker.py

# 2. 新建终端启动 FastAPI 后端
python main.py

# 3. 新建终端启动模拟设备数据上报
python mock_robot.py --num-devices 10
```

### 3. 打开浏览器访问
- 浅色版本：`http://127.0.0.1:8000/light`
- 登录页面：`http://127.0.0.1:8000/login`
- 暗黑版本：`http://127.0.0.1:8000/`

---

## 🐧 服务器部署说明 (Ubuntu 22.04 LTS)

### 1. 基础环境
```bash
sudo apt update && sudo apt install -y python3 python3-pip python3-venv ufw
```

### 2. 安装 EMQX 中间件
```bash
wget https://www.emqx.com/en/downloads/broker/v5.8.0/emqx-5.8.0-ubuntu22.04-amd64.deb
sudo dpkg -i emqx-5.8.0-ubuntu22.04-amd64.deb
sudo systemctl enable emqx --now
```

### 3. 配置后台服务
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

sudo cp robot-iot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable robot-iot --now
```

### 4. 防火墙配置
```bash
sudo ufw allow 8000/tcp    # Web 与 API 端口
sudo ufw allow 1883/tcp    # MQTT 端口
sudo ufw allow 18083/tcp   # EMQX Dashboard 端口
sudo ufw reload
```

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
