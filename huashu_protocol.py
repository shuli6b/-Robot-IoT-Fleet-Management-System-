"""HSC3 SocketCmd: matched frames, controller errors and serialized transactions."""
import json
import math
import re
import socket
import threading
import time
import uuid

from robot_commands import validate_command


class ControllerError(RuntimeError):
    def __init__(self, code, command):
        self.code=str(code)
        super().__init__(f'Controller rejected {command.split("(")[0]} (code={code})')


def array_value(value, size=6):
    if not isinstance(value,str) or not (value.startswith('{') and value.endswith('}')):
        raise ValueError('Invalid controller array')
    result=[float(x.strip()) for x in value[1:-1].split(',') if x.strip()]
    if len(result)<size or not all(math.isfinite(x) for x in result):
        raise ValueError('Incomplete/nonfinite controller array')
    return result[:size]


def bool_value(value):
    if str(value).strip().lower() in ('true','1'):
        return True
    if str(value).strip().lower() in ('false','0'):
        return False
    raise ValueError('Unknown controller boolean')


class HuashuSocketClient:
    def __init__(self, ip, port=23333, timeout=1.0, alarm_callback=None):
        self.ip,self.port,self.timeout=ip,port,timeout
        self.sock=None
        self.buffer=b''
        self.seq=0
        self.lock=threading.RLock()
        self.alarm_callback=alarm_callback
        self.connection_id=None
        self.last_action_accepted=False

    @property
    def is_connected(self):
        return self.sock is not None

    def connect(self):
        with self.lock:
            self.disconnect()
            self.sock=socket.create_connection((self.ip,self.port),timeout=self.timeout)
            self.sock.settimeout(self.timeout)
            self.connection_id=uuid.uuid4().hex
            return True

    def disconnect(self):
        with self.lock:
            if self.sock:
                self.sock.close()
            self.sock=None
            self.buffer=b''
            self.connection_id=None

    def send_cmd(self, command):
        with self.lock:
            if not self.sock:
                raise ConnectionError('Controller is offline')
            self.seq=(self.seq+1)%2147483648
            seq=self.seq
            deadline=time.monotonic()+self.timeout
            try:
                self.sock.sendall(f'i:{seq},c:{command}@hs@'.encode('utf-8'))
                while time.monotonic()<deadline:
                    if b'@hs@' not in self.buffer:
                        self.sock.settimeout(max(0.01,deadline-time.monotonic()))
                        chunk=self.sock.recv(4096)
                        if not chunk:
                            raise ConnectionError('Controller closed the connection')
                        self.buffer+=chunk
                        if len(self.buffer)>1048576:
                            raise ValueError('Oversized controller frame')
                        continue
                    packet,self.buffer=self.buffer.split(b'@hs@',1)
                    raw=packet.decode('utf-8')
                    match=re.fullmatch(r'i:(-?\d+),e:([^,]+),d:(.*)',raw,re.S)
                    if not match:
                        raise ValueError('Malformed controller response')
                    response_id,error,data=match.groups()
                    if int(response_id)==-1:
                        alarm=json.loads(data)
                        if self.alarm_callback:
                            self.alarm_callback(alarm)
                        continue
                    if int(response_id)!=seq:
                        continue
                    if error.strip() not in ('0','0x0','0X0'):
                        raise ControllerError(error,command)
                    return data
                raise TimeoutError('Controller response deadline exceeded')
            except ControllerError:
                raise
            except Exception:
                self.disconnect()
                raise

    def telemetry(self):
        with self.lock:
            quality={}
            def read(key,command,parse):
                try:
                    value=parse(self.send_cmd(command))
                    quality[key]='valid'
                    return value
                except ControllerError as e:
                    quality[key]='controller_error:'+e.code
                    return None
                except ValueError:
                    quality[key]='invalid_response'
                    return None
            joints=read('joint_angles','mot.getJntData(0)',array_value)
            loc=read('cartesian_pos','mot.getLocData(0)',array_value)
            enabled=read('enabled','mot.getGpEn(0)',bool_value)
            estop=read('emergency_stop','mot.getEstop()',bool_value)
            errors=read('error_count','sys.hasError()',int)
            current=read('motor_currents','mot.getJntEData(0)',array_value)
            speed=read('speed','mot.getVord()',int)
            mode=read('op_mode','mot.getOpMode()',int)
            model=read('robot_model','mot.getRobType(0)',str)
            version=read('controller_version','mot.getMotionVer()',str)
            p={'robot_model':model,'controller_version':version,'joint_angles':joints,'cartesian_pos':dict(zip('xyzabc',loc)) if loc else None,
               'enabled':enabled,'emergency_stop':estop,'error_count':errors,'motor_currents':current,
               'motor_current_unit':'controller_native','speed':speed,'op_mode':mode,
               'status':'error' if estop is True or (errors is not None and errors>0) else ('ready' if enabled is not None and estop is not None and errors is not None else 'unknown'),
               'field_quality':quality,'connection_id':self.connection_id}
            # The controller exposes group values, not site-specific signal names.
            io={}
            for kind,command in [('di','Din'),('do','Dout')]:
                count=read(kind+'_groups',f'io.getMax{command}Grp()',int)
                if count is None or not 0<=count<=4096:
                    io[kind]=None
                    io[kind+'_count']=0
                    continue
                io[kind+'_total_count']=count*32
                groups=min(count,2)
                mask=0
                for group in range(groups):
                    value=read(kind+str(group),f'io.get{command}Grp({group})',int)
                    if value is None or not 0<=value<=0xffffffff:
                        mask=None
                        break
                    mask|=value<<(32*group)
                io[kind]=mask
                io[kind+'_count']=groups*32
            io['connection_id']=self.connection_id
            return p,io

    def execute(self, command, params, allow_jog=False):
        self.last_action_accepted=False
        command,p=validate_command(command,params)
        with self.lock:
            def send(text):
                result=self.send_cmd(text)
                if text.startswith(('mot.set','mot.gpReset','mot.startJog','mot.stopJog','io.set','vm.')):
                    self.last_action_accepted=True
                return result
            if command in ('enable','disable'):
                desired=command=='enable'
                if desired and bool_value(send('mot.getEstop()')):
                    raise ValueError('急停有效，拒绝上使能')
                send(f'mot.setGpEn(0,{str(desired).lower()})')
                if bool_value(send('mot.getGpEn(0)')) != desired:
                    return 'unknown','控制器接受命令，但使能状态未验证',None
                return 'succeeded','使能状态已由控制器读回验证',0
            if command=='stop':
                send('mot.setEstop(true)')
                if bool_value(send('mot.getEstop()')):
                    return 'succeeded','控制器急停状态已读回验证；不替代现场硬接线急停',0
                return 'unknown','未验证控制器急停状态',None
            if command=='reset':
                send('mot.gpReset(0)')
                return 'controller_accepted','控制器接受组复位；未自动解除急停，未保证所有报警清除',0
            if command=='set_override':
                send(f'mot.setVord({p["override"]})')
                if int(send('mot.getVord()'))==p['override']:
                    return 'succeeded','运行倍率已读回验证',0
                return 'unknown','运行倍率未验证',None
            if command=='set_do':
                count=int(send('io.getMaxDoutGrp()'))*32
                if p['port']>=count:
                    raise ValueError('输出端口超出控制器范围')
                mask=int(send(f'io.getDoutMaskGrp({p["port"]//32})'))
                # 1 means virtual according to the controller IO mask contract.
                if mask & (1<<(p['port']%32)):
                    raise ValueError('输出点处于虚拟模式，拒绝声称控制物理输出')
                send(f'io.setDout({p["port"]},{str(bool(p["value"])).lower()})')
                if bool_value(send(f'io.getDout({p["port"]})'))==bool(p['value']):
                    return 'succeeded','控制器输出寄存器已读回验证；不等同外围设备动作确认',0
                return 'unknown','输出寄存器未验证',None
            if command=='jog_joint':
                if not allow_jog:
                    raise ValueError('远程点动尚未通过现场安全验收，未启用')
                if int(send('mot.getOpMode()'))!=1 or not bool_value(send('mot.getGpEn(0)')) or bool_value(send('mot.getEstop()')):
                    raise ValueError('点动必须处于T1、已使能且无急停的现场状态')
                if int(send('mot.getWorkFrame(0)'))!=0:
                    raise ValueError('请在示教器选择关节坐标系')
                before=array_value(send('mot.getJntData(0)'))
                send('mot.setManualMode(1)')
                send(f'mot.setInchLen({p["step_deg"]})')
                send(f'mot.setJogVord({p["speed"]})')
                if int(send('mot.getManualMode()'))!=1 or abs(float(send('mot.getInchLen()'))-p['step_deg'])>1e-6:
                    raise ValueError('控制器增量模式未确认')
                try:
                    send(f'mot.startJog(0,{p["axis"]-1},{0 if p["direction"]==1 else 1})')
                    deadline=time.monotonic()+5
                    while time.monotonic()<deadline:
                        after=array_value(send('mot.getJntData(0)'))
                        delta=after[p['axis']-1]-before[p['axis']-1]
                        if abs(delta-p['direction']*p['step_deg'])<=0.05 and int(send('mot.getManualStat()'))==0:
                            return 'succeeded','增量目标已由关节反馈验证',0
                        time.sleep(0.05)
                    return 'unknown','未在期限内验证目标位置',None
                finally:
                    send('mot.stopJog(0)')
            prog=p['prog_name']
            if command=='select_prog':
                send(f'vm.load("","{prog}")')
            else:
                verb={'start_cycle':'start','resume':'start','pause':'pause','stop_prog':'stop'}[command]
                send(f'vm.{verb}("{prog}")')
            return 'controller_accepted','控制器接受程序命令；未声称加工已完成',0
