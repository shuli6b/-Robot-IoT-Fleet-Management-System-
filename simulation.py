"""Explicit demo namespace: never authorizes physical device commands."""
import json
import math
import os
import re
import time
import uuid
from datetime import datetime

from security import allowed_device,sign_payload,verify_payload,timestamp_age

TYPES={'huashu_arm','luxshare_amr','robot_dog','uav_rescue'}
COMMON={'stop','emergency_stop','reset','enable','disable','pause','resume','set_override'}
COMMANDS={'huashu_arm':{'home','start_cycle','start_prog','run','pause_prog','resume_prog','select_prog','jog_joint'},
          'luxshare_amr':{'nav_to_point','resume_nav','pause_nav','pick_and_place','auto_charge'},
          'robot_dog':{'stand','sit','patrol','walk_to','auto_dock_charge'},
          'uav_rescue':{'auto_land_recharge','land','collab_patrol','multispectral_scan','takeoff','start'}}


def is_simulated(device_type,device_id,db_path=None):
    import database as db
    dev=db.get_device_by_id(device_id,db_path or db.DB_PATH)
    return bool(dev and dev['device_type']==device_type and dev['is_simulated'] and dev['simulation_enabled'])


def visible_device(device_type,device_id):
    return allowed_device(device_type,device_id) or is_simulated(device_type,device_id)


def configure_device(body,enabled=True):
    import database as db
    device_id=body.get('device_id','').strip()
    device_type=body.get('device_type','huashu_arm').strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}',device_id) or device_type not in TYPES:
        raise ValueError('设备ID或仿真品类不合法')
    if enabled and allowed_device(device_type,device_id):
        raise ValueError('禁止将已登记真机改为仿真设备')
    conn=db.get_connection()
    try:
        with conn:
            existing=conn.execute('SELECT * FROM devices WHERE device_id=?',(device_id,)).fetchall()
            if existing and (len(existing)!=1 or not existing[0]['is_simulated'] or existing[0]['device_type']!=device_type):
                raise ValueError('设备ID已由真机或其他品类占用')
            if not existing:
                if not enabled:
                    raise ValueError('仿真设备不存在')
                conn.execute("INSERT INTO devices(device_id,device_type,status,is_simulated,simulation_enabled,device_name,location,vendor) VALUES(?,?,'offline',1,1,?,?,?)",
                    (device_id,device_type,body.get('device_name') or device_id,body.get('location',''),body.get('vendor','仿真演示')))
            else:
                conn.execute("UPDATE devices SET simulation_enabled=?,status='offline' WHERE device_id=?",(int(enabled),device_id))
        return {'device_id':device_id,'is_simulated':1,'simulation_enabled':enabled}
    finally:
        conn.close()


def validate_simulation_command(device_type,command,params):
    if command not in COMMON|COMMANDS.get(device_type,set()) or not isinstance(params,dict):
        raise ValueError('仿真器未实现此命令，不会返回假成功')
    if len(json.dumps(params))>4096:
        raise ValueError('仿真参数过大')
    for key,value in params.items():
        if isinstance(value,float) and not math.isfinite(value):
            raise ValueError('参数不是有限数值')
    if command=='set_override' and (isinstance(params.get('override'),bool) or not isinstance(params.get('override'),int) or not 1<=params['override']<=100):
        raise ValueError('override必须为1至100的整数')
    if command=='jog_joint':
        if params.get('axis') not in range(1,7) or params.get('direction') not in (-1,1) or not isinstance(params.get('step_deg'),(int,float)) or not 0<params['step_deg']<=30:
            raise ValueError('点动参数不合法')
    if command=='stand' and ('height' in params and (not isinstance(params['height'],(int,float)) or not 0.1<=params['height']<=1)):
        raise ValueError('站立高度不合法')
    return command,params


def ingest(topic,raw):
    import database as db
    parts=topic.split('/')
    if len(parts)!=5 or parts[:2]!=['simulation','robot'] or len(raw)>65536:
        return
    _,_,device_type,device_id,kind=parts
    if kind not in ('state','sensor','event','cmd_ack') or not is_simulated(device_type,device_id):
        return
    p=json.loads(raw)
    if not verify_payload(p,os.getenv('SIMULATION_HMAC_KEY','')) or p.get('source')!='simulation' or p.get('device_id')!=device_id or p.get('device_type')!=device_type or not -5<=timestamp_age(p.get('timestamp'))<=30:
        return
    row=db.insert_device_data(device_id,device_type,kind,json.dumps(p,ensure_ascii=False),topic,source='simulation')
    if row is None:
        return
    if kind=='event':
        db.add_device_run_log(device_id,'info','simulator','[仿真] '+str(p.get('message','')),source='simulation',event_id=p['message_id'])
    if kind=='cmd_ack' and p.get('status') in ('succeeded','failed','expired'):
        conn=db.get_connection()
        try:
            with conn:
                command=conn.execute('SELECT * FROM command_requests WHERE task_id=? AND device_id=? AND device_type=?',(p.get('task_id'),device_id,device_type)).fetchone()
                if not command or command['command']!=p.get('command') or command['connection_id']!=p.get('connection_id') or command['state'] in ('succeeded','failed','expired'):
                    return
                conn.execute('UPDATE command_requests SET state=?,message=?,result=?,updated_at=? WHERE task_id=?',
                    (p['status'],'[仿真] '+str(p.get('message','')),json.dumps(p,ensure_ascii=False),datetime.now().isoformat(timespec='seconds'),p['task_id']))
            db.add_device_run_log(device_id,'action',command['operator'],'[仿真] '+command['command']+': '+str(p.get('message','')),source='simulation',event_id=p['message_id'])
        finally:
            conn.close()


def dispatch(device_type,device_id,command,params,task_id,operator,client,connected):
    import database as db
    from fastapi import HTTPException
    if not is_simulated(device_type,device_id):
        raise HTTPException(409,'仿真设备已停用')
    try:
        command,params=validate_simulation_command(device_type,command,params or {})
    except ValueError as e:
        raise HTTPException(422,str(e))
    latest=db.get_latest_data(device_type,device_id)
    p=latest.get('parsed_payload',{}) if latest else {}
    if not connected or client is None:
        raise HTTPException(503,'MQTT未连接，仿真命令未发送')
    if not p.get('state_fresh') or not p.get('connection_id'):
        raise HTTPException(409,'仿真服务没有当前状态，未发送')
    task_id=task_id or uuid.uuid4().hex
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',task_id):
        raise HTTPException(422,'非法task_id')
    payload={'task_id':task_id,'device_type':device_type,'device_id':device_id,'command':command,'params':params,'source':'simulation',
        'timestamp':datetime.now().astimezone().isoformat(),'expires_at':time.time()+5,'connection_id':p['connection_id']}
    conn=db.get_connection()
    try:
        with conn:
            previous=conn.execute('SELECT * FROM command_requests WHERE task_id=?',(task_id,)).fetchone()
            if previous:
                if (previous['device_id'],previous['command'],previous['params'],previous['operator'])!=(device_id,command,json.dumps(params,sort_keys=True),operator):
                    raise HTTPException(409,'task_id已用于其他请求')
                return previous['state'],previous['message'],{'task_id':task_id}
            stamp=datetime.now().isoformat(timespec='seconds')
            conn.execute("INSERT INTO command_requests(task_id,device_id,device_type,command,params,operator,state,created_at,expires_at,updated_at,connection_id,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,'simulation')",
                (task_id,device_id,device_type,command,json.dumps(params,sort_keys=True),operator,'sending',stamp,payload['expires_at'],stamp,p['connection_id']))
        signed=sign_payload(payload,os.environ['SIMULATION_COMMAND_KEY'])
        state,message='unknown','[仿真] 发送结果未知'
        try:
            info=client.publish(f'simulation/cmd/{device_type}/{device_id}',json.dumps(signed,ensure_ascii=False),qos=1,retain=False)
            if info.rc!=0:
                state,message='failed','[仿真] 消息未发送'
            else:
                info.wait_for_publish(timeout=2)
                if info.is_published():state,message='delivered','[仿真] 已发送至模拟服务，未触及真机'
        except Exception:
            pass
        with conn:
            conn.execute("UPDATE command_requests SET state=?,message=? WHERE task_id=? AND state='sending'",(state,message,task_id))
        return state,message,payload
    finally:
        conn.close()
