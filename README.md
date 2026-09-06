# 机器人生产监控与受控操作平台

本平台支持真机采集和显式仿真演示。真机事实只来自已登记、通过签名与时效校验的控制器上报；仿真使用独立账号、密钥和simulation主题，不得混入真机统计或真机命令。

## 数据边界

- 新遥测：设备登记白名单 + MQTT账号权限 + HMAC签名 + 消息去重 + 30秒时效检查。
- 历史数据：原始记录保留；旧记录标记为 legacy_unverified，不混入新的生产统计。管理员可通过 /api/admin/legacy/{table} 分页查询。
- 空值和过期值：返回 null/unknown/stale，界面显示 --，不补造正常值、坐标或工时。
- 日志：区分 platform_audit 与 controller_event；平台已阅不是控制器复位，不生成示教器模板事件。当前接口不读取示教器历史原生日志，页面只显示平台审计和已接收控制器事件。
- 总览：总台数、在线台数和在线率包含启用的仿真设备；主界面统一显示，设置保留仿真标记。后台仍区分历史来源。
- 报表：只统计选定时间范围及对应设备来源的观测。观测覆盖时间不等于通电时间，未采集的OEE、节拍、能耗和维保寿命留空。
- 程序：平台编辑器保存 platform_draft，不声称已写入控制器；不存在的文件返回404。

## 控制边界

控制请求必须具备有效管理员会话、明确确认、当前控制器连接及新鲜遥测。命令带唯一任务ID、5秒有效期和连接会话ID。禁止原生终端指令透传、离线排队重放及自动重试。

结果状态：delivered仅表示Broker确认；received仅表示边缘端收到；controller_accepted表示控制器接受但尚无完成证明；succeeded仅用于读回验证过的结果；unknown表示结果无法确定。控制器DO读回不等同外围设备动作完成。

真机远程执行默认由ROBOT_CONTROL_ENABLED=0锁定；仿真命令仅在simulation/cmd命名空间执行，不受真机验收锁影响。真机须完成可信加密接入与现场动作验收后启用。远程点动另行默认关闭，需现场安全验收后才能设置ROBOT_ALLOW_JOG=1；使用官方增量模式，不按等待时间猜测角度。回原点需要经现场确认的安全目标及路径，当前拒绝将其替代为复位。软件网络停机不能替代硬接线急停或安全PLC。

## 部署

运行服务：robot-iot.service、huashu-bridge.service、robot-mock.service、emqx.service、frpc.service。robot-mock仅根据设置中启用的仿真清单演示，不生成未登记设备，不拥有真机MQTT主题权限。

配置及凭据位于 /etc/robot-iot/backend.env 与 /etc/robot-iot/bridge.env，文件权限600。实际设备登记、控制器IP、MQTT账号、独立消息签名密钥均必须显式配置，缺失时拒绝启动。机型入口统一使用 huashu_real_bridge.py 与 huashu_protocol.py。

使用 start.sh / stop.sh 管理应用服务。停止这些服务只停止软件，不执行机器人运动或安全停机。update_server.sh只允许干净工作区和fast-forward更新，不重置本地修改。

密码采用带独立盐的PBKDF2存储；会话在服务端验证。历史默认弱密码账号首次登录必须更改密码。新账号只能注册为待审核普通用户。

Web公网入口应在配置可信TLS证书后使用HTTPS。不得在不可信网络通过HTTP传输登录凭据。MQTT和EMQX控制台不应直接暴露到公网。

## 备份

backup_service.py --database /opt/robot-iot/robot.db 使用SQLite在线备份接口生成一致性快照并执行完整性检查。文件、校验摘要及来源清单存放在BACKUP_DIR。平台数据库备份不等于控制器完整系统镜像。

备份统一在服务器本地 `BACKUP_DIR`（生产目录为 `/opt/robot-iot/backups/`）生成 SQLite 一致性快照和 SHA-256 清单，不再依赖控制器 FTP。该归档不是控制器完整系统镜像；未执行过真机恢复测试的备份不得宣传为已验证灾备切换。

## 官方错误码

resources/huashu_sdk_errors.json来自所提供ErrDef.h，共55项定义、54个码值。该表为32位SDK接口返回码，不是完整64位控制器硬件报警手册；没有原文维修步骤的条目不补造维修建议。

取消仿真后，已登记真机的有效签名状态可接替该设备；仿真历史及命令来源保持原样。仅点击取消不会生成真实数据。

## 回归

运行 python -m unittest discover -s tests。所有测试数据库、套接字和命令均为隔离测试对象，不连接实际机器人。tests/3d_mapping_sha256.json锁定原有30个3D场景及姿态映射函数，防止本次修复更改现场调试结果。
