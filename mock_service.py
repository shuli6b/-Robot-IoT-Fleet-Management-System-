#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
=============================================================================
机器人物联网智能管控平台 - 多品类工业设备集群实时遥测与闭环控制模拟服务
Fleet Telemetry & Command State Machine Simulator
=============================================================================
"""

import os
import sys
import time
import json
import math
import random
import signal
import logging
from datetime import datetime
import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
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
        
        self.battery = float(random.randint(85, 98))
        self.step = random.randint(0, 100)
        self.cycle_count = random.randint(150, 800)
        self.running_hours = round(random.uniform(120.0, 350.0), 1)
        self.speed = 80
        
        # 初始坐标与朝向
        self.x = round(random.uniform(5.0, 25.0), 2)
        self.y = round(random.uniform(2.0, 15.0), 2)
        self.z = 0.55 if device_type == "robot_dog" else (45.0 if device_type == "uav_rescue" else 0.0)
        self.c = round(random.uniform(-180.0, 180.0), 1)

        # 状态机核心变量
        self.status = "running"
        self.is_moving = True
        self.gait_mode = "trot" if device_type == "robot_dog" else "normal"
        self.enabled = True
        self.emergency_stop = False
        self.error_code = 0
        self.error_msg = "Normal"
        
        self.current_program = "BR610_MAIN_LINE.PRG" if device_type == "huashu_arm" else "TASK_AUTO.PRG"
        self.current_task = f"TASK_{random.randint(100, 200)}"
        self.joint_angles = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        self.motor_currents = [1.5, 1.8, 1.6, 0.9, 0.8, 0.5]

    def handle_command(self, cmd: str, params: dict):
        """精准响应并持久保持工业控制指令状态"""
        if not cmd:
            return
        cmd_clean = cmd.strip().lower()
        logger.info(f"[{self.device_id}] 🤖 执行指令: {cmd_clean} | 详细参数: {params}")

        # 1. 全局急停与复位
        if cmd_clean in ["stop", "emergency_stop"]:
            self.status = "stopped"
            self.is_moving = False
            self.emergency_stop = True
            self.enabled = False
            self.motor_currents = [0.0] * 6
            return

        if cmd_clean == "reset":
            self.emergency_stop = False
            self.enabled = True
            self.error_code = 0
            self.error_msg = "Normal"
            self.status = "idle"
            self.is_moving = False
            return

        if cmd_clean == "enable":
            self.enabled = True
            if self.status in ["disabled", "stopped"]:
                self.status = "idle"
            return

        if cmd_clean == "disable":
            self.enabled = False
            self.status = "disabled"
            self.is_moving = False
            self.motor_currents = [0.0] * 6
            return

        if cmd_clean in ["pause", "pause_nav"]:
            self.status = "paused"
            self.is_moving = False
            return

        if cmd_clean in ["resume", "resume_nav"]:
            self.status = "running"
            self.is_moving = True
            self.enabled = True
            self.emergency_stop = False
            return

        if cmd_clean == "set_override":
            self.speed = int(params.get("override", self.speed))
            return

        # 2. 四足机器狗专属指令响应
        if self.device_type == "robot_dog":
            if cmd_clean == "stand":
                self.status = "standing"
                self.gait_mode = "stand"
                self.is_moving = False
                self.z = float(params.get("height", 0.55))
                self.joint_angles = [0.0, 28.0, 0.0, 28.0, 0.0, 28.0]
                self.motor_currents = [0.8, 0.9, 0.8, 0.9, 0.8, 0.9]
                logger.info(f"[{self.device_id}] 🐕 机器狗已进入【站立待命姿态】(持久保持静止)")
            elif cmd_clean == "sit":
                self.status = "sitting"
                self.gait_mode = "sit"
                self.is_moving = False
                self.z = 0.22
                self.joint_angles = [35.0, 75.0, 35.0, 75.0, 35.0, 75.0]
                self.motor_currents = [0.2, 0.3, 0.2, 0.3, 0.2, 0.3]
                logger.info(f"[{self.device_id}] 🐕 机器狗已进入【蹲伏休眠姿态】")
            elif cmd_clean in ["patrol", "walk_to"]:
                self.status = "running"
                self.gait_mode = "trot"
                self.is_moving = True
                self.current_task = f"PATROL_{params.get('route', 'AREA_ZONE_1')}"
                logger.info(f"[{self.device_id}] 🐕 机器狗已启动【Trot 巡检步态】沿航线巡航")
            elif cmd_clean == "auto_dock_charge":
                self.status = "charging"
                self.is_moving = False
                self.joint_angles = [30.0, 70.0, 30.0, 70.0, 30.0, 70.0]

        # 3. 华数工业机械臂专属指令响应
        elif self.device_type == "huashu_arm":
            if cmd_clean == "home":
                self.status = "idle"
                self.is_moving = False
                self.joint_angles = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
            elif cmd_clean == "start_cycle":
                self.status = "running"
                self.is_moving = True
                self.enabled = True
            elif cmd_clean == "select_prog":
                self.current_program = params.get("prog_name", self.current_program)
            elif cmd_clean == "jog_joint":
                axis = int(params.get("axis", 1)) - 1
                step_deg = float(params.get("step_deg", 5.0)) * int(params.get("direction", 1))
                if 0 <= axis < 6:
                    self.joint_angles[axis] = round(self.joint_angles[axis] + step_deg, 2)
                    self.is_moving = False
                    self.status = "idle"

        # 4. 珞石复合 AMR 移动机器人专属指令响应
        elif self.device_type == "luxshare_amr":
            if cmd_clean == "nav_to_point":
                self.status = "running"
                self.is_moving = True
                self.current_task = f"NAV_TO_{params.get('target_point', 'BAY_02')}"
            elif cmd_clean == "pick_and_place":
                self.status = "running"
                self.is_moving = True
                self.current_task = f"TRANSFER_{params.get('source_station', 'ST_A')}_TO_{params.get('target_station', 'ST_B')}"
            elif cmd_clean == "auto_charge":
                self.status = "charging"
                self.is_moving = False
                self.current_task = "DOCK_CHARGING"

        # 5. 空地协同无人机编队指令响应
        elif self.device_type == "uav_rescue":
            if cmd_clean == "auto_land_recharge":
                self.status = "landing"
                self.is_moving = False
                self.z = 0.0
            elif cmd_clean in ["collab_patrol", "multispectral_scan"]:
                self.status = "running"
                self.is_moving = True
                self.z = 45.0

    def update_state(self):
        """每周期计算并生成符合工业物理特性的实时遥测报文"""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 仅在运动状态下递增步数与累计时间
        if self.is_moving:
            self.step += 1
            self.running_hours = round(self.running_hours + (INTERVAL / 3600.0), 3)

        # -------------------------------------------------------------
        # 1. 华数六轴工业机械臂 (huashu_arm)
        # -------------------------------------------------------------
        if self.device_type == "huashu_arm":
            if self.is_moving and self.enabled and not self.emergency_stop:
                self.cycle_count += 1
                j1 = round(math.sin(self.step * 0.15) * 45.0, 2)
                j2 = round(-25.0 + math.cos(self.step * 0.12) * 20.0, 2)
                j3 = round(80.0 + math.sin(self.step * 0.1) * 15.0, 2)
                j4 = round(math.cos(self.step * 0.2) * 35.0, 2)
                j5 = round(math.sin(self.step * 0.18) * 60.0, 2)
                j6 = round((self.step * 8) % 360 - 180.0, 2)
                self.joint_angles = [j1, j2, j3, j4, j5, j6]
                self.motor_currents = [round(1.2 + abs(math.sin(self.step * 0.15 + i)) * 1.6, 2) for i in range(6)]
                cart = {
                    "x": round(480.0 + math.cos(self.step * 0.1) * 50.0, 2),
                    "y": round(150.0 + math.sin(self.step * 0.1) * 50.0, 2),
                    "z": round(380.0 + math.sin(self.step * 0.15) * 30.0, 2),
                    "a": 180.0, "b": 0.0, "c": j1
                }
            else:
                cart = {
                    "x": 480.0, "y": 150.0, "z": 380.0,
                    "a": 180.0, "b": 0.0, "c": self.joint_angles[0] if self.joint_angles else 0.0
                }
                if not self.enabled or self.emergency_stop:
                    self.motor_currents = [0.0] * 6
                else:
                    self.motor_currents = [0.3, 0.4, 0.3, 0.2, 0.1, 0.1]

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": self.status,
                "battery": 100.0,
                "speed": self.speed if self.is_moving else 0,
                "joint_angles": self.joint_angles,
                "cartesian_pos": cart,
                "motor_currents": self.motor_currents,
                "emergency_stop": self.emergency_stop,
                "enabled": self.enabled,
                "current_program": self.current_program,
                "cycle_count": self.cycle_count,
                "running_hours": round(self.running_hours, 1),
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(37.0 + math.sin(self.step * 0.05) * 2.0, 1),
                "current": round(sum(self.motor_currents) / len(self.motor_currents), 2),
                "voltage": 24.0,
                "motor_currents": self.motor_currents
            }

        # -------------------------------------------------------------
        # 2. 珞石复合移动 AMR (luxshare_amr)
        # -------------------------------------------------------------
        elif self.device_type == "luxshare_amr":
            if self.is_moving and self.enabled and not self.emergency_stop:
                self.x = round(self.x + math.sin(self.step * 0.1) * 0.8, 2)
                self.y = round(self.y + math.cos(self.step * 0.1) * 0.8, 2)
                j1 = round(math.sin(self.step * 0.2) * 40.0, 2)
                j2 = round(25.0 + math.cos(self.step * 0.15) * 20.0, 2)
                j3 = round(-40.0 + math.sin(self.step * 0.12) * 25.0, 2)
                j4 = round(math.cos(self.step * 0.25) * 50.0, 2)
                j5 = round(math.sin(self.step * 0.2) * 65.0, 2)
                j6 = round((self.step * 10) % 360 - 180.0, 2)
                self.joint_angles = [j1, j2, j3, j4, j5, j6]
                self.motor_currents = [round(2.1 + abs(math.sin(self.step * 0.15 + i)) * 1.5, 2) for i in range(6)]
                speed_mps = round(0.9 + abs(math.sin(self.step * 0.1)) * 0.4, 2)
                self.battery = max(35.0, round(self.battery - 0.02, 1))
            else:
                speed_mps = 0.0
                if self.status == "charging":
                    self.battery = min(100.0, round(self.battery + 0.5, 1))
                    self.motor_currents = [0.1] * 6
                elif not self.enabled or self.emergency_stop:
                    self.motor_currents = [0.0] * 6
                else:
                    self.motor_currents = [0.4, 0.4, 0.4, 0.2, 0.2, 0.2]

            cart = {
                "x": round(self.x * 100, 1),
                "y": round(self.y * 100, 1),
                "z": 0.0, "a": 0.0, "b": 0.0,
                "c": round(math.atan2(math.cos(self.step * 0.1), math.sin(self.step * 0.1)) * 57.3, 1)
            }
            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": self.status,
                "battery": self.battery,
                "speed_mps": speed_mps,
                "position": {"x": self.x, "y": self.y, "z": 0.0, "floor": 1},
                "joint_angles": self.joint_angles,
                "arm_sr3_pose": self.joint_angles,
                "cartesian_pos": cart,
                "motor_currents": self.motor_currents,
                "current_task": self.current_task,
                "load_status": "loaded" if (self.step // 10) % 2 == 0 else "empty",
                "cycle_count": self.cycle_count,
                "running_hours": round(self.running_hours, 1),
                "emergency_stop": self.emergency_stop,
                "enabled": self.enabled,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(32.5 + random.uniform(0, 1.0), 1),
                "current": round(sum(self.motor_currents) / len(self.motor_currents), 2),
                "voltage": 48.0,
                "motor_currents": self.motor_currents,
                "co2_ppm": int(520 + math.sin(self.step * 0.08) * 30),
                "pm25": 18,
                "noise_db": 55.0
            }

        # -------------------------------------------------------------
        # 3. 四足仿生巡检机器狗 (robot_dog)
        # -------------------------------------------------------------
        elif self.device_type == "robot_dog":
            if self.status == "standing":
                # 站立待命姿态 (保持直立，完全静止)
                self.joint_angles = [0.0, 28.0, 0.0, 28.0, 0.0, 28.0]
                self.motor_currents = [0.8, 0.9, 0.8, 0.9, 0.8, 0.9]
                speed_mps = 0.0
                cart = {
                    "x": self.x, "y": self.y, "z": self.z,
                    "a": 0.0, "b": 0.0, "c": self.c
                }
            elif self.status == "sitting":
                # 蹲伏休眠姿态
                self.joint_angles = [35.0, 75.0, 35.0, 75.0, 35.0, 75.0]
                self.motor_currents = [0.2, 0.3, 0.2, 0.3, 0.2, 0.3]
                speed_mps = 0.0
                cart = {
                    "x": self.x, "y": self.y, "z": 0.22,
                    "a": 0.0, "b": 0.0, "c": self.c
                }
            elif self.status in ["stopped", "disabled"] or self.emergency_stop or not self.enabled:
                # 停机断电
                speed_mps = 0.0
                self.motor_currents = [0.0] * 6
                cart = {
                    "x": self.x, "y": self.y, "z": self.z,
                    "a": 0.0, "b": 0.0, "c": self.c
                }
            else:
                # 正常巡检小跑 (Trot 步态)
                self.x = round(18.0 + math.cos(self.step * 0.08) * 8.5, 2)
                self.y = round(9.0 + math.sin(self.step * 0.08) * 8.5, 2)
                self.c = round((self.step * 4) % 360 - 180.0, 2)
                
                fl_hip = round(math.sin(self.step * 0.35) * 22.0, 2)
                fl_knee = round(42.0 + math.sin(self.step * 0.35) * 28.0, 2)
                fr_hip = round(math.sin(self.step * 0.35 + math.pi) * 22.0, 2)
                fr_knee = round(42.0 + math.sin(self.step * 0.35 + math.pi) * 28.0, 2)
                hl_leg = round(math.sin(self.step * 0.35 + math.pi) * 25.0, 2)
                hr_leg = round(math.sin(self.step * 0.35) * 25.0, 2)
                self.joint_angles = [fl_hip, fl_knee, fr_hip, fr_knee, hl_leg, hr_leg]
                self.motor_currents = [round(3.2 + abs(math.sin(self.step * 0.35 + i * 0.7)) * 2.0, 2) for i in range(6)]
                speed_mps = round(0.8 + abs(math.sin(self.step * 0.15)) * 0.3, 2)
                
                cart = {
                    "x": self.x, "y": self.y,
                    "z": round(0.55 + abs(math.sin(self.step * 0.35)) * 0.06, 2),
                    "a": round(math.sin(self.step * 0.25) * 2.5, 2),
                    "b": round(math.cos(self.step * 0.25) * 1.5, 2),
                    "c": self.c
                }
                self.battery = max(30.0, round(self.battery - 0.015, 1))

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": self.status,
                "battery": self.battery,
                "gait_mode": self.gait_mode,
                "speed_mps": speed_mps,
                "joint_angles": self.joint_angles,
                "cartesian_pos": cart,
                "motor_currents": self.motor_currents,
                "imu_pitch": cart["a"],
                "imu_roll": cart["b"],
                "cycle_count": self.cycle_count,
                "running_hours": round(self.running_hours, 1),
                "emergency_stop": self.emergency_stop,
                "enabled": self.enabled,
                "uav_collab_ready": True,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(35.0 + random.uniform(0, 1.5), 1),
                "current": round(sum(self.motor_currents) / len(self.motor_currents), 2),
                "voltage": 28.8,
                "motor_currents": self.motor_currents,
                "hcho": 0.016,
                "voc": 0.10,
                "foot_traffic": 320 + int(self.step * 0.8)
            }

        # -------------------------------------------------------------
        # 4. 空地协同无人机编队 (uav_rescue)
        # -------------------------------------------------------------
        elif self.device_type == "uav_rescue":
            if self.status == "landing":
                flight_speed = 0.0
                self.motor_currents = [0.0] * 6
                self.joint_angles = [0.0] * 6
                cart = {"x": self.x, "y": self.y, "z": 0.0, "a": 0.0, "b": 0.0, "c": 0.0}
            elif self.is_moving:
                self.joint_angles = [round(math.sin(self.step * 0.25 + i * 1.0) * 15.0, 2) for i in range(6)]
                cart = {
                    "x": round(28.0 + math.sin(self.step * 0.06) * 12.0, 1),
                    "y": round(32.0 + math.cos(self.step * 0.06) * 12.0, 1),
                    "z": round(45.0 + math.sin(self.step * 0.1) * 4.0, 1),
                    "a": round(math.sin(self.step * 0.2) * 3.5, 1),
                    "b": round(math.cos(self.step * 0.2) * 2.5, 1),
                    "c": round((self.step * 5) % 360 - 180.0, 1)
                }
                self.motor_currents = [round(11.0 + abs(math.sin(self.step * 0.2 + i * 0.5)) * 2.5, 2) for i in range(6)]
                flight_speed = round(5.2 + math.cos(self.step * 0.1) * 1.2, 2)
            else:
                flight_speed = 0.0
                self.motor_currents = [2.0] * 6
                cart = {"x": self.x, "y": self.y, "z": self.z, "a": 0.0, "b": 0.0, "c": self.c}

            state_msg = {
                "timestamp": now_str,
                "device_name": self.device_name,
                "location": self.location,
                "vendor": self.vendor,
                "status": self.status,
                "battery": max(50.0, round(98.0 - (self.step % 300) * 0.1, 1)),
                "altitude_m": cart["z"],
                "flight_speed_mps": flight_speed,
                "signal_rssi_dbm": -58,
                "collab_ground_dog_id": "robot_dog_01",
                "joint_angles": self.joint_angles,
                "cartesian_pos": cart,
                "motor_currents": self.motor_currents,
                "cycle_count": self.cycle_count,
                "running_hours": round(self.running_hours, 1),
                "emergency_stop": self.emergency_stop,
                "enabled": self.enabled,
                "error_code": self.error_code,
                "error_msg": self.error_msg
            }
            sensor_msg = {
                "timestamp": now_str,
                "temperature": round(26.5 + random.uniform(0, 1.5), 1),
                "current": round(sum(self.motor_currents) / len(self.motor_currents), 2),
                "voltage": 22.2,
                "motor_currents": self.motor_currents,
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
    logger.info("  🚀 工业机器人集群遥测与控制模拟服务 (完整状态机版) 已启动")
    logger.info(f"  - MQTT Broker: {MQTT_HOST}:{MQTT_PORT}")
    logger.info(f"  - 模拟推流频率: {INTERVAL} 秒/轮")
    logger.info("==========================================================")

    robots = build_robot_fleet()
    robot_map = {r.device_id: r for r in robots}
    
    logger.info(f"已就绪 {len(robots)} 台虚拟工业设备：")
    for r in robots:
        logger.info(f"  ● [{r.device_type}] {r.device_id} ({r.device_name}) - 工位: {r.location}")

    client = mqtt.Client(client_id="fleet_mock_master_service")
    
    def on_cmd(c, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic_parts = msg.topic.split("/")
            
            # 支持 Topic: cmd/{type}/{id} 或 robot/{type}/{id}/cmd
            target_id = None
            if len(topic_parts) >= 3 and topic_parts[0] == "cmd":
                target_id = topic_parts[2]
            elif len(topic_parts) >= 4 and topic_parts[0] == "robot" and topic_parts[3] == "cmd":
                target_id = topic_parts[2]

            cmd_name = payload.get("command")
            params = payload.get("params", {})
            
            if target_id and target_id in robot_map:
                logger.info(f"[CMD] 收到精准下发指令 -> 设备: {target_id} | 指令: {cmd_name} | 参数: {params}")
                robot_map[target_id].handle_command(cmd_name, params)
            else:
                logger.warning(f"[CMD] 未知目标设备或广播指令 -> Topic: {msg.topic} | Command: {cmd_name}")
        except Exception as e:
            logger.warning(f"[CMD] 指令处理异常: {e}")

    client.on_message = on_cmd

    # 连接 MQTT Broker 并订阅控制下发主题
    while running:
        try:
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.subscribe([("cmd/#", 1), ("robot/+/+/cmd", 1)])
            client.loop_start()
            logger.info("[MQTT OK] 成功连入 MQTT Broker 并已订阅全部指令主题 [cmd/#, robot/+/+/cmd]！")
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

            if round_cnt % 15 == 0:
                active_moving = sum(1 for r in robots if r.is_moving)
                logger.info(f"[HEARTBEAT] 第 {round_cnt} 轮推流完成 | 在线: {len(robots)} 台 | 动态运行中: {active_moving} 台 | 待命/站立/充电: {len(robots) - active_moving} 台")

            time.sleep(INTERVAL)
    finally:
        client.loop_stop()
        client.disconnect()
        logger.info("模拟服务已安全退出")

if __name__ == "__main__":
    main()
