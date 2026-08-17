# 机器人物联网管理系统 — Ubuntu 22.04 LTS 系统完整部署说明书

> **合同编号**：IOT-20260811  
> **项目名称**：机器人物联网管理软件开发项目  
> **适用环境**：Ubuntu 22.04 LTS（x86_64 / aarch64）  
> **文档版本**：v1.0（2026-08-15）

---

## 目录
1. [服务器基础环境准备](#1-服务器基础环境准备)
2. [EMQX 消息中间件部署与安全加固](#2-emqx-消息中间件部署与安全加固)
3. [系统源码部署与环境配置](#3-系统源码部署与环境配置)
4. [防火墙与网络端口放行](#4-防火墙与网络端口放行)
5. [Systemd 开机自启与守护进程配置](#5-systemd-开机自启与守护进程配置)
6. [公网远程与局域网双场景适配](#6-公网远程与局域网双场景适配)
7. [系统运维、监控与数据备份](#7-系统运维监控与数据备份)

---

## 1. 服务器基础环境准备

### 1.1 系统更新与基础工具安装
登录 Ubuntu 22.04 LTS 服务器终端，执行系统软件包更新：

```bash
# 更新 APT 软件源索引与系统包
sudo apt update && sudo apt upgrade -y

# 安装常用网络与编译工具
sudo apt install -y curl wget git vim net-tools ufw build-essential
```

### 1.2 Python 3.10+ 环境确认与虚拟环境模块安装
Ubuntu 22.04 默认已自带 Python 3.10。执行以下命令安装 `pip` 与 `venv` 模块：

```bash
# 安装 Python3 pip 与虚拟环境支持
sudo apt install -y python3-pip python3-venv

# 验证 Python 版本（要求 >= 3.10）
python3 --version
# 输出示例：Python 3.10.12
```

---

## 2. EMQX 消息中间件部署与安全加固

本项目采用高吞吐、企业级 MQTT 消息中间件 **EMQX 5.x**。

### 2.1 安装 EMQX 5.x
通过 EMQX 官方 APT 源进行快速安装：

```bash
# 1. 下载并安装 EMQX GPG 公钥
curl -fsSL https://assets.emqx.com/scripts/install-emqx-deb.sh | sudo bash

# 2. 安装 EMQX 最新稳定版
sudo apt install -y emqx

# 3. 启动 EMQX 服务并设置开机自启
sudo systemctl start emqx
sudo systemctl enable emqx

# 4. 验证运行状态
sudo systemctl status emqx
```

### 2.2 EMQX 安全加固（严格满足合同安全验收标准）

#### 步骤 1：访问 EMQX Web Dashboard 重置管理员默认密码
- 打开浏览器访问：`http://<服务器IP>:18083`
- 默认初始账号：`admin`
- 默认初始密码：`public`
- **首次登录时系统会强制要求修改为强密码**（例如：`Admin_IoT_2026#Secure`）。

#### 步骤 2：关闭匿名连接（杜绝非法设备接入）
在 EMQX 5.x Dashboard 中配置：
1. 进入左侧导航菜单 **【访问控制】(Access Control)** -> **【客户端认证】(Authentication)**。
2. 点击 **【创建】(Create)**，选择 **【Password-Based】** -> **【Built-in Database】(内置数据库)**。
3. 密码哈希方式选择 **SHA256**，确认保存。
4. 此时 EMQX 会自动将 `allow_anonymous` 设置为 `false`，任何未授权的客户端均会被拒绝连接。

#### 步骤 3：创建服务端与设备鉴权账号
在 **【客户端认证】** -> **【用户管理】** 中添加以下专用账号：

| 账号用途 | 用户名 (Username) | 密码 (Password) | 对应配置文件 |
|---|---|---|---|
| **后端服务监听** | `robot_server` | `robot_server_pass` | `main.py` / `robot-iot.service` |
| **华数机械臂** | `device_huashu_arm` | `Arm_Secure_2026!` | 现场机械臂 MQTT 客户端 |
| **珞石 AMR** | `device_luxshare_amr`| `Amr_Secure_2026!` | 现场 AMR 车载通信工控机 |
| **四足机器狗** | `device_robot_dog` | `Dog_Secure_2026!` | 现场机器狗车载工控板 |

#### 步骤 4：配置主题发布权限 (ACL)
1. 进入 **【访问控制】** -> **【客户端授权】(Authorization)** -> **【内置数据库】**。
2. 配置设备权限规则：
   - 允许 `robot_server` 订阅 `robot/#`。
   - 允许设备账号 `device_huashu_arm` 仅向 `robot/huashu_arm/#` 发布数据。
   - 允许设备账号 `device_luxshare_amr` 仅向 `robot/luxshare_amr/#` 发布数据。
   - 允许设备账号 `device_robot_dog` 仅向 `robot/robot_dog/#` 发布数据。

---

## 3. 系统源码部署与环境配置

### 3.1 部署目录规划
推荐将程序部署至 `/opt/robot-iot`：

```bash
# 1. 创建部署目录
sudo mkdir -p /opt/robot-iot
sudo chown -R $USER:$USER /opt/robot-iot

# 2. 将项目全部源码文件上传/复制至 /opt/robot-iot/
# 包含：main.py, database.py, requirements.txt, static/, start.sh, mock_robot.py, robot-iot.service 等
cd /opt/robot-iot
```

### 3.2 初始化 Python 虚拟环境与依赖
```bash
# 创建虚拟环境
python3 -m venv venv

# 激活虚拟环境
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 赋予启动脚本执行权限
chmod +x start.sh
```

---

## 4. 防火墙与网络端口放行

使用 Ubuntu 自带的 `ufw` 防火墙工具进行必要业务端口放行，阻断多余未知端口：

| 端口号 | 协议 | 服务名称 | 放行说明 |
|---|---|---|---|
| **8000** | TCP | FastAPI Web 服务 | 供浏览器访问 Web 页面与 REST API |
| **1883** | TCP | EMQX MQTT 协议端口 | 供各类机器人长连接上报数据 |
| **18083** | TCP | EMQX Dashboard 后台 | 供管理员配置与监控 MQTT（可选按需放行） |
| **22** | TCP | SSH 远程登录 | 保持服务器运维连接 |

执行放行命令：

```bash
# 启用 UFW 前必须先放行 SSH 端口，防止失联
sudo ufw allow 22/tcp

# 放行业务必要端口
sudo ufw allow 8000/tcp comment 'Robot IoT Web Dashboard & API'
sudo ufw allow 1883/tcp comment 'EMQX MQTT Protocol Port'
sudo ufw allow 18083/tcp comment 'EMQX Management Dashboard'

# 启用防火墙
sudo ufw enable

# 查看当前放行状态
sudo ufw status verbose
```

---

## 5. Systemd 开机自启与守护进程配置

为了保障系统 **7×24 小时无人值守稳定运行**并在服务器重启或进程异常时自动恢复，必须配置 systemd 服务。

### 5.1 安装服务文件
```bash
# 复制项目自带的 service 文件至系统目录
sudo cp /opt/robot-iot/robot-iot.service /etc/systemd/system/

# 重新加载 systemd 守护进程
sudo systemctl daemon-reload
```

### 5.2 启动服务并设置开机自启
```bash
# 设置开机自动启动
sudo systemctl enable robot-iot.service

# 立即启动服务
sudo systemctl start robot-iot.service

# 查看服务运行状态
sudo systemctl status robot-iot.service
```

### 5.3 常用运维管理命令
```bash
# 查看实时运行日志
sudo journalctl -u robot-iot.service -f

# 查看后端日志文件
tail -f /opt/robot-iot/robot_iot.log

# 重启后台服务
sudo systemctl restart robot-iot.service

# 停止服务
sudo systemctl stop robot-iot.service
```

---

## 6. 公网远程与局域网双场景适配

### 6.1 场景 A：工厂本地局域网部署 (LAN)
- 后台服务器、EMQX 与所有机器人处于同一局域网（同一交换机或 Wi-Fi AP 网段，如 `192.168.1.x`）。
- **机器人端配置**：直接将 MQTT Broker IP 指向服务器内网 IP（如 `192.168.1.100`，端口 `1883`）。
- **浏览器访问**：局域网内任意 PC 打开 `http://192.168.1.100:8000` 即可查看。

### 6.2 场景 B：云端 / 外网远程跨地域部署 (WAN)
若服务器部署在阿里云、腾讯云、华为云或具有公网静态 IP 的工控网关：
1. **云服务器安全组配置**：在云厂商控制台放行 TCP `8000` 与 `1883` 端口入方向规则。
2. **机器人端配置**：配置 MQTT Broker 地址为服务器公网 IP 或解析域名（如 `iot.company.com:1883`）。
3. **Nginx 反向代理配置（可选启用 HTTPS）**：
   ```nginx
   server {
       listen 80;
       server_name iot.company.com;

       location / {
           proxy_pass http://127.0.0.1:8000;
           proxy_set_header Host $host;
           proxy_set_header X-Real-IP $remote_addr;
           proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
       }
   }
   ```

---

## 7. 系统运维、监控与数据备份

### 7.1 系统健康检查 (Health Check)
监控系统或巡检脚本可定期探测以下接口：
```bash
curl -s http://127.0.0.1:8000/api/health
```
正常响应示例：
```json
{
  "code": 200,
  "message": "healthy",
  "data": {
    "status": "ok",
    "database": "connected",
    "mqtt": "connected",
    "uptime_seconds": 86400,
    "version": "1.0.0"
  }
}
```

### 7.2 SQLite 数据库安全备份与恢复
由于 SQLite 开启了 **WAL (Write-Ahead Logging)** 模式，备份时建议使用 SQLite 在线备份命令或在低峰期复制：

```bash
# 在线安全备份命令（无需停机）
sqlite3 /opt/robot-iot/robot.db ".backup '/opt/robot-iot/robot_backup_$(date +%Y%m%d_%H%M%S).db'"

# 设置每日凌晨 2:00 自动备份 Cron 定时任务
(crontab -l 2>/dev/null; echo "0 2 * * * sqlite3 /opt/robot-iot/robot.db \".backup '/opt/robot-iot/robot_backup_\$(date +\%Y\%m\%d).db'\"") | crontab -
```

---
**部署技术支持**：广州擎天智技术有限责任公司 运维团队
