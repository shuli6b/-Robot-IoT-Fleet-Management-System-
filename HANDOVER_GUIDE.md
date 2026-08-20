# 昕邦智能装备 · 机器人物联网管控平台
# 项目交接、架构全景与自动化远程运维部署指南 (HANDOVER GUIDE)

---

## 📌 一、 项目全景概况与版本信息

本系统为**昕邦智能装备**定制开发的**工业级异构多品类机器人物联网管控平台（Robot IoT Fleet Management Cloud Platform）**。平台融合了物联网实时遥测、3D 数字孪生姿态展示、ECharts 动态地理态势、动态 CMS 品牌管理以及 LLM 工业大模型辅助诊断等多项核心能力。

- **GitHub 官方版本库**：`https://github.com/shuli6b/-Robot-IoT-Fleet-Management-System-.git`
- **默认开发与发布主分支**：`main`
- **线上生产大屏访问地址**：[http://106.55.248.254:8000](http://106.55.248.254:8000)
- **本地开发访问地址**：[http://127.0.0.1:8000](http://127.0.0.1:8000)
- **默认超级管理员账号**：`admin` / `admin123`
- **系统底层技术栈**：
  - **后端**：Python 3.10+ / FastAPI / Uvicorn / Paho-MQTT / aiohttp / httpx
  - **数据库**：SQLite3（开启 `PRAGMA journal_mode=WAL` 高并发写入与自动模式迁移）
  - **消息总线**：EMQX 5.8 工业物联网 Broker（标准端口：`1883`，控制台：`18083`）
  - **前端**：无打包纯原生单页架构（HTML5 + TailwindCSS CDN + ECharts 5 + Lucide Icons + Three.js 数字孪生）
  - **主题规范**：默认全站暗色科技主题（Dark Mode Default）

---

## 🌐 二、 腾讯云内网穿透中继 + 实体机自动化部署核心 SOP（必读）

本项目采用了 **「边缘物理生产服务器（真实业务机） + 腾讯云 VPS（公网中继中枢）」** 的安全混合拓扑架构。

```
┌──────────────────────────────────────────────────────────┐
│  客户端 / 移动端浏览器 / 甲方用户 / 运维开发人员            │
└──────────────┬────────────────────────────┬──────────────┘
               │ 访问 :8000 / :18083 / :1883 │
               ▼                            ▼
┌──────────────────────────────────────────────────────────┐
│  【公网穿透中继中枢】腾讯云 VPS (106.55.248.254)           │
│  - FRPS 穿透中枢 (端口: 7000, 鉴权 Token: RobotIoT_Secure_Token_2026) │
│  - 公网端口通道映射表:                                    │
│    * 8000  ──► 目标实体机 8000 (管控大屏 Web 与 REST API)  │
│    * 18083 ──► 目标实体机 18083 (EMQX 5.8 控制台)         │
│    * 1883  ──► 目标实体机 1883 (MQTT 工业消息通道)         │
│    * 2222  ──► 目标实体机 22 (SSH 反向自动化运维通道)      │
└──────────────────────────┬───────────────────────────────┘
                           │ 加密反向隧道连接
                           ▼
┌──────────────────────────────────────────────────────────┐
│  【实际业务生产服务器】目标实体机 (Ubuntu 22.04 LTS)       │
│  ├── 工作目录: /home/qtz/桌面/robot-iot-standalone/app    │
│  ├── 系统用户: qtz (密码: qtz666, 支持 sudo)             │
│  ├── FastAPI 后台服务: systemctl status robot-iot         │
│  ├── EMQX 工业 Broker: systemctl status emqx              │
│  ├── FRP 穿透客户端: systemctl status frpc                │
│  └── SQLite 数据库: robot.db (已持久化甲方全部图文与底账) │
└──────────────────────────────────────────────────────────┘
```

---

### 🚀 远程运维与自动化部署三大步骤

#### 【第一步：目标实体机执行一键建立穿透】
当有一台全新的 Ubuntu 服务器上线，或者实体机网络重连时，在实体机终端（或通过向日葵桌面）执行：
```bash
sudo apt update && sudo apt install -y openssh-server curl wget
sudo systemctl enable --now ssh
# 执行一键反向连接与环境部署
curl -fsSL https://raw.githubusercontent.com/shuli6b/-Robot-IoT-Fleet-Management-System-/main/deploy_new_server.sh | sudo bash
```
> 若实体机已配置过 FRP，只需唤醒隧道服务：
> ```bash
> sudo systemctl restart ssh && sudo systemctl restart frpc
> ```

#### 【第二步：接手人 / AI 助手通过腾讯云直连实体机】
在任何具备外网的开发终端中，通过腾讯云中继直接登录目标 Ubuntu 实体机：
```bash
ssh -p 2222 qtz@106.55.248.254
# 提示输入密码时输入: qtz666
```

#### 【第三步：在实体机上执行一键安全热升级】
成功连入实体机后，只需执行官方自动化更新脚本（自动备份现有数据库、自动合并新字段，保留所有图片与历史数据）：
```bash
curl -fsSL https://raw.githubusercontent.com/shuli6b/-Robot-IoT-Fleet-Management-System-/main/update_server.sh | sudo bash
```
或者手动进入项目目录拉取：
```bash
cd /home/qtz/桌面/robot-iot-standalone/app
git pull origin main
sudo systemctl restart robot-iot
```

---

## 📂 三、 核心代码目录与文件职责清单

```
机器人管理系统/
├── main.py                  # FastAPI 主程序入口，包含所有 RESTful 路由、MQTT 异步总线与 LLM 诊断代理
├── database.py              # SQLite 工业数据持久层，实现 WAL 模式、动态 CMS 品牌存取、单设备规格增删改查
├── mock_robot.py            # 工业遥测仿真器（支持华数机械臂、珞石AMR、仿生机器狗、空地协同编队 4 大品类）
├── requirements.txt         # Python 运行环境核心依赖库清单
├── robot-iot.service        # Linux 标准 systemd 系统守护单元配置
├── start.sh / stop.sh       # Linux 本地一键启动与停止脚本
├── update_server.sh         # 生产服务器一键安全热升级部署脚本
├── deploy_new_server.sh     # 全新 Ubuntu 服务器一键初始化脚本
├── tunnel_manager.py        # 内网穿透动态管理与 Pinggy 隧道集成模块
│
├── static/                  # 前端静态资源目录
│   ├── index_next.html      # 生产级管控大屏主页面（暗色/浅色自适应、ECharts 动态地图、四大品类健康联动、3D孪生）
│   ├── index.html           # 生产大屏主页面（与 index_next.html 保持 100% 同步）
│   ├── login.html           # 科技暗色登录门户（动态基地地图标记、单点登录鉴权）
│   ├── china.json           # 中国标准地理 GeoJSON 数据
│   └── assets/              # 甲方定制上传的基地图片与机器人真实设备高清照片
│       ├── custom_1787207360_5b2b10.png  # 番禺运营中心实景图 (甲方上传)
│       ├── custom_1787208898_2a7c1f.png  # 工业机器人与协作臂设备图 (甲方上传)
│       ├── custom_1787209622_b4b14f.png  # 复合移动机器人 AMR 设备图 (甲方上传)
│       ├── custom_1787209238_0e59b9.png  # 四足仿生机器狗实物图 (甲方上传)
│       ├── base_nansha.jpg               # 南沙研发中心基地图
│       └── huashu_br610_arm.jpg          # 华数 BR610 机械臂备用图
│
├── huashu_bridge/           # 华数 HSC3 工业总线采集网关桥接组件
├── huashu_edge_agent/       # 华数机器人端侧安装部署与联调脚本
└── offline_deploy/          # 离线单机运行独立交付包
```

---

## 💎 四、 已实现的关键业务特性与甲方定制成果

1. **甲方自定义图文与图片资产 100% 留存与固化**：
   - **平台标题**：`昕邦智能 · 多品类异构机器人智能管控平台`
   - **广州番禺运营中心**：主产线为 `云 - 边 - 端协同的具身智能训练与作业平台`，规模 `20+台工业机器人、协作机器人、AMR移动机器人、工业轮式人形机器人规划`，实景图已入库。
   - **广州南沙机器人研发中心**：核心装备为 `空地作业系统平台`，规模 `20+ “机器狗+无人机”复合机器人、“机器狗+机械臂”复合机器人`。
2. **地图散点名称全链路动态绑定**：
   - 彻底消除了地图配置项的硬编码。登录页与大屏上的中国地图散点（番禺 & 南沙）标签、浮动气泡及点击弹窗标题与 CMS 基地名称 **100% 实时联动**。
3. **四大品类机器人健康指标联动与单设备规格参数配置**：
   - **品类 1**：`工业机器人、协作机器人`（伺服电机负载与温升监测）
   - **品类 2**：`复合移动机器人AMR`（电池健康度与定位精度）
   - **品类 3**：`四足仿生机器狗`（关节扭矩与红外测温模组）
   - **品类 4**：`四足狗+无人机协同系统`（空地协同遥感与应急通讯链路）
   - **单设备档案自定义**：管理员在 3D 姿态弹窗中可自由增删键值对规格（Key-Value），并可独立重命名设备与工位。
4. **统一暗色科技风格（Dark Mode Default）**：
   - 默认加载即为科技暗黑模式，杜绝白屏闪烁。

---

## 🎯 五、 下一步工作计划与实机部署指引

1. **现场物理机真实设备接入联调（实机落地阶段）**：
   - **华数六轴机械臂**：在华数控制器工控机上部署 `huashu_edge_agent`，配置控制器 IP 与 HSC3 总线，通过 MQTT 往 `robot/huashu_arm/{dev_id}/telemetry` 主题上报真实伺服电流与各轴坐标。
   - **珞石复合 AMR**：在 AMR 车载工控机通过激光 SLAM 导航 ROS 节点将定位坐标 `(x, y, theta)` 与电量、速度发布至 `robot/luxshare_amr/{dev_id}/status`。
   - **宇树仿生机器狗**：对接机器狗板载 SDK，采集关节扭矩、双光谱红外测温模组数据并上报至 `robot/robot_dog/{dev_id}/sensors`。
2. **EMQX 生产环境安全加固**：
   - 正式生产移交客户前，在 EMQX Dashboard (`http://106.55.248.254:18083`) 中关闭匿名访问（`allow_anonymous = false`），为各现场机器人客户端创建专属 MQTT 认证账号与 ACL 权限。
3. **数据生命周期与历史自动归档**：
   - 随着设备长时间运行，`device_data` 遥测数据会逐步增加。建议配置每周自动归档或保留近 30~90 天高精数据，确保 SQLite 单机性能最优。

---

## 🛠️ 六、 常用生产运维与排查速查表

| 操作场景 | 推荐执行命令 | 说明 |
| :--- | :--- | :--- |
| **查看后端服务状态** | `systemctl status robot-iot` | 检查 FastAPI 进程是否正常运行 |
| **重启管控后台服务** | `sudo systemctl restart robot-iot` | 代码更新或配置更新后重启 |
| **实时查看运行日志** | `journalctl -u robot-iot -f -n 50` | 实时排查报错与请求调用 |
| **查看 EMQX 消息总线** | `systemctl status emqx` | 检查 MQTT Broker 运行状态 |
| **查看内网穿透客户端** | `systemctl status frpc` | 检查与腾讯云中继的连接通道 |
| **一键热更新升级** | `curl -fsSL https://raw.githubusercontent.com/shuli6b/-Robot-IoT-Fleet-Management-System-/main/update_server.sh \| sudo bash` | 3 秒完成无损热升级 |
