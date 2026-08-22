# 🦾 现场接入新机器人实战指南 (ROBOT INTEGRATION GUIDE)

> **适用机型**：华数 BR 系列机械臂 / 珞石复合移动 AMR / 四足仿生机器狗 / 空地协同无人机编队  
> **文档版本**：v2.0 (生产发布版)  
> **更新日期**：2026-08-22  
> **核心机制**：**平台采用全自动设备发现机制，机器人只要推流，大屏秒级建档上线！**

---

## 📌 一、 接入拓扑与通信架构

本平台采用统一的 **MQTT 工业物联网消息总线（Broker 端口：`1883`）**。机器人作为客户端主动推流，无需平台主动轮询，拓扑架构如下：

```
┌─────────────────────────────────────────────────────────────┐
│                 【现场真实机器人设备端】                      │
│                                                             │
│ 1. 华数机械臂 ──► 工控机 IPC 运行 huashu_edge_agent ────────┐│
│ 2. 复合移动 AMR ──► 车载工控机 ROS / Python MQTT 通信节点 ──┼┤
│ 3. 四足机器狗 ──► 板载 Jetson / Orin 巡检上报节点 ──────────┼┤
│ 4. 空地编队 ──► 5G 自组网车载边缘机 ────────────────────────┘│
└──────────────────────────────┬──────────────────────────────┘
                               │ MQTT 协议 (TCP 端口 :1883 / QoS 1)
                               ▼
┌─────────────────────────────────────────────────────────────┐
│       【云端智能管控服务器 (IP: <SERVER_PUBLIC_IP>)】            │
│                                                             │
│   - EMQX 物联网 Broker (:1883)                              │
│   - FastAPI 实时遥测引擎 (:8000)                             │
│   - 网页大屏 3D 数字孪生与控制下发 (:8000)                   │
└─────────────────────────────────────────────────────────────┘
```

---

## 🚀 二、 各品类机器人接入实战教程

### 教程 1：华数六轴工业机械臂（HSC3 控制柜 / BR 系列）

华数机械臂控制柜对外开放标准 TCP 通信接口（默认端口 `23234` 或 `23333`）。

#### 步骤 1：部署现场采集网关
在现场连接机械臂控制柜的工控机（Windows / Linux 均可）上，拷贝项目自带的 `huashu_edge_agent` 目录。

#### 步骤 2：修改配置文件 `edge_config.json`
打开 `huashu_edge_agent/edge_config.json`，根据现场实际情况配置：
```json
{
  "robots": [
    {
      "device_id": "arm_001",
      "device_name": "华数BR610六轴工业机械臂_A线",
      "ip": "10.10.56.214",
      "port": 23234,
      "group_id": 0,
      "axis_count": 6
    },
    {
      "device_id": "arm_002",
      "device_name": "华数BR610六轴工业机械臂_B线",
      "ip": "10.10.56.215",
      "port": 23234,
      "group_id": 0,
      "axis_count": 6
    }
  ],
  "mqtt": {
    "host": "<SERVER_PUBLIC_IP>",
    "port": 1883,
    "topic_state": "robot/huashu_arm/{device_id}/state",
    "topic_sensor": "robot/huashu_arm/{device_id}/sensor",
    "topic_cmd_sub": "cmd/huashu_arm/{device_id}",
    "qos": 1
  },
  "collection": {
    "interval_sec": 1.0,
    "include_io": true,
    "simulation_fallback": false
  }
}
```

#### 步骤 3：一键启动采集网关
- **Windows 工控机**：双击运行 `run_edge_agent.bat`
- **Linux 工控机**：终端执行 `bash run_edge_agent.sh`
- **设为开机自启（推荐）**：
  - Windows：按 `Win + R` 输入 `shell:startup`，将 `run_edge_agent.bat` 快捷方式放入该文件夹；
  - Linux：注册为 systemd 服务：
    ```bash
    sudo bash -c 'cat << EOF > /etc/systemd/system/huashu-agent.service
    [Unit]
    Description=Huashu Robot Edge Collector
    After=network.target

    [Service]
    Type=simple
    WorkingDirectory=/home/user/huashu_edge_agent
    ExecStart=/usr/bin/python3 huashu_edge_collector.py
    Restart=always
    RestartSec=3s

    [Install]
    WantedBy=multi-user.target
    EOF'
    sudo systemctl enable --now huashu-agent
    ```

---

### 教程 2：珞石复合移动 AMR 机器人接入（AGV + 协作臂）

复合移动机器人车载工控机（通常运行 ROS1 / ROS2）自带 4G/5G 或连入厂区 Wi-Fi。

#### 车载 Python / ROS MQTT 接入代码模板：
```python
import time
import json
import paho.mqtt.client as mqtt

MQTT_BROKER = "<SERVER_PUBLIC_IP>"
MQTT_PORT = 1883
DEVICE_ID = "amr_001"
DEVICE_TYPE = "luxshare_amr"

TOPIC_STATE = f"robot/{DEVICE_TYPE}/{DEVICE_ID}/state"
TOPIC_SENSOR = f"robot/{DEVICE_TYPE}/{DEVICE_ID}/sensor"
TOPIC_CMD = f"cmd/{DEVICE_TYPE}/{DEVICE_ID}"

def on_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        cmd = payload.get("command")
        params = payload.get("params", {})
        print(f"收到云端控制指令: [{cmd}], 参数: {params}")
        
        if cmd == "pick_and_place":
            # 执行抓取调度任务
            pass
        elif cmd == "nav_to_point":
            # 底盘导航至目标点
            pass
        elif cmd == "auto_charge":
            # 自动返回充电坞
            pass
        elif cmd == "stop":
            # 紧急制动停机
            pass
    except Exception as e:
        print("指令解析异常:", e)

# 1. 建立 MQTT 客户端连接
client = mqtt.Client(client_id=f"{DEVICE_TYPE}_{DEVICE_ID}")
client.on_message = on_message
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.subscribe(TOPIC_CMD, qos=1)
client.loop_start()

# 2. 循环推送遥测数据流 (1Hz)
try:
    while True:
        # A. 状态报文
        state_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",           # running / idle / charging / error
            "battery": 88.5,
            "position": {"x": 12.5, "y": 34.8, "z": 0.0, "floor": 1},
            "speed_mps": 1.2,
            "load_status": "loaded",
            "emergency_stop": False,
            "enabled": True
        }
        client.publish(TOPIC_STATE, json.dumps(state_data), qos=1)

        # B. 传感器报文
        sensor_data = {
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "voltage": 48.2,
            "current": 4.5,
            "temperature": 32.4,
            "co2_ppm": 550,
            "pm25": 18
        }
        client.publish(TOPIC_SENSOR, json.dumps(sensor_data), qos=1)

        time.sleep(1.0)
except KeyboardInterrupt:
    client.loop_stop()
    client.disconnect()
```

---

### 教程 3：四足仿生巡检机器狗接入

机器狗车载工控板（Jetson Orin / x86）采集 12 关节姿态、IMU 倾角与红外热成像数据：

#### 板载通信上报代码模板：
```python
import time
import json
import paho.mqtt.client as mqtt

MQTT_BROKER = "<SERVER_PUBLIC_IP>"
MQTT_PORT = 1883
DEVICE_ID = "dog_001"
DEVICE_TYPE = "robot_dog"

TOPIC_STATE = f"robot/{DEVICE_TYPE}/{DEVICE_ID}/state"
TOPIC_SENSOR = f"robot/{DEVICE_TYPE}/{DEVICE_ID}/sensor"
TOPIC_CMD = f"cmd/{DEVICE_TYPE}/{DEVICE_ID}"

def on_command(client, userdata, msg):
    payload = json.loads(msg.payload.decode())
    cmd = payload.get("command")
    print(f"机器狗收到指令: {cmd}")
    # stand / sit / patrol / start_thermal_scan / emergency_stop

client = mqtt.Client(client_id=f"dog_node_{DEVICE_ID}")
client.on_message = on_command
client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
client.subscribe(TOPIC_CMD, qos=1)
client.loop_start()

while True:
    # 状态
    client.publish(TOPIC_STATE, json.dumps({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "status": "patrolling",
        "battery": 91.0,
        "gait_mode": "trot",
        "imu_pitch": 1.5,
        "imu_roll": -0.8,
        "emergency_stop": False
    }), qos=1)

    # 传感器与红外热成像
    client.publish(TOPIC_SENSOR, json.dumps({
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "temperature": 36.8,
        "voc": 0.12,
        "hcho": 0.018,
        "foot_traffic": 450
    }), qos=1)

    time.sleep(1.0)
```

---

## 📊 三、 核心通信协议与 JSON 报文字典

### 1. 状态报文 (Topic: `robot/{device_type}/{device_id}/state`)
| 字段名 | 类型 | 必填 | 说明与示例 |
| :--- | :--- | :---: | :--- |
| `timestamp` | string | 是 | 当前时间，如 `"2026-08-22 14:00:00"` |
| `status` | string | 是 | 设备状态：`running` (运行), `idle` (待机), `error` (故障), `charging` (充电) |
| `battery` | float | 否 | 电池电量百分比，如 `95.5` |
| `joint_angles` | list[float] | 否 | 六轴关节角度数组（度），如 `[15.2, -30.5, 88.4, 0.0, 45.0, -12.8]` |
| `cartesian_pos` | object | 否 | 笛卡尔坐标与姿态 `{"x": 482.3, "y": 12.4, "z": 395.1, "a": 180.0, "b": 0.0, "c": 12.5}` |
| `emergency_stop`| bool | 否 | 急停按下状态：`true` / `false` |
| `enabled` | bool | 否 | 伺服使能状态：`true` / `false` |
| `error_code` | int | 否 | 故障代码（0 为无故障） |
| `error_msg` | string | 否 | 故障文字描述 |

### 2. 传感器报文 (Topic: `robot/{device_type}/{device_id}/sensor`)
| 字段名 | 类型 | 必填 | 说明与示例 |
| :--- | :--- | :---: | :--- |
| `timestamp` | string | 是 | 当前时间 |
| `current` | float | 否 | 母线综合工作电流（A） |
| `voltage` | float | 否 | 母线供电电压（V） |
| `temperature` | float | 否 | 控制柜内部环境温度（℃） |
| `humidity` | float | 否 | 环境湿度百分比（%） |
| `motor_currents` | list[float]| 否 | 伺服各轴独立反馈电流，如 `[2.3, 3.1, 2.8, 1.2, 0.9, 0.6]` |

### 3. 下行控制指令 (Topic: `cmd/{device_type}/{device_id}`)
| 字段名 | 类型 | 说明 |
| :--- | :--- | :--- |
| `task_id` | string | 指令唯一追踪 ID，如 `"tsk_928371"` |
| `command` | string | 控制指令标识（如 `start_cycle`, `pause`, `reset`, `enable`, `jog`, `stop`） |
| `params` | object | 指令参数字典，如 `{"speed": 80, "program": "MAIN.PRG"}` |

---

## 🛠️ 四、 现场通信排障速查表

1. **机器人连不上平台**：
   - 检查现场工控机是否能 ping 通 `106.55.248.254`；
   - 检查工控机防火墙是否放行出站 1883 端口；
2. **大屏显示“已离线”**：
   - 平台设有 30 秒掉电感知保护机制，若 30 秒内未收到设备推流则标记离线；
   - 重新启动设备端推流脚本即可 1 秒内恢复绿色在线状态；
3. **大屏 3D 姿态不随动**：
   - 确认上报的 `joint_angles` 为包含 6 个浮点数值的数组。
