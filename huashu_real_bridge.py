#!/usr/bin/env python3
"""Verified HSC3 bridge. No simulation, guessed measurements or raw commands."""
import argparse
import hashlib
import json
import logging
import os
import queue
import signal
import sqlite3
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from contextlib import closing

import paho.mqtt.client as mqtt
from huashu_protocol import HuashuSocketClient, ControllerError
from robot_commands import validate_command
from security import sign_payload, verify_payload, timestamp_age

logger=logging.getLogger('HuashuRealBridge')
STOP=threading.Event()


class HuashuRobotCollector(threading.Thread):
    def __init__(self, r_info, mqtt_client):
        super().__init__(daemon=True)
        self.device_id=r_info['device_id']
        self.mqtt=mqtt_client
        self.key=os.environ['TELEMETRY_HMAC_KEY']
        self.command_key=os.environ['COMMAND_HMAC_KEY']
        self.driver=HuashuSocketClient(r_info['ip'],int(r_info.get('port',23333)),alarm_callback=self.alarm)
        self.cmd_queue=queue.PriorityQueue(maxsize=32)
        self.counter=0
        self.counter_lock=threading.Lock()
        self.ledger=Path(os.getenv('EDGE_STATE_DIR',str(Path(__file__).parent/'edge_state')))/f'{self.device_id}.db'
        self.ledger.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(str(self.ledger))) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS received_tasks(task_id TEXT PRIMARY KEY, received_at REAL NOT NULL)')

    def emit(self,kind,payload,message_id=None):
        p=dict(payload,device_id=self.device_id,device_type='huashu_arm',source='controller',
               timestamp=datetime.now().astimezone().isoformat(timespec='milliseconds'),message_id=message_id or uuid.uuid4().hex)
        signed=sign_payload(p,self.key)
        self.mqtt.publish(f'robot/huashu_arm/{self.device_id}/{kind}',json.dumps(signed,ensure_ascii=False,allow_nan=False),qos=1,retain=kind=='state')

    def alarm(self,alarm):
        if not isinstance(alarm,dict) or 'errorCode' not in alarm or 'time' not in alarm:
            logger.warning('Rejected malformed controller alarm')
            return
        identity=hashlib.sha256((self.device_id+str(alarm['time'])+str(alarm['errorCode'])+str(alarm.get('content'))).encode()).hexdigest()
        self.emit('alarm',{'alarm_code':str(alarm['errorCode']),'alarm_msg':alarm.get('content',''),
                   'alarm_level':alarm.get('errorLevel'),'controller_timestamp':alarm['time'],
                   'controller_raw':alarm},message_id=identity)

    def ack(self,item,state,message,code=None):
        self.emit('cmd_ack',{'task_id':item['task_id'],'command':item['command'],'status':state,
                    'message':message,'code':code,'connection_id':self.driver.connection_id})

    def offer(self,item):
        if not verify_payload(item,self.command_key):
            raise ValueError('Invalid command signature')
        if os.getenv('ROBOT_CONTROL_ENABLED','0')!='1':
            raise ValueError('Remote actuator control is not commissioned')
        if item.get('device_id')!=self.device_id or item.get('device_type')!='huashu_arm':
            raise ValueError('Wrong command target')
        if not isinstance(item.get('task_id'),str) or len(item['task_id'])>100:
            raise ValueError('Invalid task identity')
        if not -5<=timestamp_age(item.get('timestamp'))<=10 or not time.time()<float(item.get('expires_at',0))<=time.time()+15:
            self.ack(item,'expired','指令已过期，未执行')
            return
        command,params=validate_command(item.get('command'),item.get('params'))
        item=dict(item,command=command,params=params)
        if not self.driver.is_connected or item.get('connection_id')!=self.driver.connection_id:
            self.ack(item,'failed','控制器连接已改变或离线，未执行')
            return
        with closing(sqlite3.connect(str(self.ledger))) as conn, conn:
            try:
                conn.execute('INSERT INTO received_tasks VALUES(?,?)',(item['task_id'],time.time()))
            except sqlite3.IntegrityError:
                return
        with self.counter_lock:
            self.counter+=1
            try:
                self.cmd_queue.put_nowait((0 if command=='stop' else 1,self.counter,item))
            except queue.Full:
                self.ack(item,'failed','控制队列已满，未执行')
                return
        self.ack(item,'received','边缘端已收到，尚未执行')

    def execute_pending(self):
        try:
            _,_,item=self.cmd_queue.get_nowait()
        except queue.Empty:
            return
        if time.time()>=item['expires_at']:
            self.ack(item,'expired','排队期间过期，未执行')
            return
        if item.get('connection_id')!=self.driver.connection_id:
            self.ack(item,'failed','连接会话已变化，未执行')
            return
        if item['command']=='stop':
            while not self.cmd_queue.empty():
                _,_,cancelled=self.cmd_queue.get_nowait()
                self.ack(cancelled,'cancelled','被停机请求取消，未执行')
        try:
            state,message,code=self.driver.execute(item['command'],item['params'],allow_jog=os.getenv('ROBOT_ALLOW_JOG','0')=='1')
            self.ack(item,state,message,code)
        except ControllerError as e:
            if getattr(self.driver,'last_action_accepted',False):
                self.ack(item,'unknown','已有控制请求被接受，后续校验失败；结果未知，禁止自动重试',e.code)
            else:
                self.ack(item,'failed','控制器明确拒绝指令',e.code)
        except (ValueError,TypeError) as e:
            uncertain=getattr(self.driver,'last_action_accepted',False)
            self.ack(item,'unknown' if uncertain else 'failed','控制请求已被接受但未完成验证' if uncertain else str(e))
        except Exception:
            self.ack(item,'unknown','通信中断，执行结果未知；禁止自动重试')
            raise

    def run(self):
        while not STOP.is_set():
            try:
                if not self.driver.is_connected:
                    self.driver.connect()
                self.execute_pending()
                state,io=self.driver.telemetry()
                self.emit('state',state)
                self.emit('io',io)
                STOP.wait(float(os.getenv('ROBOT_INTERVAL','0.5')))
            except Exception as e:
                logger.warning('[%s] Controller link unavailable: %s',self.device_id,type(e).__name__)
                self.driver.disconnect()
                self.emit('state',{'status':'offline','reason':'controller_unavailable'})
                while not self.cmd_queue.empty():
                    _,_,item=self.cmd_queue.get_nowait()
                    self.ack(item,'failed','控制器离线，取消未执行请求')
                STOP.wait(3)
        self.driver.disconnect()
        self.emit('state',{'status':'offline','reason':'bridge_stopped'})


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--robot-ip',default=os.getenv('ROBOT_IP','192.168.1.169'))
    parser.add_argument('--robot-port',type=int,default=int(os.getenv('ROBOT_PORT','23333')))
    parser.add_argument('--device-id',default=os.getenv('ROBOT_DEVICE_ID','arm_001'))
    parser.add_argument('--mqtt-host','--cloud-host',dest='mqtt_host',default=os.getenv('MQTT_HOST','127.0.0.1'))
    parser.add_argument('--mqtt-port','--cloud-port',dest='mqtt_port',type=int,default=int(os.getenv('MQTT_PORT','1883')))
    parser.add_argument('--device-name',default='')
    parser.add_argument('--config')
    args=parser.parse_args()
    if args.config:
        raise SystemExit('旧版JSON配置不再作为凭据来源；请设置受保护的服务环境变量和明确设备参数')
    for key in ('TELEMETRY_HMAC_KEY','COMMAND_HMAC_KEY','MQTT_USERNAME','MQTT_PASSWORD'):
        if not os.getenv(key):
            raise SystemExit(f'Missing required setting: {key}')
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    client=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,client_id='huashu_verified_'+args.device_id,clean_session=True)
    client.username_pw_set(os.environ['MQTT_USERNAME'],os.environ['MQTT_PASSWORD'])
    if os.getenv('MQTT_TLS_CA'):
        client.tls_set(ca_certs=os.environ['MQTT_TLS_CA'])
    collector=HuashuRobotCollector({'device_id':args.device_id,'ip':args.robot_ip,'port':args.robot_port},client)
    def on_connect(c,u,f,reason,properties):
        if not reason.is_failure:
            c.subscribe(f'cmd/huashu_arm/{args.device_id}',qos=1)
    def on_message(c,u,msg):
        if msg.retain:
            logger.warning('Rejected retained command')
            return
        try:
            if len(msg.payload)>16384:
                raise ValueError('Oversized command')
            collector.offer(json.loads(msg.payload.decode('utf-8')))
        except Exception as e:
            logger.warning('Rejected command: %s',type(e).__name__)
    client.on_connect=on_connect
    client.on_message=on_message
    client.reconnect_delay_set(1,30)
    client.max_queued_messages_set(100)
    client.connect_async(args.mqtt_host,args.mqtt_port,keepalive=30)
    client.loop_start()
    signal.signal(signal.SIGTERM,lambda *_:STOP.set())
    signal.signal(signal.SIGINT,lambda *_:STOP.set())
    collector.start()
    while collector.is_alive():
        collector.join(1)
    client.disconnect()
    client.loop_stop()


if __name__=='__main__':
    main()
