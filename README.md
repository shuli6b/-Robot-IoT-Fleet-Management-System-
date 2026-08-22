# 机器人物联网管控平台 (Robot IoT Fleet Management System)

> 📘 **重要技术文档导航**：
> - **[《交付与运维操作手册 (HANDOVER_GUIDE.md)》](./HANDOVER_GUIDE.md)**：包含公网访问入口、默认凭据、开机自启机制、双机热备与常用运维指令。
> - **[《现场接入新机器人实战指南 (ROBOT_INTEGRATION_GUIDE.md)》](./ROBOT_INTEGRATION_GUIDE.md)**：包含华数机械臂、复合 AMR、四足机器狗、无人机编队的详细接入教程、Python/ROS 代码模板与报文字典。

本项目是一套用于工业机器人设备集群监控、工况遥测分析与指令调度的管理系统。系统基于 **Python (FastAPI) + MQTT (EMQX / Mosquitto) + SQLite + Web 前端** 开发，支持机械臂、移动机器人 (AMR)、四足仿生机器狗等多品类设备的运行状态集中监控、3D 姿态展示、参数配置与故障诊断。

---

## 📌 主要功能

1. **多品类设备接入与状态监控**
   - 通过 MQTT 工业协议接入设备，支持机械臂、复合 AMR、四足机器狗及协同系统；
   - 实时采集各设备的运行状态（在线/离线/告警）、电池电量、伺服电机温度、负载电流与坐标数据；
   - 设备全离线时吞吐曲线归零，有设备上报时动态更新实时数据流量。

2. **3D 姿态与控制指令下发**
   - 3D 运动学视角查看六轴机械臂关节角度、末端空间坐标；
   - 支持管理员下发运行模式切换、启动/停止工步指令与安全急停。

3. **单台设备参数与厂商角标自由编辑**
   - 支持在详情弹窗中直接修改单台设备的名称、安装工位与厂商角标（如：宇树/昕邦定制、华数机器人等）；
   - 支持自由增加、修改、删除设备的自定义技术规格键值对（如额定负载、工作半径、重复定位精度、通讯协议等）。

4. **基地信息与品类 CMS 动态配置**
   - 系统管理员可在后台设置平台名称、所属单位、页脚版权文字；
   - 支持自定义不同运营基地（如番禺示范线、南沙研发中心）的标题、介绍及实景图片；
   - 支持修改四大机器人品类的默认名称、厂商与健康指标说明。

5. **AI 工业大模型诊断助手**
   - 支持接入通义千问、DeepSeek、OpenAI、Gemini 等大语言模型接口；
   - 结合设备实时上报的异常温度、电流过载或通信超时数据，生成故障排查建议。

6. **用户权限与操作审计日志**
   - 提供管理员 (Admin) 与普通操作员 (User) 角色权限隔离；
   - 关键操作（如指令下发、设备参数修改、CMS 设置变更）自动记录审计日志。

---

## 🛠️ 技术栈

| 层次 | 技术选型 | 说明 |
| :--- | :--- | :--- |
| **后端框架** | Python 3.10+ / FastAPI / Uvicorn | 异步高性能 REST API 服务 |
| **消息通信** | MQTT (Paho-MQTT / EMQX 或 Mosquitto) | 工业物联网设备消息订阅与分发 |
| **数据存储** | SQLite 3 (WAL 模式) | 单文件轻量持久化，无需额外安装大型数据库 |
| **前端界面** | HTML5 / Tailwind CSS / ECharts / 原生 JavaScript | 轻量单页架构，免编译，开箱即用 |
| **部署环境** | Linux (Ubuntu 20.04/22.04 LTS 等) 或 Windows | 支持 Systemd 服务守护与开机自启 |

---

## 📂 项目目录结构

```text
├── database.py             # SQLite 数据库操作层（表结构初始化、WAL模式、增删改查）
├── main.py                 # FastAPI 后端核心（MQTT订阅、REST API、AI接口与静态文件服务）
├── mock_robot.py           # 机器人遥测数据模拟器（华数臂、AMR、机器狗等数据发生器）
├── requirements.txt        # Python 依赖清单
├── start.sh / stop.sh      # Linux 环境一键启动与停止脚本
├── robot-iot.service       # Linux systemd 系统服务单元文件
├── static/                 # 前端静态资源目录
│   ├── index.html          # 管控平台主界面 (大屏看板/设备列表/3D详情/CMS后台)
│   ├── login.html          # 用户登录页
│   └── assets/             # 设备渲染图、基地实况图与静态图标
└── README.md               # 项目使用与部署说明
```

---

## 🚀 详细部署教程

本教程以 **Ubuntu 22.04 LTS** 系统为例，Windows 环境同样支持（步骤 1~3 相同）。

### 1. 系统基础环境准备

更新系统软件包并安装 Python 3 与虚拟环境工具：

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv git curl
```

### 2. 获取代码与创建虚拟环境

```bash
# 进入部署目录（可根据实际情况调整路径）
mkdir -p /home/ubuntu/robot-iot
cd /home/ubuntu/robot-iot

# 克隆仓库（或将源码复制到此目录）
git clone <仓库地址> .

# 创建 Python 虚拟环境并激活
python3 -m venv venv
source venv/bin/activate

# 安装项目依赖
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. 安装并配置 MQTT Broker

系统需要一个 MQTT 消息中间件来传输设备遥测数据。推荐使用 **Mosquitto** 或 **EMQX**。

#### 方式 A：使用 Mosquitto（轻量推荐）
```bash
sudo apt install -y mosquitto mosquitto-clients
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

#### 方式 B：使用 EMQX（具备可视化控制台）
```bash
curl -s https://assets.emqx.com/scripts/install-emqx-deb.sh | sudo bash
sudo apt install -y emqx
sudo systemctl enable emqx
sudo systemctl start emqx
# EMQX Web 仪表盘访问端口为 18083（默认账号: admin / public）
```

---

### 4. 初始化数据库与手动测试运行

```bash
# 激活虚拟环境
source venv/bin/activate

# 启动主程序
python main.py
```

终端输出类似以下信息即代表启动成功：
```text
INFO:     Started server process [PID]
INFO:     Waiting for application startup.
INFO:     MQTT client connected to localhost:1883
INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
```

此时打开浏览器访问 `http://<服务器IP>:8000` 即可看到登录页面。
- **默认管理员账号**：`admin` / `admin123`
- **默认操作员账号**：`user` / `123456`

---

### 5. 配置为 Linux Systemd 守护服务（生产环境推荐）

为保证服务器重启后系统自动拉起并保持 24 小时稳定运行，建议配置 Systemd 服务。

#### (1) 创建主服务配置 `/etc/systemd/system/robot-iot.service`

```bash
sudo nano /etc/systemd/system/robot-iot.service
```

写入以下内容（注意将其中的路径 `/home/ubuntu/robot-iot` 和用户 `ubuntu` 替换为您服务器的实际路径与用户名）：

```ini
[Unit]
Description=Robot IoT Fleet Management Cloud Platform (FastAPI + MQTT)
After=network.target mosquitto.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/robot-iot
ExecStart=/home/ubuntu/robot-iot/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5s
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

#### (2) 启用并启动服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable robot-iot
sudo systemctl start robot-iot

# 查看服务运行状态
sudo systemctl status robot-iot
```

---

### 6. 启动设备模拟器（用于测试与演示）

如果现场暂无实体机器人连接，可使用自带的模拟器脚本生成遥测报文：

#### 手动运行模拟器
```bash
source venv/bin/activate
python mock_robot.py --interval 2.0
```

#### 或将模拟器也加入 Systemd 守护（可选）
创建 `/etc/systemd/system/robot-mock.service`：

```ini
[Unit]
Description=Mock Robot IoT Telemetry Simulator
After=network.target robot-iot.service

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/robot-iot
ExecStart=/home/ubuntu/robot-iot/venv/bin/python mock_robot.py --interval 2.0
Restart=always
RestartSec=3s

[Install]
WantedBy=multi-user.target
```

启动模拟服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now robot-mock
```

---

### 7. 防火墙与网络端口设置

如服务器开启了安全组或系统防火墙（UFW），请确保放行以下通信端口：

| 端口号 | 协议 | 用途说明 |
| :--- | :--- | :--- |
| **8000** | TCP | Web 管理大屏与 RESTful API |
| **1883** | TCP | MQTT 设备数据上报与指令下发通道 |
| **18083** | TCP | EMQX 管理后台（如选用 EMQX） |

```bash
# Ubuntu UFW 开放端口示例
sudo ufw allow 8000/tcp
sudo ufw allow 1883/tcp
sudo ufw reload
```

---

## 📡 硬件设备接入规范 (MQTT Topics)

现场实体硬件或边缘采集网关遵循以下 Topic 格式推送数据：

### 1. 设备遥测上报 (Telemetry)
- **Topic**: `robot/{device_type}/{device_id}/telemetry`
- **示例**: `robot/huashu_arm/arm_001/telemetry`
- **Payload (JSON)**:
```json
{
  "joints": [0.0, -25.3, 45.1, 0.0, 30.5, 0.0],
  "currents": [1.2, 2.1, 1.8, 0.8, 0.5, 0.4],
  "temperature": 38.5,
  "battery": 95,
  "speed": 0.35,
  "timestamp": "2026-08-21T09:00:00"
}
```

### 2. 设备状态上报 (Status)
- **Topic**: `robot/{device_type}/{device_id}/status`
- **Payload (JSON)**:
```json
{
  "status": "online",
  "mode": "auto",
  "alarms": [],
  "timestamp": "2026-08-21T09:00:00"
}
```

### 3. 控制指令下发 (Commands)
- **Topic**: `robot/{device_type}/{device_id}/cmd`
- **Payload (JSON)**:
```json
{
  "command": "start_step",
  "params": { "step_id": 2 },
  "operator": "admin",
  "timestamp": "2026-08-21T09:00:00"
}
```

---

## ❓ 常见问题排查 (FAQ)

1. **Web 页面打开显示空白或无法访问？**
   - 检查 8000 端口服务是否正常运行：`sudo systemctl status robot-iot`；
   - 检查云服务器控制台安全组是否放行了 8000 端口。

2. **设备状态显示全部离线？**
   - 确认 MQTT Broker 是否在正常运行：`sudo systemctl status mosquitto`（或 `emqx`）；
   - 确认是否有数据上报到 `robot/#` 主题，可用命令监听测试：`mosquitto_sub -t "robot/#" -v`；
   - 如使用模拟器，请检查 `sudo systemctl status robot-mock`。

3. **修改的设备规格或 CMS 基地图文保存在哪里？**
   - 保存在项目根目录下的 SQLite 数据库文件（`robot.db`）中；
   - 系统支持热修改，保存后前端自动刷新生效，无需重启后端服务。

---

## 📄 开源声明
本项目代码基于通用规范编写，适用于学习、二次开发与工业现场数字化集成。
