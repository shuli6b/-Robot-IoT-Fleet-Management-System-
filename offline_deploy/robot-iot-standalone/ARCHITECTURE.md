# 机器人物联网管理系统 — 技术架构设计文档（ARCHITECTURE.md）

> **合同编号**：IOT-20260811  
> **甲方**：广州昕邦智能技术有限公司  
> **乙方**：广州擎天智技术有限责任公司  
> **目标环境**：Ubuntu 22.04 LTS  
> **文档版本**：v1.0 — 2026-08-15

---

## 一、系统总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Ubuntu 22.04 LTS                        │
│                                                             │
│  ┌──────────┐   MQTT(1883)   ┌──────────┐                  │
│  │ 华数机械臂 │──────────────▶│          │                  │
│  │ 珞石 AMR  │──────────────▶│  EMQX    │                  │
│  │ 四足机器狗 │──────────────▶│ Broker   │                  │
│  │ 模拟脚本   │──────────────▶│ (TCP)    │                  │
│  └──────────┘               └────┬─────┘                  │
│                                   │ robot/#                 │
│                                   ▼                         │
│  ┌────────────────────────────────────────────────────┐     │
│  │              main.py (FastAPI + MQTT Client)       │     │
│  │  ┌──────────────┐  ┌───────────────┐  ┌─────────┐ │     │
│  │  │ MQTT Listener │  │ REST API Layer│  │ Static  │ │     │
│  │  │ (paho-mqtt)   │  │ (FastAPI)     │  │ Files   │ │     │
│  │  └──────┬───────┘  └───────┬───────┘  └────┬────┘ │     │
│  │         │                   │                │      │     │
│  │         ▼                   ▼                │      │     │
│  │  ┌──────────────────────────────┐            │      │     │
│  │  │     database.py              │            │      │     │
│  │  │  (SQLite WAL + ORM Layer)    │            │      │     │
│  │  └──────────┬───────────────────┘            │      │     │
│  │             ▼                                │      │     │
│  │      robot.db (SQLite)                       │      │     │
│  └────────────────────────────────────────────────────┘     │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │       static/index.html (前端单页面)                   │   │
│  │   原生JS + TailwindCSS CDN │ 每5秒轮询 REST API       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────┐                                   │
│  │ systemd 服务单元       │  ── 开机自启 main.py             │
│  └──────────────────────┘                                   │
└─────────────────────────────────────────────────────────────┘
```

### 核心技术栈

| 层级 | 技术选型 | 版本要求 |
|------|---------|---------|
| 后端框架 | FastAPI + Uvicorn | Python 3.10+ |
| MQTT 客户端 | paho-mqtt | ≥1.6 |
| 数据库 | SQLite3（WAL 模式） | Python 内置 |
| 前端 | 原生 HTML/JS + TailwindCSS CDN | 免编译 |
| 消息中间件 | EMQX | 5.x |
| 部署 | systemd + start.sh | Ubuntu 22.04 LTS |

---

## 二、SQLite 数据库设计

### 2.1 数据库初始化配置

```python
# database.py 核心初始化
import sqlite3

DB_PATH = "robot.db"

def get_connection():
    """获取数据库连接，启用WAL模式防止并发写入锁"""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")       # WAL模式：允许读写并发
    conn.execute("PRAGMA busy_timeout=5000")       # 忙等5秒，避免 database locked
    conn.execute("PRAGMA synchronous=NORMAL")      # 性能与安全平衡
    conn.execute("PRAGMA foreign_keys=ON")         # 启用外键
    conn.row_factory = sqlite3.Row                 # 返回字典式结果
    return conn
```

### 2.2 设备表 `devices`

存储所有已注册设备的档案信息，由 MQTT 消息首次上报时自动创建。

```sql
CREATE TABLE IF NOT EXISTS devices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT    NOT NULL,                    -- 设备唯一标识（从Topic解析）
    device_type     TEXT    NOT NULL,                    -- 设备类型：huashu_arm / luxshare_amr / robot_dog
    status          TEXT    NOT NULL DEFAULT 'offline',  -- 在线状态：online / offline
    last_report_time TEXT   DEFAULT NULL,                -- 最后一次上报时间 ISO 8601
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(device_id, device_type)                       -- 同类型同ID唯一
);

-- 按 status 查询索引（设备列表筛选）
CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status);
-- 按 device_type 查询索引
CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type);
```

**字段说明**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | INTEGER | 自增主键 |
| `device_id` | TEXT | 设备唯一标识，从 MQTT Topic 第3段解析 |
| `device_type` | TEXT | 设备类型，从 MQTT Topic 第2段解析 |
| `status` | TEXT | `online` / `offline`，由心跳超时自动判定 |
| `last_report_time` | TEXT | 最后一次数据上报时间（ISO 8601 格式） |
| `created_at` | TEXT | 设备首次注册时间 |
| `updated_at` | TEXT | 设备信息最后更新时间 |

### 2.3 历史数据表 `device_data`

存储所有设备上报的原始 JSON 数据，支持永久留存。

```sql
CREATE TABLE IF NOT EXISTS device_data (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id       TEXT    NOT NULL,                    -- 关联设备标识
    device_type     TEXT    NOT NULL,                    -- 设备类型
    data_type       TEXT    NOT NULL,                    -- 数据类型：state / sensor / ...
    raw_payload     TEXT    NOT NULL,                    -- 原始JSON数据（完整保留）
    topic           TEXT    NOT NULL,                    -- 原始 MQTT Topic
    received_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),  -- 入库时间
    FOREIGN KEY (device_id, device_type) REFERENCES devices(device_id, device_type)
);

-- 按设备+时间查询索引（历史查询核心）
CREATE INDEX IF NOT EXISTS idx_data_device_time ON device_data(device_id, device_type, received_at DESC);
-- 按入库时间降序索引（全局时间倒序查询）
CREATE INDEX IF NOT EXISTS idx_data_received ON device_data(received_at DESC);
-- 按数据类型索引
CREATE INDEX IF NOT EXISTS idx_data_type ON device_data(data_type);
```

**字段说明**：

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | INTEGER | 自增主键 |
| `device_id` | TEXT | 对应设备标识 |
| `device_type` | TEXT | 对应设备类型 |
| `data_type` | TEXT | 数据类型（state/sensor/alarm 等） |
| `raw_payload` | TEXT | 原始上报 JSON 字符串，完整存储 |
| `topic` | TEXT | 原始 MQTT Topic（用于审计追溯） |
| `received_at` | TEXT | 服务器入库时间（ISO 8601） |

### 2.4 数据库容错设计

| 容错场景 | 处理方案 |
|---------|---------|
| 并发读写锁 | SQLite WAL 模式 + busy_timeout=5000ms |
| 数据库文件损坏 | 启动时 `PRAGMA integrity_check`，异常时自动备份旧库并重建 |
| 磁盘空间不足 | 写入异常捕获，记录日志，不影响 MQTT 监听 |
| 外键引用缺失 | INSERT 前先 upsert 设备记录，保证引用完整 |
| 大数据量查询 | 强制分页（`LIMIT` + `OFFSET`），默认每页 20 条 |

---

## 三、MQTT Topic 命名规范与数据解析

### 3.1 Topic 命名规则

```
robot/{device_type}/{device_id}/{data_type}
```

**层级说明**：

| 层级 | 含义 | 示例值 | 规范 |
|------|------|--------|------|
| 第1级 `robot` | 固定前缀 | `robot` | 所有机器人设备共用 |
| 第2级 `{device_type}` | 设备类型 | `huashu_arm`、`luxshare_amr`、`robot_dog` | 小写+下划线，不含特殊字符 |
| 第3级 `{device_id}` | 设备唯一标识 | `arm_001`、`amr_003`、`dog_002` | 同类型内唯一 |
| 第4级 `{data_type}` | 数据类型 | `state`、`sensor`、`alarm` | 枚举值，可扩展 |

**合法 Topic 示例**：

```
robot/huashu_arm/arm_001/state       # 华数机械臂状态数据
robot/huashu_arm/arm_001/sensor      # 华数机械臂传感器数据
robot/luxshare_amr/amr_001/state     # 珞石 AMR 状态数据
robot/luxshare_amr/amr_001/sensor    # 珞石 AMR 传感器数据
robot/robot_dog/dog_001/state        # 四足机器狗状态数据
robot/robot_dog/dog_001/sensor       # 四足机器狗传感器数据
```

### 3.2 服务端订阅策略

```python
# 使用通配符订阅所有机器人上报
SUBSCRIBE_TOPIC = "robot/#"
```

- 服务端只需订阅 `robot/#`，即可接收所有设备的所有数据类型
- 新增设备类型无需修改后端订阅代码，仅需约定 Topic 和 JSON 格式
- EMQX 配置账号密码鉴权，关闭匿名连接

### 3.3 Topic 解析逻辑

```python
def parse_topic(topic: str) -> dict | None:
    """
    解析 MQTT Topic，提取设备类型、设备ID、数据类型。
    返回 None 表示 Topic 格式不合法，调用方应记录日志并跳过。
    """
    parts = topic.split("/")
    if len(parts) != 4:
        logger.warning(f"Topic 格式不合法（段数≠4）: {topic}")
        return None
    if parts[0] != "robot":
        logger.warning(f"Topic 前缀不合法（非 robot）: {topic}")
        return None
    
    device_type = parts[1].strip()
    device_id = parts[2].strip()
    data_type = parts[3].strip()
    
    if not device_type or not device_id or not data_type:
        logger.warning(f"Topic 字段为空: {topic}")
        return None
    
    return {
        "device_type": device_type,
        "device_id": device_id,
        "data_type": data_type,
    }
```

### 3.4 上报数据 JSON 格式约定

#### 3.4.1 状态数据 (`state`)

```json
{
    "timestamp": "2026-08-15T10:30:00",
    "status": "running",
    "battery": 85,
    "error_code": 0,
    "error_msg": ""
}
```

### 3.5 下行任务控制指令规范（功能 F6）

**Topic 格式**：`cmd/{device_type}/{device_id}`

| 参数 | 说明 |
|------|------|
| `{device_type}` | 目标设备品类，如 `huashu_arm` / `luxshare_amr` / `robot_dog` |
| `{device_id}` | 目标设备唯一标识，如 `arm_001` / `amr_001` / `dog_001` |

**下行 JSON Payload**：

```json
{
    "task_id": "T20260815-001",
    "command": "goto",
    "params": {
        "x": 10.2,
        "y": 5.5,
        "map_id": "MAP_FLOOR_1"
    },
    "timestamp": "2026-08-15 10:00:00"
}
```

- 端侧设备需订阅 `cmd/{device_type}/{device_id}` 主题接收指令
- 后端调用 `POST /api/device/{dev_id}/cmd` 时，自动解析并经 MQTT 发布至对应主题，同时写入 `device_data` 表留痕溯源。

#### 3.4.2 传感器数据 (`sensor`)

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

#### 3.4.3 告警数据 (`alarm`) — 可扩展

```json
{
    "timestamp": "2026-08-15T10:30:00",
    "alarm_level": "warning",
    "alarm_code": "E1023",
    "alarm_msg": "电机温度过高",
    "resolved": false
}
```

> **容错策略**：服务端对 JSON Payload 解析失败时，将原始 bytes 以 `raw_payload` 存入 `device_data` 表，记录错误日志，不丢弃任何数据，不影响系统运行。

### 3.5 MQTT 消息处理流程

```
EMQX 接收设备消息
        │
        ▼
main.py on_message 回调
        │
        ├── 1. 解析 Topic → parse_topic()
        │       ├── 失败 → 记录 warning 日志，跳过
        │       └── 成功 → 提取 device_type, device_id, data_type
        │
        ├── 2. 解码 Payload → JSON
        │       ├── 失败 → 将原始 bytes 存为 raw_payload，记录 error 日志
        │       └── 成功 → JSON 字符串
        │
        ├── 3. Upsert 设备记录 → devices 表
        │       ├── 新设备 → INSERT（自动注册）
        │       └── 已有设备 → UPDATE status='online', last_report_time=now
        │
        └── 4. 插入历史数据 → device_data 表
                └── INSERT raw_payload + topic + received_at
```

---

## 四、RESTful API 接口定义

### 4.0 API 通用规范

- **Base URL**：`http://{host}:8000/api`
- **Content-Type**：`application/json`
- **字符集**：UTF-8
- **时间格式**：ISO 8601（`YYYY-MM-DDTHH:MM:SS`）
- **分页默认**：`page=1, page_size=20, max_page_size=100`

**通用响应包装**：

```json
{
    "code": 200,
    "message": "success",
    "data": { ... },
    "timestamp": "2026-08-15T10:30:00"
}
```

**通用错误响应**：

```json
{
    "code": 500,
    "message": "数据库写入失败: database is locked",
    "data": null,
    "timestamp": "2026-08-15T10:30:00"
}
```

---

### 4.1 获取设备列表

```
GET /api/devices
```

**功能**：返回所有已注册设备列表，包含在线/离线状态。

**请求参数**（Query）：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `status` | string | 否 | 全部 | 筛选设备状态：`online` / `offline` |
| `device_type` | string | 否 | 全部 | 筛选设备类型 |

**成功响应** `200`：

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "total": 3,
        "devices": [
            {
                "id": 1,
                "device_id": "arm_001",
                "device_type": "huashu_arm",
                "device_type_display": "华数机械臂",
                "status": "online",
                "last_report_time": "2026-08-15T10:30:00",
                "created_at": "2026-08-15T08:00:00",
                "updated_at": "2026-08-15T10:30:00"
            },
            {
                "id": 2,
                "device_id": "amr_001",
                "device_type": "luxshare_amr",
                "device_type_display": "珞石AMR",
                "status": "online",
                "last_report_time": "2026-08-15T10:29:55",
                "created_at": "2026-08-15T08:00:00",
                "updated_at": "2026-08-15T10:29:55"
            },
            {
                "id": 3,
                "device_id": "dog_001",
                "device_type": "robot_dog",
                "device_type_display": "四足机器狗",
                "status": "offline",
                "last_report_time": "2026-08-15T09:15:00",
                "created_at": "2026-08-15T08:00:00",
                "updated_at": "2026-08-15T09:15:00"
            }
        ]
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

---

### 4.2 获取设备实时详情

```
GET /api/devices/{device_type}/{device_id}/latest
```

**功能**：获取指定设备最近一条上报数据及设备基本信息。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `device_type` | string | 设备类型 |
| `device_id` | string | 设备标识 |

**成功响应** `200`：

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "device": {
            "device_id": "arm_001",
            "device_type": "huashu_arm",
            "device_type_display": "华数机械臂",
            "status": "online",
            "last_report_time": "2026-08-15T10:30:00"
        },
        "latest_data": {
            "id": 1024,
            "data_type": "state",
            "raw_payload": "{\"timestamp\":\"2026-08-15T10:30:00\",\"status\":\"running\",\"battery\":85,\"error_code\":0}",
            "parsed_payload": {
                "timestamp": "2026-08-15T10:30:00",
                "status": "running",
                "battery": 85,
                "error_code": 0
            },
            "topic": "robot/huashu_arm/arm_001/state",
            "received_at": "2026-08-15T10:30:01"
        }
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

**设备不存在响应** `404`：

```json
{
    "code": 404,
    "message": "设备不存在: huashu_arm/arm_999",
    "data": null,
    "timestamp": "2026-08-15T10:30:05"
}
```

**设备无数据响应** `200`（设备存在但无上报）：

```json
{
    "code": 200,
    "message": "该设备暂无上报数据",
    "data": {
        "device": { "..." : "..." },
        "latest_data": null
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

---

### 4.3 查询设备历史数据

```
GET /api/devices/{device_type}/{device_id}/history
```

**功能**：分页查询指定设备的历史上报数据，按时间倒序排列。

**路径参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `device_type` | string | 设备类型 |
| `device_id` | string | 设备标识 |

**请求参数**（Query）：

| 参数 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `page` | int | 否 | 1 | 页码（从1开始） |
| `page_size` | int | 否 | 20 | 每页条数（最大100） |
| `data_type` | string | 否 | 全部 | 筛选数据类型 |
| `start_time` | string | 否 | 无 | 起始时间（ISO 8601） |
| `end_time` | string | 否 | 无 | 截止时间（ISO 8601） |

**成功响应** `200`：

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "device_id": "arm_001",
        "device_type": "huashu_arm",
        "total": 256,
        "page": 1,
        "page_size": 20,
        "total_pages": 13,
        "records": [
            {
                "id": 1024,
                "data_type": "state",
                "raw_payload": "{\"timestamp\":\"2026-08-15T10:30:00\",\"status\":\"running\",\"battery\":85}",
                "topic": "robot/huashu_arm/arm_001/state",
                "received_at": "2026-08-15T10:30:01"
            },
            {
                "id": 1023,
                "data_type": "sensor",
                "raw_payload": "{\"timestamp\":\"2026-08-15T10:29:55\",\"temperature\":42.5}",
                "topic": "robot/huashu_arm/arm_001/sensor",
                "received_at": "2026-08-15T10:29:56"
            }
        ]
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

---

### 4.4 获取系统概览统计

```
GET /api/system/overview
```

**功能**：获取系统全局统计数据（总设备数、在线数、总数据量等）。

**成功响应** `200`：

```json
{
    "code": 200,
    "message": "success",
    "data": {
        "total_devices": 6,
        "online_devices": 4,
        "offline_devices": 2,
        "total_records": 15230,
        "device_type_stats": [
            { "device_type": "huashu_arm", "display": "华数机械臂", "count": 2, "online": 2 },
            { "device_type": "luxshare_amr", "display": "珞石AMR", "count": 2, "online": 1 },
            { "device_type": "robot_dog", "display": "四足机器狗", "count": 2, "online": 1 }
        ],
        "server_time": "2026-08-15T10:30:05",
        "uptime_seconds": 86400,
        "mqtt_connected": true
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

---

### 4.5 系统健康检查

```
GET /api/health
```

**功能**：系统健康检查，用于 systemd watchdog / 监控。

**成功响应** `200`：

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
    },
    "timestamp": "2026-08-15T10:30:05"
}
```

---

### 4.6 API 错误码一览

| HTTP 状态码 | `code` 值 | 场景 |
|------------|-----------|------|
| 200 | 200 | 请求成功 |
| 400 | 400 | 参数校验失败（`page_size` 超限等） |
| 404 | 404 | 设备不存在 |
| 500 | 500 | 服务器内部错误（DB锁、IO异常等） |

---

## 五、设备类型映射与显示名

```python
DEVICE_TYPE_DISPLAY = {
    "huashu_arm": "华数机械臂",
    "luxshare_amr": "珞石AMR",
    "robot_dog": "四足机器狗",
}

def get_device_display_name(device_type: str) -> str:
    """获取设备类型的中文显示名，未知类型返回原始类型名"""
    return DEVICE_TYPE_DISPLAY.get(device_type, device_type)
```

> **扩展性**：新增设备类型只需在此字典中添加映射，无需修改其他代码。

---

## 六、异常容错与离线状态判定方案

### 6.1 设备离线判定逻辑

**判定规则**：设备最后上报时间距当前时间超过 **30秒** 即标记为 `offline`。

```python
OFFLINE_THRESHOLD_SECONDS = 30  # 离线判定阈值
```

**实现方式**：后台定时任务，每 **10秒** 执行一次离线扫描。

```python
async def check_device_offline():
    """
    定时任务：扫描所有 status='online' 的设备，
    若 last_report_time 超过阈值则标记为 offline。
    """
    while True:
        try:
            now = datetime.now()
            threshold = now - timedelta(seconds=OFFLINE_THRESHOLD_SECONDS)
            threshold_str = threshold.strftime("%Y-%m-%dT%H:%M:%S")
            
            conn = get_connection()
            conn.execute(
                "UPDATE devices SET status='offline', updated_at=datetime('now','localtime') "
                "WHERE status='online' AND last_report_time < ?",
                (threshold_str,)
            )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"离线检测任务异常: {e}")
        
        await asyncio.sleep(10)
```

### 6.2 全局异常容错矩阵

| 异常类型 | 发生点 | 容错处理 | 影响范围 |
|---------|--------|---------|---------|
| **MQTT 连接断开** | MQTT Client | 自动重连（指数退避1s→30s），记录日志 | MQTT 临时不可用，API 仍正常 |
| **MQTT 消息解析失败** | on_message | 记录 warning 日志，跳过该条消息 | 仅当条消息丢弃 |
| **JSON Payload 解码失败** | on_message | 将原始 bytes 存入 raw_payload，记录日志 | 数据仍入库，不丢弃 |
| **Topic 格式不合法** | parse_topic | 记录 warning 日志，跳过 | 仅当条消息 |
| **数据库写入失败** | INSERT/UPDATE | 捕获异常，记录 error 日志，不影响消息循环 | 当条数据未入库 |
| **数据库文件损坏** | 启动时检查 | `integrity_check` 失败则备份旧库+重建 | 历史数据需从备份恢复 |
| **数据库锁超时** | 并发写入 | WAL 模式 + busy_timeout=5000ms | 极端并发下短暂延迟 |
| **API 请求参数非法** | REST API | 返回 400 + 具体错误信息 | 仅当次请求 |
| **设备查询不存在** | REST API | 返回 404 + 提示信息 | 仅当次请求 |
| **前端请求超时** | 轮询 | 静默捕获，下次轮询自动重试 | 页面显示短暂无更新 |
| **EMQX 服务宕机** | 全局 | MQTT 客户端持续重连 + 日志告警 | 无新数据入库，API 仍可查历史 |
| **磁盘空间不足** | DB 写入 | 捕获 `OperationalError`，记录 CRITICAL 日志 | 新数据暂不入库 |
| **Uvicorn 崩溃** | 进程级 | systemd `Restart=always` 自动重启 | 短暂不可用（~2秒） |

### 6.3 MQTT 客户端重连策略

```python
def on_disconnect(client, userdata, rc):
    """断开连接回调：非正常断开时自动重连"""
    if rc != 0:
        logger.warning(f"MQTT 非正常断开 (rc={rc})，启动自动重连...")
        # paho-mqtt 内置重连：指数退避 1s ~ 30s
        client.reconnect_delay_set(min_delay=1, max_delay=30)
```

### 6.4 日志规范

```python
import logging

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FILE = "robot_iot.log"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler()  # 同时输出到控制台
    ]
)
```

| 日志级别 | 使用场景 |
|---------|---------|
| `DEBUG` | MQTT 原始消息内容、SQL 语句 |
| `INFO` | 设备上线/离线、系统启动/停止 |
| `WARNING` | Topic 格式异常、JSON 解析失败 |
| `ERROR` | 数据库写入失败、MQTT 连接失败 |
| `CRITICAL` | 磁盘空间不足、数据库损坏 |

---

## 七、前端页面架构设计

### 7.1 页面结构

```
static/index.html（单文件，免编译）
├── TailwindCSS CDN 引入
├── 页面头部：系统名称 + 统计概览卡片
├── 设备总览表格
│   ├── 设备ID、设备类型、在线状态（彩色标识）、最后上报时间
│   ├── 点击行展开 → 实时数据面板
│   └── 每 5 秒自动轮询 /api/devices
├── 实时数据面板
│   ├── JSON 格式化展示
│   ├── 核心字段高亮
│   └── 每 5 秒轮询 /api/devices/{type}/{id}/latest
├── 历史数据查询区域
│   ├── 设备选择器
│   ├── 查询条数输入
│   ├── 时间范围筛选
│   ├── 分页翻页器
│   └── 调用 /api/devices/{type}/{id}/history
└── 页面底部：系统信息 + 版本号
```

### 7.2 前端轮询机制

```javascript
// 核心轮询逻辑
const POLL_INTERVAL = 5000; // 5秒

async function pollDevices() {
    try {
        const response = await fetch('/api/devices');
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const result = await response.json();
        renderDeviceList(result.data.devices);
    } catch (error) {
        console.error('轮询设备列表失败:', error);
        // 静默处理，下次轮询自动重试，不崩溃页面
    }
}

setInterval(pollDevices, POLL_INTERVAL);
```

### 7.3 前端容错要求

| 场景 | 处理 |
|------|------|
| API 请求超时 | `catch` 捕获，静默跳过，下次轮询重试 |
| API 返回非 200 | 显示友好提示条（非弹窗），不阻塞页面 |
| 设备无数据 | 显示"暂无上报数据"占位提示 |
| JSON 渲染异常 | `try/catch` 保护，显示原始文本 |
| 网络完全断开 | 显示"网络连接异常"横幅，恢复后自动消失 |

---

## 八、部署架构

### 8.1 端口规划

| 服务 | 端口 | 协议 | 说明 |
|------|------|------|------|
| FastAPI (Uvicorn) | 8000 | HTTP | Web 页面 + REST API |
| EMQX MQTT | 1883 | TCP | 设备 MQTT 接入 |
| EMQX Dashboard | 18083 | HTTP | EMQX 管理后台（可选关闭） |

### 8.2 systemd 服务配置

```ini
# /etc/systemd/system/robot-iot.service
[Unit]
Description=Robot IoT Management System
After=network.target emqx.service
Wants=emqx.service

[Service]
Type=simple
User=robot
WorkingDirectory=/opt/robot-iot
ExecStart=/opt/robot-iot/venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=3
StandardOutput=append:/opt/robot-iot/robot_iot.log
StandardError=append:/opt/robot-iot/robot_iot.log

[Install]
WantedBy=multi-user.target
```

### 8.3 项目目录结构

```
/opt/robot-iot/
├── main.py               # FastAPI 服务 + MQTT 客户端集成
├── database.py            # SQLite 数据模型、初始化、CRUD 操作
├── requirements.txt       # Python 依赖清单
├── start.sh               # 一键启动脚本（含虚拟环境创建）
├── mock_robot.py           # 模拟设备上报测试脚本
├── static/
│   └── index.html          # 免编译完整前端页面
├── robot.db                # SQLite 数据库文件（运行时自动生成）
├── robot_iot.log           # 运行日志文件
├── venv/                   # Python 虚拟环境
└── README.md               # 部署与对接说明书
```

### 8.4 start.sh 一键启动脚本设计

```bash
#!/bin/bash
# 一键启动脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 创建虚拟环境（如不存在）
if [ ! -d "venv" ]; then
    echo "[INFO] 创建 Python 虚拟环境..."
    python3 -m venv venv
fi

# 2. 激活虚拟环境
source venv/bin/activate

# 3. 安装依赖
echo "[INFO] 安装 Python 依赖..."
pip install -r requirements.txt -q

# 4. 启动服务
echo "[INFO] 启动机器人物联网管理系统..."
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

---

## 九、EMQX 安全配置要点

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 匿名连接 | **关闭** | `allow_anonymous = false` |
| 内置认证 | **启用** | 使用内置数据库 username/password |
| ACL 策略 | 设备仅可发布 `robot/{type}/{id}/#` | 防止设备越权操作 |
| 服务端账号 | `robot_server` / 强密码 | 用于后端 MQTT 客户端 |
| 设备账号 | `device_{type}_{id}` / 独立密码 | 每台设备独立账号 |
| Dashboard 密码 | **重置默认密码** | 修改 admin/public 默认密码 |

---

## 十、关键验收对照表

| 合同验收条款 | 架构实现方案 | 验证方法 |
|-------------|-------------|---------|
| MQTT 多设备接入 | `robot/#` 通配订阅 + Topic 解析 | mock_robot.py 模拟3类设备 |
| 设备自动注册 | on_message → upsert devices 表 | 首次上报自动创建设备记录 |
| 设备离线检测 | 30秒超时 + 10秒扫描定时任务 | 停止模拟脚本后观察状态变化 |
| 数据持久化 | SQLite WAL + device_data 完整存储 | 重启服务后数据不丢失 |
| 延迟≤5秒 | 直接入库 + 前端5秒轮询 | 发送消息后观察页面更新 |
| 24小时稳定运行 | 全局异常捕获 + systemd Restart | 压力测试 + 长时间运行 |
| 分页查询 | LIMIT/OFFSET + 时间倒序索引 | API 分页参数测试 |
| 前端免编译 | 原生 JS + TailwindCSS CDN | 浏览器直接访问验证 |
| 开机自启 | systemd 服务 | reboot 后自动运行 |
| EMQX 安全 | 账号鉴权 + 关闭匿名 | 无密码连接应被拒绝 |

---

## 十一、甲方最新技术要求（6大功能模块与AI中枢）

根据《智能机器人管理系统技术要求.docx》最新要求，系统已全面升级并支持以下 6 大核心模块：

### 11.1 功能 1：设备数据采集与实时状态监控
- **全维度遥测采集**：实时采集位置坐标、运行状态、速度、负载、电压电流、电机温度、IMU姿态等。
- **I/O 信号状态矩阵**：支持数字量输入（DI 1~4）与数字量输出（DO 1~2）实时矩阵指示，精确反应限位、急停与执行机构状态。
- **设备类型与型号官方对齐**：
  - 华数 BR610 工业机器人 (`huashu_arm`)
  - AMR 移动复合机器人（珞石 SR3 机械臂 + 定制 AGV, `luxshare_amr`)
  - 四足机器狗复合巡检机器人（南沙接入, `robot_dog`)
  - 搜救协同无人机 (`uav_rescue`)

### 11.2 功能 2：设备健康管理与故障预警、远程运维
- **健康度动态评分**：基于故障码、电机温度与运行工况实时计算设备健康度评分（0~100分）。
- **预测性维护与保养提醒**：记录累计运行小时数（Running Hours），结合润滑与保养周期（如 500 小时阈值）输出下次维保倒计时。
- **异常状态与故障告警**：故障发生时记录错误码、告警详情及发生时间，高亮警示并入库。

### 11.3 功能 3：机器人调度管理系统
- **定点取放料调度 (`pick_and_place`)**：支持调度 AMR 与珞石 SR3 机械臂在指定工位之间完成物料抓取、转运与放置。
- **低电压智能自动回充 (`auto_charge`)**：当设备电量低于阈值或接收到回充指令时，自动导航至充电桩充电。
- **单台/多台楼层避障巡检 (`floor_patrol`)**：支持多机跨区域与楼层巡检调度，具备优先级分配与避障策略。

### 11.4 功能 4：运营数据分析与效率优化
- **综合设备利用率 (OEE %)**：实时统计全场机器人运行/作业时间占总在线时间的百分比。
- **任务完成率 (%)**：统计下发调度任务的成功履约比例。
- **工序瓶颈与故障频次统计**：按设备类型聚合故障分布，为排产与产能优化提供数据决策。

### 11.5 功能 5：商业监测全维度数据
- **空气质量与化学指标**：CO₂ (ppm)、PM2.5 (μg/m³)、甲醛 HCHO (mg/m³)、VOC (mg/m³)。
- **物理与声学环境**：现场环境噪声 (dB)、环境温湿度。
- **商业与安全感知**：可燃气体 (LEL %)、人体存在感知 (human_presence)、客流统计 (foot_traffic)。

### 11.6 功能 6：空地协同救援系统与云边大模型接口
- **云边协同 LLM 接口**：提供 `GET /api/ai/context` 标准化输出当前全域机器人与环境的 Prompt Context，云端或本地大模型（DeepSeek / GPT-4o / Claude / 本地开源 LLM）可零成本接入。
- **边缘 AI 智能运维中枢**：提供 `POST /api/ai/diagnose` 接口，一键输出健康等级、故障根因分析与处置建议。
- **空地救援链路扩展**：预留四足机器狗与搜救无人机协同链路标识，支持搜救场景下的地空联动。

