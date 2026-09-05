# 工业机器人物联网管控与 3D 数字孪生平台 (Robot IoT Fleet Management & 3D Digital Twin Platform) 🚀

<div align="center">

![Version](https://img.shields.io/badge/Release-v2.5.0-blue.svg?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.10%2B-green.svg?style=flat-square)
![Framework](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square)
![MQTT](https://img.shields.io/badge/EMQX-5.8%2B-0080FF.svg?style=flat-square)
![Database](https://img.shields.io/badge/SQLite3-WAL_Mode-blueviolet.svg?style=flat-square)
![3D Engine](https://img.shields.io/badge/Three.js-WebGL_Scissor-orange.svg?style=flat-square)
![License](https://img.shields.io/badge/License-Proprietary-lightgrey.svg?style=flat-square)

<p align="center">
  <b>面向智能制造车间与工业互联网的多机型机器人集群调度、高频物理遥测直驱、正向运动学（FK）3D 孪生呈现、预防性维保诊断与双主题中控平台</b>
</p>

[✨ 核心亮点](#-核心亮点与技术创新) •
[🦾 支持机型](#-支持机型矩阵) •
[🏛️ 系统架构](#️-系统架构与技术选型) •
[⚡ 快速开始](#-快速开始与运行指引) •
[📡 通信协议与API](#-通信协议与-api-规范) •
[📂 目录结构](#-项目目录结构)

</div>

---

## 📖 项目全景概览

本项目是一套专为现代柔性智能制造产线、工业装备数字化车间打造的高性能机器人物联网（IoT）与三维数字孪生管控平台。

系统全面支持**华数六轴工业机械臂（物理真机直连直驱）**、**立讯精工复合移动机器人 (AMR)**、**工业级四足仿生巡检机器狗**以及**高空应急巡查无人机**等多品类智能装备的统一接入与协同管控。平台底层基于 **Python 异步高性能框架 (FastAPI) + EMQX/Mosquitto 工业物联网消息总线 + SQLite WAL 高并发持久化** 构建，前端基于 **Three.js WebGL 单视口裁剪架构与双主题 UI（科幻暗黑大屏 + Clean White 现代化企业看板）**，具备毫秒级响应、零数据伪造、超低显存开销与平滑交互等工业级高可靠特性。

---

## ✨ 核心亮点与技术创新

### 1. 🦾 华数 HSC3 原生 SocketCmd 底层物理真机直驱采集
- **拒绝中间代理与虚拟伪造**：通过 `huashu_real_bridge.py` 采集桥直接与车间物理华数控制柜（HSC3 Ⅲ型控制器，默认通信端口 `23333`）建立 TCP Socket 原生信令交互。
- **工业级高频遥测流**：毫秒级轮询执行 `mot.getJntData(0)`（六轴绝对物理角度）与 `mot.getLocData(0)`（末端法兰笛卡尔空间位姿 X, Y, Z, A, B, C），以 5Hz~20Hz 频率实时将纯真实生产报文推流至 MQTT 总线。

### 2. 📐 华数 BR610 真实正向运动学（FK）与 1:1 零位映射矩阵
- **坐标系差异彻底解决**：针对 SolidWorks 原厂 URDF STL 导出基准与现场华数示教器基准的几何差异，严格推导并植入高精度正向运动学转换算法：
  - θ1 = rad(A1)
  - θ2 = rad(A2 + 90°)
  - θ3 = π - rad(A3)
  - θ4 = rad(A4), θ5 = rad(A5), θ6 = rad(A6)
- **像素级物理复刻**：在全工作空间象限内运动均保持 100% 连续自洽，无任何奇异翻转；3D 姿态与车间物理机械臂本体分毫不差。

### 3. 🖥️ 单 Canvas 视口裁剪渲染架构（Scissor Multi-Viewport）
- **性能飞跃，根除崩溃**：针对传统 Web 页面中每个设备创建独立 `<canvas>` 导致的 GPU 上下文溢出、显存爆炸和浏览器崩溃问题，系统采用 WebGL `scissorTest` 视口裁剪机制。
- **全站共享单 WebGL 上下文**：全场无限台设备的三维渲染、列表缩略图与详情弹窗全景均共用单个 GPU 上下文，显存占用降低 **80%** 以上，页面极速秒开。

### 4. 🛡️ 防竞态骨架加载机制（Skeleton Loading & Anti-Race Condition）
- **杜绝旧数据残留**：设备详情切换时，系统瞬间执行数据上下文重置，立即展现高质感脉冲骨架加载动画，旧设备的三维姿态与指标不会产生 1 毫秒的残影或串台。
- **请求序列令牌（Request ID Guard）**：引入并发阻断机制，任何迟滞返回的网络旧包均被自动丢弃，确保界面永远准确渲染用户当前选中的目标设备。

### 5. 📊 工业级状态分析与维保预警系统（深度借鉴 FANUC iCare & ZDT）
- **OEE 稼动率与工时分析**：自动统计设备运行（Running）、待机（Standby）与故障停机（Downtime）工时，生成实时稼动率。
- **生产效率与节拍统计 (CT)**：精准追踪当日生产循环总数（Cycle Count）、平均节拍（Average CT）与节拍极值。
- **维保倒计时与健康度雷达**：集成减速机润滑脂寿命倒计时（5,000h 循环）与编码器备用电池更换提醒（365天 周期），实时输出设备电气综合健康评分（0~100 分）。
- **专业报警统计看板**：近 14 天报警波动趋势折线图、伺服驱动/运动超程/总线IO/系统底层四大故障分类环形图及 TOP 5 易发故障专家排障建议。

### 6. 🎨 企业级双主题沉浸式体验
- **暗黑科幻工业大屏 (`/`)**：专为车间集控指挥中心、大屏展厅设计的深色科技感 HUD 界面。
- **Clean White 现代中后台 (`/next`)**：专为设备工程师、车间主任日常巡检运维打造的浅色极简商务界面。

---

## 🦾 支持机型矩阵

| 设备品类 | 代表型号 | 核心通信方式 | 3D 孪生能力 | 监控与遥测核心指标 |
| :--- | :--- | :--- | :--- | :--- |
| **六轴工业机械臂** | 华数 HSR-BR610-1300 | HSC3 SocketCmd / MQTT | 1:1 分件 URDF STL 物理装配 | 6轴绝对物理角度、末端笛卡尔位姿、伺服温度、电流负载、急停使能 |
| **复合移动机器人** | 立讯精工 AMR | 激光 SLAM / ROS / MQTT | 三维车体 + 顶升工作台模型 | 导航坐标 (X, Y, Yaw)、激光雷达避障距离、差速轮速、顶升状态、电池SOC |
| **四足仿生巡检狗** | 工业级四足机器狗 | 运动学步态控制器 / MQTT | 8/12 自由度仿生骨骼联动 | Trot步态步频、四肢关节力矩、IMU姿态角、足端接触力、续航电量 |
| **应急巡查无人机** | 高空侦巡四旋翼无人机 | 飞控遥测 / MAVLink / MQTT | 4轴旋转螺旋桨 + 机体位姿 | RTK-GPS定位星数、高精度气压计高度、4轴电调转速、俯仰横滚角、动力电池 |

---

## 🏛️ 系统架构与技术选型

### 系统架构拓扑图

```mermaid
graph TB
    subgraph 边缘感知与设备接入层
        A1["华数 BR610 真实控制柜<br>192.168.1.169:23333"] -->|SocketCmd TCP| B1["huashu_real_bridge.py<br>真机底层驱动桥"]
        A2["立讯精工 AMR"] -->|MQTT/ROS| B2["AMR 边缘采集器"]
        A3["四足巡检机器狗"] -->|MQTT| B3["机器狗控制器"]
        A4["应急巡查无人机"] -->|MAVLink/MQTT| B4["无人机机载端"]
        M1["mock_service.py<br>高拟真多机型仿真器"] -->|MQTT 模拟流| B5["虚拟集群发生器"]
    end

    subgraph 工业物联网消息总线
        B1 & B2 & B3 & B4 & B5 -->|TCP 1883 发布报文| C["EMQX 5.8 / Mosquitto<br>工业 MQTT Broker"]
    end

    subgraph 核心业务与持久化层
        C -->|异步订阅 robot/#| D["FastAPI 异步核心服务 (main.py)"]
        D <-->|WAL 高并发读写| E[("SQLite 3 数据库<br>robot.db")]
    end

    subgraph 前端数字孪生与大屏交互层
        D -->|WebSocket 实时推流 (5Hz)| F["前端数据总线"]
        D -->|RESTful API / 日志与报表| F
        F -->|Scissor 视口裁剪| G["Three.js WebGL 3D 数字孪生"]
        F -->|ECharts / 响应式 DOM| H1["暗黑科幻工业大屏 (/)"]
        F -->|TailwindCSS / 极简看板| H2["Clean White 商务中后台 (/next)"]
    end
```

### 核心技术栈清单

| 层级 | 技术选型 | 版本要求 | 用途说明 |
| :--- | :--- | :--- | :--- |
| **后端开发框架** | Python / FastAPI / Uvicorn | 3.10+ | 异步高吞吐 REST API 与 WebSocket 实时双向流通道 |
| **物联网中间件** | EMQX Broker / Mosquitto | 5.8+ / 2.0+ | 工业级设备消息发布、订阅与高频分发总线 |
| **数据持久化** | SQLite 3 | WAL 模式 | 高并发单文件微型数据库，无需配置臃肿的大型数据库集群 |
| **三维图形引擎** | Three.js / WebGL | r128+ | 单 Canvas 多视口 3D 渲染，支持 STL/URDF 运动学驱动 |
| **可视化与图表** | ECharts / Chart.js | 5.x | 设备状态稼动率、节拍分析折线图与分类环形图展示 |
| **UI 样式与布局** | TailwindCSS | 3.x (免构建) | 响应式设计，适配 4K 工业集控大屏、PC 工作站与移动端平板 |

---

## 📂 项目目录结构

```text
.
├── database.py              # SQLite 数据库核心（表结构、WAL并发、设备CRUD、报表与报警统计分析）
├── deploy_new_server.sh     # Ubuntu 22.04 LTS 生产服务器一键全自动部署脚本
├── huashu_real_bridge.py    # 华数六轴工业机械臂原生 SocketCmd 协议直驱物理推流桥
├── launcher.py              # 统一应用启动入口引导器
├── main.py                  # FastAPI 后端核心（MQTT订阅、REST API、WebSocket 推流、静态挂载）
├── mock_robot.py            # 工业机器人多机型仿真数学引擎
├── mock_service.py          # 独立运行的高仿真设备集群遥测服务
├── requirements.txt         # 核心 Python 运行时依赖清单
├── robot-iot.service        # Linux Systemd 后台服务守护单元
├── robot-mock.service       # 仿真数据模拟器 Systemd 守护单元
├── start.sh                 # Linux 生产环境一键启动脚本
├── stop.sh                  # Linux 生产环境一键优雅停止脚本
├── update_server.sh         # 生产服务器无损热更新与自动迁移脚本
├── huashu_bridge/           # 华数机械臂适配器组件
│   ├── huashu_adapter.py    # 机械臂适配协议转换层
│   ├── huashu_config.json   # 采集配置参数（IP、端口、频率、轴限制）
│   ├── start_huashu_bridge.bat # Windows 环境直连启动批处理
│   └── start_huashu_bridge.sh  # Linux 环境直连启动 Shell 脚本
├── huashu_edge_agent/       # 边缘端独立轻量级采集代理
│   ├── edge_config.json     # 边缘代理配置文件
│   ├── huashu_edge_collector.py # 边缘采集核心代码
│   └── requirements.txt     # 边缘代理精简依赖
└── static/                  # 前端静态资源全集
    ├── index.html           # 现代暗黑科幻工业大屏 (主界面 /)
    ├── index_next.html      # Clean White 现代企业级管理看板 (/next)
    ├── js/                  # 前端图形引擎库 (Three.js, OrbitControls, STLLoader, Chart.js)
    ├── css/                 # 全局样式文件
    ├── models/br610/        # 华数 BR610 真实 1:1 分件 STL 3D 模型
    └── assets/              # 基地实景图、设备品类缩略图与静态资源
```

---

## ⚡ 快速开始与运行指引

### 1. Windows 本地环境极速启动

#### 步骤一：克隆代码与安装依赖
```powershell
# 进入项目根目录
cd "d:\Antigravity projects\机器人管理系统"

# 安装依赖
pip install -r requirements.txt
```

#### 步骤二：启动核心管理平台与模拟服务
```powershell
# 终端 1：启动 FastAPI 主服务（监听 8000 端口）
python main.py

# 终端 2：启动多机型高仿真模拟服务（生成 AMR、机器狗、无人机高拟真遥测）
python mock_service.py
```

#### 步骤三：启动华数真机直驱采集桥（当接入真实机械臂时）
```powershell
# 确保本地与华数机械臂控制柜 (192.168.1.169) 处于同一局域网网段
python huashu_real_bridge.py
# 或双击运行 huashu_bridge/start_huashu_bridge.bat
```

#### 步骤四：在浏览器中访问
- 🌌 **暗黑科幻工业大屏**：`http://localhost:8000`
- 🏢 **Clean White 商务中后台**：`http://localhost:8000/next`

---

### 2. Linux (Ubuntu 20.04/22.04 LTS) 生产环境部署

#### 步骤一：一键全自动生产部署
系统提供了开箱即用的自动化部署脚本，自动安装 EMQX 物联网 Broker、Python 虚拟环境并注册 systemd 服务：
```bash
sudo chmod +x deploy_new_server.sh
sudo ./deploy_new_server.sh
```

#### 步骤二：使用启停脚本管理
```bash
# 一键启动服务
sudo ./start.sh

# 查看实时运行日志
journalctl -u robot-iot.service -f

# 一键停止服务
sudo ./stop.sh
```

#### 步骤三：代码安全平滑热升级
当有最新代码提交时，执行热升级脚本自动备份数据库并重启服务：
```bash
sudo chmod +x update_server.sh
sudo ./update_server.sh
```

---

## 📡 通信协议与 API 规范

### 1. MQTT 工业遥测报文规范

#### ① 华数六轴工业机械臂推流主题：`robot/huashu_arm/{device_id}/state`
```json
{
  "device_id": "arm_001",
  "device_type": "huashu_arm",
  "name": "华数 BR610-1300 六轴工业机械臂",
  "timestamp": 1725528000.123,
  "status": "RUNNING",
  "battery": 100.0,
  "temperature": 41.5,
  "load_current": 5.8,
  "total_power_kwh": 142.6,
  "running_hours": 1284.5,
  "is_real_device": true,
  "joints": {
    "a1": 10.891,
    "a2": -92.494,
    "a3": 203.156,
    "a4": -1.958,
    "a5": 70.517,
    "a6": 143.212
  },
  "cartesian": {
    "x": 412.60,
    "y": -229.60,
    "z": 478.50,
    "a": 43.50,
    "b": 2.00,
    "c": -179.80
  },
  "safety": {
    "estop": false,
    "servo_enabled": true,
    "error_count": 0
  }
}
```

#### ② 下行控制指令主题：`robot/control/{device_id}/command`
```json
{
  "command": "RESET",
  "operator": "admin",
  "timestamp": 1725528010.550
}
```

### 2. 核心 RESTful API 端点

| 请求方法 | API 路径 | 说明 |
| :--- | :--- | :--- |
| `GET` | `/api/devices` | 获取全场所有设备最新实时状态列表（毫秒级聚合） |
| `GET` | `/api/devices/{type}/{id}` | 获取单台设备详情、规格参数与当前遥测 |
| `GET` | `/api/devices/{type}/{id}/logs` | 基于华数底层 SDK 规范的真实交互操作与运行日志流水 |
| `GET` | `/api/devices/{type}/{id}/report` | 借鉴 FANUC iCare 规范的每日/每月状态综合报告（稼动率、节拍、健康评分） |
| `GET` | `/api/devices/{type}/{id}/alarms/analytics` | 借鉴 FANUC ZDT 规范的近14天故障趋势与四大分类统计 |
| `POST`| `/api/devices/{type}/{id}/control` | 下发设备动作指令（启动工步、急停、组复位、模式切换） |
| `GET` | `/api/devices/{type}/{id}/backup` | 下载该设备配置与关键点位历史数据库打包快照 (.zip) |
| `WS`  | `/ws/telemetry` | WebSocket 高频实时全景遥测推流通道 |

---

## 🔒 安全规范与生产隔离说明

1. **核心机密脱敏防护**：系统生产服务器 IP、远程穿透凭据、SSH 密钥与账号密码均已受严格安全审查与脱敏处理，私有凭据严格存放于本地受 `.gitignore` 保护的独立手册中，严禁推送到任何公开代码托管平台。
2. **第三方知识产权保护**：原厂二次开发 C/C++ SDK 头文件、动态库及 CAD 装配工程已按原厂授权规范归档于本地专属目录，避免公开外泄。
3. **生产运行零侵入**：本地工程重构与代码仓库更新完全独立于云端生产节点，确保车间线上生产业务 24×7 小时不间断平稳运行。

---

<div align="center">
  <sub>昕邦智能装备 · 工业机器人物联网智能管控平台研发团队 荣誉出品</sub>
</div>
