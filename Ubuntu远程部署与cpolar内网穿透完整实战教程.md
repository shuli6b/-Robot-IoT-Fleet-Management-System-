# 机器人物联网管理平台 — Ubuntu 远程部署与 cpolar 内网穿透实战教程

> **版本**：v2.0 (2026-08-18 生产实战版)  
> **适用环境**：Ubuntu 22.04 LTS / 20.04 LTS / 任何无固定公网 IP 的局域网服务器  
> **目标**：通过 cpolar 内网穿透，将局域网内的后台管理大屏与 MQTT 工业物联网中心安全映射至公网，实现全国异地跨公网真机接入与远程运维。

---

## 架构图解与端口规划

在物联网架构中，**仅中心服务器（Ubuntu）需要公网暴露**，所有分布在全国各地的 4G 机器狗、机械臂和远程查看大屏的手机/电脑均为客户端，主动连接服务端。

```
┌─────────────────────────────────────────────────────────────┐
│                    Ubuntu 云端/局域网服务器                   │
│                                                             │
│  ┌─────────────────┐   ┌────────────────┐   ┌────────────┐  │
│  │   cpolar 穿透   │   │  FastAPI 后端  │   │ Mosquitto  │  │
│  │  (端口反向代理)  │   │  (Web/API大屏) │   │ MQTTBroker │  │
│  └────────┬────────┘   └────────┬───────┘   └─────┬──────┘  │
│           │                     │                 │         │
│           │ 映射 22 (SSH)       │ 监听 8000       │ 监听 1883│
│           │ 映射 8000 (HTTP)    │                 │         │
│           │ 映射 1883 (TCP)     │                 │         │
└───────────┼─────────────────────┼─────────────────┼─────────┘
            ▲                     ▲                 ▲
            │                     │                 │
    (cpolar 动态公网域名)   (HTTP 网页大屏访问)  (MQTT 遥测上报)
            │                     │                 │
┌───────────┴─────────┐   ┌───────┴────────┐   ┌────┴────────┐
│  AI Copilot 远程运维 │   │ 管理员手机/电脑 │   │ 工厂 4G 真机 │
│   (SSH 远程接管部署) │   │  (随时随地看板) │   │ (机械臂/狗)  │
└─────────────────────┘   └────────────────┘   └─────────────┘
```

### 核心端口映射清单

| 服务名称 | 本地端口 (Local) | cpolar 协议类型 | 隧道名称 | 作用与用途 |
|---|---|---|---|---|
| **SSH 远程登录** | `22` | `TCP` | `ssh` | 供开发人员与 AI 自动化运维远程接入操作 Linux 系统 |
| **Web 管理大屏** | `8000` | `HTTP` | `iot-web` | 供手机浏览器、PC 端随时查看大屏与大模型诊断 |
| **MQTT 工业物联网** | `1883` | `TCP` | `iot-mqtt` | 供全国各地 4G 机器狗、华数机械臂和模拟程序上报遥测 |

---

## 第一阶段：Ubuntu 系统环境准备

在远程桌面上打开终端（Terminal），执行以下基础依赖与 SSH 服务安装：

```bash
# 1. 更新系统软件源
sudo apt update -y

# 2. 安装基础工具与 openssh-server（确保允许远程 SSH 登录）
sudo apt install -y curl git unzip python3-venv python3-pip mosquitto openssh-server

# 3. 启动并开机自启 Mosquitto MQTT 服务
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

---

## 第二阶段：安装并配置 cpolar 内网穿透

### 2.1 一键安装 cpolar

```bash
curl -L https://www.cpolar.com/static/downloads/install-release-cpolar.sh | sudo bash
```

### 2.2 绑定 cpolar 账号

1. 打开 [cpolar 官网 (cpolar.com)](https://www.cpolar.com/) 注册并登录。
2. 在后台左侧“验证”中复制你的专属 `Authtoken`。
3. 在 Ubuntu 终端中执行绑定：
   ```bash
   cpolar authtoken 你的专属Token字符串
   ```

### 2.3 启动 cpolar 后台守护进程

```bash
sudo systemctl enable cpolar
sudo systemctl start cpolar
```

### 2.4 可视化创建 3 大核心隧道

在 Ubuntu 系统的浏览器中打开本地管理面板：`http://localhost:9200`，登录后进入 **“隧道管理” -> “创建隧道”**：

1. **创建 SSH 远程隧道**：
   - 隧道名称：`ssh`
   - 协议：`TCP`
   - 本地地址：`22`
   - 地区：`China Top` 或默认
   - 点击“创建”
2. **创建 Web 管理大屏隧道**：
   - 隧道名称：`iot-web`
   - 协议：`HTTP`
   - 本地地址：`8000`
   - 点击“创建”
3. **创建 MQTT 工业数据隧道**：
   - 隧道名称：`iot-mqtt`
   - 协议：`TCP`
   - 本地地址：`1883`
   - 点击“创建”

### 2.5 查看并获取公网连接地址

点击左侧 **“状态” -> “在线隧道列表”**，记录下生成的三个公网地址：
- `iot-web` 对应的 `http://xxxx.r20.cpolar.top` -> 直接发送给所有人作为**网页大屏访问入口**。
- `iot-mqtt` 对应的 `tcp://20.tcp.cpolar.top:13536` -> 提取出域名和**五位数端口号**，填入机器人和模拟器配置。
- `ssh` 对应的 `tcp://20.tcp.cpolar.top:12352` -> 供远程命令行连接维护。

---

## 第三阶段：部署后台程序与开机自启守护服务

### 3.1 放置代码并构建独立 Python 虚拟环境

将项目包解压至当前用户主目录（以用户 `qtz` 为例）：

```bash
cd /home/qtz/桌面/robot-iot-standalone/app/

# 创建 Python 虚拟隔离环境
python3 -m venv venv

# 使用清华源高速安装依赖
./venv/bin/pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
```

### 3.2 配置 systemd 系统自启守护进程

创建或配置 `/etc/systemd/system/robot-iot.service`：

```ini
[Unit]
Description=Robot IoT Fleet Management Cloud Platform (FastAPI + MQTT)
After=network.target mosquitto.service

[Service]
Type=simple
User=qtz
WorkingDirectory=/home/qtz/桌面/robot-iot-standalone/app
ExecStart=/home/qtz/桌面/robot-iot-standalone/app/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 1
Restart=always
RestartSec=3
StandardOutput=append:/home/qtz/桌面/robot-iot-standalone/app/robot_iot.log
StandardError=append:/home/qtz/桌面/robot-iot-standalone/app/robot_iot.log

[Install]
WantedBy=multi-user.target
```

### 3.3 激活并启动后台服务

```bash
sudo systemctl daemon-reload
sudo systemctl enable robot-iot
sudo systemctl restart robot-iot

# 查看运行状态
sudo systemctl status robot-iot
```

---

## 第四阶段：机器人接入与远程大屏使用

### 4.1 网页后台设备管理功能升级

在最新版管理看板中，新增了**设备全生命周期管理与快捷删除**功能：
1. **列表侧删除**：在左侧设备列表中，每台机器人右侧均有 `🗑️` 红色删除图标，点击可二次确认并彻底抹除该机器人的档案与历史脏数据。
2. **详情页删除**：在右侧遥测卡片右上角新增 `[删除设备]` 按钮，支持在查看设备状态后一键下线清除。
3. **掉电感知**：当机器人断开连接超过 10~15 秒，系统自动将其标识为灰色 `离线` 报警状态；重新上电后 1 秒内自动变绿重连。

### 4.2 客户端/模拟器跨公网连接配置

任何客户端程序（包括 Python 模拟脚本、华数机械臂中转桥接服务、4G 机器狗程序），只需配置公网 Broker 地址：

```python
# 示例：Python 客户端配置
MQTT_BROKER_HOST = "20.tcp.cpolar.top"  # 填入 cpolar iot-mqtt 隧道分配的公网 Host
MQTT_BROKER_PORT = 13536                 # 填入 cpolar 分配的 5 位数 TCP 端口
```

运行模拟器即可将数据跨省打入云端后台：
```bash
python mock_robot.py --host 20.tcp.cpolar.top --port 13536
```

---

## 第五阶段：高频踩坑与避错指南（⚠️ 必读）

### 1. cpolar.yml 格式解析报错 (`did not find expected key`)
- **原因**：通过命令行 `echo` 写入配置时换行符或空格缩进不对，破坏了 YAML 结构。
- **解决办法**：尽量在 `http://localhost:9200` 网页控制台添加隧道；若需命令行修改，请使用 `cat -n /usr/local/etc/cpolar/cpolar.yml` 检查缩进（必须为 2 空格/4 空格对齐）。

### 2. 数据库无法写入或删除失败 (`Permission Denied` / `Database is locked`)
- **原因**：如果之前用 `sudo` 启动过 Python，生成的 `robot.db` 文件的所有者会变成 `root`，导致普通用户无法写入。
- **解决办法**：一键重置项目目录权限归属为当前用户：
  ```bash
  sudo chown -R $USER:$USER /home/qtz/桌面/robot-iot-standalone/
  ```

### 3. cpolar 免费隧道端口变动
- **注意**：cpolar 免费版的 TCP 隧道在服务重启后可能会重新分配五位数端口号。每次重启 cpolar 后，请到 `http://localhost:9200` 的“在线隧道列表”中核对一下最新的 MQTT 端口号。
- **生产建议**：后续若正式交付，可在 cpolar 官网开通基础专业版（保留固定 TCP 端口与自定义二级域名），端口永不变动。
