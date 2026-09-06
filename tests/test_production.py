"""Regression tests. Every database and socket is isolated from production."""
import io
import json
import logging
import os
import socket
import sqlite3
import sys
import tempfile
import time
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from contextlib import closing
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

ROOT=Path(__file__).resolve().parents[1]
TEMP=tempfile.TemporaryDirectory(prefix='robot_regression_')
os.environ['DB_PATH']=str(Path(TEMP.name)/'test.db')
os.environ['ROBOT_ALLOWED_DEVICES']='huashu_arm/arm_test'
os.environ['TELEMETRY_HMAC_KEY']='test-telemetry-key'
os.environ['COMMAND_HMAC_KEY']='test-command-key'
os.environ['EDGE_STATE_DIR']=str(Path(TEMP.name)/'edge')
os.environ['ROBOT_CONTROL_ENABLED']='1'
sys.path.insert(0,str(ROOT))
with patch('logging.FileHandler',return_value=logging.NullHandler()),patch('logging.handlers.RotatingFileHandler',return_value=logging.NullHandler()):
    import database as db
    import main
from fastapi.testclient import TestClient
from security import sign_payload,verify_payload,create_session,password_hash,verify_password
from huashu_protocol import HuashuSocketClient,ControllerError,array_value,bool_value
from robot_commands import validate_command
from backup_service import database_snapshot,controller_backup


class FakeSocket:
    def __init__(self,chunks):self.chunks=list(chunks);self.sent=[]
    def sendall(self,value):self.sent.append(value)
    def recv(self,size):return self.chunks.pop(0) if self.chunks else b''
    def settimeout(self,value):pass
    def close(self):pass


class ProductionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert db.init_db()
        with closing(db.get_connection()) as conn, conn:
            conn.execute("INSERT INTO users(username,password_hash,role,status) VALUES(?,?,?,?)",('admin',password_hash('test-admin-password'),'admin','approved'))
            conn.execute("INSERT INTO users(username,password_hash,role,status) VALUES(?,?,?,?)",('reader',password_hash('test-reader-password'),'user','approved'))
        conn.close()
        cls.admin={'Authorization':'Bearer '+create_session('admin',db.DB_PATH)}
        cls.reader={'Authorization':'Bearer '+create_session('reader',db.DB_PATH)}
        cls.client=TestClient(main.app,raise_server_exceptions=False)
        logging.disable(logging.CRITICAL)

    def setUp(self):
        conn=db.get_connection()
        with conn:
            for table in ('device_data','devices','message_receipts','command_requests','device_run_logs','robot_programs'):
                conn.execute('DELETE FROM '+table)
        conn.close()
        main.LAST_SEEN_STATES.clear()
        main.is_mqtt_connected=False
        main.mqtt_client_instance=None
        db.upsert_device('arm_test','huashu_arm',status='offline')

    def message(self,kind='state',**overrides):
        p={'device_id':'arm_test','device_type':'huashu_arm','source':'controller','message_id':uuid.uuid4().hex,
           'timestamp':datetime.now().astimezone().isoformat(),'status':'ready','enabled':False,'emergency_stop':False,
           'joint_angles':[0,1,2,3,4,5],'error_count':0,'connection_id':'connection-test'}
        p.update(overrides)
        return sign_payload(p,os.environ['TELEMETRY_HMAC_KEY'])

    def ingest(self,p,kind='state'):
        main.on_mqtt_message(None,None,SimpleNamespace(topic='robot/huashu_arm/arm_test/'+kind,payload=json.dumps(p).encode()))

    def test_no_seed_records(self):
        with closing(db.get_connection()) as conn, conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM robot_programs').fetchone()[0],0)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM alarm_knowledge_base WHERE verified=1').fetchone()[0],54)

    def test_uncommissioned_remote_control_is_locked(self):
        with patch.dict(os.environ,{'ROBOT_CONTROL_ENABLED':'0'}):
            r=self.client.post('/api/device/arm_test/cmd',headers=self.admin,json={'command':'enable','confirmed':True})
            self.assertEqual(r.status_code,409)
            self.assertIsNone(main.mqtt_client_instance)

    def test_old_resolution_claims_excluded(self):
        with closing(db.get_connection()) as conn, conn:
            conn.execute("INSERT INTO alarm_resolutions(device_id,device_type,alarm_code,alarm_msg,solution,handler) VALUES('arm_test','huashu_arm','ACK_ALL','old','unverified','Normal')")
        self.assertEqual(db.get_alarm_resolutions('arm_test'),[])

    def test_official_sdk_catalog_search_and_duplicate(self):
        for term in ('0x810001','8454145','KM_ERR_TIME_OUT','发送消息成功'):
            result=db.get_alarm_knowledge_base(term)
            self.assertTrue(any(r['code']=='0x00810001' for r in result),term)
        duplicate=db.get_alarm_knowledge_base('0x810311')[0]
        self.assertEqual(len(duplicate['symbols']),2)
        self.assertTrue(duplicate['duplicate_definition'])
        self.assertTrue(duplicate['reference'].startswith('official-sdk:'))
        self.assertIn('32位',duplicate['scope'])
        self.assertEqual(db.get_alarm_knowledge_base('0x4040048000501a'),[])

    def test_total_online_rate_includes_configured_simulation(self):
        from simulation import configure_device
        configure_device({'device_id':'sim_test','device_type':'huashu_arm'})
        self.ingest(self.message())
        with patch.dict(os.environ,{'SIMULATION_HMAC_KEY':'sim-key'}):
            p=self.message(device_id='sim_test',source='simulation');p.pop('signature');p=sign_payload(p,'sim-key')
            main.on_mqtt_message(None,None,SimpleNamespace(topic='simulation/robot/huashu_arm/sim_test/state',payload=json.dumps(p).encode()))
        result=db.get_system_stats()
        self.assertEqual((result['total_devices'],result['online_devices'],result['online_rate_pct']),(2,2,100))
        self.assertEqual(db.get_global_history_count(),2)
        self.assertEqual({r['source'] for r in db.get_global_history()},{'controller','simulation'})

    def test_real_stream_only_replaces_cancelled_simulation_after_registration(self):
        from simulation import configure_device
        configure_device({'device_id':'handoff','device_type':'huashu_arm'})
        with patch.dict(os.environ,{'ROBOT_ALLOWED_DEVICES':'huashu_arm/arm_test,huashu_arm/handoff'}):
            packet=self.message(device_id='handoff')
            msg=SimpleNamespace(topic='robot/huashu_arm/handoff/state',payload=json.dumps(packet).encode())
            main.on_mqtt_message(None,None,msg)
            self.assertTrue(db.get_device_by_id('handoff')['is_simulated'])
            configure_device({'device_id':'handoff','device_type':'huashu_arm'},enabled=False)
            main.on_mqtt_message(None,None,msg)
            self.assertFalse(db.get_device_by_id('handoff')['is_simulated'])
            self.assertEqual(db.get_latest_data('huashu_arm','handoff')['source'],'controller')

    def test_header_forgery_rejected(self):
        r=self.client.get('/api/auth/users',headers={'X-User-Role':'admin','X-User-Name':'admin'})
        self.assertEqual(r.status_code,401)

    def test_real_admin_accepted(self):
        self.assertEqual(self.client.get('/api/auth/users',headers=self.admin).status_code,200)

    def test_reader_cannot_control(self):
        r=self.client.post('/api/device/arm_test/cmd',headers=self.reader,json={'command':'enable','confirmed':True})
        self.assertEqual(r.status_code,403)

    def test_self_registration_cannot_elevate(self):
        r=self.client.post('/api/auth/register',json={'username':'admin_'+uuid.uuid4().hex[:8],'password':'test-long-password','role':'admin'})
        self.assertEqual(r.status_code,200)
        user=db.get_user_by_username(r.json()['data']['username'])
        self.assertEqual((user['role'],user['status']),('user','pending'))

    def test_private_endpoints_require_login(self):
        for path,body in [('/api/admin/simulated_devices',{'device_id':'x'}),('/api/admin/ftp_config',{'device_id':'x'}),('/api/ai/test',{}),('/api/devices/huashu_arm/arm_test/programs',{'prog_name':'A.PRG','prog_content':'test'})]:
            with self.subTest(path=path):self.assertEqual(self.client.post(path,json=body).status_code,401)

    def test_simulation_signed_and_separate(self):
        from simulation import configure_device
        configure_device({'device_id':'sim_test','device_type':'huashu_arm'})
        with patch.dict(os.environ,{'SIMULATION_HMAC_KEY':'simulation-key'}):
            p=self.message(device_id='sim_test',source='simulation',status='running')
            p.pop('signature')
            p=sign_payload(p,'simulation-key')
            main.on_mqtt_message(None,None,SimpleNamespace(topic='simulation/robot/huashu_arm/sim_test/state',payload=json.dumps(p).encode()))
        self.assertEqual(db.get_latest_data('huashu_arm','sim_test')['parsed_payload']['source'],'simulation')
        self.assertEqual(db.get_system_stats()['total_devices'],2)
        self.assertEqual(db.get_system_stats()['real_devices'],1)
        self.assertEqual(db.get_system_stats()['simulated_devices'],1)
        self.assertEqual(db.get_device_report_data('sim_test','monthly')['source'],'simulation')

    def test_simulator_cannot_publish_as_real_device(self):
        with patch.dict(os.environ,{'SIMULATION_HMAC_KEY':'simulation-key'}):
            p=self.message(source='simulation');p.pop('signature');p=sign_payload(p,'simulation-key')
            main.on_mqtt_message(None,None,SimpleNamespace(topic='simulation/robot/huashu_arm/arm_test/state',payload=json.dumps(p).encode()))
        self.assertIsNone(db.get_latest_data('huashu_arm','arm_test'))

    def test_simulation_disable_does_not_convert_to_real(self):
        from simulation import configure_device
        configure_device({'device_id':'sim_test','device_type':'huashu_arm'})
        configure_device({'device_id':'sim_test','device_type':'huashu_arm'},enabled=False)
        row=db.get_device_by_id('sim_test')
        self.assertEqual(row['is_simulated'],1)
        self.assertEqual(row['simulation_enabled'],0)
        self.assertNotIn('sim_test',[d['device_id'] for d in db.get_all_devices()])
        with self.assertRaises(ValueError):configure_device({'device_id':'arm_test','device_type':'huashu_arm'})

    def test_simulation_control_routes_only_to_demo_namespace(self):
        from simulation import configure_device
        configure_device({'device_id':'sim_test','device_type':'huashu_arm'})
        sent=[]
        info=SimpleNamespace(rc=0,wait_for_publish=lambda timeout:None,is_published=lambda:True)
        main.mqtt_client_instance=SimpleNamespace(publish=lambda topic,payload,**kw:(sent.append((topic,payload)) or info))
        main.is_mqtt_connected=True
        with patch.dict(os.environ,{'SIMULATION_HMAC_KEY':'simulation-key','SIMULATION_COMMAND_KEY':'simulation-command','ROBOT_CONTROL_ENABLED':'0'}):
            p=self.message(device_id='sim_test',source='simulation',status='running');p.pop('signature');p=sign_payload(p,'simulation-key')
            main.on_mqtt_message(None,None,SimpleNamespace(topic='simulation/robot/huashu_arm/sim_test/state',payload=json.dumps(p).encode()))
            result=self.client.post('/api/device/sim_test/cmd',headers=self.admin,json={'command':'pause','params':{},'confirmed':True})
        self.assertEqual(result.status_code,202)
        self.assertEqual(sent[0][0],'simulation/cmd/huashu_arm/sim_test')

    def test_signature_required(self):
        p=self.message();p.pop('signature');self.ingest(p)
        self.assertIsNone(db.get_latest_data('huashu_arm','arm_test'))

    def test_replay_is_ignored(self):
        p=self.message();self.ingest(p);self.ingest(p)
        with closing(db.get_connection()) as conn, conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM device_data').fetchone()[0],1)

    def test_old_message_ignored(self):
        self.ingest(self.message(timestamp=(datetime.now()-timedelta(minutes=1)).isoformat()))
        self.assertIsNone(db.get_latest_data('huashu_arm','arm_test'))

    def test_valid_zero_preserved(self):
        self.ingest(self.message(cartesian_pos={'x':0,'y':0,'z':0}))
        d=db.get_all_devices()[0]
        self.assertEqual(d['cartesian_x'],0)
        self.assertFalse(d['enabled'])

    def test_missing_does_not_become_normal(self):
        self.ingest(self.message(enabled=None,emergency_stop=None,error_count=None,status='unknown'))
        p=db.get_latest_data('huashu_arm','arm_test')['parsed_payload']
        self.assertIsNone(p['enabled']);self.assertIsNone(p['emergency_stop'])

    def test_simulated_inventory_separate_from_real_statistics(self):
        db.upsert_device('sim_001','huashu_arm');db.set_device_simulated('sim_001',True)
        self.assertEqual([d['device_id'] for d in db.get_all_devices()],['arm_test','sim_001'])
        self.assertEqual([d['device_id'] for d in db.get_all_devices(include_simulated=False)],['arm_test'])
        self.assertEqual(db.get_system_stats()['total_devices'],2)
        self.assertEqual(db.get_system_stats()['real_devices'],1)

    def test_cmd_does_not_mark_online(self):
        db.insert_device_data('arm_test','huashu_arm','cmd',json.dumps({'command':'enable'}),'cmd/test')
        self.assertEqual(db.get_device_by_id('arm_test')['status'],'offline')

    def test_offline_command_rejected(self):
        r=self.client.post('/api/device/arm_test/cmd',headers=self.admin,json={'command':'enable','confirmed':True})
        self.assertEqual(r.status_code,409)
        self.assertEqual(db.get_device_by_id('arm_test')['status'],'offline')

    def test_disconnected_broker_rejected(self):
        self.ingest(self.message())
        r=self.client.post('/api/device/arm_test/cmd',headers=self.admin,json={'command':'enable','confirmed':True})
        self.assertEqual(r.status_code,503)

    def test_connection_observation_log_does_not_require_motion(self):
        self.ingest(self.message(enabled=False))
        logs=db.get_device_logs('arm_test')
        self.assertEqual(len(logs),1)
        self.assertEqual(logs[0]['source'],'platform_audit')
        self.assertIn('平台开始接收',logs[0]['record_content'])
        self.ingest(self.message(enabled=False))
        self.assertEqual(len(db.get_device_logs('arm_test')),1)

    def test_logs_read_is_read_only(self):
        self.assertEqual(db.get_device_logs('arm_test'),[])
        with closing(db.get_connection()) as conn, conn:self.assertEqual(conn.execute('SELECT COUNT(*) FROM device_run_logs').fetchone()[0],0)

    def test_alarm_ack_does_not_claim_reset(self):
        result=db.confirm_all_alarms_log('arm_test','admin')
        self.assertEqual(result['cleared_alarms'],0)
        self.assertIn('未改变',result['message'])

    def test_legacy_logs_excluded(self):
        with closing(db.get_connection()) as conn, conn:conn.execute("INSERT INTO device_run_logs(device_id,seq_no,log_time,record_content) VALUES('arm_test',4993,'2000-01-01','fake')")
        self.assertEqual(db.get_device_logs('arm_test'),[])

    def test_program_scope(self):
        db.save_robot_program('arm_test','huashu_arm','A.PRG','real draft')
        self.assertIsNone(db.get_robot_program_by_name('other','A.PRG'))
        self.assertEqual(db.get_robot_programs('other'),[])
        self.assertEqual(db.get_robot_programs('arm_test')[0]['source'],'platform_draft')

    def test_missing_program_is_404(self):
        self.assertEqual(self.client.get('/api/devices/huashu_arm/arm_test/programs/MISSING.PRG/download',headers=self.admin).status_code,404)

    def test_unknown_metrics_are_null(self):
        r=db.get_device_report_data('arm_test')
        self.assertIsNone(r['controller_version']);self.assertIsNone(r['health_diagnostics']['health_score'])
        a=db.get_alarm_analytics_stats('arm_test')
        self.assertIsNone(a['mtbf_hours']);self.assertIsNone(a['mttr_minutes'])

    def test_daily_date_is_bounded(self):
        self.ingest(self.message())
        r=db.get_device_report_data('arm_test',date_str='2000-01-01')
        self.assertEqual(r['state_samples'],0)
        self.assertEqual(r['operating_hours']['total_hours'],0)

    def test_month_uses_requested_date(self):
        r=db.get_device_report_data('arm_test','monthly','2000-02-15')
        self.assertEqual(r['period_label'],'2000-02')

    def test_repeated_error_states_not_alarm_events(self):
        self.ingest(self.message(error_count=1,status='error'));self.ingest(self.message(error_count=1,status='error'))
        self.assertEqual(db.get_alarm_analytics_stats('arm_test')['total_alarms'],0)

    def test_alarm_severity_and_native_time(self):
        self.ingest(self.message(alarm_code='123',alarm_msg='warning',alarm_level=3,controller_timestamp='2000-01-01T00:00:00'),'alarm')
        row=db.get_device_logs('arm_test')[0]
        self.assertEqual(row['log_level'],'WARN');self.assertIn('2000-01-01',row['record_content'])

    def test_ack_cannot_override_state(self):
        self.ingest(self.message())
        self.ingest(self.message(status='succeeded',task_id='unknown',command='enable'),'cmd_ack')
        self.assertEqual(db.get_latest_data('huashu_arm','arm_test')['parsed_payload']['status'],'ready')

    def test_stale_fields_not_merged(self):
        self.ingest(self.message(temperature=99),'sensor')
        with closing(db.get_connection()) as conn, conn:conn.execute("UPDATE device_data SET received_at='2000-01-01T00:00:00'")
        self.ingest(self.message())
        self.assertNotIn('temperature',db.get_latest_data('huashu_arm','arm_test')['parsed_payload'])

    def test_unavailable_io_is_not_reported_as_zero(self):
        self.ingest(self.message())
        self.ingest(self.message(di=None,do=None,di_count=0,do_count=0),'io')
        result=db.get_device_io('arm_test')
        self.assertEqual(result['source'],'no_data')
        self.assertIsNone(result['di_mask'])
        self.assertEqual(result['do'],[])

    def test_old_io_not_real(self):
        self.ingest(self.message(di=1,do=0,di_count=32,do_count=32),'io')
        with closing(db.get_connection()) as conn, conn:conn.execute("UPDATE device_data SET received_at='2000-01-01T00:00:00'")
        self.ingest(self.message())
        self.assertEqual(db.get_device_io('arm_test')['source'],'no_data')

    def test_natural_language(self):
        for text,command,value in [('去使能','disable',None),('下使能','disable',None),('速度设为10','set_override',10)]:
            r=self.client.post('/api/ai/parse_command',headers=self.admin,json={'natural_language':text,'device_type':'huashu_arm'})
            self.assertEqual(r.status_code,200);self.assertEqual(r.json()['data']['command'],command)
            if value is not None:self.assertEqual(r.json()['data']['params']['override'],value)
        for text in ('你好','暂停','不要启动'):
            self.assertEqual(self.client.post('/api/ai/parse_command',headers=self.admin,json={'natural_language':text,'device_type':'huashu_arm'}).status_code,422)

    def test_ai_fallback_handles_nulls(self):
        with patch.object(main,'get_llm_config',return_value={'enabled':False}):
            self.assertEqual(self.client.post('/api/ai/chat',headers=self.reader,json={'query':'status'}).status_code,200)

    def test_stored_key_not_forwarded(self):
        fake=AsyncMock(return_value=(True,'ok',{}))
        with patch.object(main,'get_llm_config',return_value={'api_key':'fake','base_url':'https://api.deepseek.com/v1'}),patch.object(main,'call_llm_api',fake):
            self.assertEqual(self.client.post('/api/ai/test',headers=self.admin,json={'base_url':'https://invalid.example/v1'}).status_code,422)
            fake.assert_not_called()

    def test_config_key_not_returned(self):
        with patch.object(main,'get_llm_config',return_value={'api_key':'secret-test'}):
            data=self.client.get('/api/ai/config',headers=self.admin).json()
            self.assertNotIn('api_key',data['data']['config'])

    def test_cms_script_breakout_escaped(self):
        with patch.object(main,'get_site_config',return_value={'system_title':'</script><script>BAD()</script>'}):
            response=main.render_page_with_site_config(ROOT/'static/index.html')
            self.assertNotIn(b'</script><script>BAD()',response.body)

    def test_protocol_arrays_fragmented(self):
        d=HuashuSocketClient('invalid');d.sock=FakeSocket([b'i:1,e:0,d:{1,2,',b'3,4,5,6,}@hs@'])
        self.assertEqual(array_value(d.send_cmd('mot.getJntData(0)')),[1,2,3,4,5,6])

    def test_protocol_error_not_success(self):
        d=HuashuSocketClient('invalid');d.sock=FakeSocket([b'i:1,e:123,d:null@hs@'])
        with self.assertRaises(ControllerError):d.send_cmd('mot.setGpEn(0,true)')

    def test_protocol_alarm_and_response_coalesced(self):
        alarms=[];d=HuashuSocketClient('invalid',alarm_callback=alarms.append)
        d.sock=FakeSocket([b'i:-1,e:0,d:{"errorCode":"1","content":"A,B"}@hs@i:1,e:0,d:true@hs@i:2,e:0,d:false@hs@'])
        self.assertTrue(bool_value(d.send_cmd('first')));self.assertFalse(bool_value(d.send_cmd('second')))
        self.assertEqual(alarms[0]['content'],'A,B')

    def test_wrong_sequence_is_not_used(self):
        d=HuashuSocketClient('invalid');d.sock=FakeSocket([b'i:999,e:0,d:false@hs@i:1,e:0,d:true@hs@'])
        self.assertTrue(bool_value(d.send_cmd('query')))

    def test_unknown_bool_raises(self):
        with self.assertRaises(ValueError):bool_value(None)

    def test_no_raw_or_fake_home(self):
        for command in ('home','mot.setGpEn(0,true)','sys.reset();mot.setEstop(false)'):
            with self.assertRaises(ValueError):validate_command(command,{})

    def test_bad_parameters_rejected(self):
        for params in ({'override':101},{'override':True},{'override':'10'}):
            with self.assertRaises(ValueError):validate_command('set_override',params)

    def test_calibrated_3d_functions_unchanged(self):
        import re,hashlib
        baseline=json.loads((ROOT/'tests/3d_mapping_sha256.json').read_text())
        for file,functions in baseline.items():
            text=(ROOT/file).read_text(encoding='utf-8').replace('\r\n','\n')
            for name,expected in functions.items():
                match=re.search(r'        function '+re.escape(name)+r'\(.*?\n        \}',text,re.S)
                self.assertIsNotNone(match,name)
                self.assertEqual(hashlib.sha256(match.group()[8:].encode()).hexdigest(),expected,file+':'+name)

    def test_static_assets_are_served(self):
        for path in ('/static/secure-ui.js','/static/tailwindcss.js','/static/echarts.min.js','/static/vendor/three.min.js'):
            with self.subTest(path=path):self.assertEqual(self.client.get(path).status_code,200)

    def test_health_probes_database(self):
        self.assertEqual(self.client.get('/api/health').status_code,503)

    def test_consistent_sqlite_backup(self):
        source=Path(TEMP.name)/('source-'+uuid.uuid4().hex+'.db');dest=Path(TEMP.name)/('dest-'+uuid.uuid4().hex+'.db')
        conn=sqlite3.connect(str(source));conn.execute('PRAGMA journal_mode=WAL');conn.execute('CREATE TABLE t(v)');conn.execute('INSERT INTO t VALUES(1)');conn.commit()
        database_snapshot(source,dest)
        other=sqlite3.connect(str(dest));self.assertEqual(other.execute('SELECT COUNT(*) FROM t').fetchone()[0],1);other.close();conn.close()

    def test_empty_ftp_backup_rejected(self):
        ftp=SimpleNamespace(connect=lambda *a,**k:None,login=lambda *a:None,mlsd=lambda remote:[],quit=lambda:None)
        with patch('ftplib.FTP',return_value=ftp):
            with self.assertRaises(ValueError):controller_backup({'host':'invalid','user':'test','password':'test'},'arm_test')

    def test_passwords_are_salted(self):
        a=password_hash('test-password-123');b=password_hash('test-password-123')
        self.assertNotEqual(a,b);self.assertTrue(verify_password('test-password-123',a))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        logging.disable(logging.NOTSET)


if __name__=='__main__':
    unittest.main()
