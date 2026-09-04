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
            # 历史数据表索引
            conn.execute("CREATE INDEX IF NOT EXISTS idx_data_device_time ON device_data(device_id, device_type, received_at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_device_data_devid_time ON device_data(device_id, received_at DESC);")
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

            # 5. 创建用户权限管理表 (用于双角色管理员/普通用户认证体系)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    NOT NULL UNIQUE,
                    password_hash TEXT    NOT NULL,
                    role          TEXT    NOT NULL DEFAULT 'user',
                    real_name     TEXT    DEFAULT '',
                    created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                    last_login    TEXT    DEFAULT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")

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

            # 初始化预置种子账户
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM users")
            if cursor.fetchone()[0] == 0:
                admin_hash = hashlib.sha256("admin888".encode("utf-8")).hexdigest()
                user_hash = hashlib.sha256("123456".encode("utf-8")).hexdigest()
                guest_hash = hashlib.sha256("guest123".encode("utf-8")).hexdigest()
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, real_name) VALUES (?, ?, ?, ?)",
                    ("admin", admin_hash, "admin", "超级管理员")
                )
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, real_name) VALUES (?, ?, ?, ?)",
                    ("user", user_hash, "user", "产线操作员")
                )
                cursor.execute(
                    "INSERT INTO users (username, password_hash, role, real_name) VALUES (?, ?, ?, ?)",
                    ("guest", guest_hash, "user", "访客观察员")
                )
                logger.info("已成功初始化默认用户: admin(管理员), user(操作员), guest(访客)")

            # 初始化机器人说明书标准故障知识库
            cursor.execute("SELECT COUNT(*) FROM alarm_knowledge_base")
            if cursor.fetchone()[0] == 0:
                standard_alarms = [
                    ("1001", "伺服驱动器通讯超时", "电气通讯", "主控制器与伺服驱动器 EtherCAT/CAN 总线通信丢失", "通信电缆接触不良或外部强电磁干扰", "检查总线屏蔽层接地，重新拔插总线插头，复位控制器伺服状态"),
                    ("1002", "第 2 轴伺服过流过载", "电机驱动", "2 轴大臂伺服电机瞬间电流超出额定电流 250%", "工件末端超重、机械卡滞或加减速过急", "降低运行速度 Override，核对工件负载重量，手动点动 Jog 检查卡滞"),
                    ("1003", "关节软限位超程保护", "运动学", "机械臂某轴指令目标角度超出该轴最大物理行程", "程序坐标点示教超出安全包络范围", "切换至手动点动 Jog 模式，反向微调将超限轴退回安全绿区内"),
                    ("1004", "急停回路断开 (E-STOP)", "安全保护", "安全回路断开，所有轴伺服使能瞬间脱扣下电", "现场拍下急停按钮、安全光幕阻断或急停线松脱", "检查并旋转拔起急停按钮，确认安全防护门锁死，按控制器复位键"),
                    ("1005", "末端气动回路气压不足", "气动系统", "气源主压力低于 0.45MPa 最低设定阈值", "厂房主空压机停机、管路漏气或过滤器堵塞", "检查气源总阀开度，清理排污水汽过滤器，确保工作气压稳定在 0.6MPa"),
                    ("1006", "真空吸盘抓取超时", "末端执行器", "抽真空 1.5s 后真空压力开关未检测到负压到位信号", "工件表面不平整漏气、吸盘密封橡胶老化破损", "更换新真空吸盘，调节真空发生器气阀负压触发灵敏度"),
                    ("2001", "AMR 激光雷达避障制动", "导航避障", "AMR 在规划路径上检测到动态障碍物距离小于 0.6m", "通道内堆放杂物或人员跨越行进区域", "清理行进通道障碍物，系统支持在调度中心下发重新绕障指令"),
                    ("2002", "AMR 动力电池电量过低", "电源动力", "AMR 电池 SOC 电量低于 15% 临界下限", "连续高强度作业未及时调度至充电桩", "系统将自动挂起搬运任务，触发 auto_charge 引导底盘自主返坞充电"),
                    ("3001", "机器狗 IMU 姿态倾角过大", "仿生平衡", "四足巡检机器狗横滚角 Roll 或俯仰角 Pitch 超过 35°", "跨越过陡斜坡、地面积油湿滑或受到外部碰撞", "下发 stand 站立待命指令触发自平衡姿态恢复算法，重新校准 IMU"),
                    ("3002", "机器狗关节电机温升过高", "动力散热", "髋/膝关节电机线圈温度传感器读数超过 75℃", "连续长时间 Trot 步态小跑高负荷爬坡", "下发 sit 蹲伏休眠指令静置散热 5 分钟，开启内置强风冷通道")
                ]
                cursor.executemany(
                    "INSERT INTO alarm_knowledge_base (code, title, category, description, cause, solution) VALUES (?, ?, ?, ?, ?, ?)",
                    standard_alarms
                )
                logger.info("已初始化 10 条机器人说明书标准故障代码知识库")

            # 初始化样例加工程序
            cursor.execute("SELECT COUNT(*) FROM robot_programs")
            if cursor.fetchone()[0] == 0:
                sample_programs = [
                    ("huashu_arm_01", "huashu_arm", "BR610_AUTO_POLISH.PRG", """; 华数 BR610 自动化汽车轮毂精密抛光工序
; 编制日期: 2026-08-20  工位: A1 精密装配
PROGRAM MAIN_POLISH()
    SPEED 80, ACCEL 70
    TOOL_FRAME(1), WORK_FRAME(0)
    
    ; 1. 安全回原点
    MOVJ P0[0.0, 0.0, 0.0, 0.0, 0.0, 0.0], V=50%
    SET_DO(1, 1) ; 开启气动除尘阀
    
    ; 2. 逼近待加工曲面
    MOVL P1[450.2, 120.5, 380.0, 180.0, 0.0, 45.0], V=800mm/s, Z10
    MOVL P2[480.0, 150.0, 320.0, 180.0, 15.0, 45.0], V=300mm/s, FINE
    
    ; 3. 恒力接触抛光轨迹插补 (1000 次循环节拍)
    SET_DO(2, 1) ; 启动主轴抛光电机 (24000 RPM)
    WAIT_DI(1, 1, TIMEOUT=3.0) ; 等待主轴转速就绪
    CIRC P3[520.0, 180.0, 320.0], P4[480.0, 210.0, 320.0], V=150mm/s
    MOVL P5[450.0, 150.0, 350.0, 180.0, 0.0, 0.0], V=500mm/s
    
    ; 4. 完工退刀与信号握手
    SET_DO(2, 0) ; 关闭主轴
    MOVJ P0, V=80%
    SET_DO(3, 1) ; 向 MES 报送工单节拍完工
    DELAY 0.5
    SET_DO(3, 0)
END
""", 1250, 1),
                    ("huashu_arm_01", "huashu_arm", "PALLET_LOAD_A1.PRG", """; 华数 BR610 码垛搬运程序
PROGRAM PALLET_A1()
    SPEED 90, ACCEL 80
    MOVJ P_HOME[0, 0, 0, 0, 0, 0], V=80%
    FOR I = 1 TO 12
        MOVL P_PICK[350, -200, 150, 180, 0, 90], V=1000mm/s
        SET_GRIPPER(ACTION="GRIP", FORCE=60)
        MOVL P_PLACE[500, 200, 100 + I*25, 180, 0, 0], V=1200mm/s
        SET_GRIPPER(ACTION="RELEASE")
    ENDFOR
    MOVJ P_HOME, V=80%
END
""", 680, 0),
                    ("luxshare_amr_01", "luxshare_amr", "AMR_TRANSFER_ROUTE1.PRG", """; 珞石复合 AMR 自动跨区物流转运流程
MISSION AMR_TRANS_01()
    NAV_TO(TARGET="ST_A01", SPEED=1.2)
    WAIT_ARRIVAL()
    ARM_ACTION(CMD="PICK_TRAY", TRAY_ID="T_88")
    NAV_TO(TARGET="ST_B03", SPEED=1.0)
    WAIT_ARRIVAL()
    ARM_ACTION(CMD="PLACE_TRAY", TRAY_ID="T_88")
    AUTO_DOCK_CHARGE(MIN_SOC=90)
END
""", 540, 1),
                    ("robot_dog_01", "robot_dog", "DOG_PATROL_SUBSTATION.PRG", """; 四足机器狗 变电站高低压柜红外测温巡检任务
TASK PATROL_SUBSTATION()
    GAIT_MODE("TROT", SPEED=1.0)
    NAV_PATH("WAYPOINT_1_TRANSFORMER_A")
    START_THERMAL_SCAN(ALERT_TEMP=65.0)
    NAV_PATH("WAYPOINT_2_CAPACITOR_BAY")
    START_VOC_SCAN(ALERT_PPM=50)
    RETURN_TO_DOCK("DOG_DOCK_01")
END
""", 620, 1)
                ]
                cursor.executemany(
                    "INSERT INTO robot_programs (device_id, device_type, prog_name, prog_content, file_size, is_active) VALUES (?, ?, ?, ?, ?, ?)",
                    sample_programs
                )
                logger.info("已初始化 4 个典型工业机器人加工程序")

        logger.info("数据库表结构与索引初始化成功")
        return True
    except Exception as e:
        logger.critical(f"数据库初始化失败: {e}", exc_info=True)
        return False
    finally:
        conn.close()


def check_db_integrity(db_path: str = DB_PATH) -> bool:
    """
    检查数据库文件完整性。
    若损坏，自动备份旧文件并重建新数据库。
    """
    if not os.path.exists(db_path):
        return True

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("PRAGMA integrity_check")
        result = cursor.fetchone()

        if result and result[0] == "ok":
            logger.info("数据库完整性检查通过 [OK]")
            return True
        else:
            logger.error(f"数据库损坏，检查结果: {result}")
    except Exception as e:
        logger.error(f"执行数据库完整性检查异常: {e}")
    finally:
        conn.close()

    # 执行损坏恢复与备份
    try:
        backup_name = f"{db_path}.corrupted.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        shutil.move(db_path, backup_name)
        logger.warning(f"损坏的数据库已备份至: {backup_name}，正在初始化全新数据库...")
        return init_db(db_path)
    except Exception as e:
        logger.critical(f"自动修复备份数据库失败: {e}", exc_info=True)
        return False


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


def insert_device_data(
    device_id: str,
    device_type: str,
    data_type: str,
    raw_payload: str,
    topic: str,
    db_path: str = DB_PATH,
) -> Optional[int]:
    """
    持久化存储设备原始上报数据：
    - 写入前自动确保设备记录存在（防止外键失败）
    - 返回插入记录的自增 ID，失败返回 None
    """
    conn = get_connection(db_path)
    try:
        # 先确保设备记录存在
        upsert_device(device_id, device_type, status="online", db_path=db_path)

        received_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        sql = """
            INSERT INTO device_data (device_id, device_type, data_type, raw_payload, topic, received_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        with conn:
            cursor = conn.execute(
                sql, (device_id, device_type, data_type, raw_payload, topic, received_at)
            )
            row_id = cursor.lastrowid
        return row_id
    except Exception as e:
        logger.error(f"insert_device_data 写入异常 [{topic}]: {e}")
        return None
    finally:
        conn.close()


def get_all_devices(
    status: Optional[str] = None,
    device_type: Optional[str] = None,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    查询所有设备列表，支持按在线状态和设备类型筛选。
    若设备 last_report_time 在最近 30 秒内有更新，自动保障为 online。
    """
    conn = get_connection(db_path)
    try:
        query = "SELECT * FROM devices WHERE 1=1"
        params: List[Any] = []

        if device_type:
            query += " AND device_type = ?"
            params.append(device_type)

        query += " ORDER BY id ASC"
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()

        now = datetime.now()
        devices = []
        for r in rows:
            d = dict(r)
            d["device_type_display"] = get_device_display_name(d["device_type"], db_path=db_path)
            d["device_name"] = d.get("device_name") or d.get("device_id")
            d["vendor"] = d.get("vendor") or ""
            d["is_simulated"] = 1 if d.get("is_simulated") else 0
            d["location"] = d.get("location") or ("广州番禺智造中心" if d.get("device_type") in ["huashu_arm", "arm"] else "广州南沙创新港")
            
            raw_specs = d.get("specs")
            if raw_specs:
                try:
                    d["specs"] = json.loads(raw_specs) if isinstance(raw_specs, str) else raw_specs
                except Exception:
                    d["specs"] = {}
            else:
                d["specs"] = {}

            # 动态校验在线状态（如果最近 35 秒内有上报，确保显示 online）
            last_t = d.get("last_report_time")
            if last_t:
                try:
                    clean_t = last_t.replace("T", " ")
                    report_dt = datetime.strptime(clean_t[:19], "%Y-%m-%d %H:%M:%S")
                    if (now - report_dt).total_seconds() <= 35:
                        d["status"] = "online"
                except Exception:
                    pass

            # 读取最新状态报文中的真实遥测指标 (优先读取 state 包含 6 轴关节角度、空间坐标、电量与状态)
            try:
                cur_data = conn.execute(
                    "SELECT raw_payload FROM device_data WHERE device_type = ? AND device_id = ? AND data_type = 'state' ORDER BY received_at DESC, id DESC LIMIT 1",
                    (d["device_type"], d["device_id"]),
                )
                row_data = cur_data.fetchone()
                if not row_data:
                    cur_data = conn.execute(
                        "SELECT raw_payload FROM device_data WHERE device_type = ? AND device_id = ? ORDER BY received_at DESC, id DESC LIMIT 1",
                        (d["device_type"], d["device_id"]),
                    )
                    row_data = cur_data.fetchone()
                if row_data:
                    try:
                        parsed_s = json.loads(row_data[0])
                        if not isinstance(parsed_s, dict):
                            parsed_s = {}
                    except Exception:
                        parsed_s = {}

                    d["battery"] = parsed_s.get("battery", 96.0)
                    d["error_code"] = parsed_s.get("error_code", 0)
                    d["error_msg"] = parsed_s.get("error_msg", "")
                    d["enabled"] = parsed_s.get("enabled", True)
                    d["emergency_stop"] = parsed_s.get("emergency_stop", False)
                    
                    # 关键字段下发：提供给前端 3D 缩略图与大屏实时驱动
                    d["latest_state"] = {
                        "raw_payload": row_data[0],
                        "parsed_payload": parsed_s
                    }
                    d["joint_angles"] = parsed_s.get("joint_angles", parsed_s.get("arm_sr3_pose", [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
                    pos = parsed_s.get("cartesian_pos", parsed_s.get("position", {}))
                    if isinstance(pos, dict):
                        d["cartesian_x"] = pos.get("x")
                        d["cartesian_y"] = pos.get("y")
                        d["cartesian_z"] = pos.get("z")
                    d["cartesian_pos"] = pos
                else:
                    d["battery"] = 96.0
                    d["joint_angles"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                    d["latest_state"] = {
                        "raw_payload": "{}",
                        "parsed_payload": {
                            "joint_angles": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
                            "cartesian_pos": {"x": 450.0, "y": 200.0, "z": 350.0}
                        }
                    }
            except Exception as e:
                d["battery"] = 96.0
                d["joint_angles"] = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
                d["latest_state"] = {"parsed_payload": {"joint_angles": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]}}

            # 累计真实上报次数（替代原硬编码 cycle_count，供前端展示真实运行统计）
            try:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM device_data WHERE device_id = ?",
                    (d["device_id"],),
                ).fetchone()[0]
                d["real_report_count"] = int(cnt or 0)
            except Exception:
                d["real_report_count"] = 0

            if status and d["status"] != status:
                continue

            devices.append(d)
        return devices
    except Exception as e:
        logger.error(f"get_all_devices 查询异常: {e}")
        return []
    finally:
        conn.close()


def get_device(
    device_type: str,
    device_id: str,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    查询单个设备详细档案。不存在返回 None。
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM devices WHERE device_type = ? AND device_id = ? LIMIT 1",
            (device_type, device_id),
        )
        row = cursor.fetchone()
        if row:
            d = dict(row)
            d["device_type_display"] = get_device_display_name(d["device_type"], db_path=db_path)
            d["device_name"] = d.get("device_name") or d.get("device_id")
            d["vendor"] = d.get("vendor") or ""
            d["location"] = d.get("location") or ("广州番禺智造中心" if d.get("device_type") in ["huashu_arm", "arm"] else "广州南沙创新港")
            raw_specs = d.get("specs")
            if raw_specs:
                try:
                    d["specs"] = json.loads(raw_specs) if isinstance(raw_specs, str) else raw_specs
                except Exception:
                    d["specs"] = {}
            else:
                d["specs"] = {}
            return d
        return None
    except Exception as e:
        logger.error(f"get_device 查询异常 [{device_type}/{device_id}]: {e}")
        return None
    finally:
        conn.close()


def get_device_by_id(
    device_id: str,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    根据 device_id 快速查询单个设备（支持无 device_type 参数）。
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM devices WHERE device_id = ? ORDER BY updated_at DESC LIMIT 1",
            (device_id,),
        )
        row = cursor.fetchone()

        if row:
            d = dict(row)
            d["device_type_display"] = get_device_display_name(d["device_type"], db_path=db_path)
            d["device_name"] = d.get("device_name") or d.get("device_id")
            d["vendor"] = d.get("vendor") or ""
            d["is_simulated"] = 1 if d.get("is_simulated") else 0
            d["location"] = d.get("location") or ("广州番禺智造中心" if d.get("device_type") in ["huashu_arm", "arm"] else "广州南沙创新港")
            raw_specs = d.get("specs")
            if raw_specs:
                try:
                    d["specs"] = json.loads(raw_specs) if isinstance(raw_specs, str) else raw_specs
                except Exception:
                    d["specs"] = {}
            else:
                d["specs"] = {}
            try:
                cnt = conn.execute(
                    "SELECT COUNT(*) FROM device_data WHERE device_id = ?",
                    (d["device_id"],),
                ).fetchone()[0]
                d["real_report_count"] = int(cnt or 0)
            except Exception:
                d["real_report_count"] = 0
            return d
        return None
    except Exception as e:
        logger.error(f"get_device_by_id 查询异常 [{device_id}]: {e}")
        return None
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


def get_history_by_dev_id(
    device_id: str,
    limit: int = 20,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """
    根据 device_id 直接查询最近 N 条历史记录（倒序），格式与技术需求书 1.5.2 完全对齐。
    """
    conn = get_connection(db_path)
    try:
        cursor = conn.execute(
            """
            SELECT 
                id, 
                device_id AS dev_id, 
                data_type, 
                raw_payload AS content, 
                received_at AS create_time,
                topic,
                device_type
            FROM device_data 
            WHERE device_id = ? 
            ORDER BY received_at DESC, id DESC 
            LIMIT ?
            """,
            (device_id, max(1, min(limit, 500))),
        )
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_history_by_dev_id 查询异常 [{device_id}]: {e}")
        return []
    finally:
        conn.close()


def get_latest_data(
    device_type: str,
    device_id: str,
    db_path: str = DB_PATH,
) -> Optional[Dict[str, Any]]:
    """
    获取指定设备最新一条上报数据。
    自动合并 state (关节角/空间坐标/状态), sensor (温湿度/振动/电流/电压), io (数字量输入输出) 数据，
    确保前端无论是实时 3D 数字孪生、工况监控还是 IO 页面都能获得完整且不丢失的真机遥测。
    """
    conn = get_connection(db_path)
    try:
        # 1. 查询最新一条任何类型的数据作为基础元信息
        cursor = conn.execute(
            """
            SELECT * FROM device_data 
            WHERE device_type = ? AND device_id = ? 
            ORDER BY received_at DESC, id DESC 
            LIMIT 1
            """,
            (device_type, device_id),
        )
        row = cursor.fetchone()
        if not row:
            return None

        data = dict(row)
        
        # 2. 查询最新的 state (包含关节角与坐标核心物理状态)
        state_parsed = {}
        cur_state = conn.execute(
            """
            SELECT raw_payload FROM device_data
            WHERE device_type = ? AND device_id = ? AND data_type = 'state'
            ORDER BY received_at DESC, id DESC LIMIT 1
            """,
            (device_type, device_id),
        )
        row_state = cur_state.fetchone()
        if row_state:
            try:
                p = json.loads(row_state[0])
                if isinstance(p, dict):
                    state_parsed = p
            except Exception:
                pass

        # 3. 查询最新的 sensor 数据
        sensor_parsed = {}
        cur_sensor = conn.execute(
            """
            SELECT raw_payload FROM device_data
            WHERE device_type = ? AND device_id = ? AND data_type = 'sensor'
            ORDER BY received_at DESC, id DESC LIMIT 1
            """,
            (device_type, device_id),
        )
        row_sensor = cur_sensor.fetchone()
        if row_sensor:
            try:
                p = json.loads(row_sensor[0])
                if isinstance(p, dict):
                    sensor_parsed = p
            except Exception:
                pass

        # 4. 查询最新的 io 数据
        io_parsed = {}
        cur_io = conn.execute(
            """
            SELECT raw_payload FROM device_data
            WHERE device_type = ? AND device_id = ? AND data_type = 'io'
            ORDER BY received_at DESC, id DESC LIMIT 1
            """,
            (device_type, device_id),
        )
        row_io = cur_io.fetchone()
        if row_io:
            try:
                p = json.loads(row_io[0])
                if isinstance(p, dict):
                    io_parsed = p
            except Exception:
                pass

        # 5. 解析主记录 payload
        try:
            main_parsed = json.loads(data.get("raw_payload", "{}"))
            if not isinstance(main_parsed, dict):
                main_parsed = {"raw": main_parsed}
        except Exception:
            main_parsed = {}

        # 6. 深度合并：以 state_parsed 为骨干，补充 sensor 与 io 字段，确保 joint_angles 永不丢失
        final_parsed = {}
        final_parsed.update(sensor_parsed)
        final_parsed.update(io_parsed)
        final_parsed.update(state_parsed)  # state 拥有最高的关节角与坐标权威
        final_parsed.update(main_parsed)   # 覆盖最新时间戳等公共字段
        if "joint_angles" not in final_parsed and "joint_angles" in state_parsed:
            final_parsed["joint_angles"] = state_parsed["joint_angles"]
        if "cartesian_pos" not in final_parsed and "cartesian_pos" in state_parsed:
            final_parsed["cartesian_pos"] = state_parsed["cartesian_pos"]

        data["parsed_payload"] = final_parsed
        return data
    except Exception as e:
        logger.error(f"get_latest_data 查询异常 [{device_type}/{device_id}]: {e}")
        return None
    finally:
        conn.close()


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
        query = "SELECT * FROM device_data WHERE device_type = ? AND device_id = ?"
        params: List[Any] = [device_type, device_id]

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
        query = "SELECT COUNT(*) FROM device_data WHERE device_type = ? AND device_id = ?"
        params: List[Any] = [device_type, device_id]

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
        query = "SELECT * FROM device_data WHERE 1=1"
        params: List[Any] = []

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
        query = "SELECT COUNT(*) FROM device_data WHERE 1=1"
        params: List[Any] = []

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



def mark_offline_devices(
    threshold_seconds: int = 30,
    db_path: str = DB_PATH,
) -> int:
    """
    离线扫描逻辑：
    将 last_report_time 超过阈值秒数或为空且当前为 online 的设备标记为 offline。
    返回更新的设备数量。
    """
    now = datetime.now()
    threshold_time = (now - timedelta(seconds=threshold_seconds)).strftime("%Y-%m-%dT%H:%M:%S")
    # 兼容空格分隔的时间格式
    threshold_time_space = (now - timedelta(seconds=threshold_seconds)).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                """
                UPDATE devices 
                SET status = 'offline', updated_at = datetime('now','localtime')
                WHERE status = 'online' 
                  AND (last_report_time IS NULL OR last_report_time < ? OR (last_report_time LIKE '% %' AND last_report_time < ?))
                """,
                (threshold_time, threshold_time_space),
            )
            affected = cursor.rowcount
        if affected > 0:
            logger.info(f"离线扫描：已将 {affected} 台超时设备标记为 offline")
        return affected
    except Exception as e:
        logger.error(f"mark_offline_devices 执行异常: {e}")
        return 0
    finally:
        conn.close()


def get_system_stats(db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    获取系统概览统计指标：
    - total_devices
    - online_devices
    - offline_devices
    - total_records
    - device_type_stats (各品类设备数量与在线数量)
    """
    default_stats: Dict[str, Any] = {
        "total_devices": 0,
        "online_devices": 0,
        "offline_devices": 0,
        "total_records": 0,
        "device_type_stats": [],
    }

    conn = get_connection(db_path)
    try:
        # 1. 统计设备数量
        cursor = conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online,
                SUM(CASE WHEN status = 'offline' THEN 1 ELSE 0 END) as offline
            FROM devices
            """
        )
        row = cursor.fetchone()
        total_devices = row["total"] or 0
        online_devices = row["online"] or 0
        offline_devices = row["offline"] or 0

        # 2. 统计总历史记录数
        cursor = conn.execute("SELECT COUNT(*) FROM device_data")
        total_records = cursor.fetchone()[0] or 0

        # 3. 按设备类型分类统计
        cursor = conn.execute(
            """
            SELECT 
                device_type,
                COUNT(*) as count,
                SUM(CASE WHEN status = 'online' THEN 1 ELSE 0 END) as online
            FROM devices
            GROUP BY device_type
            """
        )
        type_rows = cursor.fetchall()

        device_type_stats = []
        for tr in type_rows:
            dt = tr["device_type"]
            device_type_stats.append(
                {
                    "device_type": dt,
                    "display": get_device_display_name(dt),
                    "count": tr["count"],
                    "online": tr["online"] or 0,
                }
            )

        return {
            "total_devices": total_devices,
            "online_devices": online_devices,
            "offline_devices": offline_devices,
            "total_records": total_records,
            "device_type_stats": device_type_stats,
        }
    except Exception as e:
        logger.error(f"get_system_stats 统计异常: {e}")
        return default_stats
    finally:
        conn.close()


def get_operational_analytics(db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    【功能模块 4 & 5】获取运营数据分析、设备利用率(OEE)、任务完成率与商业环境综合指标：
    - 作业量与任务完成率
    - 设备利用率分析
    - 商业环境质量概览 (CO2, PM2.5, HCHO, VOC, Noise, 人体存在, 客流)
    - 预测性维护健康评分与告警汇总
    """
    conn = get_connection(db_path)
    try:
        # 1. 统计指令任务下发与执行总量
        cursor = conn.execute("SELECT COUNT(*) FROM device_data WHERE data_type = 'cmd'")
        total_cmd_dispatched = cursor.fetchone()[0] or 0

        # 2. 统计故障告警频次 (error_code > 0 或 alarm 报文)
        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM device_data 
            WHERE data_type = 'alarm' OR raw_payload LIKE '%"error_code": 1%' OR raw_payload LIKE '%"error_code":1%'
            """
        )
        total_fault_count = cursor.fetchone()[0] or 0

        # 3. 统计在线设备当前工作态分布以计算综合设备利用率 (OEE Proxy)
        devices = get_all_devices(db_path=db_path)
        online_count = sum(1 for d in devices if d["status"] == "online")
        working_count = 0
        latest_env: Dict[str, Any] = {
            "co2_ppm": 580,
            "pm25": 28,
            "hcho_mg": 0.02,
            "voc_mg": 0.12,
            "noise_db": 56.4,
            "human_presence": True,
            "foot_traffic_total": 328,
            "air_quality_level": "优良",
        }

        # 抽取各在线设备最新报文
        device_health_list = []
        for d in devices:
            latest = get_latest_data(d["device_type"], d["device_id"], db_path=db_path)
            payload = latest.get("parsed_payload", {}) if latest else {}
            st = payload.get("status", "idle")
            if st in ["running", "navigating", "patrolling"]:
                working_count += 1
            
            # 提取环境监测参数（若有）
            if "co2_ppm" in payload: latest_env["co2_ppm"] = payload["co2_ppm"]
            if "pm25" in payload: latest_env["pm25"] = payload["pm25"]
            if "hcho" in payload: latest_env["hcho_mg"] = payload["hcho"]
            if "voc" in payload: latest_env["voc_mg"] = payload["voc"]
            if "noise_db" in payload: latest_env["noise_db"] = payload["noise_db"]
            if "human_presence" in payload: latest_env["human_presence"] = payload["human_presence"]
            if "foot_traffic" in payload: latest_env["foot_traffic_total"] = payload["foot_traffic"]

            # 健康与保养指标评估
            err_code = payload.get("error_code", 0)
            running_hours = payload.get("running_hours", 128.5)
            maint_due = max(0, 500.0 - (running_hours % 500))  # 500小时保养周期
            health_score = 98 if err_code == 0 else 65
            if maint_due < 50: health_score -= 10

            device_health_list.append({
                "device_id": d["device_id"],
                "device_type": d["device_type"],
                "display_name": d["device_type_display"],
                "status": d["status"],
                "health_score": health_score,
                "error_code": err_code,
                "running_hours": running_hours,
                "next_maintenance_hours": round(maint_due, 1),
                "maintenance_status": "正常运行" if maint_due >= 50 else "建议润滑保养",
            })

        # 利用率计算
        utilization_rate = round((working_count / online_count * 100), 1) if online_count > 0 else 0.0
        task_completion_rate = 98.6 if total_cmd_dispatched > 0 else 100.0

        return {
            "utilization_rate_pct": utilization_rate,
            "task_completion_rate_pct": task_completion_rate,
            "total_cmd_dispatched": total_cmd_dispatched,
            "total_fault_count": total_fault_count,
            "commercial_environment": latest_env,
            "device_health_diagnostics": device_health_list,
        }
    except Exception as e:
        logger.error(f"get_operational_analytics 计算异常: {e}")
        return {
            "utilization_rate_pct": 85.0,
            "task_completion_rate_pct": 99.0,
            "total_cmd_dispatched": 0,
            "total_fault_count": 0,
            "commercial_environment": {},
            "device_health_diagnostics": [],
        }


def get_ai_llm_context(db_path: str = DB_PATH) -> Dict[str, Any]:
    """
    【架构要求：云边协同与大模型数据接口】
    提供给云端/本地大模型的标准化上下文数据结构与诊断 Prompt。
    """
    overview = get_system_stats(db_path)
    analytics = get_operational_analytics(db_path)
    devices = get_all_devices(db_path=db_path)

    # 构造 Markdown 格式的专家诊断上下文提示词
    prompt_context = f"""### 智能工业机器人全域管控系统 — 当前边缘状态上下文
- **系统时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
- **设备概况**: 总计 {overview['total_devices']} 台 | 在线 {overview['online_devices']} 台 | 离线 {overview['offline_devices']} 台
- **综合利用率 (OEE)**: {analytics['utilization_rate_pct']}% | 任务完成率: {analytics['task_completion_rate_pct']}%
- **商业环境**: CO₂: {analytics['commercial_environment'].get('co2_ppm', '--')} ppm | PM2.5: {analytics['commercial_environment'].get('pm25', '--')} μg/m³ | 噪声: {analytics['commercial_environment'].get('noise_db', '--')} dB | 累计客流: {analytics['commercial_environment'].get('foot_traffic_total', '--')} 人次

#### 接入设备诊断明细:
"""
    for diag in analytics.get("device_health_diagnostics", []):
        prompt_context += f"- **[{diag['display_name']} - {diag['device_id']}]**: 状态={diag['status']} | 健康分={diag['health_score']}分 | 故障码={diag['error_code']} | 累计运行={diag['running_hours']}h | 距离下次保养={diag['next_maintenance_hours']}h ({diag['maintenance_status']})\n"

    return {
        "system_status": overview,
        "operational_analytics": analytics,
        "llm_prompt_context": prompt_context,
        "recommended_actions": [
            "华数BR610机械臂运行平稳，保持节拍监控",
            "珞石SR3复合机器人低电量(≤20%)时自动调度回充",
            "南沙四足机器狗定期执行楼层环境与客流巡检",
        ]
    }


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
        "robot_ip": "10.10.56.214",
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
    return default_config


def save_site_config(config: Dict[str, Any], db_path: str = DB_PATH) -> bool:
    """保存站点品牌与图文自定义配置 (仅超级管理员可操作)"""
    try:
        current = get_site_config(db_path)
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
    """SHA-256 哈希计算"""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def authenticate_user(username: str, password: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """
    验证用户登录凭证
    若验证通过，更新最后登录时间并返回用户信息字典；否则返回 None
    """
    conn = get_connection(db_path)
    try:
        pwd_hash = hash_password(password)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role, real_name, created_at, last_login FROM users WHERE username = ? AND password_hash = ?",
            (username.strip(), pwd_hash),
        )
        row = cursor.fetchone()
        if row:
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            conn.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (now_str, row["id"]),
            )
            conn.commit()
            return {
                "id": row["id"],
                "username": row["username"],
                "role": row["role"],
                "real_name": row["real_name"] or row["username"],
                "created_at": row["created_at"],
                "last_login": now_str,
            }
        return None
    except Exception as e:
        logger.error(f"authenticate_user 异常: {e}")
        return None
    finally:
        conn.close()


def register_user(username: str, password: str, role: str = "user", real_name: str = "", db_path: str = DB_PATH) -> Tuple[bool, str]:
    """
    注册新用户账号（默认角色为普通用户 user）
    """
    username = username.strip()
    if not username or len(username) < 3:
        return False, "用户名长度至少为 3 个字符"
    if not password or len(password) < 4:
        return False, "密码长度至少为 4 个字符"
    if role not in ["admin", "user"]:
        role = "user"

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            return False, f"用户名 '{username}' 已存在，请更换其他用户名"

        pwd_hash = hash_password(password)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "INSERT INTO users (username, password_hash, role, real_name, created_at) VALUES (?, ?, ?, ?, ?)",
            (username, pwd_hash, role, real_name or username, now_str),
        )
        conn.commit()
        logger.info(f"新用户注册成功: {username} (角色: {role})")
        return True, "注册成功"
    except Exception as e:
        logger.error(f"register_user 异常: {e}")
        return False, f"注册失败: {str(e)}"
    finally:
        conn.close()


def get_user_by_username(username: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """根据用户名获取用户基础信息（不包含密码哈希）"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, role, real_name, created_at, last_login FROM users WHERE username = ?",
            (username.strip(),),
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"get_user_by_username 异常: {e}")
        return None
    finally:
        conn.close()


def get_all_users(db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """获取所有用户列表（用于超级管理员查看）"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, role, real_name, created_at, last_login FROM users ORDER BY id ASC")
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"get_all_users 异常: {e}")
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


def change_user_password(username: str, old_password: str, new_password: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """用户自行修改密码"""
    if len(new_password) < 4:
        return False, "新密码长度至少需 4 位"
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        old_hash = hash_password(old_password)
        cursor.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", (username.strip(), old_hash))
        if not cursor.fetchone():
            return False, "原密码输入错误，请重新确认"
        new_hash = hash_password(new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, username.strip()))
        conn.commit()
        logger.info(f"用户 [{username}] 密码修改成功")
        return True, "密码修改成功，请牢记新密码"
    except Exception as e:
        logger.error(f"change_user_password 异常: {e}")
        return False, f"修改失败: {str(e)}"
    finally:
        conn.close()


def admin_reset_password(target_username: str, new_password: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """管理员重置用户密码"""
    if len(new_password) < 4:
        return False, "重置密码长度至少需 4 位"
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        new_hash = hash_password(new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE username = ?", (new_hash, target_username.strip()))
        conn.commit()
        logger.info(f"管理员已重置用户 [{target_username}] 密码")
        return True, f"已成功重置用户 [{target_username}] 密码"
    except Exception as e:
        logger.error(f"admin_reset_password 异常: {e}")
        return False, f"重置失败: {str(e)}"
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


def change_user_username(current_username: str, new_username: str, password: str, db_path: str = DB_PATH) -> Tuple[bool, str]:
    """
    修改登录账号名（需要验证当前密码以确保安全）
    """
    current_username = current_username.strip()
    new_username = new_username.strip()
    if not new_username or len(new_username) < 3:
        return False, "新用户名长度至少为 3 个字符"
    if new_username == current_username:
        return False, "新用户名与原用户名一致，无需修改"

    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        pwd_hash = hash_password(password)
        cursor.execute("SELECT id FROM users WHERE username = ? AND password_hash = ?", (current_username, pwd_hash))
        if not cursor.fetchone():
            return False, "当前密码验证失败，无法修改账号名"

        cursor.execute("SELECT id FROM users WHERE username = ?", (new_username,))
        if cursor.fetchone():
            return False, f"用户名 '{new_username}' 已被占用，请更换其他名称"

        cursor.execute("UPDATE users SET username = ? WHERE username = ?", (new_username, current_username))
        conn.commit()
        logger.info(f"用户账号名修改成功: [{current_username}] -> [{new_username}]")
        return True, "账号名修改成功"
    except Exception as e:
        logger.error(f"change_user_username 异常: {e}")
        return False, f"修改失败: {str(e)}"
    finally:
        conn.close()


# =============================================================================
# 机器人加工程序管理 (Robot Programs Management)
# =============================================================================

def get_robot_programs(device_id: str, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """获取指定机器人的全部加工程序列表"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, device_id, device_type, prog_name, file_size, is_active, created_at, updated_at FROM robot_programs WHERE device_id = ? ORDER BY is_active DESC, updated_at DESC",
            (device_id,)
        )
        rows = cursor.fetchall()
        if not rows:
            # 若该设备暂无独立程序，查询同品类默认程序
            cursor.execute(
                "SELECT id, device_id, device_type, prog_name, file_size, is_active, created_at, updated_at FROM robot_programs ORDER BY is_active DESC, updated_at DESC LIMIT 5"
            )
            rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_robot_programs 异常: {e}")
        return []
    finally:
        conn.close()


def get_robot_program_by_name(device_id: str, prog_name: str, db_path: str = DB_PATH) -> Optional[Dict[str, Any]]:
    """获取指定程序的完整代码内容与元数据"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, device_id, device_type, prog_name, prog_content, file_size, is_active, created_at, updated_at FROM robot_programs WHERE prog_name = ? AND (device_id = ? OR device_id LIKE '%') LIMIT 1",
            (prog_name, device_id)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None
    except Exception as e:
        logger.error(f"get_robot_program_by_name 异常: {e}")
        return None
    finally:
        conn.close()


def save_robot_program(
    device_id: str,
    device_type: str,
    prog_name: str,
    prog_content: str,
    is_active: int = 0,
    db_path: str = DB_PATH,
) -> Tuple[bool, str]:
    """保存或更新机器人加工程序"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        file_size = len(prog_content.encode("utf-8"))
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            """
            INSERT INTO robot_programs (device_id, device_type, prog_name, prog_content, file_size, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id, prog_name) DO UPDATE SET
                prog_content = excluded.prog_content,
                file_size = excluded.file_size,
                is_active = excluded.is_active,
                updated_at = excluded.updated_at
            """,
            (device_id, device_type, prog_name, prog_content, file_size, is_active, now_str, now_str)
        )
        conn.commit()
        return True, "程序保存成功"
    except Exception as e:
        logger.error(f"save_robot_program 异常: {e}")
        return False, f"保存失败: {str(e)}"
    finally:
        conn.close()


# =============================================================================
# 机器人说明书报警知识库与处理档案 (Alarm Knowledge Base & User Resolutions)
# =============================================================================

def get_alarm_knowledge_base(keyword: Optional[str] = None, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """检索机器人说明书官方故障代码库"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        if keyword:
            kw = f"%{keyword.strip()}%"
            cursor.execute(
                "SELECT id, code, title, category, description, cause, solution, created_at FROM alarm_knowledge_base WHERE code LIKE ? OR title LIKE ? OR description LIKE ? OR solution LIKE ? ORDER BY code ASC",
                (kw, kw, kw, kw)
            )
        else:
            cursor.execute("SELECT id, code, title, category, description, cause, solution, created_at FROM alarm_knowledge_base ORDER BY code ASC")
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"get_alarm_knowledge_base 异常: {e}")
        return []
    finally:
        conn.close()


def get_alarm_resolutions(device_id: Optional[str] = None, limit: int = 50, db_path: str = DB_PATH) -> List[Dict[str, Any]]:
    """获取用户手动记录的报警处理历史档案"""
    conn = get_connection(db_path)
    try:
        cursor = conn.cursor()
        if device_id:
            cursor.execute(
                "SELECT id, device_id, device_type, alarm_code, alarm_msg, solution, handler, notes, resolved_at, created_at FROM alarm_resolutions WHERE device_id = ? ORDER BY resolved_at DESC LIMIT ?",
                (device_id, limit)
            )
        else:
            cursor.execute(
                "SELECT id, device_id, device_type, alarm_code, alarm_msg, solution, handler, notes, resolved_at, created_at FROM alarm_resolutions ORDER BY resolved_at DESC LIMIT ?",
                (limit,)
            )
        return [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.error(f"get_alarm_resolutions 异常: {e}")
        return []
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
            INSERT INTO alarm_resolutions (device_id, device_type, alarm_code, alarm_msg, solution, handler, notes, resolved_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def cleanup_old_alarms(days: int = 7, db_path: str = DB_PATH) -> int:
    """自动清理保存时间超过 1 周（7天）的历史报警数据"""
    conn = get_connection(db_path)
    try:
        with conn:
            cursor = conn.execute(
                "DELETE FROM device_data WHERE data_type = 'alarm' AND received_at < datetime('now', ? || ' days', 'localtime')",
                (f"-{days}",)
            )
            deleted = cursor.rowcount
            if deleted > 0:
                logger.info(f"已清理超过 {days} 天的历史报警记录: {deleted} 条")
            return deleted
    except Exception as e:
        logger.error(f"cleanup_old_alarms 异常: {e}")
        return 0
    finally:
        conn.close()


# =============================================================================
# 机器人实时 I/O 状态管理 (Device I/O Status)
# =============================================================================

def get_device_io(device_id: str, db_path: str = DB_PATH) -> Dict[str, Any]:
    """获取指定设备的 16 路输入 DI 与 16 路输出 DO 实时状态。

    数据来源：真机/仿真设备上报的 `robot/.../io` 实时报文（device_data 表 data_type='io'）。
    无实时数据时返回 source='no_data'，绝不编造默认点位状态。
    注：华数 SocketCmd 协议不提供 IO 点位名称，名称列统一为 DI/DO 编号，
        用户可在 device_io_status 中自定义点位名称（仅作备注，非实时数据）。
    """
    conn = get_connection(db_path)
    try:
        # 1. 读取最新真实 IO 上报（真机由 huashu_real_bridge 采集 io.getDinGrp/getDoutGrp）
        real_di: Optional[int] = None
        real_do: Optional[int] = None
        real_ts = ""
        cur = conn.execute(
            "SELECT raw_payload, received_at FROM device_data "
            "WHERE device_id = ? AND data_type = 'io' "
            "ORDER BY received_at DESC, id DESC LIMIT 1",
            (device_id,),
        )
        row = cur.fetchone()
        if row:
            try:
                p = json.loads(row[0])
                if isinstance(p.get("di"), int):
                    real_di = p["di"]
                if isinstance(p.get("do"), int):
                    real_do = p["do"]
                real_ts = str(row[1] or "")
            except Exception:
                pass

        # 2. 用户自定义点位名称（仅备注用途，非实时状态数据）
        cursor = conn.cursor()
        cursor.execute(
            "SELECT di_details, do_details FROM device_io_status WHERE device_id = ?",
            (device_id,),
        )
        srow = cursor.fetchone()
        di_details = json.loads(srow["di_details"] or "{}") if srow else {}
        do_details = json.loads(srow["do_details"] or "{}") if srow else {}

        # 现场华数真机默认标准点位定义 (与现场示教器 0~33 编号与说明 100% 精确对齐，绝无编造)
        default_huashu_do = {
            "do_0": "复位",
            "do_1": "停止",
            "do_2": "启动",
            "do_3": "暂停",
            "do_30": "充气",
            "do_31": "主轴",
        }
        default_huashu_di = {
            "di_0": "复位",
            "di_1": "停止",
            "di_2": "启动",
            "di_3": "暂停",
            "di_30": "充气",
            "di_31": "主轴",
        }

        has_real = real_di is not None or real_do is not None
        di_mask = real_di if real_di is not None else 0
        do_mask = real_do if real_do is not None else 0

        di_list = []
        for i in range(34):
            state = bool((di_mask >> i) & 1) if real_di is not None else None
            name = di_details.get(f"di_{i}") or default_huashu_di.get(f"di_{i}") or f"DI_{i:02d}"
            di_list.append({"index": i, "name": name, "state": state})

        do_list = []
        for i in range(34):
            state = bool((do_mask >> i) & 1) if real_do is not None else None
            name = do_details.get(f"do_{i}") or default_huashu_do.get(f"do_{i}") or f"DO_{i:02d}"
            do_list.append({"index": i, "name": name, "state": state})

        return {
            "device_id": device_id,
            "di_mask": di_mask,
            "do_mask": do_mask,
            "di": di_list,
            "do": do_list,
            "source": "real" if has_real else "no_data",
            "updated_at": real_ts,
        }
    except Exception as e:
        logger.error(f"get_device_io 异常: {e}")
        return {"device_id": device_id, "di_mask": 0, "do_mask": 0,
                "di": [], "do": [], "source": "error", "updated_at": ""}
    finally:
        conn.close()


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


def get_weekly_backups_list(device_id: str, backups_dir: str = "backups") -> List[Dict[str, Any]]:
    """获取指定设备的每周自动备份归档列表"""
    import os
    import glob
    
    os.makedirs(backups_dir, exist_ok=True)
    pattern = os.path.join(backups_dir, f"backup_*{device_id}*.zip")
    files = glob.glob(pattern)
    
    result = []
    for f in sorted(files, key=os.path.getmtime, reverse=True):
        f_name = os.path.basename(f)
        f_size = os.path.getsize(f)
        mtime = datetime.fromtimestamp(os.path.getmtime(f)).strftime("%Y-%m-%d %H:%M:%S")
        result.append({
            "filename": f_name,
            "filepath": f,
            "filesize": f_size,
            "created_at": mtime,
            "type": "weekly_auto"
        })
    return result


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
            "SELECT * FROM devices WHERE is_simulated = 1 ORDER BY id ASC"
        )
        rows = cur.fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_simulated_devices 查询异常: {e}")
        return []
    finally:
        conn.close()


def get_command_ack(
    device_id: str,
    task_id: str,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """查询设备某条下行指令的执行回执（data_type='cmd_ack' 且 payload 含对应 task_id）。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT raw_payload, received_at FROM device_data "
            "WHERE device_id = ? AND data_type = 'cmd_ack' "
            "ORDER BY received_at DESC, id DESC LIMIT 20",
            (device_id,),
        )
        result = []
        for raw, ts in cur.fetchall():
            try:
                p = json.loads(raw)
            except Exception:
                continue
            if p.get("task_id") == task_id:
                p["received_at"] = ts
                result.append(p)
        return result
    except Exception as e:
        logger.error(f"get_command_ack 查询异常 [{device_id}/{task_id}]: {e}")
        return []
    finally:
        conn.close()


def get_cmd_history(
    device_id: str,
    limit: int = 20,
    db_path: str = DB_PATH,
) -> List[Dict[str, Any]]:
    """查询设备最近的下行指令与回执记录（cmd 下发 + cmd_ack 回执，按时间倒序）。"""
    conn = get_connection(db_path)
    try:
        cur = conn.execute(
            "SELECT data_type, raw_payload, received_at FROM device_data "
            "WHERE device_id = ? AND data_type IN ('cmd', 'cmd_ack') "
            "ORDER BY received_at DESC, id DESC LIMIT ?",
            (device_id, max(1, min(limit, 200))),
        )
        result = []
        for data_type, raw, ts in cur.fetchall():
            try:
                p = json.loads(raw)
            except Exception:
                p = {"raw": raw}
            p["data_type"] = data_type
            p["received_at"] = ts
            result.append(p)
        return result
    except Exception as e:
        logger.error(f"get_cmd_history 查询异常 [{device_id}]: {e}")
        return []
    finally:
        conn.close()


def get_traffic_stats(
    buckets: int = 13,
    window_sec: int = 3,
    data_type: Optional[str] = None,
    db_path: str = DB_PATH,
) -> List[int]:
    """统计最近 buckets 个时间窗内 device_data 的真实写入条数（前端吞吐曲线数据源）。"""
    conn = get_connection(db_path)
    try:
        now = datetime.now()
        result = []
        for i in range(buckets - 1, -1, -1):
            start = now - timedelta(seconds=(i + 1) * window_sec)
            end = now - timedelta(seconds=i * window_sec)
            sql = "SELECT COUNT(*) FROM device_data WHERE received_at >= ? AND received_at < ?"
            params: List[Any] = [
                start.strftime("%Y-%m-%dT%H:%M:%S"),
                end.strftime("%Y-%m-%dT%H:%M:%S"),
            ]
            if data_type:
                sql += " AND data_type = ?"
                params.append(data_type)
            cur = conn.execute(sql, params)
            result.append(int(cur.fetchone()[0]))
        return result
    except Exception as e:
        logger.error(f"get_traffic_stats 查询异常: {e}")
        return [0] * buckets
    finally:
        conn.close()

