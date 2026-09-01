# 系统真实性修复记录（2026-09-01）

> **给协作者（包括 Antigravity 等 AI 工具）的重要说明**
> 本项目在 2026-09-01 经历了一次**全量真实性整改**。此前版本中存在大量由 AI 生成的**造假数据与假闭环**，本次已全部剔除并替换为**基于华数官方《V1.6.11_SocketCmd 网络通讯功能使用说明书》(97页) + SDK 头文件 + 真机实测**的真实实现。
>
> **铁律：任何新增/修改的展示字段，必须能追溯到华数官方协议/SDK 的真实返回值，否则一律不得上屏。严禁 mock、random、硬编码数值冒充真实数据。**

---

## 一、核心问题（整改前）

| 问题 | 位置 | 说明 |
|:---|:---|:---|
| 内置模拟器 | `main.py` `local_simulation_generator_task()` | 用 `math.sin/cos` 生成假数据直接写库，topic 伪装成真实上报 |
| 虚拟设备舰队 | `mock_service.py`（systemd robot-mock） | 10 台虚拟设备，订阅 `cmd/#` **模拟执行控制指令**，形成假闭环 |
| 硬编码假字段 | `huashu_real_bridge.py` | `battery:100` / `cycle_count:1890` / `running_hours:360.5` |
| 断线兜底假姿态 | 同上 | 采集失败回退假坐标 `{500,0,400}` 冒充正常 |
| IO 假默认值 | `database.py get_device_io()` | 无记录时返回硬编码"DI1 气压正常/安全门关闭"等编造点位 |
| 假流量曲线 | `static/index.html` | `Math.random()` 生成吞吐曲线 |
| 假事件流 | 大屏 | 静态写死"arm_001 周期上报正常 / amr_001 SLAM 良好"，含不存在的设备 `amr_001` |
| 假周备份文件 | `database.py get_weekly_backups_list()` | 无备份时返回硬编码假文件（filesize 45280/44190） |
| 硬编码 FTP 凭据 | `main.py` 备份接口 | `ftp.login("admin","admin888")` 占位 |
| 假健康评分 | 详情弹窗 | 固定"98 分"、假保养周期"剩余 347.6 小时" |
| 文档虚报 | 多处 | 宣称"4 台控制器"，实测 192.168.1.168/.169/.144/.170 **MAC 全相同**（同一台设备绑 4 个 IP 别名） |

## 二、真实性标准（华数官方协议白名单）

所有展示字段必须来自以下官方可查询命令（59 条中的核心项）：

```
关节角     mot.getJntData(gpId)
笛卡尔坐标  mot.getLocData(gpId)
伺服使能    mot.getGpEn(gpId)
急停       mot.getEstop()
关节电流    mot.getJntEData(gpId)
报警数/详情  sys.hasError() / sys.queryError(code)
机型       mot.getRobTypeName(gpId)
操作模式    mot.getOpMode()            # 1=T1手动 2=T2手动 3=自动 4=外部
零点       mot.getHomePosition(gpId)
数字IO     io.getDinGrp(grp) / io.getDoutGrp(grp)
程序       vm.mainProgNames / vm.load / vm.start / vm.pause / vm.stop
负载       mot.getRobLoad(gpId)
拖动示教    mot.getGpDrag(gpId)
```

**官方协议没有的数据（禁止上屏）**：电池、温度、湿度、振动、电压、电机转速、循环次数、运行时长、高度、风速等。

**控制命令映射（官方真实命令）**：
```
enable            → mot.setGpEn(0,true)
disable           → mot.setGpEn(0,false)
emergency_stop    → mot.setEstop(true)
reset             → sys.reset()
set_override      → mot.setVord(v)
set_do            → io.setDout(port,true/false)
jog_joint         → mot.startJog(0,axis,dir) → mot.stopJog(0)
home              → mot.moveTo(0,true,0,0,0,"{home}",false)
start_cycle/resume→ vm.start(entry)
pause             → vm.pause(entry)
select_prog       → vm.load(path,entry)
```

## 三、本次修复明细

### 后端
1. **`main.py`**：删除内置模拟器（`local_simulation_generator_task` 及其启动/取消代码）；指令下发改三态（`simulated/queued/delivered/failed`），不再谎报成功；新增 `cmd_ack` 执行回执订阅与查询接口；FTP 备份凭据改从 `device_ftp_config` 配置读取（未配置时明确提示，绝不硬编码）；新增 `/api/admin/simulated_devices`（仿真设备管理 CRUD）、`/api/admin/ftp_config`（FTP 凭据管理）、`/api/system/traffic`（真实吞吐统计）；故障知识库按设备类型过滤（仅华数设备返回）。
2. **`database.py`**：devices 表新增 `is_simulated` 列（仿真标记，后台可管）；`get_all_devices/get_device_by_id` 返回 `is_simulated` 与 `real_report_count`（数据库累计真实上报次数，替代假 cycle_count）；重写 `get_device_io()` —— 从真实 IO 上报报文读取，无数据返回 `source:no_data` 绝不编造；删除周备份假默认文件；新增仿真管理/指令回执/吞吐统计函数。
3. **`huashu_real_bridge.py`（重写）**：仅直连 1 台真实控制器（192.168.1.169:23333，其余 .168/.144/.170 为同 MAC 别名）；删除全部硬编码假字段；采集失败上报 offline 不输出假姿态；补采真实电流/报警/机型/操作模式/零点；新增 `cmd/` 订阅 + 官方命令映射 + `cmd_ack` 回执；运动类指令默认关闭（`HUAHSHU_ENABLE_MOTION=1` 开启）。
4. **`mock_service.py`**：保留为唯一仿真源（用户刻意保留，填补设备缺口）；设备清单改为从后台 `/api/admin/simulated_devices` 每 30 秒动态拉取（设置页增删实时生效），不再硬编码 10 台。
5. **`huashu_edge_agent/huashu_edge_collector.py`**：删除 random 假传感器（温湿度/振动/电机温度），仅保留真实电流。
6. **`huashu_bridge/huashu_adapter.py`**：退役至 `_quarantine/`（含 random 假传感器，禁止复用）。

### 前端（`static/index.html`）
- 吞吐曲线改用 `/api/system/traffic` 真实统计（去 `Math.random`）
- 设备卡片：真机不显示电池（华数臂无电池）；TCP 坐标无数据时显示"—"（删除兜底假坐标 450.2/1200.5/320.0）
- 详情弹窗：循环计数改为数据库真实上报次数；工时/保养周期/健康评分删除假值；新增**控制器机型/操作模式/报警数量**真实字段展示
- 大屏事件流改为真实设备驱动（删除含不存在设备的静态假事件）
- IO 面板：无真实数据时显示"无实时 IO 上报数据"
- 故障知识库：非华数设备显示"该设备类型暂无故障知识库"
- 华数命令面板：删除协议无映射的 `jog_cartesian`、`set_gripper`
- 设置页新增「仿真设备与备份管理」tab：仿真设备增删管理 + FTP 凭据配置（前端大屏不显示仿真标记）

### 运维/部署
- 数据库 `VACUUM`：1.4GB → 83MB（97.7% 空闲页回收）
- 每周自动备份（crontab 周日 02:00）：数据库快照 + 华数控制器轴数据（HTTP 直连，无需 FTP 密码）
- 服务器 `/home/nbrobotsys/backups/` 保存全量回滚备份

## 四、真实 vs 仿真边界（务必遵守）

- **仿真设备是有意保留的**（真实设备数量不足，用于演示），前端观感与真机一致，**不显示任何仿真标记**
- 仿真设备在后台「设置-仿真设备与备份管理」管理（增删/类型），`devices.is_simulated=1` 标记
- 对仿真设备下发指令返回 `deliver_state: "simulated"`，**不得谎报**"已发送至端侧设备"
- 真机（arm_001）的指令执行必须等 `cmd_ack` 回执确认

## 五、当前已知待办

1. **FTP 备份凭据**：华数控制器 FTP（21 端口）已开，但账号需华数现场工程师提供（示教器/控制器登录账号很可能即 FTP 账号），在后台设置页填写后启用
2. **运动类指令开关**：`jog_joint/home/start_cycle` 已映射真实命令但默认关闭，现场确认安全后置 `HUAHSHU_ENABLE_MOTION=1` 重启 `huashu-bridge`
3. **运维手册 IP 更正**：控制器地址实测为 `192.168.1.169:23333`（SocketCmd 端口；23234 是 C++ CommApi SDK 端口），手册中 `10.10.56.214` 已过时
4. **真机程序**：`vm.mainProgNames()` 实测为空，程序上传需 FTP 凭据

## 六、提交范围说明

- 本次提交包含：所有源码真实化改动、`.gitignore` 敏感文件保护、本文档
- **不包含**（已在 .gitignore 保护）：数据库、服务器密码凭据、私有运维手册、华数 SDK 压缩包、调试残留文件、`_quarantine/` 退役代码
- 服务器生产环境代码与仓库一致（`/opt/robot-iot`）
