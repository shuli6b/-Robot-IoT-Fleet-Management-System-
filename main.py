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
import re
import threading
from collections import defaultdict, deque
from logging.handlers import RotatingFileHandler
from urllib.parse import urlparse
import database
from security import create_session, session_user, revoke_sessions, verify_payload, sign_payload, allowed_device, timestamp_age
from robot_commands import validate_command
from simulation import visible_device,is_simulated
from starlette.concurrency import run_in_threadpool

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_HTML = STATIC_DIR / "index.html"
INDEX_NEXT_HTML = STATIC_DIR / "index_next.html"
LOGIN_HTML = STATIC_DIR / "login.html"
ASSETS_DIR = STATIC_DIR / "assets"

from fastapi import FastAPI, Request, Query, HTTPException, status, Body, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
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
    set_device_simulated,
    get_simulated_devices,
    save_robot_program,
    get_alarm_knowledge_base,
    get_alarm_resolutions,
    add_alarm_resolution,
    cleanup_old_alarms,
    get_device_io,
    update_device_io,
    get_weekly_backups_list,
    get_system_config,
    set_system_config,
    get_command_ack,
    get_traffic_stats,
    get_device_logs,
    add_device_run_log,
    confirm_all_alarms_log,
    admin_approve_user,
    get_device_report_data,
    get_alarm_analytics_stats,
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
        RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=5, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("robot_server")

# 环境变量配置
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
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
    status_code: Optional[int] = None,
) -> JSONResponse:
    """生成符合架构规范的统一 JSON 响应"""
    payload = {
        "code": code,
        "message": message,
        "data": data,
        "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return JSONResponse(status_code=status_code or (code if 100 <= code <= 599 else 500), content=payload)


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
                for identity in sorted(__import__('security').registered_devices()):
                    client.subscribe('robot/'+identity+'/#',qos=1)
                client.subscribe('simulation/robot/#',qos=1)
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


LAST_SEEN_STATES: Dict[str, Dict[str, Any]] = {}


def on_mqtt_message(client, userdata, msg):
    try:
        if msg.topic.startswith('simulation/'):
            from simulation import ingest
            ingest(msg.topic,msg.payload)
            return
        parsed=parse_topic(msg.topic)
        if not parsed or parsed['data_type'] not in ('state','sensor','io','alarm','cmd_ack') or len(msg.payload)>65536:
            return
        kind=parsed['data_type']
        device_id=parsed['device_id']
        device_type=parsed['device_type']
        if not allowed_device(device_type,device_id):
            return
        def invalid_constant(value):
            raise ValueError('Nonfinite JSON')
        p=json.loads(msg.payload.decode('utf-8'),parse_constant=invalid_constant)
        if not verify_payload(p,os.getenv('TELEMETRY_HMAC_KEY','')) or p.get('source')!='controller':
            return
        if p.get('device_id')!=device_id or p.get('device_type')!=device_type or not -5<=timestamp_age(p.get('timestamp'))<=30:
            return
        if not isinstance(p.get('message_id'),str) or len(p['message_id'])>100:
            return
        if kind=='state':
            if p.get('status') not in ('ready','running','standby','unknown','offline','error'):
                return
            for key in ('enabled','emergency_stop'):
                if p.get(key) is not None and not isinstance(p[key],bool):
                    return
            for key in ('joint_angles','motor_currents'):
                if p.get(key) is not None and (not isinstance(p[key],list) or len(p[key])!=6 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in p[key])):
                    return
        existing=get_device_by_id(device_id)
        if existing and existing.get('is_simulated'):
            if existing.get('simulation_enabled') or kind!='state' or not p.get('connection_id') or p.get('status') in ('offline','unknown'):
                return
            conn=database.get_connection()
            try:
                with conn:
                    conn.execute("UPDATE devices SET is_simulated=0,status='offline',last_report_time=NULL WHERE device_id=? AND device_type=? AND simulation_enabled=0",(device_id,device_type))
            finally:conn.close()
            add_device_run_log(device_id,'info','platform','已登记真机的签名状态开始接替已停用仿真；历史数据来源保持不变')
        row_id=insert_device_data(device_id,device_type,kind,json.dumps(p,ensure_ascii=False,allow_nan=False),msg.topic,source='controller')
        if row_id is None:
            return
        if kind=='alarm':
            level={0:'INFO',1:'INFO',2:'INFO',3:'WARN',4:'ERROR'}.get(p.get('alarm_level'),'INFO')
            add_device_run_log(device_id,'error' if level=='ERROR' else 'info','controller',
                f"[{p.get('alarm_code')}] {p.get('alarm_msg','')} | controller_time={p.get('controller_timestamp')}",
                log_level=level,source='controller_event',event_id=p['message_id'],event_time=p.get('timestamp'))
        elif kind=='cmd_ack':
            result_state=p.get('status')
            if result_state not in ('received','succeeded','controller_accepted','failed','unknown','expired','cancelled'):
                return
            conn=database.get_connection()
            try:
                with conn:
                    row=conn.execute('SELECT * FROM command_requests WHERE task_id=? AND device_id=? AND device_type=?',(p.get('task_id'),device_id,device_type)).fetchone()
                    if not row or row['command']!=p.get('command'):
                        return
                    if row['state'] in ('succeeded','failed','expired','cancelled','controller_accepted'):
                        return
                    if result_state=='received' and row['state'] not in ('sending','delivered','received','unknown'):
                        return
                    conn.execute('UPDATE command_requests SET state=?,message=?,controller_code=?,result=?,updated_at=? WHERE task_id=?',
                        (result_state,p.get('message',''),str(p.get('code')) if p.get('code') is not None else None,json.dumps(p,ensure_ascii=False),datetime.now().isoformat(timespec='seconds'),p['task_id']))
                add_device_run_log(device_id,'action',row['operator'],f"命令 {row['command']} [{row['task_id']}] 结果={result_state}: {p.get('message','')}",event_id=p['message_id'])
            finally:
                conn.close()
        elif kind=='state':
            identity=(device_type,device_id)
            previous=LAST_SEEN_STATES.get(identity,{})
            if p.get('connection_id') and p.get('status')!='offline' and previous.get('connection_id')!=p['connection_id']:
                add_device_run_log(device_id,'info','platform','平台开始接收当前控制器会话的已验证状态报文；不代表机器人刚开机',source='platform_audit',event_time=p.get('timestamp'))
            for key in ('enabled','emergency_stop'):
                old,new=previous.get(key),p.get(key)
                if isinstance(old,bool) and isinstance(new,bool) and old!=new:
                    add_device_run_log(device_id,'info','controller',f'控制器反馈状态变更: {key}={new}',event_time=p.get('timestamp'))
            LAST_SEEN_STATES[identity]=p
    except Exception as e:
        logger.warning('Rejected/unprocessed telemetry (%s)',type(e).__name__)


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
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 服务启动阶段
    logger.info("=== 机器人物联网管理系统服务正在启动 ===")
    for key in ('TELEMETRY_HMAC_KEY','COMMAND_HMAC_KEY','ROBOT_ALLOWED_DEVICES','MQTT_USERNAME','MQTT_PASSWORD'):
        if not os.getenv(key):
            raise RuntimeError('Missing production configuration: '+key)
    if not init_db() or not check_db_integrity():
        raise RuntimeError("Database initialization/integrity check failed; refusing to start")
    init_mqtt_client()
    offline_task = asyncio.create_task(check_device_offline_task())

    yield

    # 2. 服务关闭阶段
    logger.info("=== 机器人物联网管理系统服务正在关闭 ===")
    offline_task.cancel()
    try:
        await offline_task
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

# Same-origin API only. Identity is derived from a server-side session.
LOGIN_ATTEMPTS = defaultdict(deque)
RATE_LOCK = threading.Lock()


@app.middleware('http')
async def authenticate_request(request: Request, call_next):
    path=request.url.path
    public={'/api/auth/login','/api/auth/register','/api/health','/api/system/site_config'}
    is_public=(path in public and (path!='/api/system/site_config' or request.method=='GET'))
    if path.startswith('/api/') and not is_public:
        token=request.headers.get('Authorization','')
        token=token[7:] if token.startswith('Bearer ') else ''
        user=await run_in_threadpool(session_user,token,database.DB_PATH)
        if not user:
            return api_response(401,'请重新登录')
        request.state.user=user
        parts=path.strip('/').split('/')
        if len(parts)>=5 and parts[:2]==['api','devices'] and not visible_device(parts[2],parts[3]):
            return api_response(404,'该设备未登记为真实设备')
        if user.get('must_change_password') and path not in ('/api/auth/me','/api/auth/password','/api/auth/logout'):
            return api_response(403,'当前密码不符合生产安全要求，请先修改密码',{'must_change_password':True})
        personal=path in ('/api/auth/me','/api/auth/profile','/api/auth/password','/api/auth/username','/api/auth/logout')
        restricted_read=path.startswith('/api/admin/') or path in ('/api/auth/users','/api/ai/config','/api/devices/huashu/config','/api/tunnel/status')
        writes=request.method not in ('GET','HEAD','OPTIONS')
        ai_query=path in ('/api/ai/chat','/api/ai/diagnose')
        if ((writes and not personal and not ai_query) or restricted_read or path.endswith('/backup')) and user['role']!='admin':
            return api_response(403,'需要管理员权限')
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('Origin')
        if origin and urlparse(origin).netloc!=request.headers.get('Host'):
            return api_response(403,'拒绝跨站请求')
        try:
            if int(request.headers.get('Content-Length','0'))>2*1024*1024:
                return api_response(413,'请求过大')
        except ValueError:
            return api_response(400,'无效请求长度')
    if request.method in ('POST','PUT','PATCH') and ('application/json' in request.headers.get('Content-Type','')):
        try:
            body=await request.json()
            metadata_keys={'username','real_name','device_name','location','vendor','notes','system_title','company_name','di_details','do_details','specs','target_username','new_username'}
            def unsafe(value):
                if isinstance(value,str):
                    return any(c in value for c in ('<','>','\x00')) or len(value)>10000
                if isinstance(value,dict):
                    return any(unsafe(k) or unsafe(v) for k,v in value.items())
                if isinstance(value,list):
                    return any(unsafe(v) for v in value)
                return False
            if isinstance(body,dict):
                for key,value in body.items():
                    if (key in metadata_keys or path=='/api/system/site_config') and unsafe(value):
                        return api_response(422,'资料字段只接受纯文本，不能包含HTML标签')
        except (ValueError,UnicodeError):
            return api_response(400,'无效JSON')
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='same-origin'
    return response


@app.get('/api/admin/legacy/{table}')
def archived_legacy(table: str,page: int=Query(1,ge=1),page_size: int=Query(50,ge=1,le=100)):
    if table not in ('device_data','device_run_logs','robot_programs','alarm_resolutions'):
        raise HTTPException(404,'无此历史归档')
    conn=database.get_connection()
    try:
        rows=conn.execute(f"SELECT * FROM {table} WHERE source='legacy_unverified' ORDER BY id DESC LIMIT ? OFFSET ?",(page_size,(page-1)*page_size)).fetchall()
        return api_response(data={'source':'legacy_unverified','notice':'真实性未确认，禁止作为当前设备事实或执行依据','records':[dict(r) for r in rows]})
    finally:
        conn.close()


@app.post('/api/auth/logout')
async def logout(request: Request):
    await run_in_threadpool(revoke_sessions,request.state.user['username'],database.DB_PATH)
    return api_response(200,'已退出')



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
def api_user_login(body: LoginRequest = Body(...)):
    """
    用户登录接口 (支持超级管理员 admin 与普通用户 user，含管理员注册审核校验)
    """
    with RATE_LOCK:
        key=body.username.strip().lower()
        attempts=LOGIN_ATTEMPTS[key]
        now=time.monotonic()
        while attempts and attempts[0]<now-300:
            attempts.popleft()
        if len(attempts)>=10:
            return api_response(429,'尝试次数过多，请五分钟后重试')
        attempts.append(now)
        if len(LOGIN_ATTEMPTS)>10000:
            LOGIN_ATTEMPTS.clear()
    user_info, auth_status = authenticate_user(body.username, body.password)
    if auth_status == "PENDING_APPROVAL":
        return api_response(
            code=403,
            message="该账号正在等待管理员审核，审核通过后方可登录系统。",
            data=None,
            status_code=status.HTTP_403_FORBIDDEN
        )
    elif auth_status == "REJECTED":
        return api_response(
            code=403,
            message="该账号注册申请已被管理员拒绝，无法登录系统。如有疑问请联系管理员。",
            data=None,
            status_code=status.HTTP_403_FORBIDDEN
        )
    elif not user_info or auth_status != "OK":
        return api_response(
            code=401,
            message="账号或密码错误，请核对后重试",
            data=None,
            status_code=status.HTTP_401_UNAUTHORIZED
        )
    # 生成简单 Session Token 标识
    token = create_session(user_info['username'], database.DB_PATH)
    return api_response(
        code=200,
        message=f"欢迎登录，{user_info['real_name']} ({'超级管理员' if user_info['role'] == 'admin' else '普通操作员'})",
        data={
            "token": token,
            "must_change_password": bool(user_info.get("must_change_password")),
            "user_id": user_info["id"],
            "username": user_info["username"],
            "role": user_info["role"],
            "real_name": user_info["real_name"],
            "status": user_info.get("status", "approved"),
            "last_login": user_info["last_login"]
        }
    )


@app.post("/api/auth/register")
def api_user_register(body: RegisterRequest = Body(...)):
    """
    用户快速注册接口（普通用户需管理员在后台审核通过后方可登录）
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
            message=msg or "账号注册成功！需管理员审核通过后方可登录，请联系管理员审批。",
            data={"username": body.username, "role": "user", "status": "pending"}
        )
    else:
        return api_response(
            code=400,
            message=msg,
            data=None,
            status_code=status.HTTP_400_BAD_REQUEST
        )


@app.get("/api/auth/me")
def api_user_me(request: Request):
    return api_response(data=request.state.user)


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
def api_update_profile(body: UpdateProfileRequest = Body(...), request: Request = None):
    username=request.state.user['username']
    success,msg=update_user_profile(username,body.real_name)
    return api_response(200 if success else 400,msg,{'username':username,'real_name':body.real_name})


@app.post("/api/auth/password")
def api_change_password(body: ChangePasswordRequest = Body(...), request: Request = None):
    success,msg=change_user_password(request.state.user['username'],body.old_password,body.new_password)
    return api_response(200 if success else 400,msg)


@app.post("/api/auth/username")
def api_change_username(body: ChangeUsernameRequest = Body(...), request: Request = None):
    success,msg=change_user_username(request.state.user['username'],body.new_username,body.password)
    return api_response(200 if success else 400,msg)


def is_super_admin(request: Request) -> bool:
    user=getattr(getattr(request,'state',None),'user',None)
    return bool(user and user['username']=='admin' and user['role']=='admin')


def is_admin(request: Request) -> bool:
    user=getattr(getattr(request,'state',None),'user',None)
    return bool(user and user['role']=='admin')


@app.get("/api/auth/users")
def api_get_all_users(request: Request):
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
def api_admin_reset_password(body: AdminResetPasswordRequest = Body(...), request: Request = None):
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
def api_update_role(body: UpdateRoleRequest = Body(...), request: Request = None):
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


class AdminApproveUserRequest(BaseModel):
    target_username: str = Field(..., description="目标审核用户名")
    approved: bool = Field(..., description="是否通过审核 (True: 通过, False: 拒绝)")


@app.post("/api/auth/approve_user")
def api_admin_approve_user(body: AdminApproveUserRequest = Body(...), request: Request = None):
    """超级管理员审核普通用户注册申请 (仅超级管理员)"""
    if not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有审核用户注册的特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    success, msg = admin_approve_user(body.target_username, body.approved)
    if success:
        return api_response(code=200, message=msg)
    return api_response(code=400, message=msg, status_code=status.HTTP_400_BAD_REQUEST)



@app.get("/api/health")
async def health_check():
    def probe():
        conn=database.get_connection()
        try:
            conn.execute('SELECT 1 FROM devices LIMIT 1').fetchone()
            return True
        finally:
            conn.close()
    try:
        db_ok=await run_in_threadpool(probe)
    except Exception:
        db_ok=False
    healthy=db_ok and is_mqtt_connected
    return api_response(200 if healthy else 503,'healthy' if healthy else 'degraded',{
        'status':'ok' if healthy else 'degraded','database':'connected' if db_ok else 'unavailable',
        'mqtt':'connected' if is_mqtt_connected else 'disconnected','uptime_seconds':int(time.time()-START_TIME),'version':'3.0.0','control_enabled':os.getenv('ROBOT_CONTROL_ENABLED','0')=='1'})


@app.get("/api/system/traffic")
async def get_traffic_api(buckets: int=Query(13,ge=5,le=60)):
    from datetime import timedelta
    now=datetime.now().replace(microsecond=0)
    state=await run_in_threadpool(get_traffic_stats,buckets,3,'state',database.DB_PATH,now)
    sensor=await run_in_threadpool(get_traffic_stats,buckets,3,'sensor',database.DB_PATH,now)
    return api_response(data={'buckets':buckets,'window_seconds':3,'period_end':now.isoformat(),
        'state':state,'sensor':sensor,'labels':[(now-timedelta(seconds=i*3)).strftime('%H:%M:%S') for i in range(buckets-1,-1,-1)]})


@app.get("/api/system/overview")
def system_overview():
    """
    4.4 获取系统全局概览统计
    包含总设备数、在线数、离线数、总历史记录量、分类统计与服务运行时间
    """
    stats = get_system_stats()
    stats["server_time"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    stats["uptime_seconds"] = int(time.time() - START_TIME)
    stats["mqtt_connected"] = is_mqtt_connected
    stats["control_enabled"] = os.getenv("ROBOT_CONTROL_ENABLED","0") == "1"
    return api_response(code=200, message="success", data=stats)


@app.get("/api/devices")
def list_devices(
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
def get_device_latest(device_type: str, device_id: str):
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
def delete_device_api(request: Request,device_id: str,device_type: Optional[str]=None):
    raise HTTPException(409,'生产设备与历史证据不可通过页面删除，请通过运维归档流程停用设备')


@app.get("/api/history")
def query_global_history(
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
def query_device_history(
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
    confirmed: bool = False


def publish_command_downlink(device_type,device_id,command,params=None,task_id=None,operator='unknown'):
    if is_simulated(device_type,device_id):
        from simulation import dispatch
        return dispatch(device_type,device_id,command,params,task_id,operator,mqtt_client_instance,is_mqtt_connected)
    if os.getenv('ROBOT_CONTROL_ENABLED','0')!='1':
        raise HTTPException(409,'远程执行尚未完成加密接入与现场安全验收，当前只读监控；未发送指令')
    if not allowed_device(device_type,device_id):
        raise HTTPException(404,'设备未登记为真实受控设备')
    try:
        command,params=validate_command(command,params or {})
    except ValueError as e:
        raise HTTPException(422,str(e))
    if command=='jog_joint' and os.getenv('ROBOT_ALLOW_JOG','0')!='1':
        raise HTTPException(409,'远程点动待现场安全验收，当前未启用')
    latest=get_latest_data(device_type,device_id)
    p=latest.get('parsed_payload',{}) if latest else {}
    if not p.get('state_fresh') or p.get('status')=='offline' or not p.get('connection_id'):
        raise HTTPException(409,'没有当前控制器连接的有效遥测，拒绝下发')
    if not mqtt_client_instance or not is_mqtt_connected:
        raise HTTPException(503,'MQTT未连接，未发送，也不会排队重放')
    key=os.getenv('COMMAND_HMAC_KEY','')
    if not key:
        raise HTTPException(503,'控制通道未配置')
    task_id=task_id or uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',task_id):
        raise HTTPException(422,'非法task_id')
    payload={'task_id':task_id,'device_id':device_id,'device_type':device_type,'command':command,'params':params,
             'timestamp':datetime.now().astimezone().isoformat(timespec='milliseconds'),'expires_at':time.time()+5,
             'connection_id':p['connection_id']}
    conn=database.get_connection()
    try:
        with conn:
            old=conn.execute('SELECT * FROM command_requests WHERE task_id=?',(task_id,)).fetchone()
            if old:
                if old['source']!='controller':raise HTTPException(409,'任务ID属于其他数据来源，不能复用')
                if (old['device_id'],old['device_type'],old['command'],old['params'],old['operator'])!=(device_id,device_type,command,json.dumps(params,sort_keys=True),operator):
                    raise HTTPException(409,'task_id已用于不同请求')
                return old['state'],old['message'],{'task_id':task_id}
            now=datetime.now().isoformat(timespec='seconds')
            conn.execute("INSERT INTO command_requests(task_id,device_id,device_type,command,params,operator,state,created_at,expires_at,updated_at,connection_id,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,'controller')",
                (task_id,device_id,device_type,command,json.dumps(params,sort_keys=True),operator,'sending',now,payload['expires_at'],now,p['connection_id']))
        add_device_run_log(device_id,'action',operator,f'请求下发命令 {command}，task_id={task_id}；尚未验证执行')
        state,message='unknown','消息发送确认超时，执行结果未知；禁止自动重试'
        try:
            info=mqtt_client_instance.publish(f'cmd/{device_type}/{device_id}',json.dumps(sign_payload(payload,key),ensure_ascii=False),qos=1,retain=False)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                state,message='failed','消息总线拒绝发送'
            else:
                info.wait_for_publish(timeout=2)
                if info.is_published():
                    state,message='delivered','Broker已确认收到，等待控制器反馈'
        except Exception:
            logger.warning('Command transport result uncertain: %s',task_id)
        with conn:
            conn.execute("UPDATE command_requests SET state=?,message=?,updated_at=? WHERE task_id=? AND state='sending'",(state,message,datetime.now().isoformat(timespec='seconds'),task_id))
        return state,message,payload
    finally:
        conn.close()


@app.post("/api/device/{dev_id}/cmd")
@app.post("/api/devices/{device_type}/{device_id}/cmd")
async def dispatch_device_command(request: Request,dev_id: Optional[str]=None,device_type: Optional[str]=None,device_id: Optional[str]=None,body: CommandRequest=Body(...)):
    if not is_admin(request):
        raise HTTPException(403,'需要管理员权限')
    if not body.confirmed:
        raise HTTPException(409,'请明确确认目标设备和参数后下发')
    target=device_id or dev_id
    dev=get_device_by_id(target)
    if not dev:
        raise HTTPException(404,'设备不存在')
    if device_type and device_type!=dev['device_type']:
        raise HTTPException(409,'设备类型不匹配')
    state,message,payload=await run_in_threadpool(publish_command_downlink,dev['device_type'],target,body.command,body.params,body.task_id,request.state.user['username'])
    return api_response(202,message,{'device_id':target,'device_type':dev['device_type'],'deliver_state':state,'task':payload})


@app.get("/api/device/{dev_id}/cmd/{task_id}")
def query_command_result(dev_id: str, task_id: str):
    """查询单条下行指令的执行结果（基于 cmd_ack 回执）。"""
    rows = get_command_ack(dev_id, task_id)
    return api_response(code=200, message="success", data={"device_id": dev_id,
                                                           "task_id": task_id,
                                                           "ack": rows[0] if rows else None})


@app.get("/api/device/{dev_id}/cmd_history")
def query_command_history(dev_id: str, limit: int = Query(20, ge=1, le=200)):
    """查询设备最近的下行指令与回执记录。"""
    from database import get_cmd_history
    rows = get_cmd_history(dev_id, limit=limit)
    return api_response(code=200, message="success", data={"device_id": dev_id, "records": rows})


# ---------------------------------------------------------------------------
# 仿真设备管理（后台设置页专用，前端大屏不展示该标记）
# ---------------------------------------------------------------------------
@app.get("/api/admin/simulated_devices")
def list_simulated_devices():
    """列出所有标记为仿真的设备。"""
    try:
        devs = get_simulated_devices()
        return api_response(code=200, message="success", data={"devices": devs})
    except Exception as e:
        logger.error(f"list_simulated_devices 异常: {e}")
        return api_response(code=500, message=f"查询失败: {e}", data=None)


@app.post("/api/admin/simulated_devices")
def add_simulated_device(body: dict=Body(...)):
    from simulation import configure_device
    try:
        result=configure_device(body)
    except ValueError as e:
        raise HTTPException(409,str(e))
    return api_response(200,'仿真设备已启用，最多30秒后开始演示上报',result)


@app.delete("/api/admin/simulated_devices/{device_id}")
def remove_simulated_device(device_id: str):
    from simulation import configure_device
    dev=get_device_by_id(device_id)
    if not dev or not dev['is_simulated']:
        raise HTTPException(404,'仿真设备不存在')
    result=configure_device({'device_id':device_id,'device_type':dev['device_type']},enabled=False)
    return api_response(200,'仿真设备已停用，历史保留，不转换为真机',result)


# ---------------------------------------------------------------------------
# 设备 FTP 备份凭据管理（后台设置页专用）
# ---------------------------------------------------------------------------
@app.get("/api/admin/ftp_config")
def get_device_ftp_config():
    """读取各设备 FTP 备份凭据（密码字段脱敏）。"""
    try:
        raw = get_system_config("device_ftp_config", "{}")
        cfg = json.loads(raw) if raw else {}
        safe = {}
        for dev_id, c in cfg.items():
            masked = "***" if c.get("password") else ""
            safe[dev_id] = {"host": c.get("host", ""), "port": c.get("port", 21),
                            "user": c.get("user", ""), "password_masked": masked,
                            "has_password": bool(c.get("password"))}
        return api_response(code=200, message="success", data={"config": safe})
    except Exception as e:
        logger.error(f"get_device_ftp_config 异常: {e}")
        return api_response(code=500, message=f"读取失败: {e}", data=None)


@app.post("/api/admin/ftp_config")
def save_device_ftp_config(body: dict = Body(...)):
    """保存设备 FTP 备份凭据。body: {device_id, host, port, user, password}"""
    try:
        device_id = (body.get("device_id") or "").strip()
        if not device_id:
            return api_response(code=400, message="device_id 不能为空", data=None)
        raw = get_system_config("device_ftp_config", "{}")
        cfg = json.loads(raw) if raw else {}
        entry = cfg.get(device_id, {})
        if body.get("host"):
            entry["host"] = body["host"].strip()
        if body.get("port"):
            entry["port"] = int(body["port"])
        if body.get("user"):
            entry["user"] = body["user"].strip()
        if body.get("password"):
            entry["password"] = body["password"]
        cfg[device_id] = entry
        set_system_config("device_ftp_config", json.dumps(cfg, ensure_ascii=False))
        return api_response(code=200, message="FTP 凭据已保存", data={"device_id": device_id})
    except Exception as e:
        logger.error(f"save_device_ftp_config 异常: {e}")
        return api_response(code=500, message=f"保存失败: {e}", data=None)


@app.get("/api/device/{dev_id}/history")
def get_device_history_by_id(dev_id: str,page: int=1,page_size: int=50):
    dev=get_device_by_id(dev_id)
    if not dev or not visible_device(dev['device_type'],dev_id):
        raise HTTPException(404,'未登记的真实设备')
    return api_response(data=get_history_by_dev_id(dev_id,page=max(1,page),page_size=max(1,min(page_size,200))))


@app.get("/api/analytics/operational")
def get_operational_metrics():
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
    parsed_url=urlparse(clean_url)
    allowed_hosts=set(os.getenv('LLM_ALLOWED_HOSTS','api.deepseek.com,api.openai.com,generativelanguage.googleapis.com,dashscope.aliyuncs.com,api.siliconflow.cn').split(','))
    if parsed_url.hostname not in allowed_hosts or parsed_url.username or parsed_url.password or (parsed_url.scheme!='https' and not (parsed_url.hostname in ('localhost','127.0.0.1') and os.getenv('ALLOW_LOCAL_LLM')=='1')):
        return False,'模型服务地址未列入运维白名单或未使用TLS',{}
    if parsed_url.query or parsed_url.fragment:
        return False,'模型基础地址不得包含查询参数或片段',{} 
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
        async with httpx.AsyncClient(timeout=timeout, verify=True, trust_env=False) as client:
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
def get_ai_context():
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
def get_ai_configuration():
    """获取当前大模型接入配置与预设厂商列表"""
    cfg = get_llm_config()
    raw_key = cfg.get("api_key", "")
    masked_key = ""
    if raw_key:
        masked_key = raw_key[:3] + "****" + raw_key[-4:] if len(raw_key) > 8 else "****"

    safe_cfg = {k:v for k,v in cfg.items() if k != "api_key"}
    safe_cfg.update(api_key_masked=masked_key, has_api_key=bool(raw_key))
    return api_response(
        code=200,
        message="success",
        data={
            "config": safe_cfg,
            "presets": LLM_PROVIDER_PRESETS
        }
    )


@app.post("/api/ai/config")
def update_ai_configuration(body: LLMConfigModel = Body(...), request: Request = None):
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
    if update_data.get('base_url','').rstrip('/') != current.get('base_url','').rstrip('/') and not update_data.get('api_key'):
        raise HTTPException(422,'更换模型服务地址必须提供新服务密钥，禁止自动沿用旧密钥')
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
    site_footer_text: Optional[str] = Field(None, description="页脚版权文字别名")
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
def api_update_device(device_id: str,body: DeviceUpdateRequest=Body(...),request: Request=None):
    if not is_admin(request):
        raise HTTPException(403,'需要管理员权限')
    dev=get_device_by_id(device_id)
    if not dev:
        raise HTTPException(404,'设备不存在')
    if getattr(body,'device_type',None) and body.device_type!=dev['device_type']:
        raise HTTPException(409,'设备身份不能通过编辑资料改变')
    values=body.model_dump(exclude_none=True)
    values.pop('device_type',None)
    ok=update_device_info(device_id,**values)
    return api_response(200 if ok else 400,'平台设备资料已更新，未改变物理设备',get_device_by_id(device_id))


@app.get("/api/system/site_config")
def api_get_site_config():
    """获取全站品牌与图文自定义配置 (公开读取)"""
    cfg = get_site_config()
    return api_response(code=200, message="success", data=cfg)


@app.post("/api/system/site_config")
def api_save_site_config(body: SiteConfigModel = Body(...), request: Request = None):
    """保存全站品牌与图文自定义配置 (仅限超级管理员)"""
    if not request or not is_super_admin(request):
        return api_response(
            code=403,
            message="权限不足：仅系统默认超级管理员 (admin) 拥有修改全站品牌与图文配置的特权",
            status_code=status.HTTP_403_FORBIDDEN
        )
    update_data = {k: v for k, v in body.dict().items() if v is not None}
    footer_val = update_data.get("site_footer_text") or update_data.get("footer_text")
    if footer_val:
        update_data["footer_text"] = footer_val
        update_data["site_footer_text"] = footer_val
    success = save_site_config(update_data)
    if success:
        return api_response(code=200, message="站点品牌与图文配置保存成功，全站已实时生效", data=get_site_config())
    return api_response(code=500, message="保存站点配置失败", status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@app.post("/api/system/upload_asset")
async def api_upload_asset(file: UploadFile=File(...),request: Request=None):
    if not is_super_admin(request):
        raise HTTPException(403,'需要系统管理员权限')
    content=await file.read(2*1024*1024+1)
    if len(content)>2*1024*1024:
        raise HTTPException(413,'图片不能超过2MB')
    suffix=None
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        suffix='.png'
    elif content.startswith(b'\xff\xd8\xff'):
        suffix='.jpg'
    elif content.startswith((b'GIF87a',b'GIF89a')):
        suffix='.gif'
    elif content.startswith(b'RIFF') and content[8:12]==b'WEBP':
        suffix='.webp'
    if suffix is None:
        raise HTTPException(422,'仅允许PNG/JPEG/GIF/WebP图片，不接受SVG或HTML')
    ASSETS_DIR.mkdir(parents=True,exist_ok=True)
    name=uuid.uuid4().hex+suffix
    await run_in_threadpool((ASSETS_DIR/name).write_bytes,content)
    return api_response(data={'url':'/static/assets/'+name,'filename':name})


class LLMTestRequest(BaseModel):
    provider: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/ai/test")
async def test_ai_connection(body: LLMTestRequest = Body(...)):
    """测试大模型 API 连通性"""
    cfg = get_llm_config()
    if body.base_url and body.base_url.rstrip('/') != cfg.get('base_url','').rstrip('/') and not body.api_key:
        raise HTTPException(422,'测试不同服务地址时必须显式提供该服务密钥，禁止转发已保存密钥')
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
async def fetch_provider_models(body: LLMTestRequest=Body(...)):
    cfg=get_llm_config()
    base=(body.base_url or cfg.get('base_url','')).rstrip('/')
    if body.base_url and base!=cfg.get('base_url','').rstrip('/') and not body.api_key:
        raise HTTPException(422,'不同服务地址必须显式提供密钥')
    parsed=urlparse(base)
    allowed=set(os.getenv('LLM_ALLOWED_HOSTS','api.deepseek.com,api.openai.com,generativelanguage.googleapis.com,dashscope.aliyuncs.com,api.siliconflow.cn').split(','))
    if parsed.scheme!='https' or parsed.hostname not in allowed or parsed.username or parsed.query or parsed.fragment:
        raise HTTPException(422,'服务地址未通过安全校验')
    key=body.api_key or cfg.get('api_key','')
    url=base.removesuffix('/chat/completions')+'/models'
    async with httpx.AsyncClient(timeout=8,verify=True,trust_env=False) as client:
        response=await client.get(url,headers={'Authorization':'Bearer '+key},follow_redirects=False)
    if response.status_code!=200:
        raise HTTPException(502,'服务商未返回有效模型列表')
    data=response.json()
    models=[x['id'] for x in data.get('data',[]) if isinstance(x,dict) and isinstance(x.get('id'),str)]
    return api_response(data={'models':sorted(models)})


class ChatMessage(BaseModel):
    role: str = Field("user", description="user | assistant | system")
    content: str = Field(..., description="消息文本")


class ChatRequest(BaseModel):
    messages: List[ChatMessage] = Field(default=[], description="连续多轮对话历史列表")
    query: Optional[str] = Field(None, description="当前单次提问")
    device_id: Optional[str] = Field(None, description="指定分析的设备 ID")


@app.post("/api/ai/chat")
@app.post("/api/ai/diagnose")
async def ai_chat_and_diagnose(body: ChatRequest=Body(...)):
    context=await run_in_threadpool(get_ai_llm_context)
    cfg=await run_in_threadpool(get_llm_config)
    dialog=[{'role':m.role,'content':m.content[:10000]} for m in body.messages[-20:] if m.role in ('user','assistant')]
    if not dialog:
        dialog=[{'role':'user','content':body.query or '汇总已验证观测及缺失数据'}]
    if cfg.get('enabled') and (cfg.get('api_key') or cfg.get('provider')=='ollama'):
        ok,reply,meta=await call_llm_api(base_url=cfg.get('base_url',''),api_key=cfg.get('api_key',''),model=cfg.get('model',''),
            system_prompt='你是运维分析助手。以下是服务端已验证观测，null表示未知。不得补造测量值、官方故障解释或执行记录。不得生成执行命令。分析建议与事实分开说明。\n'+context['llm_prompt_context'],
            messages=dialog)
        if ok:
            return api_response(data={'reply':'【模型分析，非控制器原始记录】\n'+reply,'mode':'cloud_llm_analysis','raw_context':context['llm_prompt_context'],'latency_ms':meta.get('latency_ms')})
    observations=context['operational_analytics']['device_health_diagnostics']
    lines=['【已验证遥测摘要；未作健康预测】']
    for d in observations:
        lines.append(f"{d['device_id']}: 连接状态={d['status']}，控制器报警数量={d.get('error_count') if d.get('error_count') is not None else '未知'}")
    if not observations:
        lines.append('当前没有已登记真实设备的可用观测。')
    lines.append('缺失数据不表示正常；未测量的工时、寿命和环境指标不作推算。')
    return api_response(data={'reply':'\n'.join(lines),'mode':'verified_observation_summary','raw_context':context['llm_prompt_context']})


class ParseCommandRequest(BaseModel):
    natural_language: str = Field(..., description="自然语言指令描述")
    device_type: str = Field(..., description="设备品类: huashu_arm / luxshare_amr / robot_dog")
    device_id: Optional[str] = Field(None, description="设备ID")


@app.post("/api/ai/parse_command")
def ai_parse_command(body: ParseCommandRequest=Body(...)):
    if body.device_type!='huashu_arm':
        raise HTTPException(409,'该品类尚无已验证的真实控制适配器')
    text=body.natural_language.strip().lower()
    commands={'去使能':'disable','下使能':'disable','下电':'disable','disable':'disable',
              '上使能':'enable','上电':'enable','enable':'enable','暂停':'pause','pause':'pause',
              '急停':'stop','紧急停止':'stop','stop':'stop','复位':'reset','reset':'reset'}
    command=commands.get(text)
    params={}
    speed=re.fullmatch(r'(?:速度|倍率)(?:设为|设置为|调为|=|至)?\s*(\d+)\s*%?',text)
    if speed:
        command='set_override'
        params={'override':int(speed[1])}
    if command in ('pause',):
        raise HTTPException(422,'请在控制面板明确指定程序名后暂停')
    if not command:
        raise HTTPException(422,'指令不明确或未支持，请使用明确命令与参数；不会猜测启动动作')
    try:
        command,params=validate_command(command,params)
    except ValueError as e:
        raise HTTPException(422,str(e))
    return api_response(data={'command':command,'params':params,'explanation':'明确规则匹配，尚未执行；请核对目标及参数'})



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
def get_huashu_config_api():
    return api_response(data={'robot_ip':os.getenv('ROBOT_IP','192.168.1.169'),'robot_port':int(os.getenv('ROBOT_PORT','23333')),
        'device_id':os.getenv('ROBOT_DEVICE_ID','arm_001'),'source':'service_configuration','editable':False})


@app.post("/api/devices/huashu/config")
def save_huashu_config_api(body: HuashuBridgeConfigModel=Body(...)):
    raise HTTPException(409,'生产连接配置由受保护的服务配置管理；页面未修改当前控制器连接')


class HuashuTestRequest(BaseModel):
    robot_ip: str = Field(..., description="要测试的华数控制器 IP 地址")
    robot_port: int = Field(23234, description="华数控制器端口，默认 23234")
    timeout_sec: float = Field(2.5, description="握手超时时间秒数")


@app.post("/api/devices/huashu/test")
def test_huashu_connection_api(body: HuashuTestRequest=Body(...)):
    if body.robot_ip not in set(os.getenv('CONTROLLER_ALLOWED_HOSTS',os.getenv('ROBOT_IP','192.168.1.169')).split(',')) or body.robot_port!=23333:
        raise HTTPException(422,'只允许测试已登记控制器的SocketCmd端口')
    latest=get_latest_data('huashu_arm',os.getenv('ROBOT_DEVICE_ID','arm_001'))
    p=latest.get('parsed_payload',{}) if latest else {}
    connected=bool(p.get('state_fresh') and p.get('connection_id') and p.get('status')!='offline')
    return api_response(200 if connected else 503,'依据桥接器最新协议遥测判断，未创建额外控制连接',{'connected':connected,'source':'verified_bridge_telemetry'})


class TunnelStartRequest(BaseModel):
    engine: str = Field("pinggy", description="pinggy | cloudflared | cpolar | custom")
    port: int = Field(8000, description="本地需要映射的端口")
    token: Optional[str] = Field("", description="认证 Token 或密钥")
    custom_url: Optional[str] = Field("", description="自定义公网访问域名")


@app.get("/api/tunnel/status")
def get_tunnel_status_api():
    return api_response(data={'active':None,'url':get_system_config('remote_public_url',''),'engine':'externally_managed','status':'由系统服务管理，本接口不声称已验证其运行状态'})


@app.post("/api/tunnel/start")
def start_tunnel_api(body: TunnelStartRequest=Body(...)):
    raise HTTPException(409,'生产穿透由系统服务统一管理，页面不能启动额外通道')


@app.post("/api/tunnel/stop")
def stop_tunnel_api():
    raise HTTPException(409,'生产穿透由系统服务统一管理，未执行停止')


# ---------------------------------------------------------------------------
# 7.4 机器人 I/O 状态、程序管理与下载备份、说明书故障知识库与处理档案
# ---------------------------------------------------------------------------

@app.get("/api/devices/{device_type}/{device_id}/io")
def get_device_io_api(device_type: str, device_id: str):
    """获取指定机器人 16 路输入 DI 与 16 路输出 DO 实时状态"""
    data = get_device_io(device_id)
    return api_response(code=200, message="success", data=data)


class DeviceIOUpdateRequest(BaseModel):
    di_mask: Optional[int] = None
    do_mask: Optional[int] = None
    di_details: Optional[Dict[str, str]] = None
    do_details: Optional[Dict[str, str]] = None


@app.post("/api/devices/{device_type}/{device_id}/io")
def update_device_io_api(device_type: str,device_id: str,body: DeviceIOUpdateRequest=Body(...)):
    if body.di_mask is not None or body.do_mask is not None:
        raise HTTPException(409,'此接口只编辑点位备注；实际DO控制必须经已确认的控制命令接口')
    cur=get_device_io(device_id)
    ok=update_device_io(device_id,device_type,0,0,body.di_details,body.do_details)
    return api_response(200 if ok else 500,'仅更新平台点位备注，物理I/O未改变',get_device_io(device_id))


@app.get("/api/devices/{device_type}/{device_id}/programs")
def get_device_programs_api(device_type: str, device_id: str):
    """获取指定机器人的全部加工程序列表"""
    programs = get_robot_programs(device_id)
    return api_response(code=200, message="success", data=programs)


@app.get("/api/devices/{device_type}/{device_id}/programs/{prog_name}")
def get_program_detail_api(device_type: str, device_id: str, prog_name: str):
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
def save_device_program_api(device_type: str, device_id: str, body: SaveProgramRequest = Body(...)):
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
def download_program_file_api(device_type: str, device_id: str, prog_name: str):
    from fastapi.responses import Response
    prog=get_robot_program_by_name(device_id,prog_name)
    if not prog or prog['device_type']!=device_type:
        raise HTTPException(404,'该设备没有此程序文件')
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.[Pp][Rr][Gg]',prog_name):
        raise HTTPException(422,'非法文件名')
    return Response(prog['prog_content'].encode('utf-8'),media_type='text/plain',headers={
        'Content-Disposition':f'attachment; filename="{prog_name}"','X-Data-Source':prog['source']})


@app.get("/api/devices/{device_type}/{device_id}/backup")
async def backup_device_system_api(device_type: str, device_id: str):
    from backup_service import controller_backup,save_archive
    from fastapi.responses import Response
    if not allowed_device(device_type,device_id):
        raise HTTPException(404,'未登记的真实设备')
    configs=json.loads(get_system_config('device_ftp_config','{}'))
    cfg=configs.get(device_id,{})
    allowed_hosts=set(os.getenv('CONTROLLER_ALLOWED_HOSTS',os.getenv('ROBOT_IP','192.168.1.169')).split(','))
    if cfg.get('host') not in allowed_hosts:
        raise HTTPException(422,'FTP目标未在控制器白名单内，不能猜测目标地址')
    try:
        payload,manifest=await run_in_threadpool(controller_backup,cfg,device_id)
        name=await run_in_threadpool(save_archive,payload,manifest,'.zip')
    except ValueError as e:
        raise HTTPException(422,str(e))
    except Exception:
        logger.exception('Controller backup failed')
        raise HTTPException(502,'控制器备份失败或不完整，未生成成功归档')
    return Response(payload,media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="{name}"'})



@app.get("/api/devices/{device_type}/{device_id}/backups/weekly")
def get_weekly_backups_api(device_type: str, device_id: str):
    """获取每周自动备份文件列表"""
    data = get_weekly_backups_list(device_id)
    return api_response(code=200, message="success", data=data)



@app.get("/api/devices/{device_type}/{device_id}/logs")
def get_device_logs_api(
    device_type: str,
    device_id: str,
    limit: int = Query(100, ge=1, le=500, description="返回最新日志条数"),
    level: Optional[str] = Query(None, description="级别筛选: ALL/INFO/WARN/ERROR/ACTION"),
    filter_type: Optional[str] = Query(None, description="图标类型筛选: ALL/action/error/warn/info")
):
    """
    获取设备示教器规范级原生运行日志流水 (1:1 还原华数示教器 HSR-Pad 运行日志)
    """
    dev = get_device_by_id(device_id)
    if not dev:
        return api_response(code=404, message=f"未找到设备: {device_id}", data=[])
    logs = get_device_logs(device_id=device_id, limit=limit, level=level, filter_type=filter_type)
    return api_response(code=200, message="success", data=logs)


@app.post("/api/devices/{device_type}/{device_id}/logs/confirm_alarms")
def confirm_device_alarms_api(
    device_type: str,
    device_id: str,
    request: Request = None
):
    """
    1:1 复刻华数示教器【确认所有Mc报警信息!】操作
    在设备原生运行日志追加操作流水，并解除当前设备活动报警
    """
    dev = get_device_by_id(device_id)
    if not dev:
        return api_response(code=404, message=f"未找到设备: {device_id}", data=None)

    operator = "Normal"
    if request:
        user_name = request.state.user['username']
        if user_name and user_name != "guest":
            operator = user_name

    result = confirm_all_alarms_log(device_id=device_id, operator=operator)
    return api_response(code=200, message="已登记平台已阅，控制器报警未清除", data=result)



@app.get("/api/devices/{device_type}/{device_id}/report")
def get_device_report_api(
    device_type: str,
    device_id: str,
    period: str = Query("daily", description="报告周期: daily(每日) 或 monthly(每月)"),
    date: Optional[str] = Query(None, description="指定日期 YYYY-MM-DD")
):
    """
    获取设备每日/每月专业运行状态报告 (参考 FANUC iCare: 稼动率、节拍分析、健康度及维保倒计时)
    """
    dev = get_device_by_id(device_id)
    if not dev:
        return api_response(code=404, message=f"未找到设备: {device_id}", data=None)
    report = get_device_report_data(device_id=device_id, period=period, date_str=date)
    return api_response(code=200, message="success", data=report)



@app.get("/api/devices/{device_type}/{device_id}/alarms/analytics")
def get_alarm_analytics_api(
    device_type: str,
    device_id: str,
    days: int = Query(14, ge=3, le=30, description="统计分析天数")
):
    """
    获取报警统计分析图表数据 (参考 FANUC ZDT: 14天报警发生趋势、华数四大类故障分布与TOP5排障建议)
    """
    stats = get_alarm_analytics_stats(device_id=device_id, days=days)
    return api_response(code=200, message="success", data=stats)




@app.get("/api/alarms/knowledge_base")
def get_alarm_knowledge_base_api(
    device_type: Optional[str] = Query(None, description="设备类型"),
    keyword: Optional[str] = Query(None, description="搜索关键字"),
):
    """
    查询故障代码知识库。
    当前知识库导入官方ErrDef.h的32位SDK接口返回码，不是完整64位伺服硬件报警表，
    仅对 huashu_arm 类型设备返回；其他类型设备无对应故障码体系，返回空。
    """
    if device_type and device_type not in ("huashu_arm", "arm"):
        return api_response(code=200, message="该设备类型无华数故障码知识库", data=[])
    data = get_alarm_knowledge_base(keyword)
    return api_response(code=200, message="success", data=data)


@app.get("/api/alarms/resolutions")
def get_alarm_resolutions_api(
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
def add_alarm_resolution_api(body: AddAlarmResolutionRequest=Body(...),request: Request=None):
    values=body.model_dump()
    values['handler']=request.state.user['username']
    ok,msg=add_alarm_resolution(**values)
    return api_response(200 if ok else 400,msg)


@app.get("/api/devices/{device_type}/{device_id}/alarms/active")
def get_device_active_alarms_api(device_type: str,device_id: str):
    latest=get_latest_data(device_type,device_id)
    p=latest.get('parsed_payload',{}) if latest else {}
    count=p.get('error_count')
    has_error=(count>0 or p.get('emergency_stop') is True) if isinstance(count,int) and p.get('state_fresh') else None
    return api_response(data={'device_id':device_id,'device_type':device_type,'has_error':has_error,'current_error_code':None,
        'error_count':count,'recent_alarms':get_device_history(device_type,device_id,page=1,page_size=20,data_type='alarm')})


if STATIC_DIR.exists():
    app.mount('/static',StaticFiles(directory=str(STATIC_DIR)),name='static')


def render_page_with_site_config(template_path: Path) -> HTMLResponse:
    """读取 HTML 模板并在 <head> 顶部同步注入最新的 site_config，确保页面第一帧渲染即为最新自定义图文与图片，杜绝任何异步替换闪烁"""
    headers = {"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache", "Expires": "0"}
    if not template_path.exists():
        return HTMLResponse(content="页面正在就绪中...", status_code=200, headers=headers)
    
    html_content = template_path.read_text(encoding="utf-8")
    try:
        cfg = get_site_config()
        cfg_json = json.dumps(cfg, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
        # 同步注入服务端最新持久化配置，首屏即为用户自定义图文与图片，彻底消除异步替换闪烁
        injection_script = f"""<script>
window.SITE_CONFIG = {cfg_json};
try {{ localStorage.setItem('SITE_CONFIG_CACHE', JSON.stringify({cfg_json})); }} catch(e) {{}}
</script>"""
        if "<head>" in html_content:
            html_content = html_content.replace("<head>", f"<head>\n    {injection_script}", 1)
        elif "<HEAD>" in html_content:
            html_content = html_content.replace("<HEAD>", f"<HEAD>\n    {injection_script}", 1)
    except Exception as e:
        logger.error(f"render_page_with_site_config 注入异常: {e}")
        
    return HTMLResponse(content=html_content, headers=headers)


@app.get("/login", include_in_schema=False)
def serve_login_page():
    """纯净极简浅色登录页面 (带服务端配置即时同步注入)"""
    if LOGIN_HTML.exists():
        return render_page_with_site_config(LOGIN_HTML)
    if INDEX_NEXT_HTML.exists():
        return render_page_with_site_config(INDEX_NEXT_HTML)
    if INDEX_HTML.exists():
        return render_page_with_site_config(INDEX_HTML)
    return api_response(code=200, message="登录页面正在就绪中...")


@app.get("/light", include_in_schema=False)
@app.get("/v2", include_in_schema=False)
@app.get("/next", include_in_schema=False)
@app.get("/preview", include_in_schema=False)
def serve_index_next():
    """全新极简浅白企业版 UI 大屏 (带服务端配置即时同步注入，杜绝替换闪烁)"""
    if INDEX_NEXT_HTML.exists():
        return render_page_with_site_config(INDEX_NEXT_HTML)
    if INDEX_HTML.exists():
        return render_page_with_site_config(INDEX_HTML)
    return api_response(code=200, message="极简浅白版 UI 正在就绪中...")


@app.get("/dark", include_in_schema=False)
@app.get("/", include_in_schema=False)
def serve_index():
    """企业级机器人孪生大屏 UI (带服务端配置即时同步注入，杜绝替换闪烁)"""
    if INDEX_HTML.exists():
        return render_page_with_site_config(INDEX_HTML)
    if INDEX_NEXT_HTML.exists():
        return render_page_with_site_config(INDEX_NEXT_HTML)
    return api_response(code=200, message="机器人物联网管理系统 API 服务正常运行中")


# ---------------------------------------------------------------------------
# 9. 本地直接执行入口
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
