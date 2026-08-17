"""
mock_robot.py - 机器人物联网设备模拟上报测试脚本
- 模拟多品类设备：华数机械臂 (huashu_arm)、珞石AMR移动机器人 (luxshare_amr)、四足机器狗 (robot_dog)
- 遵循 Topic 规范: robot/{device_type}/{device_id}/{data_type} (如 robot/huashu_arm/arm_001/state)
- 周期性上报 state (状态/电量/工况/故障码) 和 sensor (传感器遥测数据)
- 支持标准 MQTT 上报（连接 EMQX Broker）
- 支持本地直写 SQLite 模式（方便在未启动 EMQX 的开发环境下直接自测前后端联动与离线检测）
"""

import os
import sys
import time
import json
import math
import random
import signal
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List

# 导入数据库模块用于直写模式或校验
try:
    from database import insert_device_data, upsert_device, get_all_devices
except ImportError:
    pass

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# 日志配置（兼容 Windows GBK 终端与 UTF-8）
# ---------------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
stream_handler = logging.StreamHandler(sys.stdout)
stream_handler.setLevel(logging.INFO)

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[stream_handler],
)
logger = logging.getLogger("mock_robot")

# 运行控制标志
running = True


def handle_sigint(signum, frame):
    """优雅退出信号处理"""
    global running
    logger.info("\n[INFO] 接收到退出信号 (Ctrl+C)，正在安全停止设备模拟上报...")
    running = False


signal.signal(signal.SIGINT, handle_sigint)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, handle_sigint)


# ---------------------------------------------------------------------------
# 设备模拟器类
# ---------------------------------------------------------------------------
class RobotSimulator:
    def __init__(self, device_type: str, device_id: str):
        self.device_type = device_type
        self.device_id = device_id
        self.battery = random.randint(75, 98)
        self.cycle_count = random.randint(100, 500)
        self.x = round(random.uniform(5.0, 20.0), 2)
        self.y = round(random.uniform(2.0, 15.0), 2)
        self.step = 0
        self.error_countdown = 0

    def generate_state_payload(self) -> Dict[str, Any]:
        """生成状态报文 (state)"""
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        self.step += 1

        # 模拟电量自然微小消耗（低于20%自动回充）
        if self.battery > 15:
            self.battery = max(10, round(self.battery - random.uniform(0.1, 0.3), 1))
        else:
            self.battery = 95  # 模拟充满电

        # 偶发性模拟故障码（每 40 次偶发 1 次故障，持续 2 次后恢复）
        error_code = 0
        error_msg = ""
        if self.error_countdown > 0:
            self.error_countdown -= 1
            error_code = 102
            error_msg = "电机短时过载告警"
        elif random.random() < 0.03:
            self.error_countdown = 2
            error_code = 102
            error_msg = "电机短时过载告警"

        if self.device_type == "huashu_arm":
            # 华数 BR610 机械臂专用状态
            self.cycle_count += 1
            base_angle = math.sin(self.step * 0.2) * 45.0
            joint_angles = [
                round(base_angle, 2),
                round(math.cos(self.step * 0.2) * 30.0, 2),
                round(-45.0 + math.sin(self.step * 0.1) * 20.0, 2),
                round(math.cos(self.step * 0.3) * 60.0, 2),
                round(math.sin(self.step * 0.15) * 85.0, 2),
                round(self.step % 360 - 180.0, 2),
            ]
            status_opts = ["running", "running", "running", "idle"]
            curr_status = "error" if error_code != 0 else random.choice(status_opts)
            return {
                "timestamp": now_iso,
                "model": "华数BR610",
                "status": curr_status,
                "battery": self.battery,
                "error_code": error_code,
                "error_msg": error_msg,
                "joint_angles": joint_angles,
                "speed": random.randint(55, 85),
                "payload_kg": round(random.uniform(4.8, 5.5), 2),
                "cycle_count": self.cycle_count,
                "running_hours": round(152.0 + self.step * 0.05, 1),
                "di_status": [1, 1, 0, 1],  # DI: 安全光幕/夹爪到位/急停正常/气压就绪
                "do_status": [1, 0],        # DO: 夹爪电磁阀吸附/运行警示灯
            }

        elif self.device_type == "luxshare_amr":
            # 珞石 SR3 臂 + 定制 AGV 复合机器人专用状态
            self.x = round(self.x + random.uniform(-0.5, 0.5), 2)
            self.y = round(self.y + random.uniform(-0.5, 0.5), 2)
            status_opts = ["navigating", "navigating", "idle", "charging"]
            curr_status = "error" if error_code != 0 else random.choice(status_opts)
            return {
                "timestamp": now_iso,
                "model": "珞石SR3+定制AGV",
                "status": curr_status,
                "battery": self.battery,
                "error_code": error_code,
                "error_msg": error_msg,
                "position": {"x": self.x, "y": self.y, "z": 0.0, "floor": 1},
                "speed_mps": round(random.uniform(0.8, 1.5), 2) if curr_status == "navigating" else 0.0,
                "map_id": "MAP_FLOOR_1",
                "current_task": f"task_pick_and_place_{100 + self.step % 30}",
                "load_status": "loaded" if self.step % 2 == 0 else "empty",
                "arm_sr3_pose": [0.0, 30.0, -45.0, 60.0, 0.0, 0.0],
                "running_hours": round(89.4 + self.step * 0.05, 1),
                "di_status": [1, 1, 1],     # DI: 激光雷达避障/防跌落传感器/触边防撞
                "do_status": [1, 1],        # DO: 转向指示灯/语音播报
            }

        elif self.device_type == "robot_dog":
            # 南沙四足机器狗复合巡检机器人专用状态
            status_opts = ["patrolling", "patrolling", "standing", "sitting"]
            curr_status = "error" if error_code != 0 else random.choice(status_opts)
            return {
                "timestamp": now_iso,
                "model": "南沙四足机器狗",
                "status": curr_status,
                "battery": self.battery,
                "error_code": error_code,
                "error_msg": error_msg,
                "gait_mode": random.choice(["trot", "walk", "bound"]),
                "speed_mps": round(random.uniform(0.5, 1.2), 2) if curr_status == "patrolling" else 0.0,
                "imu_pitch": round(math.sin(self.step * 0.3) * 3.5, 2),
                "imu_roll": round(math.cos(self.step * 0.3) * 2.0, 2),
                "temperature": round(36.0 + random.uniform(0, 3.5), 1),
                "running_hours": round(210.6 + self.step * 0.05, 1),
                "di_status": [1, 1],        # DI: 地形防滑/足端压力传感器
                "do_status": [1, 0],        # DO: 云台补光灯/搜救红外
                "uav_collab_ready": True,   # 无人机空地协同就绪标识
            }

        # 默认通用
        return {
            "timestamp": now_iso,
            "status": "running",
            "battery": self.battery,
            "error_code": error_code,
            "error_msg": error_msg,
        }

    def generate_sensor_payload(self) -> Dict[str, Any]:
        """生成传感器遥测报文 (sensor)，包含电气物理量与商业/环境多维参数"""
        now_iso = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        base_sensor = {
            "timestamp": now_iso,
            "temperature": round(38.0 + random.uniform(0.5, 8.0), 1),
            "humidity": round(50.0 + random.uniform(-5.0, 15.0), 1),
            "vibration": round(random.uniform(0.01, 0.08), 3),
            "current": round(random.uniform(2.0, 6.5), 2),
            "voltage": round(24.0 + random.uniform(-0.5, 0.8), 2) if self.device_type != "luxshare_amr" else round(48.0 + random.uniform(-0.8, 1.2), 2),
        }

        # 商业环境监测数据扩展 (模块 5)
        if self.device_type == "luxshare_amr":
            base_sensor.update({
                "co2_ppm": int(520 + random.uniform(-40, 150)),
                "pm25": int(24 + random.uniform(-6, 18)),
                "noise_db": round(55.2 + random.uniform(-3.0, 8.0), 1),
            })
        elif self.device_type == "robot_dog":
            base_sensor.update({
                "hcho": round(0.018 + random.uniform(-0.005, 0.015), 3),
                "voc": round(0.12 + random.uniform(-0.03, 0.08), 2),
                "combustible_gas_pct": round(max(0.0, random.uniform(0.0, 0.3)), 2),
                "human_presence": random.choice([True, True, False]),
                "foot_traffic": 280 + int(self.step * 1.5),
            })

        return base_sensor


# ---------------------------------------------------------------------------
# 主执行入口
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="机器人物联网设备模拟上报工具")
    parser.add_argument("--host", default=os.getenv("MQTT_HOST", "localhost"), help="MQTT Broker 主机地址")
    parser.add_argument("--port", type=int, default=int(os.getenv("MQTT_PORT", "1883")), help="MQTT 端口 (默认 1883)")
    parser.add_argument("--username", default=os.getenv("MQTT_USERNAME", "robot_server"), help="MQTT 用户名")
    parser.add_argument("--password", default=os.getenv("MQTT_PASSWORD", "robot_server_pass"), help="MQTT 密码")
    parser.add_argument("--interval", type=float, default=3.0, help="上报周期(秒，默认 3.0)")
    parser.add_argument("--count", type=int, default=0, help="总上报轮次 (0 表示无限循环)")
    parser.add_argument("--db", default="robot.db", help="SQLite 数据库文件路径")
    args = parser.parse_args()

    # 初始化 3 类典型工业机器人模拟实例
    simulators: List[RobotSimulator] = [
        RobotSimulator("huashu_arm", "arm_001"),
        RobotSimulator("luxshare_amr", "amr_001"),
        RobotSimulator("robot_dog", "dog_001"),
    ]

    logger.info("==========================================================")
    logger.info("[START] 机器人物联网模拟上报脚本已启动")
    logger.info(f"[TARGET] MQTT Broker: {args.host}:{args.port}")
    logger.info(f"[INTERVAL] 上报周期: {args.interval} 秒/轮")
    logger.info("[DEVICES] 模拟设备列表:")
    for sim in simulators:
        logger.info(f"   - [{sim.device_type}] {sim.device_id}")
    logger.info("==========================================================")

    # 尝试连接 MQTT Broker
    client = None
    mqtt_available = False
    try:
        # 快速测试 Broker 端口是否可达 (0.5s 超时)
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.5)
        conn_res = sock.connect_ex((args.host, args.port))
        sock.close()

        if conn_res == 0:
            if hasattr(mqtt, "CallbackAPIVersion"):
                try:
                    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="mock_robot_publisher")
                except Exception:
                    client = mqtt.Client(client_id="mock_robot_publisher")
            else:
                client = mqtt.Client(client_id="mock_robot_publisher")

            def on_cmd_message(c, userdata, msg):
                try:
                    payload = json.loads(msg.payload.decode("utf-8"))
                    logger.info(f"[COMMAND RECEIVED] 收到下发控制指令 -> Topic: {msg.topic} | TaskID: {payload.get('task_id')} | Command: {payload.get('command')} | Params: {payload.get('params')}")
                except Exception as ex:
                    logger.warning(f"[COMMAND ERROR] 收到指令但解析失败: {ex}")

            client.on_message = on_cmd_message
            logger.info(f"正在连接 MQTT Broker ({args.host}:{args.port})...")
            if args.username:
                client.username_pw_set(args.username, args.password)
            client.connect(args.host, args.port, keepalive=60)
            client.subscribe("cmd/#")
            client.loop_start()
            mqtt_available = True
            logger.info("[MQTT OK] 已成功连接到 MQTT Broker，已订阅下行指令主题 cmd/#")
        else:
            logger.warning(f"[MQTT SKIP] 未检测到运行中的 MQTT Broker ({args.host}:{args.port})")
            logger.info("[DB SYNC] 自动启用【SQLite 直写同步引擎】，数据将直接写入本地数据库，支持完整的 Web 实时轮询与离线判定测试！")
    except Exception as e:
        logger.warning(f"[MQTT SKIP] 连接 MQTT Broker 异常 ({e})")
        logger.info("[DB SYNC] 自动启用【SQLite 直写同步引擎】，数据将直接写入本地数据库，支持完整的 Web 实时轮询与离线判定测试！")

    round_idx = 0
    try:
        while running:
            round_idx += 1
            if args.count > 0 and round_idx > args.count:
                logger.info(f"已达到设定的最大上报轮次 ({args.count})，退出测试")
                break

            logger.info(f"\n--- [第 {round_idx} 轮设备遥测数据上报] ---")

            for sim in simulators:
                if not running:
                    break

                # 1. 发送 state 状态数据
                topic_state = f"robot/{sim.device_type}/{sim.device_id}/state"
                payload_state = sim.generate_state_payload()
                json_state = json.dumps(payload_state, ensure_ascii=False)

                # 2. 发送 sensor 传感器数据
                topic_sensor = f"robot/{sim.device_type}/{sim.device_id}/sensor"
                payload_sensor = sim.generate_sensor_payload()
                json_sensor = json.dumps(payload_sensor, ensure_ascii=False)

                # 发布/写入
                if mqtt_available and client:
                    try:
                        client.publish(topic_state, json_state, qos=1)
                        client.publish(topic_sensor, json_sensor, qos=1)
                    except Exception as pub_err:
                        logger.error(f"MQTT 发送失败 [{sim.device_id}]: {pub_err}")

                # 始终确保本地 DB 同步更新（即使 MQTT 离线也能测试）
                insert_device_data(
                    device_id=sim.device_id,
                    device_type=sim.device_type,
                    data_type="state",
                    raw_payload=json_state,
                    topic=topic_state,
                    db_path=args.db,
                )
                insert_device_data(
                    device_id=sim.device_id,
                    device_type=sim.device_type,
                    data_type="sensor",
                    raw_payload=json_sensor,
                    topic=topic_sensor,
                    db_path=args.db,
                )

                status_label = payload_state.get("status", "unknown")
                battery_val = payload_state.get("battery", 0)
                err_code = payload_state.get("error_code", 0)
                logger.info(
                    f"[REPORT OK] [{sim.device_type}/{sim.device_id}] "
                    f"status={status_label} | battery={battery_val}% | err_code={err_code} | "
                    f"temp={payload_sensor.get('temperature')}C"
                )

            # 休眠等待下一轮
            for _ in range(int(args.interval * 10)):
                if not running:
                    break
                time.sleep(0.1)

    finally:
        if client and mqtt_available:
            try:
                client.loop_stop()
                client.disconnect()
            except Exception:
                pass
        logger.info("\n[FINISH] 模拟设备已停止上报。")
        logger.info("[INFO] 系统将在 30 秒后自动将停止上报的设备标记为【离线】状态，可通过 Web 界面观察状态变化。")


if __name__ == "__main__":
    main()
