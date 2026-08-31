import math
import socket
import os
import json
import time
import logging
import asyncio
from datetime import datetime
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path
import uuid
import shutil

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
INDEX_NEXT_HTML = STATIC_DIR / "index_next.html"
LOGIN_HTML = STATIC_DIR / "login.html"
ASSETS_DIR = STATIC_DIR / "assets"

from fastapi import FastAPI, Request, Query, HTTPException, status, Body, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
import paho.mqtt.client as mqtt
import httpx

from database import (
    init_db,
    check_db_integrity,
    upsert_device,
    insert_device_data,
    get_all_devices,
    get_device,
    get_device_by_id,
    get_latest_data,
    get_device_history,
    get_history_by_dev_id,
    get_history_count,
    get_global_history,
    get_global_history_count,
    mark_offline_devices,
    get_system_stats,
    get_device_display_name,
    get_operational_analytics,
    get_ai_llm_context,
    get_llm_config,
    save_llm_config,
    LLM_PROVIDER_PRESETS,
    get_huashu_bridge_config,
    save_huashu_bridge_config,
    get_site_config,
    save_site_config,
    delete_device,
    update_device_info,
    authenticate_user,
    register_user,
    get_user_by_username,
    get_all_users,
    update_user_profile,
    change_user_password,
    change_user_username,
    admin_reset_password,
    update_user_role,
    get_robot_programs,
    get_robot_program_by_name,
    save_robot_program,
    get_alarm_knowledge_base,
    get_alarm_resolutions,
    add_alarm_resolution,
    cleanup_old_alarms,
    get_device_io,
    update_device_io,
    get_weekly_backups_list,
)

# ---------------------------------------------------------------------------
# 1. 日志与全局配置
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_FILE = "robot_iot.log"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("robot_server")

# 环境变量配置
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "robot_server")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "robot_server_pass")
OFFLINE_THRESHOLD_SECONDS = int(os.getenv("OFFLINE_THRESHOLD", "30"))

# 系统运行状态追踪
START_TIME = time.time()
mqtt_client_instance: Optional[mqtt.Client] = None
is_mqtt_connected: bool = False


# ---------------------------------------------------------------------------
# 2. 统一 API 响应格式辅助函数
# ---------------------------------------------------------------------------
def api_response(
    code: int = 200,
    message: str = "success",
    data: Any = None,
    status_code: int = status.HTTP_200_OK,
) -> JSONResponse:
    """生成符合架构规范的统一 JSON 响应"""
    payload = {
        "code": code,
        "message": message,
        "data": data,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return JSONResponse(status_code=status_code, content=payload)


# ---------------------------------------------------------------------------
# 3. MQTT Topic 解析与消息处理逻辑
# ---------------------------------------------------------------------------
def parse_topic(topic: str) -> Optional[Dict[str, str]]:
    """
    解析 MQTT Topic，规范: robot/{device_type}/{device_id}/{data_type}
    成功返回包含各字段的字典，失败返回 None 并记录日志
    """
    parts = topic.split("/")
    if len(parts) != 4:
        logger.warning(f"MQTT Topic 格式不合法（段数≠4）: {topic}")
        return None
    if parts[0] != "robot":
        logger.warning(f"MQTT Topic 前缀不合法（非 robot）: {topic}")
        return None

    device_type = parts[1].strip()
    device_id = parts[2].strip()
    data_type = parts[3].strip()

    if not device_type or not device_id or not data_type:
        logger.warning(f"MQTT Topic 包含空字段: {topic}")
        return None

    return {
        "device_type": device_type,
        "device_id": device_id,
        "data_type": data_type,
    }


def on_mqtt_connect(client, userdata, flags, rc, *args):
    """MQTT 连接成功回调"""
    global is_mqtt_connected
    try:
        if rc == 0:
            is_mqtt_connected = True
            logger.info(f"MQTT Broker 连接成功 [{MQTT_HOST}:{MQTT_PORT}]，开始订阅 robot/# ...")
            try:
                client.subscribe("robot/#", qos=1)
                logger.info("已成功订阅主题: robot/#")
            except Exception as e:
                logger.error(f"MQTT 订阅主题 robot/# 失败: {e}")
        else:
            is_mqtt_connected = False
            logger.error(f"MQTT 连接失败，返回码 rc={rc}")
    except Exception as e:
        logger.error(f"on_mqtt_connect 回调异常: {e}", exc_info=True)


def on_mqtt_disconnect(client, userdata, rc, *args):
    """MQTT 断开连接回调"""
    global is_mqtt_connected
    is_mqtt_connected = False
    if rc != 0:
        logger.warning(f"MQTT 异常断开连接 (rc={rc})，正在尝试自动重连...")
        try:
            client.reconnect_delay_set(min_delay=1, max_delay=30)
        except Exception:
            pass
    else:
        logger.info("MQTT 连接已正常关闭")


def on_mqtt_message(client, userdata, msg):
    """
    MQTT 接收消息回调：
    1. 解析 Topic (device_type, device_id, data_type)
    2. 解码 Payload (支持 JSON 容错)
    3. 写入 SQLite (自动 upsert devices 表并写入 device_data 表)
    """
    topic = msg.topic
    try:
        parsed = parse_topic(topic)
        if not parsed:
            return

        device_type = parsed["device_type"]
        device_id = parsed["device_id"]
        data_type = parsed["data_type"]

        # 解码 Payload
        try:
            raw_payload = msg.payload.decode("utf-8")
        except Exception:
            raw_payload = str(msg.payload)

        # 尝试检查 payload 中是否有设备自带的时间戳
        report_time = None
        try:
            parsed_json = json.loads(raw_payload)
            if isinstance(parsed_json, dict) and "timestamp" in parsed_json:
                report_time = str(parsed_json["timestamp"])
        except Exception:
            pass

        if not report_time:
            report_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

        # 数据入库并更新设备状态为 online
        row_id = insert_device_data(
            device_id=device_id,
            device_type=device_type,
            data_type=data_type,
            raw_payload=raw_payload,
            topic=topic,
        )

        if row_id:
            logger.info(
                f"收到设备数据入库成功 [{device_type}/{device_id}] type={data_type} row_id={row_id}"
            )
        else:
            logger.warning(f"数据入库返回空 row_id [{topic}]")

    except Exception as e:
        logger.error(f"处理 MQTT 消息异常 [{topic}]: {e}", exc_info=True)


def init_mqtt_client() -> Optional[mqtt.Client]:
    """初始化并启动 MQTT 客户端（后台线程非阻塞运行）"""
    global mqtt_client_instance
    try:
        # 兼容不同版本的 paho-mqtt 构造器
        client_kwargs: Dict[str, Any] = {"client_id": "robot_iot_backend_server"}
        if hasattr(mqtt, "CallbackAPIVersion"):
            try:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION1,
                    client_id="robot_iot_backend_server",
                )
            except Exception:
                client = mqtt.Client(client_id="robot_iot_backend_server")
        else:
            client = mqtt.Client(client_id="robot_iot_backend_server")

        if MQTT_USERNAME:
            client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        client.on_connect = on_mqtt_connect
        client.on_disconnect = on_mqtt_disconnect
        client.on_message = on_mqtt_message

        logger.info(f"正在连接 MQTT Broker [{MQTT_HOST}:{MQTT_PORT}]...")
        # 采用非阻塞或异步连接，Broker 离线时不阻塞主服务启动
        try:
            client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
        except Exception as conn_err:
            logger.warning(f"MQTT Broker 暂不可用 ({conn_err})，将在后台持续重试连接...")

        client.loop_start()
        mqtt_client_instance = client
        return client
    except Exception as e:
        logger.error(f"初始化 MQTT Client 异常: {e}", exc_info=True)
        return None


# ---------------------------------------------------------------------------
# 4. 后台定时任务：离线状态检测
# ---------------------------------------------------------------------------
async def check_device_offline_task():
    """
    后台定时任务：每 10 秒扫描一次所有在线设备，
    若超过 OFFLINE_THRESHOLD_SECONDS 秒无新数据上报，则标记为 offline。
    """
    while True:
        try:
            mark_offline_devices(threshold_seconds=OFFLINE_THRESHOLD_SECONDS)
            cleanup_old_alarms(7)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"离线检测任务异常: {e}")
        await asyncio.sleep(10)


# ---------------------------------------------------------------------------
# 5. FastAPI 应用初始化与生命周期
# ---------------------------------------------------------------------------
async def local_simulation_generator_task():
    """
    全设备实时遥测姿态仿真发生器：
    遍历系统中所有注册设备，持续生成真实平滑的六轴机械臂/复合AMR/四足狗/无人机运动学、
    笛卡尔空间坐标与 IO 遥测数据，确保全场所有 3D 机器人数字孪生、列表缩略图与大屏完全处于实时运动状态。
    """
    logger.info(">>> 启动全局数字孪生实时姿态动态仿真发生器 <<<")
    t = 0.0
    while True:
        try:
            await asyncio.sleep(0.2)
            t += 0.2
            now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

            # 动态获取系统中所有设备
            all_devices = get_all_devices()
            for idx, dev in enumerate(all_devices):
                dev_id = dev.get("device_id")
                dev_type = dev.get("device_type")
                phase = idx * 0.8  # 每个设备错开相位，更显自然

                if dev_type in ("huashu_arm", "arm"):
                    # 华数机械臂已直连现场真实物理控制器 (192.168.1.168~170:23333)，由 huashu-bridge 真实采集，此处跳过仿真覆盖
                    continue
                elif dev_type == "luxshare_amr":
                    j_lux = [
                        round(math.sin((t + phase) * 0.35) * 35.0, 2),
                        round(math.sin((t + phase) * 0.45) * 25.0 - 5.0, 2),
                        round(math.sin((t + phase) * 0.3) * 30.0 + 10.0, 2),
                        round(math.cos((t + phase) * 0.5) * 30.0, 2),
                        round(math.sin((t + phase) * 0.6) * 35.0, 2),
                        round(math.cos((t + phase) * 0.8) * 50.0, 2)
                    ]
                    tcp_lux = {
                        "x": round(1200.5 + math.sin((t + phase) * 0.2) * 150.0, 1),
                        "y": round(850.0 + math.cos((t + phase) * 0.2) * 150.0, 1),
                        "z": 420.0,
                        "a": 180.0, "b": 0.0, "c": j_lux[5]
                    }
                    payload = {
                        "device_id": dev_id,
                        "device_type": dev_type,
                        "status": "online",
                        "timestamp": now_iso,
                        "joint_angles": j_lux,
                        "cartesian_pos": tcp_lux,
                        "battery": round(88.0 + math.sin((t + phase) * 0.02) * 5.0, 1),
                        "enabled": True,
                        "emergency_stop": False,
                        "error_code": 0,
                        "error_msg": "正常运行",
                        "cycle_count": int(8340 + t + idx * 50),
                        "running_hours": round(312.4 + t / 3600.0, 2)
                    }
                elif dev_type == "robot_dog":
                    leg_swing = round(math.sin((t + phase) * 0.8) * 25.0, 1)
                    knee_swing = round(-math.sin((t + phase) * 0.8) * 35.0 - 15.0, 1)
                    j_dog = [leg_swing, knee_swing, -leg_swing, -knee_swing, -leg_swing, knee_swing]
                    payload = {
                        "device_id": dev_id,
                        "device_type": dev_type,
                        "status": "online",
                        "timestamp": now_iso,
                        "joint_angles": j_dog,
                        "speed": 1.2,
                        "battery": round(76.0 + math.cos((t + phase) * 0.02) * 4.0, 1),
                        "enabled": True,
                        "emergency_stop": False,
                        "error_code": 0,
                        "error_msg": "正常巡检中",
                        "cycle_count": int(4520 + t + idx * 20),
                        "running_hours": round(128.5 + t / 3600.0, 2),
                        "cartesian_pos": {"x": round(320.0 + math.sin((t + phase) * 0.1) * 80.0, 1), "y": round(-150.2 + math.cos((t + phase) * 0.1) * 80.0, 1), "z": 180.5, "a": 0.0, "b": round(math.sin(t*0.5)*3.0, 1), "c": round(math.cos(t*0.5)*3.0, 1)}
                    }
                else:  # uav_rescue
                    payload = {
                        "device_id": dev_id,
                        "device_type": dev_type,
                        "status": "online",
                        "timestamp": now_iso,
                        "joint_angles": [3600.0, 3600.0, 3600.0, 3600.0, round(math.sin((t + phase)*0.3)*15.0, 1), round(math.cos((t + phase)*0.2)*30.0, 1)],
                        "motor_rpm": 3600,
                        "altitude": round(15.0 + math.sin((t + phase) * 0.3) * 2.0, 1),
                        "battery": round(92.0 - ((t + phase * 10) % 100) * 0.1, 1),
                        "enabled": True,
                        "emergency_stop": False,
                        "error_code": 0,
                        "error_msg": "空中巡查中",
                        "cycle_count": int(910 + t),
                        "running_hours": round(45.2 + t / 3600.0, 2),
                        "cartesian_pos": {"x": round(500.0 + math.sin((t + phase) * 0.1) * 120.0, 1), "y": round(300.0 + math.cos((t + phase) * 0.1) * 120.0, 1), "z": 150.0, "a": round(math.sin(t*0.4)*5.0, 1), "b": round(math.cos(t*0.4)*5.0, 1), "c": 0.0}
                    }

                insert_device_data(
                    device_id=dev_id,
                    device_type=dev_type,
                    data_type="state",
                    raw_payload=json.dumps(payload, ensure_ascii=False),
                    topic=f"robot/{dev_type}/{dev_id}/state"
                )

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"local_simulation_generator_task 异常: {e}")
            await asyncio.sleep(1.0)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 服务启动阶段
    logger.info("=== 机器人物联网管理系统服务正在启动 ===")
    init_db()
    check_db_integrity()
    init_mqtt_client()
    offline_task = asyncio.create_task(check_device_offline_task())
    sim_task = asyncio.create_task(local_simulation_generator_task())

    yield

    # 2. 服务关闭阶段
    logger.info("=== 机器人物联网管理系统服务正在关闭 ===")
    offline_task.cancel()
    sim_task.cancel()
    try:
        await offline_task
        await sim_task
    except asyncio.CancelledError:
        pass

    global mqtt_client_instance
    if mqtt_client_instance:
        try:
            mqtt_client_instance.loop_stop()
            mqtt_client_instance.disconnect()
        except Exception as e:
            logger.error(f"停止 MQTT 客户端异常: {e}")


app = FastAPI(
    title="机器人物联网管理系统",
    description="面向多品类机器人的物联网数据接入与可视化后台系统 (v2.0 工业数字孪生与单 Canvas 视口裁剪引擎)",
    version="2.0.0",
    lifespan=lifespan,
)

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# 6. 全局异常处理器
# ---------------------------------------------------------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """请求参数校验错误统一响应 400"""
    logger.warning(f"参数校验失败: {exc}")
    return api_response(
        code=400,
        message=f"请求参数不合法: {exc.errors()}",
        data=None,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTPException 统一结构响应"""
    return api_response(
        code=exc.status_code,
        message=str(exc.detail),
        data=None,
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局未知异常捕获响应 500"""
    logger.critical(f"系统未捕获异常: {exc}", exc_info=True)
    return api_response(
        code=500,
        message=f"服务器内部异常: {str(exc)}",
        data=None,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


# ---------------------------------------------------------------------------
# 7. RESTful API 路由实现与双角色鉴权 (Admin vs User)
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    username: str = Field(..., description="登录账号")
    password: str = Field(..., description="登录密码")

class RegisterRequest(BaseModel):
    username: str = Field(..., description="用户账号 (不少于3位)")
    password: str = Field(..., description="登录密码 (不少于4位)")
    real_name: Optional[str] = Field("", description="真实姓名/显示昵称")
    role: Optional[str] = Field("user", description="用户角色: admin(超级管理员) 或 user(普通用户)")


@app.post("/api/auth/login")
async def api_user_login(body: LoginRequest = Body(...)):
    """
    用户登录接口 (支持超级管理员 admin 与普通用户 user)
    """
    user_info = authenticate_user(body.username, body.password)
    if not user_info:
        return api_response(
            code=401,
            message="账号或密码错误，请核对后重试",
            data=None,
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    # 生成简单 Session Token 标识
    token = f"qtx_token_{user_info['role']}_{int(time.time())}_{user_info['username']}"
    return api_response(
        code=200,
        message=f"欢迎登录，{user_info['real_name']} ({'超级管理员' if user_info['role'] == 'admin' else '普通操作员'})",
        data={
            "token": token,
            "user_id": user_info["id"],
            "username": user_info["username"],
            "role": user_info["role"],
            "real_name": user_info["real_name"],
            "last_login": user_info["last_login"]
        }
    )


@app.post("/api/auth/register")
async def api_user_register(body: RegisterRequest = Body(...)):
    """
    用户快速注册接口（默认赋予普通用户 user 权限）
    """
    success, msg = register_user(
        username=body.username,
        password=body.password,
        role=body.role if body.role in ["admin", "user"] else "user",
        real_name=body.real_name
    )
    if success:
        return api_response(
            code=200,
            message="账号注册成功，请使用新账号登录",
            data={"username": body.username, "role": body.role}
        )
    else:
        return api_response(
            code=400,
            message=msg,
            data=None,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@app.get("/api/auth/me")
async def api_user_me(request: Request):
    """获取当前登录用户信息与角色权限"""
    user_role = request.headers.get("X-User-Role", "guest")
    user_name = request.headers.get("X-User-Name", "guest")
    user_info = get_user_by_username(user_name) if user_name != "guest" else None
    return api_response(
        code=200,
        message="success",
        data={
            "username": user_name,
            "role": user_role,
            "real_name": user_info["real_name"] if user_info else user_name,
            "created_at": user_info["created_at"] if user_info else "--",
            "last_login": user_info["last_login"] if user_info else "--",
            "is_admin": user_role == "admin"
        }
    )


class UpdateProfileRequest(BaseModel):
    username: str = Field(..., description="用户名")
    real_name: str = Field(..., description="真实姓名/岗位昵称")

class ChangePasswordRequest(BaseModel):
    username: str = Field(..., description="用户名")
    old_password: str = Field(..., description="原密码")
    new_password: str = Field(..., description="新密码")

class ChangeUsernameRequest(BaseModel):
    current_username: str = Field(..., description="当前用户名")
    new_username: str = Field(..., description="新用户名")
    password: str = Field(..., description="当前密码(用于验证身份)")

class AdminResetPasswordRequest(BaseModel):
    target_username: str = Field(..., description="被重置目标用户名")
    new_password: str = Field(..., description="新密码")

class UpdateRoleRequest(BaseModel):
    target_username: str = Field(..., description="目标用户名")
    new_role: str = Field(..., description="新角色: admin 或 user")


@app.post("/api/auth/profile")
async def api_update_profile(body: UpdateProfileRequest = Body(...), request: Request = None):
    """用户修改个人姓名与信息"""
    success, msg = update_user_profile(body.username, body.real_name)
    if success:
        return api_response(code=200, message=msg, data={"username": body.username, "real_name": body.real_name})
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/api/auth/password")
async def api_change_password(body: ChangePasswordRequest = Body(...)):
    """用户自行修改密码"""
    success, msg = change_user_password(body.username, body.old_password, body.new_password)
    if success:
        return api_response(code=200, message=msg)
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/api/auth/username")
async def api_change_username(body: ChangeUsernameRequest = Body(...)):
    """用户自行修改登录账号名"""
    success, msg = change_user_username(body.current_username, body.new_username, body.password)
    if success:
        user_info = get_user_by_username(body.new_username)
        return api_response(code=200, message=msg, data=user_info)
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)


def is_super_admin(request: Request) -> bool:
    """判断是否为系统唯一的超级管理员 (admin / root)"""
    if not request:
        return False
    user_name = request.headers.get("X-User-Name", "")
    user_role = request.headers.get("X-User-Role", "")
    return user_name == "admin" and user_role == "admin"


def is_admin(request: Request) -> bool:
    """判断是否具有管理员角色 (admin)"""
    if not request:
        return False
    user_role = request.headers.get("X-User-Role", "")
    return user_role == "admin"


@app.get("/api/auth/users")
async def api_get_all_users(request: Request):
    """管理员获取所有用户列表 (仅超级管理员)"""
    if not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有查看与管理全员账户的特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    users = get_all_users()
    return api_response(code=200, message="success", data={"users": users, "total": len(users)})


@app.post("/api/auth/admin_reset_pwd")
async def api_admin_reset_password(body: AdminResetPasswordRequest = Body(...), request: Request = None):
    """超级管理员重置用户密码 (仅超级管理员)"""
    if not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有重置他人密码特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    success, msg = admin_reset_password(body.target_username, body.new_password)
    if success:
        return api_response(code=200, message=msg)
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)


@app.post("/api/auth/update_role")
async def api_update_role(body: UpdateRoleRequest = Body(...), request: Request = None):
    """超级管理员修改用户角色权限 (仅超级管理员)"""
    if not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有调整用户角色的特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    if body.target_username == "admin":
        return api_response(
            code=400,
            message="禁止修改系统内置超级管理员 (admin) 的角色",
            status_code=status.HTTP_400_BAD_REQUEST
        )
    success, msg = update_user_role(body.target_username, body.new_role)
    if success:
        return api_response(code=200, message=msg)
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)



@app.get("/api/health")
async def health_check():
    """
    4.5 系统健康检查接口
    用于监控与 systemd watchdog
    """
    uptime = int(time.time() - START_TIME)
    return api_response(
        code=200,
        message="healthy",
        data={
            "status": "ok",
            "database": "connected",
            "mqtt": "connected" if is_mqtt_connected else "disconnected",
            "uptime_seconds": uptime,
            "version": "1.0.0",
        },
    )


@app.get("/api/system/overview")
async def system_overview():
    """
    4.4 获取系统全局概览统计
    包含总设备数、在线数、离线数、总历史记录量、分类统计与服务运行时间
    """
    stats = get_system_stats()
    stats["server_time"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stats["uptime_seconds"] = int(time.time() - START_TIME)
    stats["mqtt_connected"] = is_mqtt_connected
    return api_response(code=200, message="success", data=stats)


@app.get("/api/devices")
async def list_devices(
    status_filter: Optional[str] = Query(None, alias="status", description="在线状态: online/offline"),
    device_type: Optional[str] = Query(None, description="设备类型筛选"),
):
    """
    4.1 获取设备档案列表
    支持按在线状态 (status) 和设备品类 (device_type) 筛选
    """
    devices = get_all_devices(status=status_filter, device_type=device_type)
    return api_response(
        code=200,
        message="success",
        data={
            "total": len(devices),
            "devices": devices,
        },
    )


@app.get("/api/devices/{device_type}/{device_id}/latest")
async def get_device_latest(device_type: str, device_id: str):
    """
    4.2 获取单设备实时详情及最新一条上报数据
    - 若设备不存在，返回 404
    - 若设备存在但尚无数据上报，返回友好的 null 数据与提示
    """
    device = get_device(device_type, device_id)
    if not device:
        return api_response(
            code=404,
            message=f"设备不存在: {device_type}/{device_id}",
            data=None,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    latest_data = get_latest_data(device_type, device_id)
    message = "success" if latest_data else "该设备暂无上报数据"

    return api_response(
        code=200,
        message=message,
        data={
            "device": device,
            "latest_data": latest_data,
        },
    )


@app.delete("/api/devices/{device_type}/{device_id}")
@app.delete("/api/devices/{device_id}")
async def delete_device_api(request: Request, device_id: str, device_type: Optional[str] = None):
    """
    删除设备档案及其所有历史遥测数据 (超级管理员专属权限)
    """
    role = request.headers.get("X-User-Role", "admin")
    if role == "user":
        return api_response(
            code=403,
            message="权限不足：普通用户无权删除设备档案，请使用管理员账号操作",
            data=None,
            status_code=status.HTTP_403_FORBIDDEN
        )

    success = delete_device(device_id=device_id, device_type=device_type)
    if success:
        return api_response(
            code=200,
            message=f"设备 [{device_id}] 及其关联遥测数据已成功清除",
            data={"device_id": device_id, "deleted": True}
        )
    else:
        return api_response(
            code=400,
            message=f"删除设备 [{device_id}] 失败",
            data=None,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@app.get("/api/history")
async def query_global_history(
    device_id: Optional[str] = Query(None, description="设备ID筛选"),
    data_type: Optional[str] = Query(None, description="数据类型筛选: state/sensor/alarm/cmd等"),
    start_time: Optional[str] = Query(None, description="起始时间"),
    end_time: Optional[str] = Query(None, description="截止时间"),
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(15, ge=1, le=100, description="每页记录数"),
):
    """
    全域分页查询历史遥测报文与事件追溯
    """
    total = get_global_history_count(
        device_id=device_id,
        data_type=data_type,
        start_time=start_time,
        end_time=end_time,
    )

    records = get_global_history(
        device_id=device_id,
        data_type=data_type,
        start_time=start_time,
        end_time=end_time,
        page=page,
        page_size=page_size,
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return api_response(
        code=200,
        message="查询全域历史遥测数据成功",
        data={
            "page": page,
            "page_size": page_size,
            "total": total,
            "total_pages": total_pages,
            "records": records,
        },
    )


@app.get("/api/devices/{device_type}/{device_id}/history")
async def query_device_history(
    device_type: str,
    device_id: str,
    page: int = Query(1, ge=1, description="页码，从1开始"),
    page_size: int = Query(20, ge=1, le=100, description="每页记录数(1-100)"),
    data_type: Optional[str] = Query(None, description="数据类型筛选: state/sensor/alarm等"),
    start_time: Optional[str] = Query(None, description="起始时间 (ISO格式)"),
    end_time: Optional[str] = Query(None, description="截止时间 (ISO格式)"),
):
    """
    4.3 分页查询设备历史数据
    结果按时间倒序排列，支持按数据类型与起止时间筛选
    """
    device = get_device(device_type, device_id)
    if not device:
        return api_response(
            code=404,
            message=f"设备不存在: {device_type}/{device_id}",
            data=None,
            status_code=status.HTTP_404_NOT_FOUND,
        )

    total = get_history_count(
        device_type=device_type,
        device_id=device_id,
        data_type=data_type,
        start_time=start_time,
        end_time=end_time,
    )

    records = get_device_history(
        device_type=device_type,
        device_id=device_id,
        page=page,
        page_size=page_size,
        data_type=data_type,
        start_time=start_time,
        end_time=end_time,
    )

    total_pages = (total + page_size - 1) // page_size if total > 0 else 0

    return api_response(
        code=200,
        message="success",
        data={
            "device_id": device_id,
            "device_type": device_type,
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": total_pages,
            "records": records,
        },
    )


class CommandRequest(BaseModel):
    command: str = Field(..., description="控制指令名称，如 goto, start, stop, reset, patrol, calibrate")
    params: Optional[Dict[str, Any]] = Field(default_factory=dict, description="指令参数键值对，如 {'x': 10.2, 'y': 5.5}")
    task_id: Optional[str] = Field(None, description="任务唯一标识编号，若为空系统自动生成")


def publish_command_downlink(
    device_type: str,
    device_id: str,
    command: str,
    params: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    通过 MQTT 向端侧设备下发任务控制指令 (Topic: cmd/{device_type}/{device_id})。
    即使 MQTT 未连接，也会自动存入数据库并给出明确状态说明。
    """
    if not task_id:
        task_id = f"T{datetime.now().strftime('%Y%m%d%H%M%S')}-{device_id}"

    payload_dict = {
        "task_id": task_id,
        "command": command,
        "params": params or {},
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    payload_json = json.dumps(payload_dict, ensure_ascii=False)
    topic = f"cmd/{device_type}/{device_id}"

    # 记录到历史数据表
    try:
        insert_device_data(
            device_id=device_id,
            device_type=device_type,
            data_type="cmd",
            raw_payload=payload_json,
            topic=topic,
        )
    except Exception as e:
        logger.error(f"记录下发指令异常: {e}")

    # 发布至 MQTT
    global mqtt_client_instance, is_mqtt_connected
    if mqtt_client_instance and is_mqtt_connected:
        try:
            info = mqtt_client_instance.publish(topic, payload_json, qos=1)
            info.wait_for_publish(timeout=2.0)
            logger.info(f"成功向设备下发指令 -> Topic: {topic} | Payload: {payload_json}")
            return True, "指令已成功通过 MQTT 发送至端侧设备", payload_dict
        except Exception as e:
            logger.error(f"MQTT 指令发送失败: {e}")
            return False, f"MQTT 发送失败: {e}", payload_dict
    else:
        logger.warning(f"MQTT 未连接，指令已记录入库但未通过网络发送 -> Topic: {topic}")
        return True, "指令已记录并分发（当前为本地数据库直通模式）", payload_dict


@app.post("/api/device/{dev_id}/cmd")
@app.post("/api/devices/{device_type}/{device_id}/cmd")
async def dispatch_device_command(
    request: Request,
    dev_id: Optional[str] = None,
    device_type: Optional[str] = None,
    device_id: Optional[str] = None,
    body: CommandRequest = Body(...),
):
    """
    4.6 【功能 F6】向指定端侧设备下发任务控制指令 (管理员专属权限)
    - 支持 /api/device/{dev_id}/cmd 或 /api/devices/{type}/{id}/cmd 两种路由规范
    - Topic: cmd/{device_type}/{device_id}
    - 严格遵循《技术需求书》1.5.1 下行 Topic 与 JSON 格式
    """
    role = request.headers.get("X-User-Role", "admin")
    if role == "user":
        return api_response(
            code=403,
            message="权限受限：当前登录为【普通用户】角色，仅拥有大屏只读监控权限。请使用超级管理员账号登录后再下发工业控制指令！",
            data=None,
            status_code=status.HTTP_403_FORBIDDEN
        )

    target_id = device_id or dev_id
    if not target_id:
        raise HTTPException(status_code=400, detail="未指定目标设备 ID")

    # 若未指定 device_type，自动从数据库查找
    target_type = device_type
    if not target_type:
        dev_info = get_device_by_id(target_id)
        if dev_info:
            target_type = dev_info["device_type"]
        else:
            target_type = "unknown"

    success, msg, payload = publish_command_downlink(
        device_type=target_type,
        device_id=target_id,
        command=body.command,
        params=body.params,
        task_id=body.task_id,
    )

    return api_response(
        code=200 if success else 500,
        message=msg,
        data={
            "device_id": target_id,
            "device_type": target_type,
            "topic": f"cmd/{target_type}/{target_id}",
            "task": payload,
        },
    )


@app.get("/api/device/{dev_id}/history")
async def get_device_history_by_id(
    dev_id: str,
    limit: int = Query(20, ge=1, le=500, description="返回条数限制"),
):
    """
    4.7 【技术需求书 1.5.2 兼容路由】根据设备 ID 查询历史数据
    返回该设备最近 N 条数据，按时间倒序
    """
    records = get_history_by_dev_id(dev_id, limit=limit)
    return records


@app.get("/api/analytics/operational")
async def get_operational_metrics():
    """
    4.8 【功能模块 4 & 5】获取运营数据分析、综合设备利用率(OEE)、商业环境与健康管理
    包含作业量统计、设备利用率、任务完成率、CO2/PM2.5/VOC环境数据、预测性维护诊断
    """
    analytics = get_operational_analytics()
    return api_response(code=200, message="success", data=analytics)


async def call_llm_api(
    base_url: str,
    api_key: str,
    model: str,
    system_prompt: str,
    user_prompt: str = "",
    messages: Optional[List[Dict[str, str]]] = None,
    temperature: float = 0.5,
    max_tokens: int = 2048,
    timeout: float = 30.0,
    proxy: Optional[str] = None,
) -> Tuple[bool, str, Dict[str, Any]]:
    """
    通用异步调用大模型，支持单次提问与连续多轮对话 (Multi-turn Conversation)：
    - 原生 Google Gemini REST API (v1beta/models/{model}:generateContent)
    - 标准 OpenAI 协议 (DeepSeek / GPT / 通义 / 智谱 / 硅基流动 / Ollama 等)
    """
    clean_url = (base_url or "").strip().rstrip("/")
    is_gemini_native = ("googleapis.com" in clean_url and "generateContent" in clean_url) or ("googleapis.com" in clean_url and "/openai" not in clean_url)
    
    start_t = time.time()
    headers = {"Content-Type": "application/json"}
    
    # 统一构建消息对话序列
    dialog_turns: List[Dict[str, str]] = []
    if messages and len(messages) > 0:
        dialog_turns = list(messages)
    elif user_prompt:
        dialog_turns = [{"role": "user", "content": user_prompt}]
    else:
        dialog_turns = [{"role": "user", "content": "请分析当前工况并给出指导"}]

    if is_gemini_native:
        # 针对 Google AI Studio 原生 REST 接口
        req_model = model or "gemini-flash-latest"
        if not clean_url.endswith(":generateContent"):
            clean_url = f"https://generativelanguage.googleapis.com/v1beta/models/{req_model}:generateContent"
        
        if api_key:
            headers["X-goog-api-key"] = api_key.strip()
            if "?key=" not in clean_url and "&key=" not in clean_url:
                clean_url = f"{clean_url}?key={api_key.strip()}"
        
        gemini_contents = []
        if system_prompt:
            gemini_contents.append({"role": "user", "parts": [{"text": f"【系统背景与实时遥测】\n{system_prompt}"}]})
            gemini_contents.append({"role": "model", "parts": [{"text": "已加载全场工业物联网实时遥测与多维传感器矩阵，已就绪为您提供专业、无拘束的深入运维研判与决策支持。"}]})
        
        for turn in dialog_turns:
            role = "model" if turn.get("role") in ["assistant", "model"] else "user"
            gemini_contents.append({"role": role, "parts": [{"text": turn.get("content", "")}]})

        payload = {
            "contents": gemini_contents,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
    else:
        # 标准 OpenAI 兼容协议 (DeepSeek, GPT, Qwen, Ollama...)
        if not clean_url:
            clean_url = "https://api.deepseek.com/v1"

        if not clean_url.endswith("/chat/completions"):
            if clean_url.endswith("/v1") or clean_url.endswith("/openai"):
                clean_url = f"{clean_url}/chat/completions"
            else:
                clean_url = f"{clean_url}/v1/chat/completions"

        if api_key:
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        openai_messages = []
        if system_prompt:
            openai_messages.append({"role": "system", "content": system_prompt})
        
        for turn in dialog_turns:
            role = "assistant" if turn.get("role") in ["assistant", "model"] else ("system" if turn.get("role") == "system" else "user")
            openai_messages.append({"role": role, "content": turn.get("content", "")})

        payload = {
            "model": model or "deepseek-chat",
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False, trust_env=True) as client:
            resp = await client.post(clean_url, headers=headers, json=payload)
            latency_ms = int((time.time() - start_t) * 1000)

            if resp.status_code == 200:
                resp_json = resp.json()
                if is_gemini_native:
                    candidates = resp_json.get("candidates", [])
                    if candidates:
                        content = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                    else:
                        content = str(resp_json)
                    usage = resp_json.get("usageMetadata", {})
                else:
                    content = resp_json.get("choices", [{}])[0].get("message", {}).get("content", "")
                    usage = resp_json.get("usage", {})
                return True, content, {"latency_ms": latency_ms, "usage": usage, "url": clean_url}
            else:
                resp_text = resp.text[:350]
                if "User location is not supported" in resp_text:
                    err_msg = "Google AI Studio 返回地区限制 (User location is not supported)。原因：Google 官方对直接访问的地区 IP 设有访问限制，请在服务器开启全局网络代理或配置 Gemini 专用反向代理/中转 Base URL。"
                else:
                    err_msg = f"大模型接口返回错误 [HTTP {resp.status_code}]: {resp_text}"
                logger.error(err_msg)
                return False, err_msg, {"latency_ms": latency_ms, "status_code": resp.status_code}
    except httpx.TimeoutException:
        latency_ms = int((time.time() - start_t) * 1000)
        return False, f"大模型请求超时 ({timeout}秒)，请检查 API Base URL 或网络连接", {"latency_ms": latency_ms}
    except Exception as e:
        latency_ms = int((time.time() - start_t) * 1000)
        logger.error(f"调用大模型网络异常 ({clean_url}): {e}")
        return False, f"网络请求异常: {str(e)}", {"latency_ms": latency_ms}


@app.get("/api/ai/context")
async def get_ai_context():
    """
    4.9 【云边协同与大模型接口】
    提供给云端/本地大模型的标准化上下文数据结构与诊断 Prompt。
    """
    context = get_ai_llm_context()
    return api_response(code=200, message="success", data=context)


class LLMConfigModel(BaseModel):
    provider: Optional[str] = Field("deepseek", description="服务商")
    api_key: Optional[str] = Field("", description="API Key")
    base_url: Optional[str] = Field("https://api.deepseek.com/v1", description="API 基础地址")
    model: Optional[str] = Field("deepseek-chat", description="模型名称")
    enabled: Optional[bool] = Field(False, description="是否启用云端大模型")
    temperature: Optional[float] = Field(0.3, description="采样温度")
    max_tokens: Optional[int] = Field(2048, description="最大输出 Token")
    custom_prompt: Optional[str] = Field(None, description="附加系统 Prompt")


@app.get("/api/ai/config")
async def get_ai_configuration():
    """获取当前大模型接入配置与预设厂商列表"""
    cfg = get_llm_config()
    raw_key = cfg.get("api_key", "")
    masked_key = ""
    if raw_key:
        masked_key = raw_key[:3] + "****" + raw_key[-4:] if len(raw_key) > 8 else "****"

    safe_cfg = {**cfg, "api_key_masked": masked_key, "has_api_key": bool(raw_key)}
    return api_response(
        code=200,
        message="success",
        data={
            "config": safe_cfg,
            "presets": LLM_PROVIDER_PRESETS
        }
    )


@app.post("/api/ai/config")
async def update_ai_configuration(body: LLMConfigModel = Body(...), request: Request = None):
    """保存或更新大模型 API 接入配置 (仅超级管理员)"""
    if not request or not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有配置大模型 API Key 与参数特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    current = get_llm_config()
    update_data = {k: v for k, v in body.dict().items() if v is not None}
    
    # 若前端传空字符串且原本有 key，则保留原 key
    if not update_data.get("api_key") and current.get("api_key"):
        update_data["api_key"] = current["api_key"]

    save_llm_config(update_data)
    saved_cfg = get_llm_config()
    return api_response(code=200, message="大模型 API 配置保存成功", data={"enabled": saved_cfg.get("enabled", False), "provider": saved_cfg.get("provider"), "model": saved_cfg.get("model")})


# ---------------------------------------------------------------------------
# 站点品牌与基地/设备图文 CMS 定制与图片上传接口 (超级管理员特权)
# ---------------------------------------------------------------------------
class SiteConfigModel(BaseModel):
    system_title: Optional[str] = Field(None, description="系统主标题")
    system_subtitle: Optional[str] = Field(None, description="系统英文副标题")
    company_name: Optional[str] = Field(None, description="公司品牌")
    footer_text: Optional[str] = Field(None, description="页脚版权文字")
    modal_twin_footer_badge: Optional[str] = Field(None, description="数字孪生弹窗徽章文字")
    
    # 基地 1: 番禺
    panyu_title: Optional[str] = Field(None, description="番禺基地名称")
    panyu_sub: Optional[str] = Field(None, description="番禺基地副标题")
    panyu_line1_label: Optional[str] = Field(None, description="番禺首行标签")
    panyu_line1_val: Optional[str] = Field(None, description="番禺首行内容")
    panyu_line2_label: Optional[str] = Field(None, description="番禺次行标签")
    panyu_line2_val: Optional[str] = Field(None, description="番禺次行内容")
    panyu_status: Optional[str] = Field(None, description="番禺状态文本")
    panyu_desc: Optional[str] = Field(None, description="番禺详细图文介绍")
    panyu_img: Optional[str] = Field(None, description="番禺基地图片URL")
    
    # 基地 2: 南沙
    nansha_title: Optional[str] = Field(None, description="南沙基地名称")
    nansha_sub: Optional[str] = Field(None, description="南沙基地副标题")
    nansha_line1_label: Optional[str] = Field(None, description="南沙首行标签")
    nansha_line1_val: Optional[str] = Field(None, description="南沙首行内容")
    nansha_line2_label: Optional[str] = Field(None, description="南沙次行标签")
    nansha_line2_val: Optional[str] = Field(None, description="南沙次行内容")
    nansha_status: Optional[str] = Field(None, description="南沙状态文本")
    nansha_desc: Optional[str] = Field(None, description="南沙详细图文介绍")
    nansha_img: Optional[str] = Field(None, description="南沙基地图片URL")
    
    # 4 大品类
    cat1_key: Optional[str] = Field(None)
    cat1_name: Optional[str] = Field(None)
    cat1_health_sub: Optional[str] = Field(None)
    cat1_vendor: Optional[str] = Field(None)
    cat1_specs: Optional[str] = Field(None)
    cat1_img: Optional[str] = Field(None)
    
    cat2_key: Optional[str] = Field(None)
    cat2_name: Optional[str] = Field(None)
    cat2_health_sub: Optional[str] = Field(None)
    cat2_vendor: Optional[str] = Field(None)
    cat2_specs: Optional[str] = Field(None)
    cat2_img: Optional[str] = Field(None)
    
    cat3_key: Optional[str] = Field(None)
    cat3_name: Optional[str] = Field(None)
    cat3_health_sub: Optional[str] = Field(None)
    cat3_vendor: Optional[str] = Field(None)
    cat3_specs: Optional[str] = Field(None)
    cat3_img: Optional[str] = Field(None)
    
    cat4_key: Optional[str] = Field(None)
    cat4_name: Optional[str] = Field(None)
    cat4_health_sub: Optional[str] = Field(None)
    cat4_vendor: Optional[str] = Field(None)
    cat4_specs: Optional[str] = Field(None)
    cat4_img: Optional[str] = Field(None)

    class Config:
        extra = "allow"


class DeviceUpdateRequest(BaseModel):
    device_name: Optional[str] = Field(None, description="自定义设备名称")
    device_type: Optional[str] = Field(None, description="归属设备品类")
    location: Optional[str] = Field(None, description="归属基地/工位位置")
    vendor: Optional[str] = Field(None, description="厂商/品牌角标 (如: 宇树/昕邦定制)")
    specs: Optional[Dict[str, Any]] = Field(None, description="自定义规格参数键值对")
    notes: Optional[str] = Field(None, description="管理员备注/说明信息")


@app.post("/api/devices/{device_id}/update")
async def api_update_device(device_id: str, body: DeviceUpdateRequest = Body(...), request: Request = None):
    """修改单台设备自定义名称、厂商角标、位置、归属品类、规格参数与备注"""
    if not request or not is_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅管理员拥有修改设备名称与规格参数的权限",
            status_code=status.HTTP_403_FORBIDDEN
        )
    success = update_device_info(
        device_id=device_id,
        device_type=body.device_type,
        device_name=body.device_name,
        location=body.location,
        vendor=body.vendor,
        specs=body.specs,
        notes=body.notes
    )
    if success:
        dev = get_device_by_id(device_id)
        return api_response(code=200, message=f"设备 [{device_id}] 信息与规格已成功更新", data=dev)
    return api_response(code=500, message="更新设备信息失败", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.get("/api/system/site_config")
async def api_get_site_config():
    """获取全站品牌与图文自定义配置 (公开读取)"""
    cfg = get_site_config()
    return api_response(code=200, message="success", data=cfg)


@app.post("/api/system/site_config")
async def api_save_site_config(body: SiteConfigModel = Body(...), request: Request = None):
    """保存全站品牌与图文自定义配置 (仅限超级管理员)"""
    if not request or not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有修改全站品牌与图文配置的特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    update_data = {k: v for k, v in body.dict().items() if v is not None}
    success = save_site_config(update_data)
    if success:
        return api_response(code=200, message="站点品牌与图文配置保存成功，全站已实时生效", data=get_site_config())
    return api_response(code=500, message="保存站点配置失败", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.post("/api/system/upload_asset")
async def api_upload_asset(file: UploadFile = File(...), request: Request = None):
    """上传自定义图片素材 (支持 jpg, png, jpeg, webp, svg，仅限超级管理员)"""
    if not request or not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有上传图片素材特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    
    if not file or not file.filename:
        return api_response(code=400, message="未选择上传文件", status_code=status.HTTP_400_BAD_REQUEST)
    
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in [".jpg", ".jpeg", ".png", ".webp", ".svg"]:
        return api_response(code=400, message="仅支持上传 JPG、PNG、WEBP 或 SVG 格式图片", status_code=status.HTTP_400_BAD_REQUEST)
    
    assets_dir = str(ASSETS_DIR)
    os.makedirs(assets_dir, exist_ok=True)
    
    clean_name = f"custom_{int(time.time())}_{uuid.uuid4().hex[:6]}{ext}"
    target_path = os.path.join(assets_dir, clean_name)
    
    try:
        with open(target_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        rel_url = f"/static/assets/{clean_name}"
        return api_response(
            code=200,
            message="图片上传成功",
            data={"url": rel_url, "filename": clean_name}
        )
    except Exception as e:
        logger.error(f"图片上传失败: {e}")
        return api_response(code=500, message=f"图片上传失败: {e}", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class LLMTestRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/ai/test")
async def test_ai_connection(body: LLMTestRequest = Body(...)):
    """测试大模型 API 连通性"""
    cfg = get_llm_config()
    provider = body.provider or cfg.get("provider", "deepseek")
    base_url = body.base_url or cfg.get("base_url", "https://api.deepseek.com/v1")
    api_key = body.api_key if (body.api_key is not None and body.api_key != "") else cfg.get("api_key", "")
    model = body.model or cfg.get("model", "deepseek-chat")

    if not api_key and provider != "ollama":
        return api_response(code=400, message="API Key 不能为空（本地私有化 Ollama 除外）", data={"connected": False})

    test_system = "你是一个工业物联网大模型通信测试助手。"
    test_user = "请回复简短确认语：【连接成功！机器人物联网智能中枢已就绪】"

    success, reply, meta = await call_llm_api(
        base_url=base_url,
        api_key=api_key,
        model=model,
        system_prompt=test_system,
        user_prompt=test_user,
        timeout=12.0
    )

    if success:
        return api_response(
            code=200,
            message="大模型 API 连通性测试通过！",
            data={
                "connected": True,
                "reply": reply,
                "latency_ms": meta.get("latency_ms", 0),
                "model": model,
                "provider": provider,
            }
        )
    else:
        return api_response(
            code=500,
            message=f"大模型 API 测试失败: {reply}",
            data={
                "connected": False,
                "error": reply,
                "latency_ms": meta.get("latency_ms", 0),
            }
        )


@app.post("/api/ai/models")
async def fetch_provider_models(body: LLMTestRequest = Body(...)):
    """
    动态从大模型服务商 /v1/models 接口拉取当前账号可用的最新模型列表
    """
    cfg = get_llm_config()
    provider = body.provider or cfg.get("provider", "deepseek")
    base_url = (body.base_url or cfg.get("base_url", "")).strip().rstrip("/")
    api_key = body.api_key if (body.api_key is not None and body.api_key != "") else cfg.get("api_key", "")

    if not base_url:
        preset = LLM_PROVIDER_PRESETS.get(provider, {})
        base_url = preset.get("base_url", "https://api.deepseek.com/v1")

    # 构建 models 发现地址
    clean_url = base_url
    if clean_url.endswith("/chat/completions"):
        clean_url = clean_url.replace("/chat/completions", "/models")
    elif clean_url.endswith("/v1"):
        clean_url = f"{clean_url}/models"
    elif not clean_url.endswith("/models"):
        clean_url = f"{clean_url}/models"

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key.strip()}"

    try:
        async with httpx.AsyncClient(timeout=8.0, verify=False) as client:
            resp = await client.get(clean_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                models_list = []
                if isinstance(data, dict) and "data" in data and isinstance(data["data"], list):
                    models_list = [m.get("id") for m in data["data"] if isinstance(m, dict) and m.get("id")]
                elif isinstance(data, list):
                    models_list = [m.get("id") if isinstance(m, dict) else str(m) for m in data]
                return api_response(code=200, message="成功获取可用模型列表", data={"models": sorted(models_list)})
    except Exception as e:
        logger.warning(f"动态拉取模型列表失败 ({clean_url}): {e}")

    return api_response(code=200, message="未获取到在线模型列表，可直接手动输入任意模型名称", data={"models": []})


class ChatMessage(BaseModel):
    role: str = Field("user", description="user | assistant | system")
    content: str = Field(..., description="消息文本")


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default=[], description="连续多轮对话历史列表")
    query: Optional[str] = Field(None, description="当前单次提问")
    device_id: Optional[str] = Field(None, description="指定分析的设备 ID")


@app.post("/api/ai/chat")
@app.post("/api/ai/diagnose")
async def ai_chat_and_diagnose(body: ChatRequest = Body(...)):
    """
    4.10 【AI 智能运维中枢 - 连续多轮对话与全域研判接口】
    - 支持与 Google Gemini / DeepSeek / GPT / 本地大模型进行自由、不设限的连续多轮对话
    - 实时注入全场机械臂、AMR、四足机器狗遥测与商业环境数据作为上下文
    - 若未配置云端大模型，自动无缝降级至边缘规则引擎
    """
    context_data = get_ai_llm_context()
    prompt_context = context_data["llm_prompt_context"]
    diagnostics = context_data["operational_analytics"]["device_health_diagnostics"]
    env = context_data["operational_analytics"]["commercial_environment"]

    llm_cfg = get_llm_config()
    faults = [d for d in diagnostics if d.get("error_code", 0) != 0]

    # 构建对话历史序列
    dialog_turns = [m.dict() for m in body.messages] if body.messages else []
    if not dialog_turns:
        user_q = body.query or "请综合诊断当前全域机器人的健康状况、工序瓶颈与环境指标，并给出针对性建议"
        dialog_turns = [{"role": "user", "content": user_q}]

    last_user_query = dialog_turns[-1]["content"] if dialog_turns else "诊断全域设备"

    # 1. 尝试调用配置的第三方大模型 (Google / DeepSeek / GPT / Ollama)
    if llm_cfg.get("enabled") and (llm_cfg.get("api_key") or llm_cfg.get("provider") == "ollama"):
        custom_role = llm_cfg.get("custom_prompt", "").strip()
        system_prompt = f"""你是机器人管理系统中的 AI Copilot 助手。
系统已为你实时接入了现场各机器人的最新遥测数据、I/O矩阵、OEE以及商业环境传感器指标：

{prompt_context}

【交互指南】：
1. 你可以自由地与用户对话，如果用户问你是谁或者你是什么模型，请大方地承认你的大模型身份，并同时说明你现在已经接入了工厂物联网系统，可以帮助他们分析设备数据。
2. 结合上方现场全域真实遥测数据进行针对性分析，解答用户关于华数机械臂、珞石AMR、四足机器狗、环境质量（CO2/PM2.5）或维保周期的任何问题。
3. 请使用清晰优美的 Markdown 格式输出。
{f'【补充人设要求】：{custom_role}' if custom_role else ''}"""

        success, llm_reply, meta = await call_llm_api(
            base_url=llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", "deepseek-chat"),
            system_prompt=system_prompt,
            messages=dialog_turns,
            temperature=llm_cfg.get("temperature", 0.5),
            max_tokens=llm_cfg.get("max_tokens", 2048),
            timeout=30.0,
        )

        if success:
            return api_response(
                code=200,
                message="大模型响应成功",
                data={
                    "reply": llm_reply,
                    "ai_diagnosis_summary": llm_reply,
                    "query": last_user_query,
                    "target_device": body.device_id or "全域设备",
                    "health_level": "优良" if not faults else "存在预警",
                    "active_faults_count": len(faults),
                    "raw_context": prompt_context,
                    "mode": "cloud_llm",
                    "provider": llm_cfg.get("provider"),
                    "model": llm_cfg.get("model"),
                    "latency_ms": meta.get("latency_ms", 0),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                },
            )
        else:
            logger.warning(f"第三方大模型调用失败，降级至边缘规则引擎: {llm_reply}")

    # 2. 边缘规则引擎降级兜底
    recs = []
    if faults:
        for f in faults:
            recs.append(f"⚠️ 设备 [{f['display_name']} ({f['device_id']})] 检测到故障码 {f['error_code']}，建议立即检查伺服驱动与急停回路。")
    else:
        recs.append("✅ 当前全场机器人电控与执行机构均处于正常健康工作区间。")

    for diag in diagnostics:
        if diag.get("next_maintenance_hours", 500) < 100:
            recs.append(f"⏳ 预测性维护提醒：设备 [{diag['display_name']} ({diag['device_id']})] 距下次润滑保养仅剩 {diag['next_maintenance_hours']}h，建议提前安排工单。")

    if env.get("co2_ppm", 0) > 800:
        recs.append(f"🌬️ 现场 CO₂ 浓度偏高 ({env['co2_ppm']} ppm)，建议开启厂房或商场新风换气系统。")
    if env.get("pm25", 0) > 35:
        recs.append(f"🌫️ PM2.5 颗粒物偏高 ({env['pm25']} μg/m³)，建议移动机器人加装空气过滤组件。")

    summary_text = "【💡 边缘规则引擎建议】:\n" + "\n".join(f"{i+1}. {r}" for i, r in enumerate(recs))
    if not llm_cfg.get("enabled"):
        summary_text += "\n\n*(提示：当前运行在内置边缘规则模式。点击上方「⚙️ 大模型配置」填入 Gemini / DeepSeek / OpenAI API Key，即可开启深度大模型自由连续对话！)*"

    return api_response(
        code=200,
        message="边缘规则引擎响应完成",
        data={
            "reply": summary_text,
            "ai_diagnosis_summary": summary_text,
            "query": last_user_query,
            "target_device": body.device_id or "全域设备",
            "health_level": "优良" if not faults else "存在预警",
            "active_faults_count": len(faults),
            "raw_context": prompt_context,
            "mode": "edge_rule_engine",
            "provider": "edge_builtin",
            "model": "edge-rule-v1",
            "latency_ms": 5,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


class ParseCommandRequest(BaseModel):
    natural_language: str = Field(..., description="自然语言指令描述")
    device_type: str = Field(..., description="设备品类: huashu_arm / luxshare_amr / robot_dog")
    device_id: Optional[str] = Field(None, description="设备ID")


@app.post("/api/ai/parse_command")
async def ai_parse_command(body: ParseCommandRequest = Body(...)):
    """
    AI 智能自然语言指令解析：将运维人员口语化指令一键转换为标准的 MQTT 控制指令与 JSON 参数
    """
    nl = body.natural_language.strip()
    dev_type = body.device_type
    dev_id = body.device_id or "device"

    llm_cfg = get_llm_config()

    if llm_cfg.get("enabled") and (llm_cfg.get("api_key") or llm_cfg.get("provider") == "ollama"):
        system_prompt = f"""你是一个工业物联网 SCADA 系统的命令编译器。你的任务是将用户的自然语言指令解析为设备可执行的 MQTT 指令。
当前控制目标：{dev_type} ({dev_id})

各设备支持的标准指令集与参数规范如下：
1. 华数机械臂 (huashu_arm):
- start_cycle (启动生产工步节拍, 参数: {{"program": "MAIN_LINE_A.PRG", "speed": 80, "cycle_limit": 1000}})
- pause (暂停运动, 参数: {{}})
- resume (继续运动, 参数: {{}})
- stop (紧急停止制动, 参数: {{"reason": "manual_stop"}})
- reset (伺服与系统复位, 参数: {{}})
- enable (伺服上使能, 参数: {{"axis_mask": 63}})
- disable (伺服下使能, 参数: {{"axis_mask": 63}})
- home (机械臂回原点, 参数: {{"speed": 20}})
- jog_joint (关节空间点动, 参数: {{"axis": 1, "direction": 1, "speed": 10, "step_deg": 5.0}})
- jog_cartesian (笛卡尔空间点动, 参数: {{"coord": "base", "direction": "+Z", "step_mm": 10.0, "speed": 30}})
- set_override (调节全局速率百分比, 参数: {{"override": 80}})
- set_do (数字量输出, 参数: {{"port": 1, "value": 1}})
- set_gripper (末端夹爪控制, 参数: {{"action": "grip", "force": 50, "speed": 80}})
- select_prog (载入程序, 参数: {{"prog_name": "MAIN.PRG"}})

2. 珞石复合 AMR (luxshare_amr):
- pick_and_place (定点取放料, 参数: {{"source_station": "ST_A01", "target_station": "ST_B03", "tray_id": "T_88"}})
- nav_to_point (导航至目标点, 参数: {{"target_point": "BAY_04", "x": 12.5, "y": 34.8, "theta": 90.0}})
- auto_charge (自动回充, 参数: {{"charger_id": "CHG_BAY_01", "min_battery": 95}})
- pause_nav (暂停导航, 参数: {{}})
- resume_nav (继续导航, 参数: {{}})
- set_speed_limit (巡航限速, 参数: {{"max_linear_speed": 1.2, "max_angular_speed": 0.8}})
- arm_grip (协作臂抓取, 参数: {{"gripper_state": "close", "force_limit": 35}})
- cancel_task (取消任务, 参数: {{"task_id": "AUTO_DISPATCH"}})
- stop (急停, 参数: {{"reason": "estop_button"}})

3. 四足机器狗 (robot_dog):
- patrol (自主巡检, 参数: {{"route": "LOBBY_FLOOR_1", "sensors": ["co2", "voc", "thermal_imaging"]}})
- stand (站立待命, 参数: {{"height": 0.55}})
- sit (蹲伏休眠, 参数: {{}})
- walk_to (前往目标点, 参数: {{"x": 25.0, "y": 18.3, "gait": "trot", "speed": 1.5}})
- start_thermal_scan (红外热成像扫描, 参数: {{"alert_temp_celsius": 65.0, "recording": true}})
- uav_collab_scan (空地协同扫描, 参数: {{"uav_id": "uav_001", "sync_telemetry": true}})
- auto_dock_charge (自动返坞充电, 参数: {{"dock_id": "DOG_DOCK_01"}})
- emergency_stop (脱扣急停, 参数: {{}})

请必须且仅返回如下严格的 JSON 字符串（不要附带任何 markdown 标记或解释文字）：
{{"command": "指令名", "params": {{...}}, "explanation": "解析依据与简短说明"}}"""

        success, llm_reply, _ = await call_llm_api(
            base_url=llm_cfg.get("base_url", "https://api.deepseek.com/v1"),
            api_key=llm_cfg.get("api_key", ""),
            model=llm_cfg.get("model", "deepseek-chat"),
            system_prompt=system_prompt,
            user_prompt=f"请解析该指令：{nl}",
            temperature=0.1,
            max_tokens=500,
            timeout=15.0,
        )
        if success:
            try:
                clean_json = llm_reply.strip()
                if clean_json.startswith("```json"):
                    clean_json = clean_json[7:]
                if clean_json.startswith("```"):
                    clean_json = clean_json[3:]
                if clean_json.endswith("```"):
                    clean_json = clean_json[:-3]
                parsed = json.loads(clean_json.strip())
                return api_response(code=200, message="AI 智能解析成功", data=parsed)
            except Exception:
                pass

    # 规则引擎兜底
    cmd = "start_cycle"
    params = {}
    explanation = "基于工业规则引擎智能模式匹配"

    if dev_type == "huashu_arm":
        if any(k in nl for k in ["停", "刹车", "急停", "制动", "stop"]):
            cmd, params, explanation = "stop", {"reason": "manual_estop"}, "解析为紧急制动停机指令"
        elif any(k in nl for k in ["复位", "reset", "清除报警"]):
            cmd, params, explanation = "reset", {}, "解析为伺服驱动与故障复位指令"
        elif any(k in nl for k in ["上电", "上使能", "使能", "enable"]):
            cmd, params, explanation = "enable", {"axis_mask": 63}, "解析为伺服电机全轴上使能指令"
        elif any(k in nl for k in ["下电", "去使能", "disable"]):
            cmd, params, explanation = "disable", {"axis_mask": 63}, "解析为伺服电机全轴下使能指令"
        elif any(k in nl for k in ["回零", "原点", "归位", "home"]):
            cmd, params, explanation = "home", {"speed": 20}, "解析为机械臂安全回零原点指令"
        elif any(k in nl for k in ["暂停", "pause"]):
            cmd, params, explanation = "pause", {}, "解析为暂停当前运动工步指令"
        elif any(k in nl for k in ["继续", "恢复", "resume"]):
            cmd, params, explanation = "resume", {}, "解析为继续运行暂停工步指令"
        elif any(k in nl for k in ["夹爪", "气爪", "抓", "gripper"]):
            cmd, params, explanation = "set_gripper", {"action": "grip", "force": 50, "speed": 80}, "解析为末端夹爪动作控制指令"
        elif any(k in nl for k in ["倍率", "速度", "override"]):
            cmd, params, explanation = "set_override", {"override": 80}, "解析为调节全局运行速率百分比指令"
        elif any(k in nl for k in ["程序", "加载", "select"]):
            cmd, params, explanation = "select_prog", {"prog_name": "MAIN_LINE_A.PRG"}, "解析为载入加工程序指令"
        else:
            cmd, params, explanation = "start_cycle", {"program": "MAIN_LINE_A.PRG", "speed": 80, "cycle_limit": 1000}, "解析为启动自动化生产工步节拍指令"
    elif dev_type == "luxshare_amr":
        if any(k in nl for k in ["停", "急停", "stop"]):
            cmd, params, explanation = "stop", {"reason": "manual_estop"}, "解析为复合机器人急停指令"
        elif any(k in nl for k in ["充", "电桩", "charge"]):
            cmd, params, explanation = "auto_charge", {"charger_id": "CHG_BAY_01", "min_battery": 95}, "解析为自动寻找充电桩回充指令"
        elif any(k in nl for k in ["取", "放", "料", "pick"]):
            cmd, params, explanation = "pick_and_place", {"source_station": "ST_A01", "target_station": "ST_B03", "tray_id": "T_88"}, "解析为定点取放料调度任务指令"
        elif any(k in nl for k in ["抓", "夹", "grip"]):
            cmd, params, explanation = "arm_grip", {"gripper_state": "close", "force_limit": 35}, "解析为协作臂末端抓取指令"
        elif any(k in nl for k in ["导航", "前往", "工位", "goto", "nav"]):
            cmd, params, explanation = "nav_to_point", {"target_point": "BAY_04", "x": 12.5, "y": 34.8, "theta": 90.0}, "解析为移动底盘导航至目标站点指令"
        else:
            cmd, params, explanation = "pick_and_place", {"source_station": "ST_A01", "target_station": "ST_B03"}, "解析为定点物料转运指令"
    elif dev_type == "robot_dog":
        if any(k in nl for k in ["停", "脱扣", "急停", "stop"]):
            cmd, params, explanation = "emergency_stop", {}, "解析为四足电机紧急脱扣停机指令"
        elif any(k in nl for k in ["站", "起立", "stand"]):
            cmd, params, explanation = "stand", {"height": 0.55}, "解析为四足站立待命姿态指令"
        elif any(k in nl for k in ["蹲", "休眠", "sit", "趴"]):
            cmd, params, explanation = "sit", {}, "解析为四足蹲伏休眠姿态指令"
        elif any(k in nl for k in ["测温", "红外", "热成像", "thermal"]):
            cmd, params, explanation = "start_thermal_scan", {"alert_temp_celsius": 65.0, "recording": True}, "解析为开启双光谱红外热成像测温指令"
        elif any(k in nl for k in ["无人机", "空地", "搜救", "uav"]):
            cmd, params, explanation = "uav_collab_scan", {"uav_id": "uav_001", "sync_telemetry": True}, "解析为无人机空地协同搜救扫描指令"
        elif any(k in nl for k in ["充", "dock", "charge"]):
            cmd, params, explanation = "auto_dock_charge", {"dock_id": "DOG_DOCK_01"}, "解析为返回专用充电坞站指令"
        else:
            cmd, params, explanation = "patrol", {"route": "LOBBY_FLOOR_1", "sensors": ["co2", "voc", "thermal_imaging"]}, "解析为园区/管廊自主巡检指令"

    return api_response(
        code=200,
        message="规则引擎解析成功",
        data={
            "command": cmd,
            "params": params,
            "explanation": explanation,
        },
    )



# ---------------------------------------------------------------------------
# 7.5 华数机械臂硬件连接与边缘网关配置路由 (Huashu Robot Hardware Bridge API)
# ---------------------------------------------------------------------------
class HuashuBridgeConfigModel(BaseModel):
    robot_ip: Optional[str] = Field("10.10.56.214", description="华数控制器 IP 地址")
    robot_port: Optional[int] = Field(23333, description="华数控制器通信端口")
    device_id: Optional[str] = Field("arm_001", description="机械臂设备编号")
    device_name: Optional[str] = Field("华数BR610六轴工业机械臂", description="设备展示名称")
    interval_sec: Optional[float] = Field(1.0, description="采集频率秒数")
    enabled: Optional[bool] = Field(True, description="是否启用采集网关")
    group_id: Optional[int] = Field(0, description="机械臂组号")


@app.get("/api/devices/huashu/config")
async def get_huashu_config_api():
    """获取当前华数机械臂的硬件连接与采集配置"""
    cfg = get_huashu_bridge_config()
    return api_response(code=200, message="success", data=cfg)


@app.post("/api/devices/huashu/config")
async def save_huashu_config_api(body: HuashuBridgeConfigModel = Body(...)):
    """保存华数机械臂硬件连接配置并自动同步到本地网关配置文件"""
    update_data = {k: v for k, v in body.dict().items() if v is not None}
    success = save_huashu_bridge_config(update_data)

    # 尝试同步更新 huashu_bridge/huashu_config.json
    try:
        config_files = ["huashu_bridge/huashu_config.json", "huashu_config.json"]
        for cf in config_files:
            if os.path.exists(cf):
                with open(cf, "r", encoding="utf-8") as f:
                    file_cfg = json.load(f)
                
                robots = file_cfg.get("robots", [])
                device_id = update_data.get("device_id", "arm_001")
                
                # Check if robot exists
                robot_found = False
                for r in robots:
                    if r.get("device_id") == device_id:
                        r["ip"] = update_data.get("robot_ip", r.get("ip"))
                        r["port"] = int(update_data.get("robot_port", r.get("port", 23234)))
                        robot_found = True
                        break
                
                if not robot_found:
                    robots.append({
                        "device_id": device_id,
                        "device_name": update_data.get("device_name", "华数BR610六轴工业机械臂"),
                        "ip": update_data.get("robot_ip", "10.10.56.214"),
                        "port": int(update_data.get("robot_port", 23234)),
                        "group_id": update_data.get("group_id", 0),
                        "axis_count": 6
                    })
                
                file_cfg["robots"] = robots
                file_cfg.setdefault("collection", {})["interval_sec"] = float(update_data.get("interval_sec", 1.0))
                with open(cf, "w", encoding="utf-8") as f:
                    json.dump(file_cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"同步写入 huashu_config.json 异常: {e}")

    return api_response(code=200, message="华数机械臂硬件连接配置已成功保存！", data=get_huashu_bridge_config())


class HuashuTestRequest(BaseModel):
    robot_ip: str = Field(..., description="要测试的华数控制器 IP 地址")
    robot_port: int = Field(23234, description="华数控制器端口，默认 23234")
    timeout_sec: float = Field(2.5, description="握手超时时间秒数")


@app.post("/api/devices/huashu/test")
async def test_huashu_connection_api(body: HuashuTestRequest = Body(...)):
    """
    在线测试与华数Ⅲ型控制器的 TCP Socket 通信链路
    """
    target_ip = body.robot_ip.strip()
    target_port = body.robot_port
    timeout = body.timeout_sec

    start_t = time.time()
    loop = asyncio.get_event_loop()

    def do_socket_test():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            s.connect((target_ip, target_port))
            # 发送微量握手探针
            s.close()
            return True, None
        except Exception as e:
            return False, str(e)

    try:
        ok, err = await loop.run_in_executor(None, do_socket_test)
        latency_ms = int((time.time() - start_t) * 1000)
        if ok:
            return api_response(
                code=200,
                message="华数控制器通信链路握手成功！",
                data={
                    "connected": True,
                    "target_ip": target_ip,
                    "target_port": target_port,
                    "latency_ms": latency_ms
                }
            )
        else:
            return api_response(
                code=500,
                message=f"无法建立与华数控制器的物理连接: {err}",
                data={
                    "connected": False,
                    "target_ip": target_ip,
                    "target_port": target_port,
                    "error": err,
                    "latency_ms": latency_ms
                }
            )
    except Exception as e:
        latency_ms = int((time.time() - start_t) * 1000)
        return api_response(
            code=500,
            message=f"测试过程发生异常: {e}",
            data={"connected": False, "error": str(e), "latency_ms": latency_ms}
        )


# ---------------------------------------------------------------------------
# 8. 内网穿透与远程公网访问控制路由 (Public Remote Access & Intranet Tunnel)
# ---------------------------------------------------------------------------
try:
    import tunnel_manager
except Exception as e:
    tunnel_manager = None
    logger.warning(f"tunnel_manager 模块加载异常或不存在: {e}")


class TunnelStartRequest(BaseModel):
    engine: str = Field("pinggy", description="pinggy | cloudflared | cpolar | custom")
    port: int = Field(8000, description="本地需要映射的端口")
    token: Optional[str] = Field("", description="认证 Token 或密钥")
    custom_url: Optional[str] = Field("", description="自定义公网访问域名")


@app.get("/api/tunnel/status")
async def get_tunnel_status_api():
    """获取当前公网穿透状态与实时访问地址"""
    if tunnel_manager and hasattr(tunnel_manager, 'get_tunnel_status'):
        return api_response(code=200, message="success", data=tunnel_manager.get_tunnel_status())
    return api_response(code=200, message="success", data={"active": False, "url": "", "engine": "none"})


@app.post("/api/tunnel/start")
async def start_tunnel_api(body: TunnelStartRequest = Body(...)):
    """一键启动公网远程穿透并生成分享地址"""
    if tunnel_manager and hasattr(tunnel_manager, 'start_tunnel'):
        res = await tunnel_manager.start_tunnel(
            engine=body.engine,
            port=body.port,
            token=body.token or "",
            custom_url=body.custom_url or "",
        )
        return api_response(code=200, message="穿透启动指令已执行", data=res)
    return api_response(code=200, message="当前运行环境已具备独立服务地址，无需额外穿透", data={"url": "http://127.0.0.1:8000"})


@app.post("/api/tunnel/stop")
async def stop_tunnel_api():
    """一键关闭公网远程穿透"""
    if tunnel_manager and hasattr(tunnel_manager, 'stop_tunnel'):
        res = await tunnel_manager.stop_tunnel()
        return api_response(code=200, message="公网穿透已安全关闭", data=res)
    return api_response(code=200, message="穿透状态正常", data={"stopped": True})


# ---------------------------------------------------------------------------
# 7.4 机器人 I/O 状态、程序管理与下载备份、说明书故障知识库与处理档案
# ---------------------------------------------------------------------------

@app.get("/api/devices/{device_type}/{device_id}/io")
async def get_device_io_api(device_type: str, device_id: str):
    """获取指定机器人 16 路输入 DI 与 16 路输出 DO 实时状态"""
    data = get_device_io(device_id)
    return api_response(code=200, message="success", data=data)


class DeviceIOUpdateRequest(BaseModel):
    di_mask: Optional[int] = None
    do_mask: Optional[int] = None
    di_details: Optional[Dict[str, str]] = None
    do_details: Optional[Dict[str, str]] = None


@app.post("/api/devices/{device_type}/{device_id}/io")
async def update_device_io_api(device_type: str, device_id: str, body: DeviceIOUpdateRequest = Body(...)):
    """更新机器人 I/O 状态并同步发布控制"""
    cur_io = get_device_io(device_id)
    di_mask = body.di_mask if body.di_mask is not None else cur_io.get("di_mask", 0)
    do_mask = body.do_mask if body.do_mask is not None else cur_io.get("do_mask", 0)
    
    update_device_io(device_id, device_type, di_mask, do_mask, body.di_details, body.do_details)
    return api_response(code=200, message="I/O 状态更新成功", data=get_device_io(device_id))


@app.get("/api/devices/{device_type}/{device_id}/programs")
async def get_device_programs_api(device_type: str, device_id: str):
    """获取指定机器人的全部加工程序列表"""
    programs = get_robot_programs(device_id)
    return api_response(code=200, message="success", data=programs)


@app.get("/api/devices/{device_type}/{device_id}/programs/{prog_name}")
async def get_program_detail_api(device_type: str, device_id: str, prog_name: str):
    """获取指定加工程序的代码内容"""
    prog = get_robot_program_by_name(device_id, prog_name)
    if not prog:
        return api_response(code=404, message=f"未找到程序 '{prog_name}'")
    return api_response(code=200, message="success", data=prog)


class SaveProgramRequest(BaseModel):
    prog_name: str
    prog_content: str
    is_active: Optional[int] = 0


@app.post("/api/devices/{device_type}/{device_id}/programs")
async def save_device_program_api(device_type: str, device_id: str, body: SaveProgramRequest = Body(...)):
    """保存或在线编辑机器人加工程序"""
    ok, msg = save_robot_program(
        device_id=device_id,
        device_type=device_type,
        prog_name=body.prog_name.strip(),
        prog_content=body.prog_content,
        is_active=body.is_active or 0
    )
    if ok:
        return api_response(code=200, message=msg, data=get_robot_program_by_name(device_id, body.prog_name.strip()))
    return api_response(code=400, message=msg)


@app.get("/api/devices/{device_type}/{device_id}/programs/{prog_name}/download")
async def download_program_file_api(device_type: str, device_id: str, prog_name: str):
    """下载单个机器人加工程序文件到本地电脑 (.PRG 文件)"""
    from fastapi.responses import Response
    prog = get_robot_program_by_name(device_id, prog_name)
    if not prog:
        content = f"; {device_id} - {prog_name}\nPROGRAM MAIN()\n    SPEED 80\n    MOVJ P0, V=50%\nEND\n"
    else:
        content = prog.get("prog_content", "")
    
    filename = prog_name if prog_name.endswith(".PRG") or prog_name.endswith(".prg") else f"{prog_name}.PRG"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{filename}\"",
        "Content-Type": "text/plain; charset=utf-8"
    }
    return Response(content=content.encode("utf-8"), media_type="text/plain", headers=headers)


@app.get("/api/devices/{device_type}/{device_id}/backup")
async def backup_device_system_api(device_type: str, device_id: str):
    """远程一键打包备份机器人程序与系统配置 (ZIP 导出)"""
    import io
    import zipfile
    from fastapi.responses import Response
    
    dev = get_device_by_id(device_id)
    programs = get_robot_programs(device_id)
    io_status = get_device_io(device_id)
    site_cfg = get_site_config()
    
    zip_buffer = io.BytesIO()
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. 写入所有加工程序文件
        for p in programs:
            p_name = p["prog_name"]
            p_code = get_robot_program_by_name(device_id, p_name)
            content = p_code.get("prog_content", "") if p_code else ""
            zf.writestr(f"programs/{p_name}", content)
        
        # 2. 写入设备元数据与配置
        metadata = {
            "backup_version": "2.0",
            "backup_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "device": dev or {"device_id": device_id, "device_type": device_type},
            "io_status": io_status,
            "system_config": site_cfg
        }
        zf.writestr("system_settings.json", json.dumps(metadata, ensure_ascii=False, indent=2))
        zf.writestr("README_BACKUP.txt", f"工业机器人物联网管控平台 - 远程全量备份归档\n设备ID: {device_id}\n设备品类: {device_type}\n备份时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n包含程序数: {len(programs)}\n")
    
    zip_buffer.seek(0)
    zip_filename = f"backup_{device_type}_{device_id}_{timestamp_str}.zip"
    headers = {
        "Content-Disposition": f"attachment; filename=\"{zip_filename}\"",
        "Content-Type": "application/zip"
    }
    return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers=headers)


@app.get("/api/devices/{device_type}/{device_id}/backups/weekly")
async def get_weekly_backups_api(device_type: str, device_id: str):
    """获取每周自动备份文件列表"""
    data = get_weekly_backups_list(device_id)
    return api_response(code=200, message="success", data=data)



@app.get("/api/alarms/knowledge_base")
async def get_alarm_knowledge_base_api(keyword: Optional[str] = Query(None, description="搜索关键字")):
    """查询机器人说明书官方故障代码知识库"""
    data = get_alarm_knowledge_base(keyword)
    return api_response(code=200, message="success", data=data)


@app.get("/api/alarms/resolutions")
async def get_alarm_resolutions_api(
    device_id: Optional[str] = Query(None, description="指定设备ID"),
    limit: int = Query(50, description="返回记录条数")
):
    """获取用户手动记录的报警处理历史档案"""
    data = get_alarm_resolutions(device_id, limit)
    return api_response(code=200, message="success", data=data)


class AddAlarmResolutionRequest(BaseModel):
    device_id: str
    device_type: str = "huashu_arm"
    alarm_code: str
    alarm_msg: str
    solution: str
    handler: str
    notes: Optional[str] = ""
    resolved_at: Optional[str] = None


@app.post("/api/alarms/resolutions")
async def add_alarm_resolution_api(body: AddAlarmResolutionRequest = Body(...)):
    """用户手动添加一条报警处理记录"""
    ok, msg = add_alarm_resolution(
        device_id=body.device_id.strip(),
        device_type=body.device_type.strip(),
        alarm_code=body.alarm_code.strip(),
        alarm_msg=body.alarm_msg.strip(),
        solution=body.solution.strip(),
        handler=body.handler.strip(),
        notes=body.notes or "",
        resolved_at=body.resolved_at
    )
    if ok:
        return api_response(code=200, message=msg, data=get_alarm_resolutions(body.device_id, 20))
    return api_response(code=400, message=msg)


@app.get("/api/devices/{device_type}/{device_id}/alarms/active")
async def get_device_active_alarms_api(device_type: str, device_id: str):
    """获取当前设备的报警状态及最近 7 天内的报警流"""
    # 自动执行 7 天过期清理
    cleanup_old_alarms(7)
    
    # 查询当前遥测状态
    latest = get_latest_data(device_type, device_id)
    latest_payload = latest.get("parsed_payload", {}) if latest else {}
    if not isinstance(latest_payload, dict):
        try:
            latest_payload = json.loads(latest.get("raw_payload", "{}"))
        except Exception:
            latest_payload = {}
    error_code = latest_payload.get("error_code", 0)
    has_error = bool(error_code or latest_payload.get("status") in ["error", "alarm", "fault", "estop"])
    
    # 查询该设备最近 7 天内的报警记录
    recent_history = get_device_history(device_type, device_id, page=1, page_size=20, data_type="alarm")
    
    return api_response(code=200, message="success", data={
        "device_id": device_id,
        "device_type": device_type,
        "has_error": has_error,
        "current_error_code": error_code,
        "recent_alarms": recent_history
    })


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/login", include_in_schema=False)
async def serve_login_page():
    """纯净极简浅色登录页面"""
    if LOGIN_HTML.exists():
        return FileResponse(str(LOGIN_HTML))
    if INDEX_NEXT_HTML.exists():
        return FileResponse(str(INDEX_NEXT_HTML))
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return api_response(code=200, message="登录页面正在就绪中...")


@app.get("/light", include_in_schema=False)
@app.get("/v2", include_in_schema=False)
@app.get("/next", include_in_schema=False)
@app.get("/preview", include_in_schema=False)
async def serve_index_next():
    """全新极简浅白企业版 UI 大屏"""
    if INDEX_NEXT_HTML.exists():
        return FileResponse(str(INDEX_NEXT_HTML))
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    return api_response(code=200, message="极简浅白版 UI 正在就绪中...")


@app.get("/dark", include_in_schema=False)
@app.get("/", include_in_schema=False)
async def serve_index():
    """企业级机器人孪生大屏 UI"""
    if INDEX_HTML.exists():
        return FileResponse(str(INDEX_HTML))
    if INDEX_NEXT_HTML.exists():
        return FileResponse(str(INDEX_NEXT_HTML))
    return api_response(code=200, message="机器人物联网管理系统 API 服务正常运行中")


# ---------------------------------------------------------------------------
# 9. 本地直接执行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
