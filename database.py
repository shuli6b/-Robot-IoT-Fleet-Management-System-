"""
database.py - SQLite 数据模型与数据库管理模块
- 开启 WAL 模式防止高并发读写锁
- 包含数据库完整性检查与自动修复/备份
- 提供设备状态更新与历史数据写入/分页查询函数
- 全部函数覆盖 try/except 容错机制
"""

import os
import json
import sqlite3
import logging
import shutil
import hashlib
import re
import math
from security import password_hash, verify_password, validate_password, timestamp_age, allowed_device
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple

logger = logging.getLogger("database")

DB_PATH = os.getenv("DB_PATH", "robot.db")

DEVICE_TYPE_DISPLAY = {
    "huashu_arm": "华数BR610工业机械臂",
    "luxshare_amr": "珞石SR3+定制AGV复合机器人",
    "robot_dog": "南沙四足机器狗复合巡检机器人",
    "uav_rescue": "四足狗+无人机协同救援系统(规划)",
}


def get_device_display_name(device_type: str, db_path: str = DB_PATH) -> str:
    """获取设备类型的中文显示名，优先从 CMS 动态配置中获取"""
    try:
        cfg = get_site_config(db_path)
        if device_type in ["huashu_arm", "arm"]:
            return cfg.get("cat1_name") or "华数 BR610 六轴工业机械臂"
        elif device_type in ["luxshare_amr", "amr"]:
            return cfg.get("cat2_name") or "珞石 SR3 复合移动 AMR"
        elif device_type in ["robot_dog", "dog"]:
            return cfg.get("cat3_name") or "四足仿生巡检机器狗"
        elif device_type in ["uav_rescue", "collaborative_arm", "custom"]:
            return cfg.get("cat4_name") or "四足狗+无人机协同系统"
    except Exception:
        pass
    return DEVICE_TYPE_DISPLAY.get(device_type, device_type)


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """
    获取数据库连接并进行核心参数配置：
    - PRAGMA journal_mode=WAL: 允许读写并发，提升高频写入性能
    - PRAGMA busy_timeout=5000: 锁等待超时 5000ms，避免 database is locked
    - PRAGMA synchronous=NORMAL: 平衡写入性能与数据安全
    - PRAGMA foreign_keys=ON: 启用外键约束
    - row_factory = sqlite3.Row: 支持类似字典的列名访问
    """
    try:
        conn = sqlite3.connect(db_path, timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        return conn
    except Exception as e:
        logger.critical(f"数据库连接失败 ({db_path}): {e}", exc_info=True)
        raise


def init_db(db_path: str = DB_PATH) -> bool:
    """
    初始化数据库表结构与索引：
    - devices: 设备档案及在线状态表
    - device_data: 设备历史原始上报数据表
    - 自动创建高效查询索引
    """
    conn = get_connection(db_path)
    try:
        with conn:
            # 1. 创建 devices 设备表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS devices (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id        TEXT    NOT NULL,
                    device_type      TEXT    NOT NULL,
                    status           TEXT    NOT NULL DEFAULT 'offline',
                    last_report_time TEXT    DEFAULT NULL,
                    device_name      TEXT    DEFAULT '',
                    location         TEXT    DEFAULT '',
                    specs            TEXT    DEFAULT '{}',
                    notes            TEXT    DEFAULT '',
                    created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    UNIQUE(device_id, device_type)
                )
                """
            )
            # 动态补齐 devices 表扩展列（若已存在旧表）
            for col_name, col_def in [
                ("device_name", "TEXT DEFAULT ''"),
                ("location", "TEXT DEFAULT ''"),
                ("vendor", "TEXT DEFAULT ''"),
                ("specs", "TEXT DEFAULT '{}'"),
                ("notes", "TEXT DEFAULT ''"),
                ("is_simulated", "INTEGER DEFAULT 0"),
                ("simulation_enabled", "INTEGER NOT NULL DEFAULT 1"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE devices ADD COLUMN {col_name} {col_def}")
                except Exception:
                    pass

            # 设备表索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_status ON devices(status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_devices_type ON devices(device_type)")

            # 2. 创建 device_data 历史数据表
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_data (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id        TEXT    NOT NULL,
                    device_type      TEXT    NOT NULL,
                    data_type        TEXT    NOT NULL,
                    raw_payload      TEXT    NOT NULL,
                    topic            TEXT    NOT NULL,
                    received_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    FOREIGN KEY (device_id, device_type) REFERENCES devices(device_id, device_type)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_data_device_time ON device_data(device_id, device_type, received_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_data_devid_time ON device_data(device_id, received_at DESC);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_data_dev_type_datatype ON device_data(device_type, device_id, data_type, received_at DESC, id DESC)")
            # 3. 创建与技术需求书 1.6 完全兼容的视图/别名 device_info
            conn.execute(
                """
                CREATE VIEW IF NOT EXISTS device_info AS 
                SELECT 
                    device_id AS id, 
                    device_type AS dev_type, 
                    (CASE WHEN status='online' THEN 1 ELSE 0 END) AS online, 
                    last_report_time AS last_report
                FROM devices
                """
            )

            # 4. 创建系统参数配置表 (用于持久化云端/本地大模型 API 配置等)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_config (
                    config_key   TEXT PRIMARY KEY,
                    config_value TEXT NOT NULL,
                    updated_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )

            # 5. 创建用户权限管理表 (用于双角色管理员/普通用户认证体系，支持普通用户注册审核)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    NOT NULL UNIQUE,
                    password_hash TEXT    NOT NULL,
                    role          TEXT    NOT NULL DEFAULT 'user',
                    real_name     TEXT    DEFAULT '',
                    status        TEXT    NOT NULL DEFAULT 'approved',
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    last_login    TEXT    DEFAULT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
            try:
                conn.execute("ALTER TABLE users ADD COLUMN status TEXT DEFAULT 'approved'")
            except Exception:
                pass

            # 6. 创建机器人加工程序表 (robot_programs)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS robot_programs (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id    TEXT    NOT NULL,
                    device_type  TEXT    NOT NULL,
                    prog_name    TEXT    NOT NULL,
                    prog_content TEXT    NOT NULL,
                    file_size    INTEGER DEFAULT 0,
                    is_active    INTEGER DEFAULT 0,
                    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    UNIQUE(device_id, prog_name)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_programs_dev ON robot_programs(device_id)")

            # 7. 创建机器人说明书标准故障知识库 (alarm_knowledge_base)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alarm_knowledge_base (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    code        TEXT    NOT NULL UNIQUE,
                    title       TEXT    NOT NULL,
                    category    TEXT    DEFAULT '通用故障',
                    description TEXT    NOT NULL,
                    cause       TEXT    NOT NULL,
                    solution    TEXT    NOT NULL,
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )

            # 8. 创建用户报警处理历史记录表 (alarm_resolutions)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alarm_resolutions (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id   TEXT    NOT NULL,
                    device_type TEXT    NOT NULL,
                    alarm_code  TEXT    NOT NULL,
                    alarm_msg   TEXT    NOT NULL,
                    solution    TEXT    NOT NULL,
                    handler     TEXT    NOT NULL,
                    notes       TEXT    DEFAULT '',
                    resolved_at TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_alarm_resolutions_dev ON alarm_resolutions(device_id, resolved_at DESC)")

            # 9. 创建机器人实时 I/O 状态表 (device_io_status)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_io_status (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id   TEXT    NOT NULL UNIQUE,
                    device_type TEXT    NOT NULL,
                    di_mask     INTEGER DEFAULT 0,
                    do_mask     INTEGER DEFAULT 0,
                    di_details  TEXT    DEFAULT '{}',
                    do_details  TEXT    DEFAULT '{}',
                    updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )

            # 10. 创建机器人示教器规范级原生运行日志表 (device_run_logs)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS device_run_logs (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id      TEXT    NOT NULL,
                    seq_no         INTEGER NOT NULL,
                    icon_type      TEXT    NOT NULL DEFAULT 'action',
                    log_time       TEXT    NOT NULL,
                    operator       TEXT    NOT NULL DEFAULT 'Normal',
                    log_level      TEXT    NOT NULL DEFAULT 'INFO',
                    record_content TEXT    NOT NULL,
                    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_run_logs_dev_seq ON device_run_logs(device_id, seq_no DESC)")

            # Accounts are provisioned explicitly. Never generate sample production data.
            for table, column, definition in [
                ("users", "must_change_password", "INTEGER NOT NULL DEFAULT 0"),
                ("robot_programs", "source", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
                ("alarm_knowledge_base", "verified", "INTEGER NOT NULL DEFAULT 0"),
                ("alarm_knowledge_base", "reference", "TEXT NOT NULL DEFAULT ''"),
                ("device_data", "source", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
                ("device_run_logs", "source", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
                ("device_run_logs", "event_id", "TEXT"),
                ("alarm_resolutions", "source", "TEXT NOT NULL DEFAULT 'legacy_unverified'"),
            ]:
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if column not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
            conn.execute("CREATE TABLE IF NOT EXISTS auth_sessions (token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_session_user ON auth_sessions(username)")
            conn.execute("""CREATE TABLE IF NOT EXISTS command_requests (
                task_id TEXT PRIMARY KEY, device_id TEXT NOT NULL, device_type TEXT NOT NULL,
                command TEXT NOT NULL, params TEXT NOT NULL, operator TEXT NOT NULL,
                state TEXT NOT NULL, message TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
                expires_at REAL NOT NULL, updated_at TEXT NOT NULL, controller_code TEXT,
                connection_id TEXT, result TEXT)""")
            command_columns={row[1] for row in conn.execute('PRAGMA table_info(command_requests)')}
            if 'source' not in command_columns:
                conn.execute("ALTER TABLE command_requests ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy_unverified'")
                conn.execute("UPDATE command_requests SET source='simulation' WHERE device_id IN (SELECT device_id FROM devices WHERE is_simulated=1)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_command_device_time ON command_requests(device_id, created_at DESC)")
            conn.execute("""CREATE TABLE IF NOT EXISTS message_receipts (
                message_id TEXT PRIMARY KEY, received_at TEXT NOT NULL)""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_receipt_time ON message_receipts(received_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_data_time ON device_data(source,data_type,received_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_verified_device_time ON device_data(device_id,device_type,source,data_type,received_at DESC,id DESC)")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_log_event ON device_run_logs(event_id) WHERE event_id IS NOT NULL")
            # Existing rows stay intact but are excluded from verified production queries.
            for row in conn.execute("SELECT username,password_hash FROM users").fetchall():
                if row['password_hash'] in {hashlib.sha256(p.encode()).hexdigest() for p in ('admin888','123456','guest123')}:
                    conn.execute("UPDATE users SET must_change_password=1 WHERE username=?", (row['username'],))
            conn.execute("UPDATE devices SET status='offline' WHERE is_simulated=1")
            conn.execute("CREATE VIEW IF NOT EXISTS verified_device_data AS SELECT * FROM device_data WHERE source='controller'")
            from alarm_catalog import install_catalog
            install_catalog(conn)


        logger.info("数据库表结构与索引初始化成功")
        return True
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        return False
    finally:
        conn.close()


def check_db_integrity(db_path: str = DB_PATH) -> bool:
    """Never replace a damaged database with an empty one."""
    conn = get_connection(db_path)
    try:
        return conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def upsert_device(
    device_id: str,
    device_type: str,
    last_report_time: Optional[str] = None,
    status: str = "online",
    db_path: str = DB_PATH,
) -> bool:
    """
    插入或更新设备记录：
    - 新设备：插入档案，默认 online
    - 已有设备：更新 status='online'、last_report_time、updated_at
    """
    if not device_id or not device_type:
        logger.warning("upsert_device 参数无效: device_id 或 device_type 为空")
        return False

    report_time = last_report_time or datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    sql = """
        INSERT INTO devices (device_id, device_type, status, last_report_time, created_at, updated_at)
        VALUES (?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'))
        ON CONFLICT(device_id, device_type) DO UPDATE SET
            status = excluded.status,
            last_report_time = excluded.last_report_time,
            updated_at = datetime('now','localtime')
    """
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(sql, (device_id, device_type, status, report_time))
        return True
    except Exception as e:
        logger.error(f"upsert_device 写入异常 [{device_type}/{device_id}]: {e}")
        return False
    finally:
        conn.close()


def insert_device_data(device_id, device_type, data_type, raw_payload, topic, db_path=DB_PATH, source='legacy_unverified'):
    """Only authenticated state telemetry advances liveness; commands never do."""
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        raise ValueError('Payload must be an object')
    now = datetime.now().isoformat(timespec='seconds')
    conn = get_connection(db_path)
    try:
        with conn:
            if source in ('controller','simulation'):
                message_id = payload.get('message_id')
                if not message_id:
                    raise ValueError('Missing message identity')
                existing = conn.execute('SELECT 1 FROM message_receipts WHERE message_id=?', (message_id,)).fetchone()
                if existing:
                    return None
                conn.execute('INSERT INTO message_receipts VALUES(?,?)', (message_id, now))
            conn.execute("INSERT OR IGNORE INTO devices(device_id,device_type,status) VALUES(?,?,'offline')", (device_id,device_type))
            cur = conn.execute('INSERT INTO device_data(device_id,device_type,data_type,raw_payload,topic,received_at,source) VALUES(?,?,?,?,?,?,?)',
                               (device_id,device_type,data_type,raw_payload,topic,now,source))
            if source in ('controller','simulation') and data_type == 'state':
                state = 'offline' if payload.get('status') == 'offline' else 'online'
                conn.execute('UPDATE devices SET status=?,last_report_time=?,updated_at=? WHERE device_id=? AND device_type=?',
                             (state,now,now,device_id,device_type))
            return cur.lastrowid
    finally:
        conn.close()


def get_all_devices(status=None, device_type=None, db_path=DB_PATH,include_simulated=True):
    conn = get_connection(db_path)
    try:
        rows = conn.execute('SELECT * FROM devices WHERE is_simulated=0 OR simulation_enabled=1 ORDER BY id').fetchall()
    finally:
        conn.close()
    result = []
    for row in rows:
        dev = dict(row)
        if (dev['is_simulated'] and not include_simulated) or (not dev['is_simulated'] and not allowed_device(dev['device_type'],dev['device_id'])) or (device_type and dev['device_type'] != device_type):
            continue
        dev['device_type_display'] = get_device_display_name(dev['device_type'],db_path)
        dev['device_name'] = dev.get('device_name') or dev['device_id']
        dev['location'] = dev.get('location') or '未配置'
        try:
            dev['specs'] = json.loads(dev.get('specs') or '{}')
        except ValueError:
            dev['specs'] = {}
        latest = get_latest_data(dev['device_type'],dev['device_id'],db_path)
        p = latest['parsed_payload'] if latest else {}
        fresh = bool(latest and p.get('state_fresh'))
        dev['status'] = 'online' if fresh and p.get('status') != 'offline' else 'offline'
        if status and dev['status'] != status:
            continue
        for key in ('battery','enabled','emergency_stop','error_code','error_msg','error_count','joint_angles','cartesian_pos','is_mains_powered','power_source'):
            dev[key] = p.get(key)
        pos = p.get('cartesian_pos') or {}
        for axis in ('x','y','z'):
            dev['cartesian_'+axis] = pos.get(axis)
        dev['latest_state'] = {'parsed_payload':p,'raw_payload':latest['raw_payload'] if latest else None}
        dev['source'] = 'simulation' if dev['is_simulated'] else ('controller' if fresh else 'no_current_data')
        dev['real_report_count'] = None
        io_ok=p.get('quality',{}).get('io',{}).get('fresh') and fresh
        dev['io_summary']=(f"已采样 DI {p.get('di_count',0)}/{p.get('di_total_count','--')}，DO {p.get('do_count',0)}/{p.get('do_total_count','--')}" if io_ok and isinstance(p.get('di'),int) and isinstance(p.get('do'),int) else '无有效I/O上报')
        result.append(dev)
    return result


def get_device(device_type, device_id, db_path=DB_PATH):
    return next((d for d in get_all_devices(device_type=device_type,db_path=db_path) if d['device_id']==device_id),None)


def get_device_by_id(dev_id, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        rows=conn.execute('SELECT * FROM devices WHERE device_id=?',(dev_id,)).fetchall()
        if len(rows)!=1:
            return None
        d=dict(rows[0])
        try:
            d['specs']=json.loads(d.get('specs') or '{}')
        except ValueError:
            d['specs']={}
        return d
    finally:
        conn.close()


def update_device_info(
    device_id: str,
    device_type: Optional[str] = None,
    device_name: Optional[str] = None,
    location: Optional[str] = None,
    vendor: Optional[str] = None,
    specs: Optional[Any] = None,
    notes: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """更新单台设备自定义名称、厂商角标、归属基地、规格参数字典及管理员备注"""
    conn = get_connection(db_path)
    try:
        fields = ["updated_at = datetime('now','localtime')"]
        params: List[Any] = []
        if device_name is not None:
            fields.append("device_name = ?")
            params.append(device_name)
        if location is not None:
            fields.append("location = ?")
            params.append(location)
        if vendor is not None:
            fields.append("vendor = ?")
            params.append(vendor)
        if specs is not None:
            fields.append("specs = ?")
            params.append(json.dumps(specs, ensure_ascii=False) if not isinstance(specs, str) else specs)
        if notes is not None:
            fields.append("notes = ?")
            params.append(notes)

        where = "WHERE device_id = ?"
        params.append(device_id)
        if device_type:
            where += " AND device_type = ?"
            params.append(device_type)

        sql = f"UPDATE devices SET {', '.join(fields)} {where}"
        with conn:
            conn.execute(sql, params)
        return True
    except Exception as e:
        logger.error(f"update_device_info 写入异常 [{device_id}]: {e}")
        return False
    finally:
        conn.close()


def get_history_by_dev_id(device_id,page=1,page_size=20,db_path=DB_PATH):
    dev=get_device_by_id(device_id,db_path)
    if not dev:
        return []
    return get_device_history(dev['device_type'],device_id,page=page,page_size=page_size,db_path=db_path)


def get_latest_data(device_type, device_id, db_path=DB_PATH):
    conn = get_connection(db_path)
    samples = {}
    dev=get_device_by_id(device_id,db_path)
    data_source='simulation' if dev and dev.get('is_simulated') else 'controller'
    try:
        for kind in ('state','sensor','io'):
            row = conn.execute("SELECT * FROM device_data WHERE device_type=? AND device_id=? AND data_type=? AND source=? ORDER BY received_at DESC,id DESC LIMIT 1",(device_type,device_id,kind,data_source)).fetchone()
            if row:
                samples[kind] = dict(row)
    finally:
        conn.close()
    state = samples.get('state')
    if not state:
        return None
    merged = {}
    quality = {}
    threshold = int(os.getenv('OFFLINE_THRESHOLD','30'))
    for kind in ('sensor','io','state'):
        row = samples.get(kind)
        if not row:
            quality[kind] = {'fresh':False,'received_at':None}
            continue
        p = json.loads(row['raw_payload'])
        fresh = 0 <= timestamp_age(row['received_at']) <= threshold and -5 <= timestamp_age(p.get('timestamp')) <= threshold
        quality[kind] = {'fresh':fresh,'received_at':row['received_at'],'sampled_at':p.get('timestamp')}
        if fresh:
            merged.update({k:v for k,v in p.items() if k not in ('signature','message_id')})
    state_p = json.loads(state['raw_payload'])
    merged['state_fresh'] = quality.get('state',{}).get('fresh',False)
    if not merged['state_fresh']:
        merged = {'status':'offline','state_fresh':False}
    elif state_p.get('status') == 'offline':
        merged = {'status':'offline','state_fresh':True,'timestamp':state_p.get('timestamp')}
    merged['quality'] = quality
    merged['source'] = data_source
    merged['is_simulated'] = data_source=='simulation'
    state['parsed_payload'] = merged
    return state


def get_device_history(
    device_type: str,
    device_id: str,
    page: int = 1,
    page_size: int = 20,
    data_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    分页查询指定设备的历史数据，按时间倒序排列。
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        dev=get_device_by_id(device_id,db_path)
        source="simulation" if dev and dev.get("is_simulated") else "controller"
        query = "SELECT * FROM device_data WHERE source=? AND device_type = ? AND device_id = ?"
        params: List[Any] = [source,device_type, device_id]

        if data_type:
            query += " AND data_type = ?"
            params.append(data_type)
        if start_time:
            query += " AND received_at >= ?"
            params.append(start_time)
        if end_time:
            query += " AND received_at <= ?"
            params.append(end_time)

        query += " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_device_history 查询异常 [{device_type}/{device_id}]: {e}")
        return []
    finally:
        conn.close()


def get_history_count(
    device_type: str,
    device_id: str,
    data_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """
    查询符合筛选条件的历史数据总条数。
    """
    conn = get_connection(db_path)
    try:
        dev=get_device_by_id(device_id,db_path)
        source="simulation" if dev and dev.get("is_simulated") else "controller"
        query = "SELECT COUNT(*) FROM device_data WHERE source=? AND device_type = ? AND device_id = ?"
        params: List[Any] = [source,device_type, device_id]

        if data_type:
            query += " AND data_type = ?"
            params.append(data_type)
        if start_time:
            query += " AND received_at >= ?"
            params.append(start_time)
        if end_time:
            query += " AND received_at <= ?"
            params.append(end_time)

        cursor = conn.execute(query, params)
        total = cursor.fetchone()[0]
        return total
    except Exception as e:
        logger.error(f"get_history_count 查询异常 [{device_type}/{device_id}]: {e}")
        return 0
    finally:
        conn.close()


def get_global_history(
    device_id: Optional[str] = None,
    data_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    全域分页查询历史遥测数据（支持按设备、报文类型、时间范围多维过滤）。
    """
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    offset = (page - 1) * page_size

    conn = get_connection(db_path)
    try:
        dev=get_device_by_id(device_id,db_path) if device_id else None
        source="simulation" if dev and dev.get("is_simulated") else "controller"
        query = "SELECT * FROM device_data WHERE source IN (?,?)"
        params: List[Any] = [source,source if device_id else "simulation"]

        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)
        if data_type:
            query += " AND data_type = ?"
            params.append(data_type)
        if start_time:
            query += " AND received_at >= ?"
            params.append(start_time)
        if end_time:
            query += " AND received_at <= ?"
            params.append(end_time)

        query += " ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?"
        params.extend([page_size, offset])

        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_global_history 查询异常: {e}")
        return []
    finally:
        conn.close()


def get_global_history_count(
    device_id: Optional[str] = None,
    data_type: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    db_path: str = DB_PATH,
) -> int:
    """
    查询全域符合条件的历史遥测数据总条数。
    """
    conn = get_connection(db_path)
    try:
        dev=get_device_by_id(device_id,db_path) if device_id else None
        source="simulation" if dev and dev.get("is_simulated") else "controller"
        query = "SELECT COUNT(*) FROM device_data WHERE source IN (?,?)"
        params: List[Any] = [source,source if device_id else "simulation"]

        if device_id:
            query += " AND device_id = ?"
            params.append(device_id)
        if data_type:
            query += " AND data_type = ?"
            params.append(data_type)
        if start_time:
            query += " AND received_at >= ?"
            params.append(start_time)
        if end_time:
            query += " AND received_at <= ?"
            params.append(end_time)

        cursor = conn.execute(query, params)
        return cursor.fetchone()[0]
    except Exception as e:
        logger.error(f"get_global_history_count 查询异常: {e}")
        return 0
    finally:
        conn.close()



def mark_offline_devices(threshold_seconds=30, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        with conn:
            cur=conn.execute("UPDATE devices SET status='offline' WHERE status='online' AND (last_report_time IS NULL OR julianday(last_report_time)<julianday('now','localtime')-?/86400.0)",(threshold_seconds,))
        return cur.rowcount
    finally:
        conn.close()


def get_system_stats(db_path=DB_PATH):
    devices=get_all_devices(db_path=db_path)
    simulations=[d for d in devices if d['is_simulated']]
    types={}
    for d in devices:
        item=types.setdefault(d['device_type'],{'device_type':d['device_type'],'display':d['device_type_display'],'count':0,'online':0})
        item['count']+=1;item['online']+=int(d['status']=='online')
    conn=get_connection(db_path)
    try:
        count=conn.execute("SELECT COUNT(*) FROM device_data WHERE source IN ('controller','simulation')").fetchone()[0]
    finally:conn.close()
    online=sum(d['status']=='online' for d in devices)
    return {'total_devices':len(devices),'online_devices':online,'offline_devices':len(devices)-online,
        'online_rate_pct':round(online/len(devices)*100,1) if devices else 0,
        'total_records':count,'device_type_stats':list(types.values()),'source':'registered_fleet_total',
        'real_devices':len(devices)-len(simulations),'simulated_devices':len(simulations),
        'simulated_online':sum(d['status']=='online' for d in simulations)}


def get_operational_analytics(db_path=DB_PATH):
    devices=get_all_devices(db_path=db_path,include_simulated=False)
    env={key:None for key in ('co2_ppm','pm25','hcho_mg','voc_mg','noise_db','human_presence','foot_traffic_total')}
    env['air_quality_level']='未评估'
    health=[]
    for d in devices:
        p=d.get('latest_state',{}).get('parsed_payload',{})
        for src,dest in [('co2_ppm','co2_ppm'),('pm25','pm25'),('hcho','hcho_mg'),('voc','voc_mg'),('noise_db','noise_db'),('foot_traffic','foot_traffic_total')]:
            if p.get(src) is not None:
                env[dest]=p[src]
        health.append({'device_id':d['device_id'],'device_type':d['device_type'],'display_name':d['device_type_display'],
            'status':d['status'],'health_score':None,'error_code':p.get('error_code'),'error_count':p.get('error_count'),
            'running_hours':None,'next_maintenance_hours':None,'maintenance_status':'未接入维保计量'})
    conn=get_connection(db_path)
    try:
        states={r[0]:r[1] for r in conn.execute("SELECT c.state,COUNT(*) FROM command_requests c JOIN devices d ON d.device_id=c.device_id AND d.device_type=c.device_type WHERE c.source='controller' GROUP BY c.state")}
        alarms=conn.execute("SELECT COUNT(*) FROM verified_device_data WHERE data_type='alarm'").fetchone()[0]
    finally:
        conn.close()
    finished=states.get('succeeded',0)+states.get('failed',0)
    return {'utilization_rate_pct':None,'task_completion_rate_pct':round(states.get('succeeded',0)/finished*100,1) if finished else None,
        'completion_basis':'已终结控制指令的验证成功率，不等同生产任务完成率',
        'total_cmd_dispatched':sum(states.values()),'total_fault_count':alarms,'commercial_environment':env,'device_health_diagnostics':health}


def get_ai_llm_context(db_path=DB_PATH):
    overview=get_system_stats(db_path)
    analytics=get_operational_analytics(db_path)
    return {'system_status':overview,'operational_analytics':analytics,
        'llm_prompt_context':json.dumps({'overview':overview,'observations':analytics,'data_policy':'设备总量和在线率包含已登记仿真；诊断遥测仅真机。null=未知；离线不等于正常；禁止补造事实或生成可执行控制命令'},ensure_ascii=False),
        'recommended_actions':[]}


def get_system_config(key: str, default: Optional[str] = None, db_path: str = DB_PATH) -> Optional[str]:
    """获取系统配置项"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT config_value FROM system_config WHERE config_key = ?", (key,))
        row = cursor.fetchone()
        if row:
            return row["config_value"]
        return default
    except Exception as e:
        logger.error(f"get_system_config 异常 [{key}]: {e}")
        return default
    finally:
        conn.close()


def set_system_config(key: str, value: str, db_path: str = DB_PATH) -> bool:
    """设置或更新系统配置项"""
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO system_config (config_key, config_value, updated_at)
                VALUES (?, ?, datetime('now','localtime'))
                ON CONFLICT(config_key) DO UPDATE SET
                    config_value = excluded.config_value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value)),
            )
        return True
    except Exception as e:
        logger.error(f"set_system_config 异常 [{key}]: {e}")
        return False
    finally:
        conn.close()


# 大模型厂商平台渠道预设（支持用户自定义填入任意最新发布的模型，永不落后）
LLM_PROVIDER_PRESETS = {
    "google": {
        "name": "Google AI Studio 平台 (Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "default_model": "gemini-2.0-flash",
        "api_key_url": "https://aistudio.google.com/app/apikey",
        "doc": "Google 官方开放平台，支持最新 Gemini 系列模型"
    },
    "deepseek": {
        "name": "DeepSeek 深度求索官方平台",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "api_key_url": "https://platform.deepseek.com/",
        "doc": "DeepSeek 官方 API，支持 V3/R1/最新演进模型"
    },
    "openai": {
        "name": "OpenAI 官方平台 (ChatGPT)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
        "api_key_url": "https://platform.openai.com/api-keys",
        "doc": "OpenAI 官方 API，支持 GPT-4o/o3/最新演进模型"
    },
    "qwen": {
        "name": "阿里云百炼 / 通义千问平台",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
        "api_key_url": "https://bailian.console.aliyun.com/",
        "doc": "阿里百炼大模型服务，支持 Qwen/QwQ 全系列"
    },
    "zhipu": {
        "name": "智谱 AI 开放平台 (GLM)",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-plus",
        "api_key_url": "https://open.bigmodel.cn/",
        "doc": "智谱清言大模型开放平台，支持 GLM 全系列"
    },
    "moonshot": {
        "name": "月之暗面 Kimi 平台 (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-32k",
        "api_key_url": "https://platform.moonshot.cn/",
        "doc": "Kimi 开放平台，支持超长上下文文本解析"
    },
    "siliconflow": {
        "name": "硅基流动 SiliconFlow 聚合平台",
        "base_url": "https://api.siliconflow.cn/v1",
        "default_model": "deepseek-ai/DeepSeek-V3",
        "api_key_url": "https://cloud.siliconflow.cn/",
        "doc": "高速大模型托管与推理加速平台"
    },
    "baidu": {
        "name": "百度智能云千帆 / 文心一言平台",
        "base_url": "https://qianfan.baidubce.com/v2",
        "default_model": "ernie-4.0-8k-latest",
        "api_key_url": "https://cloud.baidu.com/product/wenxinworkshop",
        "doc": "百度文心大模型系列"
    },
    "tencent": {
        "name": "腾讯混元大模型开放平台",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "default_model": "hunyuan-standard",
        "api_key_url": "https://cloud.tencent.com/product/hunyuan",
        "doc": "腾讯混元工业与多模态大模型"
    },
    "minimax": {
        "name": "MiniMax 稀宇科技开放平台",
        "base_url": "https://api.minimax.chat/v1",
        "default_model": "abab6.5s-chat",
        "api_key_url": "https://platform.minimaxi.com/",
        "doc": "MiniMax 高性能大语言模型"
    },
    "stepfun": {
        "name": "阶跃星辰 StepFun 开放平台",
        "base_url": "https://api.stepfun.com/v1",
        "default_model": "step-1-8k",
        "api_key_url": "https://platform.stepfun.com/",
        "doc": "阶跃星辰大模型系列"
    },
    "ollama": {
        "name": "本地私有化部署平台 (Ollama / vLLM / LocalAI)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "deepseek-r1:8b",
        "api_key_url": "https://ollama.com/",
        "doc": "本地工控机/私有服务器离线运行，免 API Key"
    },
    "custom": {
        "name": "🔧 自定义 OpenAI 兼容接口 / 本地私有化网关",
        "base_url": "http://localhost:8000/v1",
        "default_model": "custom-model",
        "api_key_url": "",
        "doc": "支持 OneAPI、FastChat、自建私有模型、聚合网关等自由填入"
    }
}


def get_llm_config(db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取大模型综合配置（若未配置则加载安全默认值）"""
    raw_cfg = get_system_config("llm_api_config", default=None, db_path=db_path)
    default_config = {
        "provider": "deepseek",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "enabled": False,
        "temperature": 0.3,
        "max_tokens": 2048,
        "custom_prompt": "你是由广州昕邦智能与广州擎天智联合研发的工业机器人智能管控大模型运维专家。请基于实时工业边缘遥测、环境监测与健康指标，给出专业、严谨且可落地的诊断与排产优化建议。"
    }

    if raw_cfg:
        try:
            saved = json.loads(raw_cfg)
            if isinstance(saved, dict):
                default_config.update(saved)
        except Exception:
            pass

    return default_config


def save_llm_config(config: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    """持久化保存大模型配置"""
    try:
        current = get_llm_config(db_path)
        current.update(config)
        return set_system_config("llm_api_config", json.dumps(current, ensure_ascii=False), db_path=db_path)
    except Exception as e:
        logger.error(f"save_llm_config 异常: {e}")
        return False


def get_huashu_bridge_config(db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取华数机械臂硬件连接与边缘网关配置"""
    raw_cfg = get_system_config("huashu_bridge_config", default=None, db_path=db_path)
    default_config = {
        "robot_ip": "192.168.1.169",
        "robot_port": 23333,
        "device_id": "arm_001",
        "device_name": "华数BR610六轴工业机械臂",
        "interval_sec": 1.0,
        "enabled": True,
        "group_id": 0
    }
    if raw_cfg:
        try:
            saved = json.loads(raw_cfg)
            if isinstance(saved, dict):
                default_config.update(saved)
        except Exception:
            pass
    return default_config


def save_huashu_bridge_config(config: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    """保存华数机械臂硬件连接与边缘网关配置"""
    try:
        current = get_huashu_bridge_config(db_path)
        current.update(config)
        return set_system_config("huashu_bridge_config", json.dumps(current, ensure_ascii=False), db_path=db_path)
    except Exception as e:
        logger.error(f"save_huashu_bridge_config 异常: {e}")
        return False


def get_site_config(db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取站点品牌与基地/设备图文自定义配置 (支持CMS实时热更新)"""
    raw_cfg = get_system_config("site_branding_config", default=None, db_path=db_path)
    default_config = {
        "system_title": "昕邦智能 · 多品类异构机器人智能管控平台",
        "system_subtitle": "NEWBOND Robot AIoT PLATFORM",
        "company_name": "昕邦智能/NEWBOND",
        "footer_text": "© 2026 昕邦智能/NEWBOND · 机器人物联网管控平台 (广州番禺 · 广州南沙)",
        "site_footer_text": "© 2026 昕邦智能/NEWBOND · 机器人物联网管控平台 (广州番禺 · 广州南沙)",
        "modal_twin_footer_badge": "广州番禺运营中心 · 昕邦工业机器人数字孪生接入点",
        
        # 基地 1: 广州番禺运营中心
        "panyu_title": "广州番禺运营中心",
        "panyu_sub": "具身智能机器人应用展示",
        "panyu_line1_label": "主产线",
        "panyu_line1_val": "云 - 边 - 端协同的具身智能训练与作业平台",
        "panyu_line2_label": "设备规模",
        "panyu_line2_val": "20+台工业机器人、协作机器人、AMR移动机器人、工业轮式人形机器人规划",
        "panyu_status": "正常运行",
        "panyu_desc": "广州番禺运营中心专注于具身智能训练平台推广，平台覆盖从数据采集、仿真训练、实机迁移到多机协同作业的完整流程。核心团队拥有近20年的智能机器人行业经验，在推广具身智能训练平台的同时，致力于推动AI+机器人在工业、商业项目落地。",
        "panyu_img": "/static/assets/custom_1788160060_dd68dd.png",
        
        # 基地 2: 广州南沙研发中心
        "nansha_title": "广州南沙研发中心",
        "nansha_sub": "空地作业机器人编队",
        "nansha_line1_label": "核心装备",
        "nansha_line1_val": "空地作业系统平台",
        "nansha_line2_label": "设备规模",
        "nansha_line2_val": "20+ “机器狗+无人机”复合机器人、“机器狗+机械臂”复合机器人",
        "nansha_status": "正常运行",
        "nansha_desc": "广州南沙研发中心专注于空地作业平台开发，包括机器人软硬件及控制算法，底层运动控制小脑开发、上层VLA大模型。致力于推广空地平台复合机器人在电力、矿山、森林等场景的危险作业、高空作业。",
        "nansha_img": "/static/assets/base_nansha.jpg",
        
        # 4 大品类机器人档案与健康指标配置
        "cat1_key": "huashu_arm",
        "cat1_name": "工业机器人、协作机器人",
        "cat1_health_sub": "伺服电机负载与温升",
        "cat1_vendor": "华数机器人",
        "cat1_specs": "负载 10kg | 工作半径 1450mm | 重复定位精度 ±0.03mm | 防护等级 IP65",
        "cat1_img": "/static/assets/custom_1787208898_2a7c1f.png",
        "robot_arm_name": "工业机器人、协作机器人",
        "robot_arm_img": "/static/assets/custom_1787208898_2a7c1f.png",
        
        "cat2_key": "luxshare_amr",
        "cat2_name": "复合移动机器人AMR",
        "cat2_health_sub": "电池健康度与定位精度",
        "cat2_vendor": "珞石智能",
        "cat2_specs": "底盘载重 200kg | 激光SLAM导航 | 最大航速 1.5m/s | 续航 8h",
        "cat2_img": "/static/assets/custom_1787209622_b4b14f.png",
        "robot_amr_name": "复合移动机器人AMR",
        "robot_amr_img": "/static/assets/custom_1787209622_b4b14f.png",
        
        "cat3_key": "robot_dog",
        "cat3_name": "四足仿生机器狗",
        "cat3_health_sub": "关节扭矩与红外测温模组",
        "cat3_vendor": "仿生机器人",
        "cat3_specs": "12 自由度高扭矩 | 越障能力 25cm/35° | 双光热成像吊舱 | IP67 全天候",
        "cat3_img": "/static/assets/custom_1787209238_0e59b9.png",
        "robot_dog_name": "四足仿生机器狗",
        "robot_dog_img": "/static/assets/custom_1787209238_0e59b9.png",
        
        "cat4_key": "uav_rescue",
        "cat4_name": "四足狗+无人机协同系统",
        "cat4_health_sub": "空地协同遥感与应急通讯链路",
        "cat4_vendor": "昕邦智能联合研制",
        "cat4_specs": "多机编队协同 | 5G专网自组网 | 实时多源传感融合 | 边缘AI智能识别",
        "cat4_img": "/static/assets/huashu_br610_arm.jpg",
        "robot_collab_name": "四足狗+无人机协同系统",
        "robot_collab_img": "/static/assets/huashu_br610_arm.jpg"
    }
    if raw_cfg:
        try:
            saved = json.loads(raw_cfg)
            if isinstance(saved, dict):
                default_config.update(saved)
        except Exception:
            pass
    
    # 保证 footer_text 与 site_footer_text 双向同步
    footer_val = default_config.get("site_footer_text") or default_config.get("footer_text")
    if footer_val:
        default_config["footer_text"] = footer_val
        default_config["site_footer_text"] = footer_val

    return default_config


def save_site_config(config: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    """保存站点品牌与图文自定义配置 (仅超级管理员可操作)"""
    try:
        current = get_site_config(db_path)
        # 同步别名字段
        footer_val = config.get("site_footer_text") or config.get("footer_text")
        if footer_val:
            config["footer_text"] = footer_val
            config["site_footer_text"] = footer_val
        current.update(config)
        return set_system_config("site_branding_config", json.dumps(current, ensure_ascii=False), db_path=db_path)
    except Exception as e:
        logger.error(f"save_site_config 异常: {e}")
        return False


def delete_device(device_id: str, device_type: Optional[str] = None, db_path: str = DB_PATH) -> bool:
    """
    从数据库中删除指定设备及其所有历史遥测数据
    """
    conn = get_connection(db_path)
    try:
        if device_type:
            conn.execute(
                "DELETE FROM device_data WHERE device_type = ? AND device_id = ?",
                (device_type, device_id),
            )
            conn.execute(
                "DELETE FROM devices WHERE device_type = ? AND device_id = ?",
                (device_type, device_id),
            )
        else:
            conn.execute("DELETE FROM device_data WHERE device_id = ?", (device_id,))
            conn.execute("DELETE FROM devices WHERE device_id = ?", (device_id,))
        conn.commit()
        logger.info(f"已成功删除设备档案及历史数据: {device_type or '*'}/{device_id}")
        return True
    except Exception as e:
        logger.error(f"删除设备异常 ({device_id}): {e}", exc_info=True)
        return False
    finally:
        conn.close()


# -------------------------------------------------------------
# 用户账号体系与权限管理 (双角色系统：admin vs user)
# -------------------------------------------------------------

def hash_password(password: str) -> str:
    return password_hash(password)


def authenticate_user(username: str, password: str, db_path: str = DB_PATH):
    conn = get_connection(db_path)
    try:
        row = conn.execute("SELECT * FROM users WHERE username=?", (username.strip(),)).fetchone()
        if not row or not verify_password(password, row['password_hash']):
            return None, "INVALID_CREDENTIALS"
        if row['status'] != 'approved':
            return None, "PENDING_APPROVAL" if row['status'] == 'pending' else "REJECTED"
        now = datetime.now().isoformat(timespec='seconds')
        with conn:
            conn.execute("UPDATE users SET last_login=? WHERE id=?", (now, row['id']))
            if not row['password_hash'].startswith('pbkdf2_sha256$'):
                conn.execute("UPDATE users SET password_hash=? WHERE id=?", (hash_password(password), row['id']))
        user = {k: row[k] for k in ('id','username','role','real_name','status','created_at','must_change_password')}
        user['last_login'] = now
        return user, 'OK'
    finally:
        conn.close()


def register_user(username: str, password: str, role: str = 'user', real_name: str = '', db_path: str = DB_PATH):
    username = username.strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,64}', username):
        return False, '用户名仅支持3至64位字母、数字、下划线及短横线'
    try:
        validate_password(password)
    except ValueError as e:
        return False, str(e)
    conn = get_connection(db_path)
    try:
        with conn:
            conn.execute("INSERT INTO users(username,password_hash,role,real_name,status) VALUES(?,?,?,?,?)",
                         (username, hash_password(password), 'user', real_name[:100] or username, 'pending'))
        return True, '注册申请已提交，等待管理员审核'
    except sqlite3.IntegrityError:
        return False, '用户名已存在'
    finally:
        conn.close()


def admin_approve_user(target_username: str, approved: bool, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """
    超级管理员审核普通用户注册申请
    approved=True: 设为 approved (允许登录)
    approved=False: 设为 rejected (拒绝登录)
    """
    target_username = target_username.strip()
    if target_username == "admin":
        return False, "超级管理员主账号状态受系统核心保护，不可更改"

    conn = get_connection(db_path)
    try:
        new_status = "approved" if approved else "rejected"
        cursor = conn.cursor()
        cursor.execute("SELECT id, status FROM users WHERE username = ?", (target_username,))
        row = cursor.fetchone()
        if not row:
            return False, f"用户 '{target_username}' 不存在"

        conn.execute("UPDATE users SET status = ? WHERE username = ?", (new_status, target_username))
        conn.commit()
        status_cn = "已审核通过，现可正常登录" if approved else "已被驳回/拒绝登录权限"
        logger.info(f"管理员审批用户 [{target_username}] -> {new_status}")
        return True, f"审批成功：用户 [{target_username}] {status_cn}"
    except Exception as e:
        logger.error(f"admin_approve_user 异常: {e}")
        return False, f"审批处理失败: {str(e)}"
    finally:
        conn.close()


def get_user_by_username(username: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """根据用户名获取用户基础信息（不包含密码哈希）"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role, real_name, status, created_at, last_login FROM users WHERE username = ?",
            (username.strip(),),
        )
        row = cursor.fetchone()
        if row:
            u = dict(row)
            if not u.get("status"):
                u["status"] = "approved"
            return u
        return None
    except Exception as e:
        logger.error(f"get_user_by_username 异常: {e}")
        return None
    finally:
        conn.close()


def get_all_users(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """获取所有用户列表（包含 status 审核状态，用于超级管理员查看与审核）"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, real_name, status, created_at, last_login FROM users ORDER BY id ASC")
        users = []
        for r in cursor.fetchall():
            u = dict(r)
            if not u.get("status"):
                u["status"] = "approved"
            users.append(u)
        return users
    except Exception as e:
        logger.error(f"get_all_users 异常: {e}")
        return []
        return []
    finally:
        conn.close()


def update_user_profile(username: str, real_name: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """更新用户真实姓名或岗位信息"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET real_name = ? WHERE username = ?", (real_name.strip(), username.strip()))
        conn.commit()
        return True, "个人信息更新成功"
    except Exception as e:
        logger.error(f"update_user_profile 异常: {e}")
        return False, f"更新失败: {str(e)}"
    finally:
        conn.close()


def change_user_password(username, old_password, new_password, db_path=DB_PATH):
    try:
        validate_password(new_password)
    except ValueError as e:
        return False, str(e)
    conn = get_connection(db_path)
    try:
        row = conn.execute('SELECT password_hash FROM users WHERE username=?', (username,)).fetchone()
        if not row or not verify_password(old_password, row[0]):
            return False, '原密码错误'
        if old_password == new_password:
            return False, '新密码不能与旧密码相同'
        with conn:
            conn.execute('UPDATE users SET password_hash=?,must_change_password=0 WHERE username=?', (hash_password(new_password), username))
            conn.execute('DELETE FROM auth_sessions WHERE username=?', (username,))
        return True, '密码已更新，请重新登录'
    finally:
        conn.close()


def admin_reset_password(target_username, new_password, db_path=DB_PATH):
    try:
        validate_password(new_password)
    except ValueError as e:
        return False, str(e)
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute('UPDATE users SET password_hash=?,must_change_password=1 WHERE username=?', (hash_password(new_password), target_username))
            conn.execute('DELETE FROM auth_sessions WHERE username=?', (target_username,))
        return (True, '密码已重置，用户首次登录须修改') if cur.rowcount else (False, '用户不存在')
    finally:
        conn.close()


def update_user_role(target_username: str, new_role: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """管理员调整用户角色权限"""
    if new_role not in ["admin", "user"]:
        return False, "非法角色"
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET role = ? WHERE username = ?", (new_role, target_username.strip()))
        conn.commit()
        logger.info(f"管理员已调整用户 [{target_username}] 角色为 [{new_role}]")
        return True, f"已调整用户 [{target_username}] 权限为 [{new_role}]"
    except Exception as e:
        logger.error(f"update_user_role 异常: {e}")
        return False, f"权限调整失败: {str(e)}"
    finally:
        conn.close()


def change_user_username(current_username, new_username, password, db_path=DB_PATH):
    if current_username == 'admin':
        return False, '系统主账号不能更名'
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,64}', new_username):
        return False, '账号格式不合法'
    conn = get_connection(db_path)
    try:
        row = conn.execute('SELECT password_hash FROM users WHERE username=?', (current_username,)).fetchone()
        if not row or not verify_password(password, row[0]):
            return False, '密码验证失败'
        with conn:
            conn.execute('UPDATE users SET username=? WHERE username=?', (new_username, current_username))
            conn.execute('DELETE FROM auth_sessions WHERE username=?', (current_username,))
        return True, '账号已更新，请重新登录'
    except sqlite3.IntegrityError:
        return False, '账号已存在'
    finally:
        conn.close()


# =============================================================================
# 机器人加工程序管理 (Robot Programs Management)
# =============================================================================

def get_robot_programs(device_id, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute("SELECT id,device_id,device_type,prog_name,file_size,is_active,created_at,updated_at,source FROM robot_programs WHERE device_id=? AND source IN ('platform_draft','controller_file') ORDER BY updated_at DESC",(device_id,))]
    finally:
        conn.close()


def get_robot_program_by_name(device_id, prog_name, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        row=conn.execute("SELECT * FROM robot_programs WHERE device_id=? AND prog_name=? AND source IN ('platform_draft','controller_file')",(device_id,prog_name)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def save_robot_program(device_id,device_type,prog_name,prog_content,is_active=0,db_path=DB_PATH):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.[Pp][Rr][Gg]',prog_name) or len(prog_content.encode('utf-8'))>1024*1024:
        return False,'程序名或大小不合法'
    conn=get_connection(db_path)
    try:
        with conn:
            conn.execute("""INSERT INTO robot_programs(device_id,device_type,prog_name,prog_content,file_size,is_active,source)
                VALUES(?,?,?,?,?,0,'platform_draft') ON CONFLICT(device_id,prog_name) DO UPDATE SET
                prog_content=excluded.prog_content,file_size=excluded.file_size,is_active=0,source='platform_draft',updated_at=datetime('now','localtime')""",
                (device_id,device_type,prog_name,prog_content,len(prog_content.encode('utf-8'))))
        return True,'平台草稿已保存，未写入控制器，也未运行'
    finally:
        conn.close()


# =============================================================================
# 机器人说明书报警知识库与处理档案 (Alarm Knowledge Base & User Resolutions)
# =============================================================================

def get_alarm_knowledge_base(keyword=None, db_path=DB_PATH):
    from alarm_catalog import enrich
    conn=get_connection(db_path)
    try:
        query="SELECT * FROM alarm_knowledge_base WHERE verified=1 AND reference<>''"
        params=[]
        if keyword and keyword.strip():
            term=keyword.strip()
            candidates=[]
            for base in (10,16):
                try:
                    value=int(term,base)
                    if 0<=value<=0xffffffff:candidates.append(f'0x{value:08X}')
                except ValueError:pass
            query+=' AND (code LIKE ? OR title LIKE ? OR description LIKE ?'
            params=['%'+term+'%']*3
            if candidates:
                query+=' OR code IN ('+','.join('?' for _ in candidates)+')'
                params.extend(candidates)
            query+=')'
        return enrich(conn.execute(query+' ORDER BY code',params).fetchall())
    finally:
        conn.close()


def get_alarm_resolutions(device_id=None,limit=50,db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        query="SELECT * FROM alarm_resolutions WHERE source='operator_note'"
        params=[]
        if device_id:
            query+=' AND device_id=?'
            params.append(device_id)
        return [dict(r) for r in conn.execute(query+' ORDER BY created_at DESC,id DESC LIMIT ?',params+[max(1,min(limit,200))])]
    finally:
        conn.close()


def add_alarm_resolution(
    device_id: str,
    device_type: str,
    alarm_code: str,
    alarm_msg: str,
    solution: str,
    handler: str,
    notes: str = "",
    resolved_at: Optional[str] = None,
    db_path: str = DB_PATH,
) -> Tuple[bool, str]:
    """用户手动添加报警处理记录"""
    if not alarm_code or not solution or not handler:
        return False, "故障代码、处理方法和处理人必须填写完整"

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        res_time = resolved_at or now_str
        cursor.execute(
            """
            INSERT INTO alarm_resolutions (device_id, device_type, alarm_code, alarm_msg, solution, handler, notes, resolved_at, created_at,source)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?,'operator_note')
            """,
            (device_id, device_type, alarm_code, alarm_msg, solution, handler, notes, res_time, now_str)
        )
        conn.commit()
        logger.info(f"成功添加报警处理记录: [设备:{device_id}] [代码:{alarm_code}] [处理人:{handler}]")
        return True, "报警处理记录添加成功"
    except Exception as e:
        logger.error(f"add_alarm_resolution 异常: {e}")
        return False, f"添加记录失败: {str(e)}"
    finally:
        conn.close()


def cleanup_old_alarms(days=7, db_path=DB_PATH):
    """Raw controller events are retained; reads must never delete audit evidence."""
    return 0


# =============================================================================
# 机器人实时 I/O 状态管理 (Device I/O Status)
# =============================================================================

def get_device_io(device_id, db_path=DB_PATH):
    dev=get_device_by_id(device_id,db_path)
    if not dev or dev.get('is_simulated'):
        return {'device_id':device_id,'di':[],'do':[],'source':'no_data','di_mask':None,'do_mask':None}
    latest=get_latest_data(dev['device_type'],device_id,db_path)
    p=latest['parsed_payload'] if latest else {}
    has_value=any(isinstance(p.get(k),int) and not isinstance(p.get(k),bool) for k in ('di','do'))
    fresh=p.get('quality',{}).get('io',{}).get('fresh',False) and p.get('state_fresh') and p.get('status')!='offline' and has_value
    conn=get_connection(db_path)
    try:
        row=conn.execute('SELECT di_details,do_details FROM device_io_status WHERE device_id=?',(device_id,)).fetchone()
    finally:
        conn.close()
    result={'device_id':device_id,'source':'controller' if fresh else 'no_data','updated_at':p.get('quality',{}).get('io',{}).get('received_at')}
    for key,idx in [('di',0),('do',1)]:
        mask=p.get(key) if fresh else None
        if not isinstance(mask,int) or isinstance(mask,bool):
            mask=None
        details=json.loads(row[idx] or '{}') if row else {}
        count=p.get(key+'_count',0) if fresh and mask is not None else 0
        result[key+'_mask']=str(mask) if mask is not None else None
        result[key+'_total_count']=p.get(key+'_total_count') if fresh else None
        result[key]=[{'index':i,'name':details.get(f'{key}_{i}') or f'{key.upper()}_{i:02d}',
                      'state':bool(mask & (1<<i)) if mask is not None else None} for i in range(min(int(count),64))]
    return result


def update_device_io(
    device_id: str,
    device_type: str,
    di_mask: int,
    do_mask: int,
    di_details: Optional[Dict] = None,
    do_details: Optional[Dict] = None,
    db_path: str = DB_PATH,
) -> bool:
    """更新设备的 16 路 DI/DO 状态"""
    conn = get_connection(db_path)
    try:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO device_io_status (device_id, device_type, di_mask, do_mask, di_details, do_details, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                di_mask = excluded.di_mask,
                do_mask = excluded.do_mask,
                di_details = COALESCE(excluded.di_details, device_io_status.di_details),
                do_details = COALESCE(excluded.do_details, device_io_status.do_details),
                updated_at = excluded.updated_at
            """,
            (
                device_id,
                device_type,
                di_mask,
                do_mask,
                json.dumps(di_details or {}, ensure_ascii=False),
                json.dumps(do_details or {}, ensure_ascii=False),
                now_str,
            )
        )
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"update_device_io 异常: {e}")
        return False
    finally:
        conn.close()


def get_weekly_backups_list(device_id,backups_dir=None):
    from backup_service import list_backups
    return {'backups':list_backups(device_id),'schedule':'由服务器计划任务执行；具体时间以运维配置为准'}



def set_device_simulated(
    device_id: str,
    flag: bool,
    db_path: str = DB_PATH,
) -> bool:
    """将设备标记为仿真设备 (flag=True) 或真实设备 (flag=False)。"""
    conn = get_connection(db_path)
    try:
        with conn:
            cur = conn.execute(
                "UPDATE devices SET is_simulated = ?, updated_at = datetime('now','localtime') WHERE device_id = ?",
                (1 if flag else 0, device_id),
            )
            return cur.rowcount > 0
    except Exception as e:
        logger.error(f"set_device_simulated 异常 [{device_id}]: {e}")
        return False
    finally:
        conn.close()


def get_simulated_devices(
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """查询所有标记为仿真的设备（供后台设置页管理与仿真服务拉取清单）。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT * FROM devices WHERE is_simulated = 1 AND simulation_enabled=1 ORDER BY id ASC"
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_simulated_devices 查询异常: {e}")
        return []
    finally:
        conn.close()


def get_command_ack(device_id, task_id, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        row=conn.execute('SELECT * FROM command_requests WHERE task_id=? AND device_id=?',(task_id,device_id)).fetchone()
        if not row:
            return []
        d=dict(row)
        if d['state'] in ('sending','delivered','received') and d['expires_at']+15<__import__('time').time():
            d['state']='unknown'
            d['message']='未收到最终执行回执，结果未知，禁止自动重试'
        d['status']=d['state']
        return [d]
    finally:
        conn.close()


def get_cmd_history(device_id,limit=20,db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        return [dict(r) for r in conn.execute('SELECT * FROM command_requests WHERE device_id=? ORDER BY created_at DESC LIMIT ?',(device_id,max(1,min(limit,200))))]
    finally:
        conn.close()


def get_traffic_stats(buckets=13, window_sec=3, data_type=None, db_path=DB_PATH,end_time=None):
    now=end_time or datetime.now().replace(microsecond=0)
    start=now-timedelta(seconds=buckets*window_sec)
    conn=get_connection(db_path)
    try:
        rows=conn.execute("SELECT received_at FROM device_data WHERE source IN ('controller','simulation') AND data_type=? AND received_at>=? AND received_at<?",(data_type,start.isoformat(),now.isoformat())).fetchall()
        result=[0]*buckets
        for r in rows:
            i=int((datetime.fromisoformat(r[0])-start).total_seconds()//window_sec)
            if 0<=i<buckets:
                result[i]+=1
        return result
    finally:
        conn.close()


# =============================================================================
# 模块一：设备详情实时日志 (严格遵循华数官方 SDK 接口规范与报文映射)
# =============================================================================

# =============================================================================
# 模块一：设备详情运行日志 (1:1 华数示教器原生【运行日志】标准规范)
# 包含：图标 (👆/❗/ℹ️) | 递减编号 | 精确时间 | 操作用户 (Normal/Admin) | 记录项 (包含确认报警与 64 位伺服错误码)
# =============================================================================

def format_teach_pendant_time(dt: Optional[datetime] = None) -> str:
    """格式化为示教器原厂毫秒时间格式：YYYY-MM-DD HH:MM:SS'f"""
    if dt is None:
        dt = datetime.now()
    return dt.strftime("%Y-%m-%d %H:%M:%S") + f"'{dt.microsecond // 100000}"


def seed_default_run_logs(device_id, db_path=DB_PATH):
    """Retained for compatibility. Empty history remains empty."""
    return None


def add_device_run_log(device_id, icon_type, operator, record_content, log_level='INFO', db_path=DB_PATH, source='platform_audit', event_id=None, event_time=None):
    import uuid
    conn=get_connection(db_path)
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            seq=conn.execute('SELECT COALESCE(MAX(seq_no),0)+1 FROM device_run_logs WHERE device_id=?',(device_id,)).fetchone()[0]
            cur=conn.execute('INSERT OR IGNORE INTO device_run_logs(device_id,seq_no,icon_type,log_time,operator,log_level,record_content,source,event_id) VALUES(?,?,?,?,?,?,?,?,?)',
                            (device_id,seq,icon_type,event_time or datetime.now().isoformat(timespec='milliseconds'),operator,log_level,record_content,source,event_id or uuid.uuid4().hex))
        return seq if cur.rowcount else 0
    finally:
        conn.close()


def confirm_all_alarms_log(device_id, operator='unknown', db_path=DB_PATH):
    seq=add_device_run_log(device_id,'action',operator,'操作员已阅平台报警记录；未清除控制器报警',db_path=db_path)
    return {'success':bool(seq),'seq_no':seq,'message':'已登记平台已阅，控制器报警状态未改变','cleared_alarms':0}


def get_device_logs(device_id, limit=100, level=None, filter_type=None, db_path=DB_PATH):
    conn=get_connection(db_path)
    try:
        query="SELECT * FROM device_run_logs WHERE device_id=? AND source IN ('platform_audit','controller_event','simulation')"
        params=[device_id]
        if filter_type and filter_type.lower()!='all':
            query+=' AND icon_type=?'
            params.append(filter_type.lower())
        elif level and level.upper()!='ALL':
            query+=' AND log_level=?'
            params.append(level.upper())
        rows=conn.execute(query+' ORDER BY id DESC LIMIT ?',params+[min(500,max(1,limit))]).fetchall()
        result=[]
        for r in rows:
            d=dict(r)
            d.update(timestamp=d['log_time'],level=d['log_level'],message=d['record_content'])
            result.append(d)
        return result
    finally:
        conn.close()


# =============================================================================
# 模块二：每日/每月运行状态报告 (参考 FANUC iCare 极简专业设计)
# =============================================================================

def get_device_report_data(device_id, period='daily', date_str=None, db_path=DB_PATH):
    from reporting import device_report
    return device_report(device_id,period,date_str,db_path)


# =============================================================================
# 模块三：报警统计分析图表 (参考 FANUC ZDT 工业看板 - 纯真实数据驱动)
# =============================================================================

def get_alarm_analytics_stats(device_id=None, days=14, db_path=DB_PATH):
    from reporting import alarm_report
    return alarm_report(device_id,days,db_path)


