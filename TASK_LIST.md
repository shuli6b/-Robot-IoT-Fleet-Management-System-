# 机器人物联网管理系统 — 开发任务清单（TASK_LIST.md）

> **关联文档**：[ARCHITECTURE.md](file:///d:/Antigravity%20projects/机器人管理系统/ARCHITECTURE.md)  
> **合同编号**：IOT-20260811  
> **任务总数**：5 个子任务，按顺序执行

---

## Task 1：数据库层 + 项目骨架搭建

**目标**：完成 `database.py`、`requirements.txt`，建立项目目录结构，确保数据库可正常初始化。

### 1.1 创建 `requirements.txt`

```text
fastapi>=0.100.0
uvicorn[standard]>=0.23.0
paho-mqtt>=1.6.1
```

### 1.2 创建 `database.py`

实现以下全部功能，每个函数都必须包含 `try/except` 容错：

| 函数 | 功能 | 容错要求 |
|------|------|---------|
| `get_connection()` | 返回 SQLite 连接，启用 WAL 模式、busy_timeout=5000、foreign_keys=ON | 连接失败记录 CRITICAL 日志 |
| `init_db()` | 创建 `devices` 表和 `device_data` 表及全部索引 | 启动时调用，失败则退出进程 |
| `check_db_integrity()` | 执行 `PRAGMA integrity_check`，失败则备份旧库并重建 | 备份文件名含时间戳 |
| `upsert_device(device_id, device_type, last_report_time)` | 新设备 INSERT、已有设备 UPDATE status/last_report_time | 捕获所有 DB 异常，记录日志 |
| `insert_device_data(device_id, device_type, data_type, raw_payload, topic)` | 插入历史数据记录 | DB 写入异常不影响主流程 |
| `get_all_devices(status=None, device_type=None)` | 查询设备列表，支持可选筛选 | 查询异常返回空列表 |
| `get_device(device_type, device_id)` | 查询单个设备记录 | 不存在返回 None |
| `get_latest_data(device_type, device_id)` | 获取设备最新一条上报数据 | 无数据返回 None |
| `get_device_history(device_type, device_id, page, page_size, data_type, start_time, end_time)` | 分页查询历史数据（时间倒序） | 参数校验：page≥1, 1≤page_size≤100 |
| `get_history_count(device_type, device_id, data_type, start_time, end_time)` | 查询符合条件的历史总条数 | 异常返回 0 |
| `mark_offline_devices(threshold_seconds)` | 将超时设备标记为 offline | 异常仅记录日志 |
| `get_system_stats()` | 返回系统统计数据（总设备、在线数、总记录数、分类统计） | 异常返回默认值字典 |

**SQLite 表结构**：严格按 ARCHITECTURE.md 第二节定义。

### 1.3 验证标准

- [ ] `python -c "from database import init_db; init_db()"` 执行成功
- [ ] 生成 `robot.db` 文件，包含 `devices` 和 `device_data` 两张表
- [ ] `PRAGMA journal_mode` 返回 `wal`
- [ ] 所有函数的 `try/except` 块覆盖完整
- [ ] 单元级手动测试：插入设备 → 查询 → 插入数据 → 分页查询 → 标记离线

---

## Task 2：MQTT 监听 + FastAPI 后端服务（`main.py`）

**目标**：完成 `main.py`，集成 MQTT 消息监听与 FastAPI RESTful API，实现核心业务逻辑。

### 2.1 MQTT 客户端集成

| 功能 | 实现要求 | 容错要求 |
|------|---------|---------|
| 连接 EMQX | 使用 paho-mqtt，配置 host/port/username/password（从环境变量或默认值读取） | 连接失败记录日志，不阻止 FastAPI 启动 |
| 订阅 `robot/#` | 连接成功后自动订阅 | 订阅失败记录日志 |
| `on_message` 回调 | 解析 Topic → 解码 JSON → upsert 设备 → 插入数据 | 每步独立 try/except，任一失败不影响后续消息 |
| `on_disconnect` 回调 | 非正常断开时记录日志 | paho 自动重连 min=1s, max=30s |
| Topic 解析 `parse_topic()` | 拆分为 device_type/device_id/data_type | 格式不合法返回 None + 日志 |
| JSON 解码 | 尝试 `json.loads(payload)` | 失败时将原始 bytes decode 存入 raw_payload |
| 后台线程运行 | MQTT client `loop_start()` 在后台线程 | 不阻塞 FastAPI 事件循环 |

### 2.2 FastAPI REST API

实现 ARCHITECTURE.md 第四节定义的全部 5 个接口：

| 接口 | 路由 | 方法 | 说明 |
|------|------|------|------|
| 设备列表 | `/api/devices` | GET | 支持 status/device_type 筛选 |
| 设备实时详情 | `/api/devices/{device_type}/{device_id}/latest` | GET | 返回设备信息 + 最新数据 |
| 设备历史数据 | `/api/devices/{device_type}/{device_id}/history` | GET | 分页 + 时间倒序 + 筛选 |
| 系统概览 | `/api/system/overview` | GET | 统计信息 + MQTT 状态 |
| 健康检查 | `/api/health` | GET | 系统可用性 |

**API 通用要求**：
- 所有接口统一响应格式 `{ code, message, data, timestamp }`
- 所有接口添加全局异常处理器（`@app.exception_handler(Exception)`）
- 参数校验失败返回 400
- 设备不存在返回 404

### 2.3 后台定时任务

| 任务 | 间隔 | 功能 |
|------|------|------|
| 离线检测 | 每 10 秒 | 扫描 online 设备，超过 30 秒无上报标记 offline |

使用 `asyncio.create_task` + `while True` + `asyncio.sleep(10)` 实现。

### 2.4 FastAPI 生命周期事件

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时：初始化DB → 启动 MQTT → 启动离线检测
    init_db()
    start_mqtt_client()
    task = asyncio.create_task(check_device_offline())
    yield
    # 关闭时：停止 MQTT → 取消定时任务
    stop_mqtt_client()
    task.cancel()
```

### 2.5 静态文件挂载

```python
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")
```

### 2.6 设备类型中文映射

```python
DEVICE_TYPE_DISPLAY = {
    "huashu_arm": "华数机械臂",
    "luxshare_amr": "珞石AMR",
    "robot_dog": "四足机器狗",
}
```

### 2.7 环境变量配置

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MQTT_HOST` | `localhost` | EMQX 地址 |
| `MQTT_PORT` | `1883` | EMQX 端口 |
| `MQTT_USERNAME` | `robot_server` | MQTT 用户名 |
| `MQTT_PASSWORD` | `robot_server_pass` | MQTT 密码 |
| `OFFLINE_THRESHOLD` | `30` | 离线判定秒数 |
| `DB_PATH` | `robot.db` | 数据库路径 |

### 2.8 验证标准

- [ ] `uvicorn main:app --host 0.0.0.0 --port 8000` 启动无报错
- [ ] 访问 `http://localhost:8000/api/health` 返回 200
- [ ] 访问 `http://localhost:8000/api/devices` 返回空设备列表
- [ ] 访问 `http://localhost:8000/` 返回 index.html（此时可先放一个占位页面）
- [ ] MQTT 连接失败时日志正确记录，API 仍可正常访问
- [ ] 全局异常处理器工作正常（手动触发异常测试）

---

## Task 3：前端页面开发（`static/index.html`）

**目标**：创建免编译单文件 Web 页面，使用 TailwindCSS CDN + 原生 JS，实现所有前端交互功能。

### 3.1 页面模块

| 模块 | 功能 | 数据来源 |
|------|------|---------|
| **顶部导航栏** | 系统名称 "机器人物联网管理系统" + Logo | 静态 |
| **统计概览卡片** | 总设备数、在线数、离线数、总数据量（4张卡片） | `GET /api/system/overview` |
| **设备总览表格** | 设备ID、类型、状态标识、最后上报时间 | `GET /api/devices` |
| **实时数据面板** | 点击设备行展开，显示最新上报 JSON | `GET /api/devices/{type}/{id}/latest` |
| **历史数据查询** | 设备选择器 + 条数输入 + 分页 + 表格展示 | `GET /api/devices/{type}/{id}/history` |
| **底部状态栏** | 系统版本、最后刷新时间、MQTT 连接状态 | `GET /api/system/overview` |

### 3.2 UI 设计要求

| 要素 | 规范 |
|------|------|
| 配色 | 深色主题（暗灰底 + 科技蓝/翠绿强调色） |
| 字体 | Google Fonts - Inter |
| 在线状态 | 绿色圆点 + "在线" 文字 |
| 离线状态 | 红色圆点 + "离线" 文字 |
| 响应式 | 适配 PC 和平板（≥768px） |
| 动画 | 卡片数据更新时淡入效果；状态切换过渡动画 |
| 空状态 | "暂无设备数据" 友好提示图标 |

### 3.3 轮询机制

```javascript
const POLL_INTERVAL = 5000; // 5秒

// 设备列表轮询
setInterval(async () => {
    try {
        const res = await fetch('/api/devices');
        // ...渲染
    } catch (e) {
        // 静默处理，显示连接异常横幅
    }
}, POLL_INTERVAL);

// 统计概览轮询
setInterval(async () => {
    try {
        const res = await fetch('/api/system/overview');
        // ...渲染
    } catch (e) { /* 静默 */ }
}, POLL_INTERVAL);

// 选中设备的实时数据轮询
let selectedDevice = null;
setInterval(async () => {
    if (!selectedDevice) return;
    try {
        const res = await fetch(`/api/devices/${selectedDevice.type}/${selectedDevice.id}/latest`);
        // ...渲染
    } catch (e) { /* 静默 */ }
}, POLL_INTERVAL);
```

### 3.4 前端容错清单

- [ ] 所有 `fetch` 调用包裹在 `try/catch` 中
- [ ] 网络断开时显示顶部红色横幅 "网络连接异常，正在重试..."
- [ ] 网络恢复时自动隐藏横幅
- [ ] API 返回空数据时显示友好占位
- [ ] JSON 渲染失败时 `catch` 保护，显示原始文本
- [ ] 页面不使用 `alert()`，所有提示使用 Toast 组件
- [ ] 分页参数边界保护（page≥1、page_size∈[1,100]）

### 3.5 验证标准

- [ ] 浏览器访问 `http://localhost:8000/` 页面正常渲染
- [ ] 无任何 Console 报错
- [ ] 统计卡片每5秒自动更新（观察时间戳变化）
- [ ] 设备表格正确显示，在线/离线状态颜色区分
- [ ] 点击设备行可查看实时数据 JSON
- [ ] 历史数据分页查询功能正常
- [ ] 关闭后端后页面显示连接异常提示，不崩溃
- [ ] 重启后端后页面自动恢复
- [ ] 页面美观、专业、响应式布局

---

## Task 4：模拟测试脚本（`mock_robot.py`）

**目标**：创建完整的模拟设备上报脚本，覆盖 3 种设备类型，支持甲方离线自测。

### 4.1 模拟设备列表

| 设备类型 | Topic 前缀 | 模拟设备数 | 数据类型 |
|---------|-----------|-----------|---------|
| 华数机械臂 | `robot/huashu_arm/arm_001` | 1 | state, sensor |
| 珞石 AMR | `robot/luxshare_amr/amr_001` | 1 | state, sensor |
| 四足机器狗 | `robot/robot_dog/dog_001` | 1 | state, sensor |

### 4.2 模拟数据格式

**华数机械臂 state**：
```json
{
    "timestamp": "2026-08-15T10:30:00",
    "status": "running|idle|error|stopped",
    "battery": 85,
    "error_code": 0,
    "error_msg": "",
    "joint_angles": [0.5, 1.2, -0.8, 0.3, 1.5, -0.2],
    "speed": 50,
    "payload_kg": 5.5,
    "cycle_count": 1024
}
```

**珞石 AMR state**：
```json
{
    "timestamp": "2026-08-15T10:30:00",
    "status": "navigating|charging|idle|error",
    "battery": 72,
    "error_code": 0,
    "position": {"x": 12.5, "y": 8.3, "z": 0.0},
    "speed_mps": 1.2,
    "map_id": "warehouse_floor_1",
    "current_task": "deliver_001",
    "load_status": "loaded"
}
```

**四足机器狗 state**：
```json
{
    "timestamp": "2026-08-15T10:30:00",
    "status": "patrolling|standing|sitting|error",
    "battery": 90,
    "error_code": 0,
    "gait_mode": "trot",
    "speed_mps": 0.8,
    "imu_pitch": 2.1,
    "imu_roll": -0.5,
    "temperature": 38.5
}
```

**通用 sensor 数据**：
```json
{
    "timestamp": "2026-08-15T10:30:00",
    "temperature": 42.5,
    "humidity": 65.2,
    "vibration": 0.03,
    "current": 2.8,
    "voltage": 24.1
}
```

### 4.3 脚本功能要求

| 功能 | 说明 |
|------|------|
| 周期上报 | 默认每 5 秒上报一次 state + sensor |
| 数据随机化 | 每次上报数据有合理随机波动 |
| 命令行参数 | `--host`、`--port`、`--username`、`--password`、`--interval` |
| 优雅退出 | 捕获 `Ctrl+C` (SIGINT)，断开连接后退出 |
| 连接容错 | EMQX 未启动时不崩溃，持续重连 |
| 日志输出 | 每次上报打印 Topic + 关键字段摘要 |
| 独立运行 | `python mock_robot.py` 即可启动 |

### 4.4 验证标准

- [ ] `python mock_robot.py` 启动后持续输出上报日志
- [ ] 上报数据可被 `main.py` MQTT 客户端正确接收
- [ ] 3 种设备自动出现在 `/api/devices` 列表中
- [ ] 状态为 `online`，停止脚本后 30 秒内变为 `offline`
- [ ] 前端页面实时展示模拟设备数据
- [ ] `Ctrl+C` 可正常停止脚本
- [ ] EMQX 未启动时脚本不崩溃，输出重连日志

---

## Task 5：启动脚本 + 部署文档 + 集成测试

**目标**：完成 `start.sh`、`README.md`，执行全流程集成测试，确保系统满足全部验收标准。

### 5.1 创建 `start.sh`

```bash
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "[INFO] 创建 Python 虚拟环境..."
    python3 -m venv venv
fi

# 激活并安装依赖
source venv/bin/activate
pip install -r requirements.txt -q

# 启动服务
echo "[INFO] 启动机器人物联网管理系统..."
echo "[INFO] Web 管理页面: http://$(hostname -I | awk '{print $1}'):8000"
echo "[INFO] 按 Ctrl+C 停止服务"
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

### 5.2 创建 `README.md`

README.md 需包含以下完整章节：

| 章节 | 内容 |
|------|------|
| 系统简介 | 功能概述、技术栈、架构图 |
| 环境要求 | Ubuntu 22.04、Python 3.10+、EMQX 5.x |
| 快速部署 | 5 步完成部署（安装Python → 安装EMQX → 克隆代码 → 配置 → 启动） |
| EMQX 配置指南 | 安装、创建账号、关闭匿名、ACL 配置 |
| 一键启动 | `bash start.sh` 用法 |
| systemd 开机自启配置 | 完整的 service 文件 + 安装步骤 |
| 防火墙配置 | `ufw` 开放 8000/1883 端口 |
| 模拟测试 | `python mock_robot.py` 使用说明 |
| API 接口文档 | 5 个接口的简要说明 + 示例 |
| 设备对接指南 | MQTT Topic 规范、JSON 格式、新设备接入步骤 |
| 常见故障排查 | 10 个常见问题及解决方案 |
| 目录结构说明 | 每个文件的用途 |

### 5.3 集成测试清单

#### 5.3.1 功能验收测试

| # | 测试项 | 操作 | 预期结果 |
|---|--------|------|---------|
| F1 | 系统启动 | `bash start.sh` | 无报错，日志显示 MQTT 连接成功 |
| F2 | 页面访问 | 浏览器 `http://IP:8000` | 页面美观加载，无 JS 报错 |
| F3 | 模拟上报 | 启动 `mock_robot.py` | 3 台设备出现在页面，状态在线 |
| F4 | 实时数据 | 点击设备行 | 展示最新 JSON 数据，≤5秒延迟 |
| F5 | 自动刷新 | 等待 10 秒 | 页面数据自动更新（观察时间戳变化） |
| F6 | 离线检测 | 停止 mock_robot.py | 30 秒内设备状态变为离线（红色） |
| F7 | 历史查询 | 输入条数点查询 | 返回时间倒序数据，分页正常 |
| F8 | API 健康 | `curl /api/health` | 返回 200 + 健康信息 |
| F9 | 设备筛选 | API 传 `status=online` | 仅返回在线设备 |
| F10 | 无数据提示 | 未上报设备查看详情 | 显示"暂无上报数据" |

#### 5.3.2 容错测试

| # | 测试项 | 操作 | 预期结果 |
|---|--------|------|---------|
| E1 | MQTT 断开 | 停止 EMQX | 日志记录断开，API 仍可访问，页面显示历史数据 |
| E2 | MQTT 重连 | 重启 EMQX | 自动重连成功，日志记录 |
| E3 | 非法 Topic | 发送 `invalid/topic` | 日志 warning，系统不崩溃 |
| E4 | 非法 JSON | 发送非 JSON payload | 原始数据存入 DB，日志 error |
| E5 | 网络断开 | 断开前端网络 | 页面显示连接异常横幅，不崩溃 |
| E6 | 网络恢复 | 恢复前端网络 | 横幅消失，数据自动恢复 |
| E7 | 进程崩溃恢复 | `kill -9` + systemd | 自动重启，数据不丢失 |
| E8 | 大数据分页 | 插入 1000+ 条数据查询 | 分页流畅，无超时 |

#### 5.3.3 安全验收测试

| # | 测试项 | 操作 | 预期结果 |
|---|--------|------|---------|
| S1 | 匿名连接 | 无密码 MQTT 连接 | 连接被拒绝 |
| S2 | 错误密码 | 错误密码 MQTT 连接 | 连接被拒绝 |
| S3 | 防火墙 | 扫描非开放端口 | 无响应 |

#### 5.3.4 非功能性验收

| # | 测试项 | 标准 | 验证方法 |
|---|--------|------|---------|
| N1 | 数据延迟 | ≤5 秒 | MQTT 发送到页面展示计时 |
| N2 | 24h 稳定性 | 无崩溃、无数据丢失 | mock_robot 连续运行 24h |
| N3 | 开机自启 | reboot 后自动运行 | 服务器重启验证 |
| N4 | 兼容性 | Ubuntu 22.04 | 目标服务器部署 |

### 5.4 验证标准

- [ ] `start.sh` 一键启动成功
- [ ] `README.md` 内容完整，步骤可操作
- [ ] 功能测试 F1-F10 全部通过
- [ ] 容错测试 E1-E8 全部通过
- [ ] systemd 服务配置可正常 enable/start/restart
- [ ] 全部交付物文件齐全：main.py / database.py / requirements.txt / static/index.html / start.sh / mock_robot.py / README.md

---

## 交付物文件清单总览

| 文件 | 产出 Task | 说明 |
|------|----------|------|
| `requirements.txt` | Task 1 | Python 依赖 |
| `database.py` | Task 1 | 数据库模型与操作 |
| `main.py` | Task 2 | FastAPI + MQTT 核心 |
| `static/index.html` | Task 3 | 完整前端页面 |
| `mock_robot.py` | Task 4 | 模拟设备脚本 |
| `start.sh` | Task 5 | 一键启动脚本 |
| `README.md` | Task 5 | 部署与对接说明 |
| `robot.db` | 运行时自动生成 | SQLite 数据库 |

---

## 执行顺序与依赖关系

```
Task 1 (database.py)
   │
   ▼
Task 2 (main.py) ──依赖── Task 1 的 database 模块
   │
   ▼
Task 3 (index.html) ──依赖── Task 2 的 API 接口
   │
   ▼
Task 4 (mock_robot.py) ──依赖── Task 2 的 MQTT 监听
   │
   ▼
Task 5 (start.sh + README.md + 集成测试) ──依赖── Task 1~4 全部完成
```

> **注意**：每完成一个 Task，必须运行该 Task 的验证标准全部通过后，再进入下一个 Task。
