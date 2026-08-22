# -*- coding: utf-8 -*-
"""
mock_service.py - 工业机器人集群遥测数据常驻模拟服务
用于在大屏上常驻呈现 10 台多品类真实感机器人运行状态与 3D 动作
支持：华数机械臂 (4台)、复合 AMR (3台)、四足机器狗 (2台)、空地协同无人机编队 (1套)
"""

import sys
import os
import time
import json
import math
import random
import signal
import logging
from datetime import datetime

try:
    import paho.mqtt.client as mqtt
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "paho-mqtt==2.1.0"])
    import paho.mqtt.client as mqtt

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
logger = logging.getLogger("robot_mock_service")

MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
INTERVAL = float(os.getenv("MOCK_INTERVAL", "2.0"))

running = True

def handle_exit(signum, frame):
    global running
    logger.info("收到退出信号，正在停止模拟推流服务...")
    running = False

signal.signal(signal.SIGINT, handle_exit)
if hasattr(signal, "SIGTERM"):
    signal.signal(signal.SIGTERM, handle_exit)

class VirtualRobot:
    def __init__(self, device_type, device_id, device_name, location, vendor):
        self.device_type = device_type
        self.device_id = device_id
        self.device_name = device_name
        self.location = location
        self.vendor = vendor
        self.battery = random.randint(82, 98)
        self.step = random.randint(0, 100)
        self.cycle_count = random.randint(120, 850)
        self.speed = random.randint(70, 90)
        self.x = round(random.uniform(5.0, 35.0), 2)
        self.y = round(random.uniform(2.0, 20.0), 2)
        self.status = "running"
        self.error_code = 0
        self.error_msg = "Normal"

    def update_state(self):
        self.step += 1
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 偶发极低概率微小告警(每100步最多1次短暂告警)
        if self.step % 120 == 0:
            self.status = "idle"
        else:
            self.status = "running"
            self.error_code = 0
            self.error_msg = "Normal"

        if self.device_type == "huashu_arm":
            self.cycle_count += 1
            j1 = round(math.sin(self.step * 0.15) * 45.0, 2)
            j2 = round(-25.0 + math.cos(self.step * 0.12) * 20.0, 2)
            j3 = round(80.0 + math.sin(self.step * 0.1) * 15.0, 2)
            j4 = round(math.cos(self.step * 0.2) * 35.0, 2)
            j5 = round(math.sin(self.step * 0.18) * 60.0, 2)
            j6 = round((self.step * 8) % 360 - 180.0, 2)
            joints = [j1, j2, j3, j4, j5, j6]
            cart = {
                "x": round(480.0 + math.cos(self.step * 0.1) * 50.0, 2),
                "y": round(150.0 + math.sin(self.step * 0.1) * 50.0, 2),
                "z": round(380.0 + math.sin(self.step * 0.15) * 30.0, 2),
                "a": 180.0, "b": 0.0, "c": j1
            }
            currents = [round(1.2 + abs(math.sin(self.step * 0.15 + i)) * 1.6, 2) for i in range(6)]
            
            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": self.status,
                "battery": 100.0,
                "speed": self.speed,
                "joint_angles": joints,
                "cartesian_pos": cart,
                "motor_currents": currents,
                "emergency_stop": False,
                "enabled": True,
                "cycle_count": self.cycle_count,
                "running_hours": round(180.0 + self.step * 0.02, 1),
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(37.0 + math.sin(self.step * 0.05) * 2.5, 1),
                "current": round(sum(currents) / len(currents), 2),
                "voltage": round(24.0 + math.sin(self.step * 0.1) * 0.3, 2),
                "motor_currents": currents
            }

        elif self.device_type == "luxshare_amr":
            self.x = round(self.x + math.sin(self.step * 0.1) * 0.8, 2)
            self.y = round(self.y + math.cos(self.step * 0.1) * 0.8, 2)
            
            # 复合 AMR 车载 6 轴协作臂动态插补运动
            j1 = round(math.sin(self.step * 0.2) * 40.0, 2)
            j2 = round(25.0 + math.cos(self.step * 0.15) * 20.0, 2)
            j3 = round(-40.0 + math.sin(self.step * 0.12) * 25.0, 2)
            j4 = round(math.cos(self.step * 0.25) * 50.0, 2)
            j5 = round(math.sin(self.step * 0.2) * 65.0, 2)
            j6 = round((self.step * 10) % 360 - 180.0, 2)
            amr_joints = [j1, j2, j3, j4, j5, j6]

            cart = {
                "x": round(self.x * 100, 1),
                "y": round(self.y * 100, 1),
                "z": 0.0,
                "a": 0.0,
                "b": 0.0,
                "c": round(math.atan2(math.cos(self.step * 0.1), math.sin(self.step * 0.1)) * 57.3, 1)
            }
            currents = [round(2.1 + abs(math.sin(self.step * 0.15 + i)) * 1.5, 2) for i in range(6)]

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": "running" if self.status != "idle" else "idle",
                "battery": max(35.0, round(96.0 - (self.step % 500) * 0.1, 1)),
                "speed_mps": round(0.9 + abs(math.sin(self.step * 0.1)) * 0.4, 2),
                "position": {"x": self.x, "y": self.y, "z": 0.0, "floor": 1},
                "joint_angles": amr_joints,
                "arm_sr3_pose": amr_joints,
                "cartesian_pos": cart,
                "motor_currents": currents,
                "current_task": f"TASK_TRANS_{100 + self.step % 20}",
                "load_status": "loaded" if (self.step // 10) % 2 == 0 else "empty",
                "cycle_count": int(self.step * 2),
                "running_hours": round(145.0 + self.step * 0.02, 1),
                "emergency_stop": False,
                "enabled": True,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(32.5 + random.uniform(0, 1.5), 1),
                "current": round(sum(currents) / len(currents), 2),
                "voltage": 48.0,
                "motor_currents": currents,
                "co2_ppm": int(520 + math.sin(self.step * 0.08) * 40),
                "pm25": int(20 + math.cos(self.step * 0.08) * 8),
                "noise_db": round(56.0 + random.uniform(0, 3.0), 1)
            }

        elif self.device_type == "robot_dog":
            # 四足仿生 Trot 对角交替小跑动态步态 (前左/后右同相，前右/后左反相)
            fl_hip = round(math.sin(self.step * 0.35) * 22.0, 2)
            fl_knee = round(42.0 + math.sin(self.step * 0.35) * 28.0, 2)
            fr_hip = round(math.sin(self.step * 0.35 + math.pi) * 22.0, 2)
            fr_knee = round(42.0 + math.sin(self.step * 0.35 + math.pi) * 28.0, 2)
            hl_leg = round(math.sin(self.step * 0.35 + math.pi) * 25.0, 2)
            hr_leg = round(math.sin(self.step * 0.35) * 25.0, 2)
            dog_joints = [fl_hip, fl_knee, fr_hip, fr_knee, hl_leg, hr_leg]

            dog_cart = {
                "x": round(18.0 + math.cos(self.step * 0.08) * 8.5, 2),
                "y": round(9.0 + math.sin(self.step * 0.08) * 8.5, 2),
                "z": round(0.55 + abs(math.sin(self.step * 0.35)) * 0.06, 2),
                "a": round(math.sin(self.step * 0.25) * 2.5, 2),
                "b": round(math.cos(self.step * 0.25) * 1.5, 2),
                "c": round((self.step * 4) % 360 - 180.0, 2)
            }
            currents = [round(3.2 + abs(math.sin(self.step * 0.35 + i * 0.7)) * 2.0, 2) for i in range(6)]

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": "running" if self.status != "idle" else "standing",
                "battery": max(40.0, round(92.0 - (self.step % 400) * 0.1, 1)),
                "gait_mode": "trot",
                "speed_mps": round(0.8 + abs(math.sin(self.step * 0.15)) * 0.3, 2),
                "joint_angles": dog_joints,
                "cartesian_pos": dog_cart,
                "motor_currents": currents,
                "imu_pitch": dog_cart["a"],
                "imu_roll": dog_cart["b"],
                "cycle_count": int(self.step * 4),
                "running_hours": round(210.6 + self.step * 0.02, 1),
                "emergency_stop": False,
                "enabled": True,
                "uav_collab_ready": True,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(35.0 + random.uniform(0, 2.0), 1),
                "current": round(sum(currents) / len(currents), 2),
                "voltage": 28.8,
                "motor_currents": currents,
                "hcho": 0.016,
                "voc": 0.10,
                "foot_traffic": 320 + int(self.step * 0.8)
            }

        elif self.device_type == "uav_rescue":
            uav_joints = [round(math.sin(self.step * 0.25 + i * 1.0) * 15.0, 2) for i in range(6)]
            uav_cart = {
                "x": round(28.0 + math.sin(self.step * 0.06) * 12.0, 1),
                "y": round(32.0 + math.cos(self.step * 0.06) * 12.0, 1),
                "z": round(45.0 + math.sin(self.step * 0.1) * 4.0, 1),
                "a": round(math.sin(self.step * 0.2) * 3.5, 1),
                "b": round(math.cos(self.step * 0.2) * 2.5, 1),
                "c": round((self.step * 5) % 360 - 180.0, 1)
            }
            currents = [round(11.0 + abs(math.sin(self.step * 0.2 + i * 0.5)) * 2.5, 2) for i in range(6)]

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": "running",
                "battery": max(50.0, round(98.0 - (self.step % 300) * 0.1, 1)),
                "altitude_m": uav_cart["z"],
                "flight_speed_mps": round(5.2 + math.cos(self.step * 0.1) * 1.2, 2),
                "signal_rssi_dbm": -58,
                "collab_ground_dog_id": "robot_dog_01",
                "joint_angles": uav_joints,
                "cartesian_pos": uav_cart,
                "motor_currents": currents,
                "cycle_count": int(self.step * 2),
                "running_hours": round(98.4 + self.step * 0.02, 1),
                "emergency_stop": False,
                "enabled": True,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(26.5 + random.uniform(0, 1.5), 1),
                "current": round(sum(currents) / len(currents), 2),
                "voltage": 22.2,
                "motor_currents": currents,
                "wind_speed_mps": round(2.8 + random.uniform(0, 0.8), 1)
            }

        return state_msg, sensor_msg

def build_robot_fleet():
    return [
        # 1~4: 华数工业机械臂
        VirtualRobot("huashu_arm", "huashu_arm_01", "华数BR610六轴工业机械臂_A线", "A1精密装配工位", "华数机器人"),
        VirtualRobot("huashu_arm", "huashu_arm_02", "华数BR610六轴工业机械臂_B线", "B2自动涂胶工位", "华数机器人"),
        VirtualRobot("huashu_arm", "huashu_arm_03", "华数BR616大负载搬运机械臂", "C1重载码垛工位", "华数机器人"),
        VirtualRobot("huashu_arm", "huashu_arm_04", "华数MD410高速分拣机械臂", "D3高速分拣工位", "华数机器人"),
        # 5~7: 珞石复合移动 AMR
        VirtualRobot("luxshare_amr", "luxshare_amr_01", "珞石SR3复合移动AMR_1号", "车间物料转运环线", "珞石智能"),
        VirtualRobot("luxshare_amr", "luxshare_amr_02", "珞石SR3复合移动AMR_2号", "成品库自动配送区", "珞石智能"),
        VirtualRobot("luxshare_amr", "luxshare_amr_03", "智能全向重载复合AMR_3号", "原料自动入库区", "珞石智能"),
        # 8~9: 四足仿生巡检机器狗
        VirtualRobot("robot_dog", "robot_dog_01", "四足仿生巡检机器狗_01号", "配电房与管道巡检区", "宇树/昕邦定制"),
        VirtualRobot("robot_dog", "robot_dog_02", "四足仿生巡检机器狗_02号", "厂区周界安防巡逻线", "宇树/昕邦定制"),
        # 10: 空地协同无人机编队系统
        VirtualRobot("uav_rescue", "uav_rescue_01", "四足狗+无人机空地协同编队", "南沙高空与地面协同作业场", "昕邦智能联合研制"),
    ]

def main():
    logger.info("==========================================================")
    logger.info("  🚀 工业机器人集群遥测常驻模拟推流服务已启动")
    logger.info(f"  - MQTT Broker: {MQTT_HOST}:{MQTT_PORT}")
    logger.info(f"  - 模拟推流频率: {INTERVAL} 秒/轮")
    logger.info("==========================================================")

    robots = build_robot_fleet()
    logger.info(f"已初始化 {len(robots)} 台虚拟机器人设备：")
    for r in robots:
        logger.info(f"  ● [{r.device_type}] {r.device_id} ({r.device_name}) - 工位: {r.location}")

    client = mqtt.Client(client_id="fleet_mock_master_service")
    
    def on_cmd(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            logger.info(f"[CMD] 收到云端下行指令 -> Topic: {msg.topic} | Command: {payload.get('command')}")
        except Exception as e:
            logger.warning(f"[CMD] 指令解析异常: {e}")

    client.on_message = on_cmd

    # 尝试连接 MQTT Broker
    while running:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.subscribe("cmd/#", qos=1)
            client.loop_start()
            logger.info("[MQTT OK] 成功连入 MQTT Broker，开始推流！")
            break
        except Exception as e:
            logger.warning(f"MQTT Broker 连接失败 ({e})，3秒后重试...")
            time.sleep(3)

    round_cnt = 0
    try:
        while running:
            round_cnt += 1
            for r in robots:
                if not running:
                    break
                state_data, sensor_data = r.update_state()

                topic_state = f"robot/{r.device_type}/{r.device_id}/state"
                topic_sensor = f"robot/{r.device_type}/{r.device_id}/sensor"

                client.publish(topic_state, json.dumps(state_data, ensure_ascii=False), qos=1)
                client.publish(topic_sensor, json.dumps(sensor_data, ensure_ascii=False), qos=1)

            if round_cnt % 10 == 0:
                logger.info(f"[HEARTBEAT] 已完成 {round_cnt} 轮推流，{len(robots)} 台虚拟设备全部在线正常")

            time.sleep(INTERVAL)
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("模拟服务已停止")

if __name__ == "__main__":
    main()
