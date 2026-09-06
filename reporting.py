"""Reports over verified observations. Unmeasured quantities remain null."""
import json
import time
from collections import Counter
from datetime import datetime, timedelta


def boundaries(period, date_str):
    day = datetime.fromisoformat(date_str) if date_str else datetime.now()
    if period == 'daily':
        start = day.replace(hour=0,minute=0,second=0,microsecond=0)
        return start,start+timedelta(days=1),start.strftime('%Y-%m-%d')
    if period != 'monthly':
        raise ValueError('Unsupported report period')
    start = day.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    end = (start.replace(day=28)+timedelta(days=4)).replace(day=1)
    return start,end,start.strftime('%Y-%m')


def device_report(device_id, period, date_str, db_path):
    from database import get_connection
    start,end,label=boundaries(period,date_str)
    conn=get_connection(db_path)
    try:
        dev=conn.execute('SELECT * FROM devices WHERE device_id=?',(device_id,)).fetchone()
        if not dev:
            return {'error':'Device not found'}
        source='simulation' if dev['is_simulated'] else 'controller'
        rows=conn.execute("SELECT received_at,raw_payload FROM device_data WHERE device_id=? AND source=? AND data_type='state' AND received_at>=? AND received_at<? ORDER BY received_at,id",(device_id,source,start.isoformat(),end.isoformat()))
        observed=0.0
        operating={'running':0.0,'standby':0.0,'error':0.0}
        known_motion=False
        previous=None
        sample_count=0
        latest={}
        deadline=time.monotonic()+10
        for row in rows:
            if time.monotonic()>deadline:
                raise TimeoutError('Report exceeds synchronous time budget; no partial report is returned')
            stamp=datetime.fromisoformat(row[0])
            p=json.loads(row[1])
            sample_count+=1
            latest=p
            if previous:
                old_stamp,old=previous
                seconds=(stamp-old_stamp).total_seconds()
                if 0<seconds<=30 and old.get('status')!='offline':
                    observed+=seconds
                    mode=old.get('operating_state')
                    if mode in operating:
                        known_motion=True
                        operating[mode]+=seconds
            previous=(stamp,p)
        sensor_rows=conn.execute("SELECT raw_payload FROM device_data WHERE device_id=? AND source=? AND data_type='sensor' AND received_at>=? AND received_at<?",(device_id,source,start.isoformat(),end.isoformat())).fetchall()
        temperatures=[]
        for r in sensor_rows:
            v=json.loads(r[0]).get('temperature')
            if isinstance(v,(int,float)) and not isinstance(v,bool):
                temperatures.append(v)
        # latest is the last observation inside the requested period.
        hours={k:round(v/3600,4) if known_motion else None for k,v in operating.items()}
        return {
            'device_id':device_id,'device_name':dev['device_name'] or device_id,'device_type':dev['device_type'],
            'location':dev['location'] or '未配置','period':period,'period_label':label,
            'report_generated_at':datetime.now().isoformat(timespec='seconds'),
            'controller_version':latest.get('controller_version'),
            'source':source,'state_samples':sample_count,
            'operating_hours':{'total_hours':round(observed/3600,4),'running_hours':hours['running'],
                'standby_hours':hours['standby'],'downtime_hours':hours['error'],'oee_pct':None,
                'basis':'相邻有效上报间隔累计，超过30秒的数据缺口不计入；不等同通电工时'},
            'production_metrics':{'cycles_completed':None,'avg_cycle_time_sec':None,'min_cycle_time_sec':None,
                'max_cycle_time_sec':None,'cycle_stability':'未接入可验证的加工循环事件'},
            'health_diagnostics':{'health_score':None,'health_grade':'未评估','motor_load_avg_pct':None,
                'motor_temp_peak_c':max(temperatures) if temperatures else None,
                'power_consumption_kwh':None,'energy_cost_rmb':None},
            'maintenance_countdown':{'grease_remaining_hours':None,'grease_total_hours':None,
                'battery_remaining_days':None,'battery_total_days':None,'belt_inspection_remaining_hours':None},
            'evaluation_summary':f"{'仿真演示数据，非真机实测。' if source=='simulation' else '真机采集数据。'}本周期记录 {sample_count} 条状态报文。观测覆盖时长 {observed/3600:.4f} 小时。未采集或未经验证的生产、能耗和寿命指标不作推算。"
        }
    finally:
        conn.close()


def alarm_report(device_id, days, db_path):
    from database import get_connection
    today=datetime.now().date()
    dates=[(today-timedelta(days=i)).isoformat() for i in range(days-1,-1,-1)]
    conn=get_connection(db_path)
    try:
        sql="SELECT received_at,raw_payload FROM verified_device_data WHERE data_type='alarm' AND received_at>=? AND received_at<?"
        args=[dates[0]+'T00:00:00',(today+timedelta(days=1)).isoformat()+'T00:00:00']
        if device_id:
            sql+=' AND device_id=?'
            args.append(device_id)
        rows=conn.execute(sql,args).fetchall()
        trend=Counter()
        codes=Counter()
        details={}
        for r in rows:
            p=json.loads(r[1])
            trend[r[0][:10]]+=1
            code=str(p.get('alarm_code','unknown'))
            codes[code]+=1
            details[code]=p
        top=[{'code':code,'title':details[code].get('alarm_msg',''),
              'category':'控制器原始报警','count':count,'avg_downtime_min':None,
              'solution':'暂无经核验的官方处置条目；请按控制器原始报警及现场安全规程处理'}
             for code,count in codes.most_common(5)]
        return {'device_id':device_id,'days':days,'total_alarms':len(rows),'mtbf_hours':None,'mttr_minutes':None,
                'auto_recovery_rate_pct':None,'trend':[{'date':d,'count':trend[d]} for d in dates],
                'categories':[],'top_alarms':top,'source':'verified_controller_events',
                'coverage_note':'仅统计已接收到的控制器报警事件；无记录不代表设备无故障'}
    finally:
        conn.close()
