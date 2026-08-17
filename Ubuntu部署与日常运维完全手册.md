# 📖 机器人物联网管理系统 — Ubuntu 部署与运维完全操作手册

> **适用系统**：Ubuntu 20.04 / 22.04 LTS (x86_64 / amd64)  
> **服务端口**：8000 (Web 大屏/API)、1883 (MQTT 报文)、18083 (EMQX 消息中台)  
> **发布日期**：2026-08-17

---

## 🧹 一、彻底清理与卸载旧环境命令

> **适用场景**：重新部署前、测试环境清理、彻底卸载旧版本。

```bash
# 1. 停止并禁用开机自启的 systemd 后台服务（若不存在则忽略报错）
sudo systemctl stop robot-iot.service 2>/dev/null || true
sudo systemctl disable robot-iot.service 2>/dev/null || true

# 2. 删除注册的系统服务文件并刷新 systemd 守护进程
sudo rm -f /etc/systemd/system/robot-iot.service
sudo systemctl daemon-reload

# 3. 强制终止所有可能残留的后台进程（主服务、Python 模拟器、Uvicorn 网关）
sudo pkill -9 -f "uvicorn" 2>/dev/null || true
sudo pkill -9 -f "main:app" 2>/dev/null || true
sudo pkill -9 -f "mock_robot" 2>/dev/null || true
sudo pkill -9 -f "huashu_adapter" 2>/dev/null || true

# 4. 删除旧版本的安装部署目录与旧日志文件
cd ~/Desktop || cd ~/桌面 || cd ~
rm -rf robot-iot-standalone
rm -f robot_iot.log

# 5. 检查关键端口是否已彻底释放（无输出即代表已完全释放）
sudo lsof -i :8000 || echo "✅ 8000 端口已完全释放，旧环境清理完毕！"
```

---

## 🚀 二、全新解压与一键离线部署命令

> **适用场景**：将新安装包 `robot-iot-standalone-ubuntu22.04.tar.gz` 上传后全新部署。

```bash
# 1. 进入存放安装包的目录（中文系统通常为 ~/桌面，英文系统为 ~/Desktop）
cd ~/Desktop 2>/dev/null || cd ~/桌面 2>/dev/null || cd ~

# 2. 解压全量离线部署包
tar -zxvf robot-iot-standalone-ubuntu22.04.tar.gz

# 3. 进入项目部署根目录
cd robot-iot-standalone

# 4. 赋予所有控制脚本可执行权限
chmod +x *.sh packages/bin/* 2>/dev/null || true

# 5. 执行一键离线自动化安装脚本（自动安装 EMQX + 离线 Python 依赖 + 注册开机自启）
sudo bash install.sh
```

> 💡 **带公网 IP 安装（可选）**：  
> 若现场已有固定公网 IP，可直接在安装时指定：  
> `sudo bash install.sh --public-ip http://118.24.15.88:8000`

---

## ⚙️ 三、日常服务管理与运维命令

> **注意**：在 `robot-iot-standalone` 目录下执行。

| 操作需求 | 推荐命令 | 命令解释 |
|---|---|---|
| **查看服务运行状态** | `sudo systemctl status robot-iot` | 查看服务是否为 `active (running)` 绿色正常运行 |
| **重启主服务** | `sudo systemctl restart robot-iot` | 修改代码或配置后重启后端与 Web 服务 |
| **停止主服务** | `sudo systemctl stop robot-iot` | 临时停止主服务 |
| **启动主服务** | `sudo systemctl start robot-iot` | 启动主服务 |
| **查看实时运行日志** | `sudo journalctl -u robot-iot -f` | 滚动查看系统实时日志（按 `Ctrl+C` 退出） |
| **启动机器人模拟器** | `./start.sh mock` | 启动 3 台模拟设备（华数机械臂、AMR、机器狗）上报数据 |
| **停止机器人模拟器** | `./stop.sh mock` | 停止模拟器后台进程 |
| **重启 EMQX 消息中台** | `sudo systemctl restart emqx` | 重启底层 MQTT Broker |

---

## 🦾 四、华数Ⅲ型工业机械臂真实接入

### 方式 1：直接在网页大屏配置（最推荐，免命令行）
1. 浏览器打开大屏：`http://服务器IP:8000/`
2. 点击顶部导航栏 👉 **`🦾 机械臂硬件接入`**
3. 填入华数控制器 IP（如 `10.10.56.214` 或 `192.168.1.100`），端口 `23234`
4. 点击 **`🧪 测试控制器连通性`** 进行毫秒级握手测通
5. 点击 **`💾 保存配置并开启实时采集`**，大屏立即展示真实机械臂数据！

### 方式 2：在工控机/终端启动独立桥接采集器
```bash
cd ~/Desktop/robot-iot-standalone/huashu_bridge
# 启动采集桥接器（自动读取 huashu_config.json 或指定 IP）
python3 huashu_adapter.py --robot-ip 10.10.56.214 --mqtt-host 127.0.0.1
```

---

## 🛡️ 五、网络与防火墙放行命令（如果外部打不开网页）

```bash
# Ubuntu 防火墙放行平台核心端口
sudo ufw allow 8000/tcp comment "Web Dashboard & REST API"
sudo ufw allow 1883/tcp comment "MQTT Broker"
sudo ufw allow 18083/tcp comment "EMQX Dashboard"
sudo ufw reload
```

---

## 🌐 六、验收访问地址速查

- **物联网大屏主页**：`http://<您的Ubuntu_IP>:8000/`
- **API 接口与健康检查**：`http://<您的Ubuntu_IP>:8000/docs`
- **EMQX 消息中台管理**：`http://<您的Ubuntu_IP>:18083/`（默认账号：`admin` / `public`）
