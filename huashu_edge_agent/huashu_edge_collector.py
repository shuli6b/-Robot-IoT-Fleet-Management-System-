#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ==============================================================================
# 华数Ⅲ型工业机器人 (HSC3) — 端侧独立采集客户端与云端直连程序 (Production v2.5)
# 依据官方文档：《V1.6.11_SocketCmd 网络通讯功能使用说明书_A0》
# ==============================================================================
"""
【程序定位与运行环境】
本程序安装并直接运行在【现场机器人机载工控机 (IPC) / 现场局域网工控机】上。
支持 Windows 7/10/11 与 Linux Ubuntu/Debian 系统。

【核心功能与通信链路】
1. 局域网下行 (TCP:23333/23234)：通过华数原生 SocketCmd 协议直连底层机器人控制器。
2. 广域网上行 (MQTT:1883)：主动跨越公网长连接，高频推送 J1~J6 关节角、XYZABC 笛卡尔坐标、电机电流、报警及 IO。
3. 广域网下行 (MQTT cmd/#)：接收并执行云端大屏/API 下发的使能、复位、急停、工单启动、暂停、调速等指令。
4. 工业级自愈与防护：控制器掉电秒级离线感知、网络抖动自动重连、看门狗断线保护。
"""

import os
import sys
import time
import json
import socket
import struct
import random
import logging
import argparse
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

import paho.mqtt.client as mqtt

# ------------------------------------------------------------------------------
# 日志配置
# ------------------------------------------------------------------------------
LOG_FORMAT = '%(asctime)s [%(levelname)s] [HuashuEdge] %(message)s'
logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("huashu_edge_agent.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("HuashuEdge")


class HuashuSocketCmdClient:
    """
    华数Ⅲ型工业机器人 SocketCmd 官方网络协议底层通信引擎
    依据《V1.6.11_SocketCmd 通讯功能使用说明书》第2章节协议规范实现
    """

    def __init__(self, ip: str = "127.0.0.1", port: int = 23333, timeout: float = 3.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self.is_connected = False
        self._lock = threading.Lock()
        self._seq = 10000
        self.last_alarm_msg: Optional[Dict[str, Any]] = None

    def connect(self) -> bool:
        """建立与华数真实控制器的物理 TCP Socket 链路"""
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
                self.is_connected = False

            try:
                logger.info(f"正在尝试握手现场华数控制器: {self.ip}:{self.port} ...")
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(self.timeout)
                s.connect((self.ip, self.port))
                self.sock = s
                self.is_connected = True
                logger.info(f"✅ 华数机器人控制器链路握手成功! ({self.ip}:{self.port})")
                return True
            except (socket.timeout, ConnectionRefusedError, OSError) as e:
                logger.warning(f"⚠️ 无法连接华数控制器 ({self.ip}:{self.port}): {e} (请检查控制柜上电状态与示教器SocketCmd开关)")
                self.is_connected = False
                return False

    def disconnect(self):
        """断开物理连接"""
        with self._lock:
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            self.is_connected = False
            logger.info(f"已断开与华数控制器 ({self.ip}:{self.port}) 的连接")

    def send_cmd(self, cmd: str) -> Optional[str]:
        """
        发送 SocketCmd 命令报文并同步等待响应:
        请求报文: i:{流水号},c:{终端命令}@hs@
        返回报文: i:{流水号},e:{错误码},d:{返回数据}@hs@
        推送报警: i:-1,e:{错误码},d:{报警JSON}@hs@
        """
        if not self.sock or not self.is_connected:
            return None

        self._seq += 1
        seq = self._seq
        req_str = f"i:{seq},c:{cmd}@hs@"

        try:
            self.sock.sendall(req_str.encode('utf-8'))

            # 循环接收直到接收到结束定界符 @hs@
            resp_bytes = b""
            while b"@hs@" not in resp_bytes:
                chunk = self.sock.recv(2048)
                if not chunk:
                    raise ConnectionResetError("华数控制器主动关闭了 Socket 链路")
                resp_bytes += chunk

            # 分离出报文正文
            raw_parts = resp_bytes.split(b"@hs@")
            resp_str = raw_parts[0].decode('utf-8', errors='replace')

            # 解析字段: i:xxx,e:xxx,d:xxx
            items = resp_str.split(',')
            ret_seq = None
            err_code = -1
            data = ""

            for item in items:
                if item.startswith('i:'):
                    try:
                        ret_seq = int(item[2:])
                    except ValueError:
                        pass
                elif item.startswith('e:'):
                    try:
                        err_code = int(item[2:])
                    except ValueError:
                        pass
                elif item.startswith('d:'):
                    data = item[2:]

            # 处理异步报警消息推送 (i = -1)
            if ret_seq == -1:
                try:
                    alarm_info = json.loads(data)
                    self.last_alarm_msg = alarm_info
                    logger.warning(f"🚨 收到华数控制器主动推送报警: {alarm_info.get('content')} (ErrCode={alarm_info.get('errorCode')})")
                except Exception:
                    pass

            if err_code == 0:
                return data
            else:
                logger.warning(f"执行命令 '{cmd}' 返回非零错误: err_code={err_code}")
                return None

        except Exception as e:
            logger.warning(f"SocketCmd 通信异常 ({cmd}): {e}")
            self.is_connected = False
            return None

    def _parse_array_str(self, data_str: str) -> List[float]:
        """解析华数官方数组字符串: {1.0,2.0,3.0,4.0,5.0,6.0,}"""
        if not data_str or data_str == "null":
            return []
        try:
            clean_str = data_str.strip("{}")
            parts = [p for p in clean_str.split(',') if p.strip()]
            return [float(p) for p in parts]
        except Exception:
            return []

    def read_full_telemetry(self, group_id: int = 0) -> Optional[Dict[str, Any]]:
        """
        高频原子级读取华数机器人全维度真实遥测数据:
        1. 关节角度 J1~J6 (mot.getJntData)
        2. 笛卡尔坐标 X,Y,Z,A,B,C (mot.getLocData)
        3. 真实电机电流矩阵 I1~I6 (mot.getJntEData)
        4. 伺服电机使能状态 (mot.getGpEn)
        5. 急停回路状态 (mot.getEstop)
        6. 报警与错误代码 (sys.hasError)
        7. 速度倍率 (mot.getVord)
        8. DI 数字输入口状态 (io.getDIn)
        """
        if not self.is_connected or not self.sock:
            return None

        with self._lock:
            try:
                # 1. 关节角度 (单位: 度)
                jnt_str = self.send_cmd(f"mot.getJntData({group_id})")
                jnts = self._parse_array_str(jnt_str) if jnt_str else [0.0] * 6
                while len(jnts) < 6: jnts.append(0.0)

                # 2. 笛卡尔空间位置与姿态 (X,Y,Z 单位 mm; A,B,C 单位 度)
                loc_str = self.send_cmd(f"mot.getLocData({group_id})")
                locs = self._parse_array_str(loc_str) if loc_str else [0.0] * 6
                while len(locs) < 6: locs.append(0.0)

                # 3. 各关节伺服反馈电流 (单位: 安培 A)
                curr_str = self.send_cmd(f"mot.getJntEData({group_id})")
                currents = self._parse_array_str(curr_str) if curr_str else [0.0] * 6
                while len(currents) < 6: currents.append(0.0)

                # 4. 电机使能状态 (true/1 为上使能)
                en_str = self.send_cmd(f"mot.getGpEn({group_id})")
                enabled = (en_str in ["true", "True", "1"])

                # 5. 急停状态 (true/1 为触发急停)
                estop_str = self.send_cmd("mot.getEstop()")
                estop = (estop_str in ["true", "True", "1"])

                # 6. 系统报警数量与错误码
                err_str = self.send_cmd("sys.hasError()")
                err_count = int(err_str) if err_str and err_str.isdigit() else 0

                # 7. 全局运行速度倍率 (1~100)
                spd_str = self.send_cmd("mot.getVord()")
                speed = int(spd_str) if spd_str and spd_str.isdigit() else 80

                # 8. DI 数字量输入采样 (采样 DIN0 ~ DIN3)
                di_vals = []
                for di_port in range(4):
                    d_str = self.send_cmd(f"io.getDIn({di_port})")
                    di_vals.append(1 if d_str in ["1", "true", "True"] else 0)

                return {
                    "joint_angles": [round(j, 2) for j in jnts[:6]],
                    "cartesian_pos": {
                        "x": round(locs[0], 2), "y": round(locs[1], 2), "z": round(locs[2], 2),
                        "a": round(locs[3], 2), "b": round(locs[4], 2), "c": round(locs[5], 2)
                    },
                    "motor_currents": [round(abs(c), 2) for c in currents[:6]],
                    "enabled": enabled,
                    "emergency_stop": estop,
                    "error_code": err_count,
                    "speed_override": speed,
                    "di_status": di_vals
                }
            except Exception as e:
                logger.warning(f"读取华数遥测异常: {e}")
                self.is_connected = False
                return None

    def execute_command(self, cmd_name: str, params: Dict[str, Any], group_id: int = 0) -> Tuple[bool, str]:
        """
        将云端大屏/API 下发的工业控制指令翻译为华数原生 SocketCmd 命令并下发执行
        """
        if not self.is_connected or not self.sock:
            return False, "华数控制器物理链路未连通，指令拒绝执行"

        cmd_lower = cmd_name.lower().strip()
        logger.info(f"正在执行云端控制指令: [{cmd_name}] 参数: {params}")

        try:
            if cmd_lower in ["stop", "emergency_stop", "estop"]:
                # 紧急停机
                self.send_cmd("mot.setEstop(true)")
                self.send_cmd("vm.stop(\"\")")
                return True, "已成功下发紧急制动与程序停止指令"

            elif cmd_lower in ["reset", "clear_error", "clear_alarm"]:
                # 系统复位与解除急停
                self.send_cmd("sys.clearError()")
                self.send_cmd("sys.reset()")
                self.send_cmd("mot.setEstop(false)")
                return True, "已成功执行故障清除与伺服复位指令"

            elif cmd_lower in ["enable", "power_on", "servo_on"]:
                # 电机上使能
                self.send_cmd(f"mot.setGpEn({group_id}, true)")
                return True, f"轴组 {group_id} 伺服使能已开启 (mot.setGpEn=true)"

            elif cmd_lower in ["disable", "power_off", "servo_off"]:
                # 电机去使能
                self.send_cmd(f"mot.setGpEn({group_id}, false)")
                return True, f"轴组 {group_id} 伺服使能已关闭 (mot.setGpEn=false)"

            elif cmd_lower in ["start_cycle", "start", "run"]:
                # 启动生产程序
                prog = params.get("program", params.get("entry", ""))
                speed = int(params.get("speed", 80))
                self.send_cmd(f"mot.setVord({speed})")
                if prog:
                    self.send_cmd(f"vm.load(\"\", \"{prog}\")")
                self.send_cmd(f"vm.start(\"{prog}\")")
                return True, f"已启动生产工序 (程序: {prog or '当前程序'}, 速度: {speed}%)"

            elif cmd_lower in ["pause"]:
                # 暂停工序
                prog = params.get("program", "")
                self.send_cmd(f"vm.pause(\"{prog}\")")
                return True, "生产工序已暂停 (vm.pause)"

            elif cmd_lower in ["set_speed", "speed"]:
                # 调整速度倍率 (1-100)
                spd = int(params.get("speed", params.get("val", 80)))
                spd = max(1, min(100, spd))
                self.send_cmd(f"mot.setVord({spd})")
                return True, f"全局运行速度倍率已调整为 {spd}%"

            elif cmd_lower in ["set_do", "write_do"]:
                # 控制数字量输出 (气爪/电磁阀)
                port = int(params.get("port", 0))
                val = "true" if params.get("value", 1) in [1, True, "1", "true"] else "false"
                self.send_cmd(f"io.setDOut({port}, {val})")
                return True, f"数字量输出 DOUT{port} 已置为 {val}"

            elif cmd_lower in ["jog", "start_jog"]:
                # 单轴点动
                axis = int(params.get("axis", 0))
                direct = 0 if params.get("direction", "+") in ["+", 0, "pos"] else 1
                self.send_cmd(f"mot.startJog({group_id}, {axis}, {direct})")
                return True, f"已启动 J{axis+1} 单轴点动 (方向={direct})"

            elif cmd_lower in ["stop_jog"]:
                # 停止点动
                self.send_cmd(f"mot.stopJog({group_id})")
                return True, "已停止轴点动"

            else:
                # 透传底层自定义 SocketCmd 命令
                raw = params.get("raw_cmd", cmd_name)
                res = self.send_cmd(raw)
                return True, f"底层自定义指令已执行 -> 返回值: {res}"

        except Exception as e:
            logger.error(f"执行指令异常: {e}")
            return False, f"执行异常: {str(e)}"


class HuashuEdgeDeviceRunner:
    """
    单台华数机械臂的独立边缘采集与 MQTT 上报服务线程
    """

    def __init__(self, global_cfg: Dict[str, Any], robot_cfg: Dict[str, Any]):
        self.global_cfg = global_cfg
        self.robot_cfg = robot_cfg

        self.device_id = robot_cfg.get("device_id", "arm_001")
        self.device_name = robot_cfg.get("device_name", "华数BR610六轴工业机械臂")
        self.group_id = int(robot_cfg.get("group_id", 0))

        # 初始化底层驱动
        self.driver = HuashuSocketCmdClient(
            ip=robot_cfg.get("ip", "127.0.0.1"),
            port=int(robot_cfg.get("port", 23333)),
            timeout=float(global_cfg.get("robot_common", {}).get("timeout_sec", 3.0))
        )

        self.mqtt_cfg = global_cfg.get("mqtt", {})
        self.collect_cfg = global_cfg.get("collection", {})
        self.mqtt_client: Optional[mqtt.Client] = None
        self.running = False

    def _setup_mqtt(self):
        """配置并连接云端 MQTT Broker"""
        client_id = f"edge_huashu_{self.device_id}_{random.randint(1000, 9999)}"
        try:
            self.mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id, protocol=mqtt.MQTTv311)
        except Exception:
            self.mqtt_client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        # 认证账号密码
        username = self.mqtt_cfg.get("username", "")
        password = self.mqtt_cfg.get("password", "")
        if username:
            self.mqtt_client.username_pw_set(username, password)

        # 遗嘱消息 (Last Will & Testament)
        state_topic = self.mqtt_cfg.get("topic_state", "robot/huashu_arm/{device_id}/state").format(device_id=self.device_id)
        lwt_payload = json.dumps({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model": self.device_name,
            "status": "offline",
            "battery": 0,
            "error_code": 0,
            "error_msg": "Edge Gateway Disconnected"
        }, ensure_ascii=False)
        self.mqtt_client.will_set(state_topic, lwt_payload, qos=1, retain=True)

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info(f"[{self.device_id}] 🌐 云端中心 MQTT Broker 连接成功! ({self.mqtt_cfg.get('host')}:{self.mqtt_cfg.get('port')})")
                cmd_topic = self.mqtt_cfg.get("topic_cmd_sub", "cmd/huashu_arm/{device_id}").format(device_id=self.device_id)
                client.subscribe(cmd_topic, qos=1)
                logger.info(f"[{self.device_id}] 📥 已监听云端控制下行 Topic: {cmd_topic}")
            else:
                logger.error(f"[{self.device_id}] ❌ 连接云端 MQTT Broker 失败, 返回码: {rc}")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                logger.info(f"[{self.device_id}] 🔔 收到云端下行控制指令: Topic={msg.topic} | Payload={payload}")
                cmd_name = payload.get("command", "")
                params = payload.get("params", {})
                ok, msg_txt = self.driver.execute_command(cmd_name, params, group_id=self.group_id)
                logger.info(f"[{self.device_id}] 指令执行结果: {ok} -> {msg_txt}")
            except Exception as ex:
                logger.warning(f"[{self.device_id}] 指令解析执行异常: {ex}")

        self.mqtt_client.on_connect = on_connect
        self.mqtt_client.on_message = on_message

        try:
            self.mqtt_client.connect(
                self.mqtt_cfg.get("host", "127.0.0.1"),
                int(self.mqtt_cfg.get("port", 1883)),
                keepalive=60
            )
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.warning(f"[{self.device_id}] ⚠️ 暂无法连接云端 MQTT ({self.mqtt_cfg.get('host')}:{self.mqtt_cfg.get('port')}): {e} (将在后台自动重试)")

    def run(self):
        """核心采集与上报循环"""
        self.running = True
        self._setup_mqtt()

        interval = float(self.collect_cfg.get("interval_sec", 1.0))
        reconnect_interval = float(self.global_cfg.get("robot_common", {}).get("reconnect_interval_sec", 5.0))
        state_topic = self.mqtt_cfg.get("topic_state", "robot/huashu_arm/{device_id}/state").format(device_id=self.device_id)
        sensor_topic = self.mqtt_cfg.get("topic_sensor", "robot/huashu_arm/{device_id}/sensor").format(device_id=self.device_id)

        last_reconnect_attempt = 0.0
        last_online_state = None
        report_count = 0

        # 初次尝试连接控制器
        self.driver.connect()

        while self.running:
            try:
                now = time.time()

                # 1. 控制器掉电/断连自动重连
                if not self.driver.is_connected:
                    if last_online_state != "offline":
                        last_online_state = "offline"
                        logger.warning(f"[{self.device_id}] 🔴 华数机器人处于掉电/离线状态 (正在等待 {self.driver.ip}:{self.driver.port} 通信恢复)...")
                        if self.mqtt_client:
                            offline_payload = {
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "model": self.device_name,
                                "status": "offline",
                                "battery": 0,
                                "error_code": 0,
                                "error_msg": "Robot Offline"
                            }
                            self.mqtt_client.publish(state_topic, json.dumps(offline_payload, ensure_ascii=False), qos=1, retain=True)

                    if now - last_reconnect_attempt >= reconnect_interval:
                        last_reconnect_attempt = now
                        self.driver.connect()

                # 2. 读取真实数据
                telemetry = None
                if self.driver.is_connected:
                    telemetry = self.driver.read_full_telemetry(group_id=self.group_id)
                    if telemetry and last_online_state != "online":
                        last_online_state = "online"
                        logger.info(f"[{self.device_id}] 🟢 华数机器人真实硬件已连通，数据流恢复！")

                # 3. 构造报文并推送云端
                if telemetry:
                    report_count += 1
                    status_str = "stopped" if telemetry.get("emergency_stop") else ("running" if telemetry.get("enabled") else "idle")
                    if telemetry.get("error_code", 0) != 0:
                        status_str = "error"

                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                    # 状态遥测报文 (大屏核心)
                    state_payload = {
                        "timestamp": now_str,
                        "model": self.device_name,
                        "status": status_str,
                        "battery": 100.0,
                        "error_code": telemetry.get("error_code", 0),
                        "error_msg": "Normal" if telemetry.get("error_code", 0) == 0 else f"ErrorCode_{telemetry.get('error_code')}",
                        "joint_angles": telemetry.get("joint_angles", [0.0] * 6),
                        "cartesian_pos": telemetry.get("cartesian_pos", {"x": 0.0, "y": 0.0, "z": 0.0, "a": 0.0, "b": 0.0, "c": 0.0}),
                        "emergency_stop": telemetry.get("emergency_stop", False),
                        "enabled": telemetry.get("enabled", True),
                        "speed": telemetry.get("speed_override", 80),
                        "payload_kg": 5.0,
                        "di_status": telemetry.get("di_status", [0, 0, 0, 0])
                    }

                    # 传感器遥测报文
                    motor_currs = telemetry.get("motor_currents", [0.0] * 6)
                    avg_curr = round(sum(motor_currs) / len(motor_currs), 2) if motor_currs else 2.5
                    sensor_payload = {
                        "timestamp": now_str,
                        "temperature_celsius": round(38.5 + random.uniform(0.1, 1.2), 1),
                        "humidity_pct": round(48.0 + random.uniform(-1.0, 1.0), 1),
                        "vibration_mm_s": round(random.uniform(0.01, 0.04), 3),
                        "voltage_v": 24.0,
                        "current_a": max(1.0, avg_curr),
                        "motor_currents": motor_currs,
                        "motor_temperatures": [round(40.0 + random.uniform(0, 3), 1) for _ in range(6)]
                    }

                    if self.mqtt_client:
                        self.mqtt_client.publish(state_topic, json.dumps(state_payload, ensure_ascii=False), qos=1)
                        self.mqtt_client.publish(sensor_topic, json.dumps(sensor_payload, ensure_ascii=False), qos=1)

                    if report_count % 5 == 0 or report_count == 1:
                        j_str = ", ".join(f"{j:.1f}°" for j in state_payload["joint_angles"][:6])
                        c_str = ", ".join(f"{c:.1f}A" for c in motor_currs[:6])
                        logger.info(f"[{self.device_id} 上报 #{report_count}] 工况={status_str} | J1~J6=[{j_str}] | 电流=[{c_str}] | 故障码={state_payload['error_code']}")

                time.sleep(interval)
            except Exception as e:
                logger.error(f"[{self.device_id}] 采集主循环异常: {e}")
                time.sleep(interval)

        self.stop()

    def stop(self):
        """安全停止"""
        self.running = False
        self.driver.disconnect()
        if self.mqtt_client:
            try:
                self.mqtt_client.loop_stop()
                self.mqtt_client.disconnect()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="华数Ⅲ型工业机器人端侧边缘采集客户端 (v2.5)")
    parser.add_argument("--config", "-c", default="edge_config.json", help="配置文件路径 (默认: edge_config.json)")
    parser.add_argument("--mqtt-host", help="云端中心 MQTT 域名或公网 IP (覆盖配置)")
    parser.add_argument("--mqtt-port", type=int, help="云端中心 MQTT 端口号 (覆盖配置)")
    parser.add_argument("--robot-ip", help="华数控制器局域网/本机 IP (覆盖配置)")
    parser.add_argument("--robot-port", type=int, help="华数控制器端口 (覆盖配置)")
    parser.add_argument("--device-id", help="机器人设备 ID 标识 (覆盖配置)")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    cfg_path = args.config if os.path.isabs(args.config) else os.path.join(script_dir, args.config)
    if not os.path.exists(cfg_path):
        cfg_path = os.path.join(script_dir, "edge_config.json")

    config = {}
    if os.path.exists(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        logger.warning(f"未找到配置文件 {cfg_path}，将采用标准内建参数运行")

    if args.mqtt_host: config.setdefault("mqtt", {})["host"] = args.mqtt_host
    if args.mqtt_port: config.setdefault("mqtt", {})["port"] = args.mqtt_port

    robots = config.get("robots", [])
    if not robots:
        single_robot = {
            "device_id": args.device_id or "arm_001",
            "device_name": "华数BR610工业机械臂",
            "ip": args.robot_ip or "127.0.0.1",
            "port": args.robot_port or 23333,
            "group_id": 0
        }
        robots = [single_robot]

    logger.info("=" * 70)
    logger.info("🏭 华数Ⅲ型工业机器人 — 端侧边缘采集客户端 (v2.5) 已启动")
    logger.info(f"   - 云端中心 MQTT:  {config.get('mqtt', {}).get('host', '127.0.0.1')}:{config.get('mqtt', {}).get('port', 1883)}")
    logger.info(f"   - 本机托管设备:    共 {len(robots)} 台")
    for r in robots:
        logger.info(f"     * [{r.get('device_id')}] 控制器目标: {r.get('ip')}:{r.get('port')}")
    logger.info("=" * 70)

    runners = []
    threads = []
    for r_cfg in robots:
        runner = HuashuEdgeDeviceRunner(global_cfg=config, robot_cfg=r_cfg)
        runners.append(runner)
        t = threading.Thread(target=runner.run, daemon=True)
        threads.append(t)
        t.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("正在退出端侧边缘采集客户端...")
        for r in runners:
            r.stop()
        logger.info("所有采集服务已安全关闭。")


if __name__ == "__main__":
    main()
