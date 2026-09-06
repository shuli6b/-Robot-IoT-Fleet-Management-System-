"""Explicit, bounded application commands. No raw terminal passthrough."""
import math
import re

ALIASES={'servo_on':'enable','servo_off':'disable','fault_reset':'reset','emergency_stop':'stop','set_speed':'set_override',
         'load_prog':'select_prog','start_prog':'start_cycle','pause_prog':'pause','resume_prog':'resume','set_dout':'set_do'}
SUPPORTED={'enable','disable','reset','stop','set_override','set_do','select_prog','start_cycle','pause','resume','stop_prog','jog_joint'}


def validate_command(command, params):
    command=ALIASES.get(command,command)
    if command not in SUPPORTED:
        raise ValueError('不支持此命令；回原点需要现场核验的安全目标和路径，禁止替代为复位')
    if not isinstance(params,dict):
        raise ValueError('参数必须是JSON对象')
    p=dict(params)
    permitted={'set_override':{'override','speed'},'set_do':{'port','value'},'jog_joint':{'axis','direction','step_deg','speed'},
               'select_prog':{'prog_name','program'},'start_cycle':{'prog_name','program'},'pause':{'prog_name','program'},'resume':{'prog_name','program'},'stop_prog':{'prog_name','program'}}.get(command,{'reason','axis_mask'})
    if set(p)-permitted:
        raise ValueError('包含该命令不支持的参数，未忽略或猜测执行')
    def number(key,low,high,integer=False):
        value=p.get(key)
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'{key}必须在{low}至{high}范围内')
        if integer and int(value)!=value:
            raise ValueError(f'{key}必须是整数')
        return int(value) if integer else float(value)
    if command=='set_override':
        if 'speed' in p and 'override' not in p:
            p['override']=p.pop('speed')
        p={'override':number('override',1,100,True)}
    elif command=='set_do':
        p={'port':number('port',0,63,True),'value':number('value',0,1,True)}
    elif command=='jog_joint':
        axis=number('axis',1,6,True)
        direction=number('direction',-1,1,True)
        if direction not in (-1,1):
            raise ValueError('direction必须为-1或1')
        p={'axis':axis,'direction':direction,'step_deg':number('step_deg',0.1,5),'speed':number('speed',1,10,True)}
    elif command in ('select_prog','start_cycle','pause','resume','stop_prog'):
        prog=p.get('prog_name',p.get('program'))
        if not isinstance(prog,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}\.[Pp][Rr][Gg]',prog):
            raise ValueError('必须明确提供合法的控制器程序名')
        p={'prog_name':prog}
    else:
        # Compatibility: the old UI sent axis_mask=63, which means group zero.
        if set(p)-{'reason','axis_mask'} or ('axis_mask' in p and p['axis_mask']!=63):
            raise ValueError('该命令不接受这些参数')
        p={}
    return command,p
