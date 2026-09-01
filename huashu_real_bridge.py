#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
huashu_real_bridge.py - 生产级真实华数六轴工业机械臂采集与控制服务
=============================================================================
功能说明：
1. 直连真实华数 Ⅲ 型控制器 (192.168.1.169:23333)。
   ⚠️ 192.168.1.168/.144/.170 与 .169 的 MAC 同为 70:93:14:53:29:2c，系同一台设备的
      IP 别名，接入多个只会得到重复数据，故只接入 1 个。
2. 通过原生 HSC3 SocketCmd 协议（官方《V1.6.11_SocketCmd 网络通讯功能使用说明书》）
   采集物理机械臂 J1~J6 真实关节角度、末端笛卡尔坐标、关节反馈电流、报警状态。
3. 严格遵循真实物理状态：静止即静止，运动即运动，急停与报警 100% 真实映射。
   采集失败时上报 offline，绝不输出伪造姿态。
4. 订阅云端下行指令并映射为官方真实命令执行，执行结果回传 cmd_ack。
5. 消息经由本地 MQTT (127.0.0.1:1883) 转发至物联网管控平台。
=============================================================================
"""

import os
import sys
import time
import json
import socket
import logging
import threading
import signal
from datetime import datetime

import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] [HuashuRealBridge] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("HuashuRealBridge")

# 现场唯一真实物理机械臂控制器配置
ROBOTS = [
    {"device_id": "arm_001", "ip": "192.168.1.169", "name": "华数BR610六轴工业机械臂"},
]

MQTT_HOST = "127.0.0.1"
MQTT_PORT = 1883
INTERVAL = 0.2  # 5Hz 高频实时姿态上报

# 安全开关：运动类指令（jog/home/start_cycle）默认关闭，待现场确认安全后开启
ENABLE_MOTION_COMMANDS = os.getenv("HUAHSHU_ENABLE_MOTION", "0") == "1"

running = True


def handle_exit(signum, frame):
    global running
    logger.info("收到退出信号，停止真实机械臂采集桥接...")
    running = False


signal.signal(signal.SIGINT, handle_exit)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, handle_exit)


def parse_array_str(s):
    """解析官方返回格式 {1.0,2.0,3.0,} 为 float 列表。"""
    if not s or s == "null":
        return []
    try:
        clean = s.strip()
        if clean.startswith("{"):
            clean = clean[1:]
        if clean.endswith("}"):
            clean = clean[:-1]
        parts = [p.strip() for p in clean.split(",") if p.strip()]
        return [float(p) for p in parts]
    except Exception as e:
        logger.warning(f"解析数组异常: {s} -> {e}")
        return []


class HuashuRobotCollector(threading.Thread):
    """单台真机采集 + 指令执行线程。"""

    # 前端指令 -> 官方命令模板（%s 处由参数填充）
    SAFE_CMD_MAP = {
        "enable": "mot.setGpEn(0,true)",
        "disable": "mot.setGpEn(0,false)",
        "emergency_stop": "mot.setEstop(true)",
        "stop": "mot.setEstop(true)",
        "reset": "sys.reset()",
        "set_override": "mot.setVord({v})",
        "set_do": "io.setDout({port},{val})",
    }
    MOTION_CMD_MAP = {
        "jog_joint": ("mot.startJog(0,{axis},{dir})", "mot.stopJog(0)", "{step_sec}"),
        "home": "mot.moveTo(0,true,0,0,0,\"{home}\",false)",
        "start_cycle": "vm.start({entry})",
        "pause": "vm.pause({entry})",
        "resume": "vm.start({entry})",
        "select_prog": "vm.load({path},{entry})",
    }

    def __init__(self, r_info, mqtt_client):
        super().__init__(daemon=True)
        self.device_id = r_info["device_id"]
        self.ip = r_info["ip"]
        self.name = r_info["name"]
        self.mqtt = mqtt_client
        self.seq = 1
        self.buffer = b""
        self.lock = threading.Lock()
        self.robot_model = ""
        self.op_mode = -1
        self.home_pos = ""

    # ------------------------------------------------------------------ #
    # SocketCmd 协议通信
    # ------------------------------------------------------------------ #
    def _send_raw(self, sock, cmd, timeout=3.0):
        """发送命令并读取完整报文，返回 (ok, err_code, data_str)。"""
        with self.lock:
            self.seq += 1
            curr_seq = self.seq
            req = f"i:{curr_seq},c:{cmd}@hs@".encode('utf-8')
            sock.sendall(req)
            sock.settimeout(timeout)

            while True:
                if b"@hs@" in self.buffer:
                    packet, self.buffer = self.buffer.split(b"@hs@", 1)
                    raw_str = packet.decode('utf-8', errors='ignore')
                    # 只接受匹配当前流水号的响应，其余视为过期响应丢弃
                    if (f"i:{curr_seq}," in raw_str or f"i:{curr_seq}:" in raw_str
                            or raw_str.startswith(f"i:{curr_seq}")):
                        # 解析错误码 e:（位于 d: 之前，不含逗号）
                        err_code = -1
                        ei = raw_str.find("e:")
                        if ei != -1:
                            seg = raw_str[ei + 2:].split(",")[0].strip()
                            try:
                                err_code = int(seg)
                            except Exception:
                                err_code = -1
                        # 解析数据 d:（内容可能含逗号，取 d: 之后全部内容）
                        data = ""
                        di = raw_str.find("d:")
                        if di != -1:
                            data = raw_str[di + 2:].strip()
                        return err_code == 0, err_code, data
                    continue
                chunk = sock.recv(4096)
                if not chunk:
                    raise ConnectionResetError("连接断开")
                self.buffer += chunk

    def send_cmd(self, sock, cmd, timeout=3.0):
        """便捷包装：返回 (ok, data)。"""
        ok, err, data = self._send_raw(sock, cmd, timeout)
        return ok, data

    # ------------------------------------------------------------------ #
    # 真实数据采集
    # ------------------------------------------------------------------ #
    def collect_once(self, sock):
        """采集一帧真实数据；任何一项失败抛异常交由上层进入重连。"""
        out = {}

        ok, jnt_str = self.send_cmd(sock, "mot.getJntData(0)")
        if not ok:
            raise RuntimeError("getJntData 命令失败")
        jnt_arr = parse_array_str(jnt_str)
        if len(jnt_arr) < 6:
            raise RuntimeError("getJntData 返回数据不完整")
        out["joint_angles"] = [round(x, 2) for x in jnt_arr[:6]]

        ok, loc_str = self.send_cmd(sock, "mot.getLocData(0)")
        if not ok:
            raise RuntimeError("getLocData 命令失败")
        loc_arr = parse_array_str(loc_str)
        if len(loc_arr) < 6:
            raise RuntimeError("getLocData 返回数据不完整")
        out["cartesian_pos"] = {
            "x": round(loc_arr[0], 1), "y": round(loc_arr[1], 1), "z": round(loc_arr[2], 1),
            "a": round(loc_arr[3], 1), "b": round(loc_arr[4], 1), "c": round(loc_arr[5], 1),
        }

        ok, en_str = self.send_cmd(sock, "mot.getGpEn(0)")
        out["enabled"] = ok and en_str.strip().lower() == "true"

        ok, estop_str = self.send_cmd(sock, "mot.getEstop()")
        out["emergency_stop"] = ok and estop_str.strip().lower() == "true"

        # 关节反馈电流（官方 4.9.48）
        ok, cur_str = self.send_cmd(sock, "mot.getJntEData(0)")
        cur_arr = parse_array_str(cur_str)
        out["motor_currents"] = [round(x, 2) for x in cur_arr[:6]] if ok and len(cur_arr) >= 6 else []

        # 真实报警数（官方 4.4.2）
        ok, err_str = self.send_cmd(sock, "sys.hasError()")
        out["error_code"] = int(err_str) if ok and err_str.strip().isdigit() else 0
        if out["error_code"] > 0:
            # 查询首条报警详情（官方 4.4.3）
            ok, q_str = self.send_cmd(sock, f"sys.queryError({out['error_code']})")
            out["error_msg"] = q_str.strip()[:200] if ok and q_str else f"报警数 {out['error_code']}"
        else:
            out["error_msg"] = ""

        # 运行模式（官方 4.9.5：1=T1 2=T2 3=自动 4=外部）
        ok, op_str = self.send_cmd(sock, "mot.getOpMode()")
        self.op_mode = int(op_str.strip()) if ok and op_str.strip().isdigit() else -1
        out["op_mode"] = self.op_mode

        # 机型与零点（仅在启动时缓存一次）
        if not self.robot_model:
            ok, m_str = self.send_cmd(sock, "mot.getRobTypeName(0)")
            self.robot_model = m_str.strip() if ok else ""
        out["robot_model"] = self.robot_model

        if not self.home_pos:
            ok, h_str = self.send_cmd(sock, "mot.getHomePosition(0)")
            if ok:
                self.home_pos = h_str.strip()
        out["home_position"] = self.home_pos

        # 数字 IO（官方 4.11.5/4.11.6）
        ok, di_str = self.send_cmd(sock, "io.getDinGrp(0)")
        ok2, do_str = self.send_cmd(sock, "io.getDoutGrp(0)")
        out["di"] = int(di_str) if ok and di_str.strip().isdigit() else 0
        out["do"] = int(do_str) if ok2 and do_str.strip().isdigit() else 0

        if out["emergency_stop"]:
            status = "error"
        elif out["error_code"] > 0:
            status = "error"
        elif out["enabled"]:
            status = "online"
        else:
            status = "standby"
        out["status"] = status

        return out

    def publish_state(self, data: dict):
        payload_state = {
            "device_id": self.device_id,
            "device_type": "huashu_arm",
            "status": data.get("status", "standby"),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "joint_angles": data.get("joint_angles", []),
            "cartesian_pos": data.get("cartesian_pos", {}),
            "enabled": data.get("enabled", False),
            "emergency_stop": data.get("emergency_stop", False),
            "error_code": data.get("error_code", 0),
            "error_msg": data.get("error_msg", ""),
            "op_mode": data.get("op_mode", -1),
            "robot_model": data.get("robot_model", ""),
            "motor_currents": data.get("motor_currents", []),
            "di": data.get("di", 0),
            "do": data.get("do", 0),
            "simulated": False,
        }
        self.mqtt.publish(
            f"robot/huashu_arm/{self.device_id}/state",
            json.dumps(payload_state, ensure_ascii=False),
            qos=1,
        )

        payload_io = {
            "device_id": self.device_id,
            "timestamp": payload_state["timestamp"],
            "di": data.get("di", 0),
            "do": data.get("do", 0),
        }
        self.mqtt.publish(
            f"robot/huashu_arm/{self.device_id}/io",
            json.dumps(payload_io, ensure_ascii=False),
            qos=1,
        )

    def publish_offline(self, reason: str = ""):
        payload = {
            "device_id": self.device_id,
            "device_type": "huashu_arm",
            "status": "offline",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "error_code": -1,
            "error_msg": reason or "控制器通信中断",
            "simulated": False,
        }
        self.mqtt.publish(
            f"robot/huashu_arm/{self.device_id}/state",
            json.dumps(payload, ensure_ascii=False),
            qos=1, retain=True,
        )
        logger.warning(f"真机 [{self.device_id}] 上报离线: {reason}")

    # ------------------------------------------------------------------ #
    # 指令执行（映射官方真实命令）
    # ------------------------------------------------------------------ #
    def execute_command(self, sock, command: str, params: dict, task_id: str):
        """执行一条下行指令，返回 (ok, err_code, raw_response, message)。"""
        cmd_lower = (command or "").strip().lower()
        result = {"task_id": task_id, "command": command, "ok": False,
                  "err_code": -1, "raw_response": "", "message": "",
                  "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

        try:
            real_cmd = None
            hold_sec = 0.0

            if cmd_lower in self.SAFE_CMD_MAP:
                tpl = self.SAFE_CMD_MAP[cmd_lower]
                if cmd_lower == "set_override":
                    real_cmd = tpl.format(v=int(params.get("override", 80)))
                elif cmd_lower == "set_do":
                    val = "true" if int(params.get("value", 1)) > 0 else "false"
                    real_cmd = tpl.format(port=int(params.get("port", 1)), val=val)
                else:
                    real_cmd = tpl
            elif cmd_lower in self.MOTION_CMD_MAP:
                if not ENABLE_MOTION_COMMANDS:
                    result["message"] = "运动类指令未开放（现场确认安全后置 HUAHSHU_ENABLE_MOTION=1 重启服务）"
                    return result
                tpl = self.MOTION_CMD_MAP[cmd_lower]
                if cmd_lower == "jog_joint":
                    real_cmd = tpl[0].format(axis=int(params.get("axis", 1)),
                                             dir=int(params.get("direction", 1)))
                    stop_cmd = tpl[1]
                    hold_sec = float(params.get("step_deg", 5.0)) / 10.0
                    hold_sec = max(0.2, min(hold_sec, 2.0))
                    # 点动：start -> 保持 -> stop
                    self.send_cmd(sock, real_cmd)
                    time.sleep(hold_sec)
                    self.send_cmd(sock, stop_cmd)
                    result["ok"] = True
                    result["message"] = "点动指令已执行"
                    return result
                elif cmd_lower == "home":
                    real_cmd = tpl.format(home=self.home_pos or "{0,-90,180,0,0,0}")
                elif cmd_lower == "select_prog":
                    real_cmd = tpl.format(path=params.get("prog_name", "MAIN.PRG"),
                                          entry=params.get("prog_name", "MAIN.PRG"))
                elif cmd_lower in ("start_cycle", "resume"):
                    real_cmd = tpl.format(entry=params.get("entry", "MAIN"))
                elif cmd_lower == "pause":
                    real_cmd = tpl.format(entry=params.get("entry", "MAIN"))
            else:
                result["message"] = f"未知指令类型: {command}"
                return result

            if not real_cmd:
                result["message"] = "指令映射为空"
                return result

            ok, err, data = self._send_raw(sock, real_cmd)
            result["ok"] = ok
            result["err_code"] = err
            result["raw_response"] = data if data else ""
            result["message"] = "指令执行成功" if ok else f"指令执行失败 (err={err})"
            if not ok:
                logger.warning(f"[{self.device_id}] 指令 {cmd_lower} 执行失败 err={err}")
            else:
                logger.info(f"[{self.device_id}] 指令 {cmd_lower} 执行成功: {real_cmd}")
        except Exception as e:
            result["message"] = f"指令执行异常: {e}"
            logger.warning(f"[{self.device_id}] 指令异常: {e}")
        return result

    def on_cmd_message(self, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8", errors="ignore"))
        except Exception:
            logger.warning(f"[{self.device_id}] 指令报文解析失败: {msg.payload[:200]}")
            return
        command = payload.get("command", "")
        params = payload.get("params", {}) or {}
        task_id = payload.get("task_id", f"T{int(time.time()*1000)}")
        logger.info(f"[{self.device_id}] 收到指令: {command} 参数: {params}")

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((self.ip, 23333))
        except Exception as e:
            ack = {"task_id": task_id, "command": command, "ok": False,
                   "err_code": -1, "message": f"控制器不可达: {e}",
                   "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            self.mqtt.publish(f"robot/huashu_arm/{self.device_id}/cmd_ack",
                              json.dumps(ack, ensure_ascii=False), qos=1)
            return
        try:
            result = self.execute_command(sock, command, params, task_id)
        finally:
            try:
                sock.close()
            except Exception:
                pass
        self.mqtt.publish(
            f"robot/huashu_arm/{self.device_id}/cmd_ack",
            json.dumps(result, ensure_ascii=False), qos=1,
        )

    # ------------------------------------------------------------------ #
    # 主采集循环
    # ------------------------------------------------------------------ #
    def run(self):
        logger.info(f"启动机械臂采集线程 [{self.device_id}] IP: {self.ip}:23333 ...")
        while running:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(3.0)
                sock.connect((self.ip, 23333))
                logger.info(f"✅ 成功连接华数真机 [{self.device_id}] ({self.ip}:23333)")

                while running:
                    t_start = time.time()
                    try:
                        data = self.collect_once(sock)
                        self.publish_state(data)
                    except Exception as e:
                        logger.warning(f"真机 [{self.device_id}] 通信读取异常: {e}")
                        self.publish_offline(str(e))
                        break

                    sleep_dur = INTERVAL - (time.time() - t_start)
                    if sleep_dur > 0:
                        time.sleep(sleep_dur)
            except Exception as e:
                logger.warning(f"真机 [{self.device_id}] 连接失败 ({self.ip}): {e}，5秒后重试...")
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass
            if running:
                time.sleep(3.0)


def main():
    logger.info("==================================================")
    logger.info("   华数真实工业机器人 1:1 物理数字孪生采集与控制服务启动")
    logger.info("==================================================")

    mqtt_client = None
    try:
        try:
            mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                      client_id="huashu_real_fleet_bridge")
        except Exception:
            mqtt_client = mqtt.Client(client_id="huashu_real_fleet_bridge")
    except Exception as e:
        logger.error(f"MQTT 客户端创建失败: {e}")
        return

    # 指令回调：路由到对应设备采集线程
    cmd_routers = {}

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info(f"MQTT 连接成功 [{MQTT_HOST}:{MQTT_PORT}]")
            for r in ROBOTS:
                topic = f"cmd/huashu_arm/{r['device_id']}"
                client.subscribe(topic, qos=1)
                logger.info(f"已订阅指令主题: {topic}")
        else:
            logger.error(f"MQTT 连接失败, rc={rc}")

    def on_message(client, userdata, msg):
        if msg.topic.startswith("cmd/"):
            parts = msg.topic.split("/")
            if len(parts) >= 3:
                dev_id = parts[2]
                router = cmd_routers.get(dev_id)
                if router:
                    router(msg)

    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message

    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
    except Exception as e:
        logger.error(f"MQTT 连接失败: {e}")
        return

    collectors = []
    for r in ROBOTS:
        c = HuashuRobotCollector(r, mqtt_client)
        cmd_routers[r["device_id"]] = c.on_cmd_message
        c.start()
        collectors.append(c)

    while running:
        time.sleep(1.0)

    mqtt_client.loop_stop()
    mqtt_client.disconnect()
    logger.info("华数采集桥接已安全退出。")


if __name__ == "__main__":
    main()
