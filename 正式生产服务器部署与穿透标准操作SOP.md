# 昕邦智能装备 · 机器人物联网管控平台
## 正式生产服务器全自动部署与内网穿透标准操作规程 (SOP)

---

### 一、 整体系统架构与网络拓扑

本系统采用 **「边缘物理生产服务器（业务底座） + 腾讯云 VPS（公网中继穿透）」** 的高可用混合拓扑架构。

```
┌──────────────────────────────────────────────────────────┐
│  客户端 / 移动端浏览器 / 远程用户                         │
└──────────────┬────────────────────────────┬──────────────┘
               │ 访问 :8000 / :18083 / :1883 │
               ▼                            ▼
┌──────────────────────────────────────────────────────────┐
│  【公网穿透中继中枢】腾讯云 VPS (106.55.248.254)           │
│  - 纯粹运行 FRPS 服务 (端口: 7000, 密钥鉴权)               │
│  - 开放端口通道:                                          │
│    * 8000  -> 映射至物理服务器的管控大屏 Web 与 REST API   │
│    * 18083 -> 映射至物理服务器的 EMQX 物联网控制台         │
│    * 1883  -> 映射至物理服务器的 MQTT 工业消息通道         │
│    * 2222  -> 映射至物理服务器的 22 (SSH 远程自动化运维)  │
└──────────────────────────┬───────────────────────────────┘
                           │ 安全 FRP 加密隧道 (Token 鉴权)
                           ▼
┌──────────────────────────────────────────────────────────┐
│  【实际业务生产服务器】目标 Ubuntu 22.04 LTS (实体机)       │
│  ├── 1. FastAPI 机器人物联网管控平台 (Port: 8000)         │
│  ├── 2. EMQX 5.8 工业物联网 Broker & Dashboard (1883/18083)│
│  ├── 3. SQLite 持久化历史数据库 & 工业资产底账            │
│  └── 4. FRPC 穿透客户端守护进程 (frpc.service)            │
└──────────────────────────────────────────────────────────┘
```

---

### 二、 下次部署全新服务器的“一键接入”极简流程

当客户或现场准备好一台全新的 Ubuntu 物理服务器时，只需两步即可完成全自动化部署：

#### 【第一步：用户在目标服务器上执行一键穿透连接命令】
用户只需在目标 Ubuntu 服务器的终端中，复制粘贴并执行下面这行指令（无需配置任何公网 IP）：

```bash
curl -fsSL http://106.55.248.254:8000/static/connect_frp.sh | sudo bash || (sudo mkdir -p /usr/local/frp && sudo curl -o /usr/local/frp/frpc https://github.com/fatedier/frp/releases/download/v0.58.1/frp_0.58.1_linux_amd64.tar.gz)
```
*(或者直接执行以下通用 3 行命令建立反向运维隧道)*：
```bash
sudo apt update && sudo apt install -y wget curl
wget -qO- https://raw.githubusercontent.com/shuli6b/-Robot-IoT-Fleet-Management-System-/main/deploy_new_server.sh | sudo bash
```

#### 【第二步：AI 助手通过反向隧道登入并自动化部署】
目标服务器建立连接后，AI 助手将通过腾讯云 VPS 的 `2222` 端口直接连接到该服务器：
```bash
ssh -p 2222 root@106.55.248.254
# 或使用现场用户
ssh -p 2222 qtz@106.55.248.254
```
连接成功后，AI 助手将自动执行：
1. 拉取 GitHub 最新版本代码（包含 CMS 动态修改、超管权限隔离、暗黑/浅白双主题、三端机器人孪生）；
2. 自动化配置 Python3.10 虚拟环境与依赖；
3. 一键安装并启动工业级 EMQX 5.8.0 消息中间件；
4. 注册 `robot-iot.service` 和 `frpc.service` 随开机自启；
5. 全量自检端口通信与 Web 访问。

---

### 三、 生产环境标准配置一览表

#### 1. 腾讯云 VPS (穿透中枢 `106.55.248.254`)
- **配置文件路径**：`/usr/local/frp/frps.toml`
- **内容规范**：
  ```toml
  bindPort = 7000
  auth.token = "RobotIoT_Secure_Token_2026"

  webServer.addr = "0.0.0.0"
  webServer.port = 7500
  webServer.user = "admin"
  webServer.password = "Admin_Robot_2026"
  ```
- **服务管理**：`sudo systemctl restart frps`

#### 2. 目标实体 Ubuntu 服务器 (业务核心)
- **代码部署路径**：`/opt/robot-iot`
- **FRP 客户端配置**：`/usr/local/frp/frpc.toml`
- **内容规范**：
  ```toml
  serverAddr = "106.55.248.254"
  serverPort = 7000
  auth.token = "RobotIoT_Secure_Token_2026"

  [[proxies]]
  name = "iot-web"
  type = "tcp"
  localIP = "127.0.0.1"
  localPort = 8000
  remotePort = 8000

  [[proxies]]
  name = "iot-mqtt"
  type = "tcp"
  localIP = "127.0.0.1"
  localPort = 1883
  remotePort = 1883

  [[proxies]]
  name = "emqx-dashboard"
  type = "tcp"
  localIP = "127.0.0.1"
  localPort = 18083
  remotePort = 18083

  [[proxies]]
  name = "local-ssh"
  type = "tcp"
  localIP = "127.0.0.1"
  localPort = 22
  remotePort = 2222
  ```

---

### 四、 核心服务管理与常用运维命令

在实体 Ubuntu 服务器上：

| 操作项 | 对应执行命令 |
| :--- | :--- |
| **重启主管控平台** | `sudo systemctl restart robot-iot` |
| **查看主服务实时日志** | `sudo journalctl -u robot-iot -f` |
| **重启 EMQX 物联网 Broker** | `sudo systemctl restart emqx` |
| **查看 EMQX 运行状态** | `sudo systemctl status emqx` |
| **重启穿透客户端** | `sudo systemctl restart frpc` |
| **查看穿透链路连接状态** | `sudo journalctl -u frpc -n 20 --no-pager` |
| **数据备份** | `cp /opt/robot-iot/robot.db /opt/robot-iot/robot_backup_$(date +%F).db` |

---

### 五、 全局访问入口与账号凭据

- **公网管控大屏**：`http://106.55.248.254:8000/`
- **系统登录页面**：`http://106.55.248.254:8000/login`
- **超级管理员账号**：`admin` / `admin123` *(唯一拥有重置其他账号密码及全站 CMS 动态修改权限)*
- **普通操作员账号**：`operator` / `operator123`
- **EMQX 物联网控制台**：`http://106.55.248.254:18083/` *(账号: `admin` / 密码: `public`)*
- **FRP 穿透控制台**：`http://106.55.248.254:7500/` *(账号: `admin` / 密码: `Admin_Robot_2026`)*
