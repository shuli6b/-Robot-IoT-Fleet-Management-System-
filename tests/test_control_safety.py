"""Protocol and command-state tests use in-memory sockets and temporary ledgers."""
import json
import os
import queue
import tempfile
import time
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from huashu_protocol import HuashuSocketClient,ControllerError
from huashu_real_bridge import HuashuRobotCollector
from security import sign_payload


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='edge_safety_')
        self.env=patch.dict(os.environ,{'EDGE_STATE_DIR':self.temp.name,'TELEMETRY_HMAC_KEY':'fake-telemetry','COMMAND_HMAC_KEY':'fake-command','ROBOT_CONTROL_ENABLED':'1'})
        self.env.start()
        self.sent=[]
        self.bridge=HuashuRobotCollector({'device_id':'arm_test','ip':'invalid'},SimpleNamespace(publish=lambda *a,**k:self.sent.append((a,k))))
        self.bridge.driver=SimpleNamespace(is_connected=True,connection_id='connection-test',execute=lambda *a,**k:('succeeded','verified',0))
    def tearDown(self):
        self.env.stop();self.temp.cleanup()
    def command(self,**extra):
        p={'task_id':uuid.uuid4().hex,'device_id':'arm_test','device_type':'huashu_arm','command':'enable','params':{},
           'timestamp':datetime.now().astimezone().isoformat(),'expires_at':time.time()+5,'connection_id':'connection-test'}
        p.update(extra)
        return sign_payload(p,'fake-command')
    def states(self):return [json.loads(args[1])['status'] for args,_ in self.sent if args[0].endswith('cmd_ack')]
    def test_receipt_is_not_execution(self):
        self.bridge.offer(self.command())
        self.assertEqual(self.states(),['received'])
        self.bridge.execute_pending()
        self.assertEqual(self.states(),['received','succeeded'])
    def test_duplicates_do_not_execute_twice(self):
        item=self.command();self.bridge.offer(item);self.bridge.offer(item)
        self.assertEqual(self.bridge.cmd_queue.qsize(),1)
    def test_expired_command_not_queued(self):
        self.bridge.offer(self.command(expires_at=time.time()-1))
        self.assertEqual(self.states(),['expired']);self.assertTrue(self.bridge.cmd_queue.empty())
    def test_changed_connection_not_queued(self):
        self.bridge.offer(self.command(connection_id='previous-connection'))
        self.assertEqual(self.states(),['failed']);self.assertTrue(self.bridge.cmd_queue.empty())
    def test_signature_required(self):
        p=self.command();p['params']={'override':100}
        with self.assertRaises(ValueError):self.bridge.offer(p)
    def test_controller_error_reports_failure(self):
        def fail(*a,**k):raise ControllerError('123','enable')
        self.bridge.driver.execute=fail
        self.bridge.offer(self.command());self.bridge.execute_pending()
        self.assertEqual(self.states(),['received','failed'])
        self.assertEqual(json.loads(self.sent[-1][0][1])['code'],'123')
    def test_readback_failure_after_accepted_write_is_unknown(self):
        driver=HuashuSocketClient('invalid')
        driver.sock=object();driver.connection_id='connection-test'
        def send(command):
            if command=='mot.getEstop()':return 'false'
            if command=='mot.setGpEn(0,true)':return 'null'
            raise ControllerError(123,command)
        driver.send_cmd=send
        self.bridge.driver=driver
        self.bridge.offer(self.command());self.bridge.execute_pending()
        self.assertEqual(self.states(),['received','unknown'])

    def test_transport_failure_is_unknown(self):
        def fail(*a,**k):raise ConnectionError()
        self.bridge.driver.execute=fail
        self.bridge.offer(self.command())
        with self.assertRaises(ConnectionError):self.bridge.execute_pending()
        self.assertEqual(self.states(),['received','unknown'])
    def test_stop_cancels_pending_nonstop_commands(self):
        self.bridge.offer(self.command());self.bridge.offer(self.command(command='stop'))
        self.bridge.execute_pending()
        self.assertEqual(self.states()[-2:],['cancelled','succeeded'])
        self.assertTrue(self.bridge.cmd_queue.empty())
    def test_offline_queue_not_executed_after_reconnect(self):
        self.bridge.offer(self.command());self.bridge.driver.connection_id='new-connection'
        self.bridge.execute_pending();self.assertEqual(self.states()[-1],'failed')
    def test_jog_disabled_by_default(self):
        driver=HuashuSocketClient('invalid')
        with self.assertRaises(ValueError):driver.execute('jog_joint',{'axis':1,'direction':1,'step_deg':1,'speed':5})
    def test_discrete_jog_native_direction_and_step(self):
        driver=HuashuSocketClient('invalid');commands=[];position_reads=0
        def send(command):
            nonlocal position_reads
            commands.append(command)
            fixed={'mot.getOpMode()':'1','mot.getGpEn(0)':'true','mot.getEstop()':'false','mot.getWorkFrame(0)':'0',
                   'mot.getManualMode()':'1','mot.getInchLen()':'1.0','mot.getManualStat()':'0'}
            if command=='mot.getJntData(0)':
                position_reads+=1
                return '{0,0,0,0,0,0}' if position_reads==1 else '{1,0,0,0,0,0}'
            return fixed.get(command,'null')
        driver.send_cmd=send
        result=driver.execute('jog_joint',{'axis':1,'direction':1,'step_deg':1,'speed':5},allow_jog=True)
        self.assertEqual(result[0],'succeeded')
        self.assertIn('mot.startJog(0,0,0)',commands)
        self.assertIn('mot.setInchLen(1.0)',commands)
        self.assertEqual(commands[-1],'mot.stopJog(0)')
    def test_large_native_io_group_count_is_bounded_not_discarded(self):
        driver=HuashuSocketClient('invalid')
        def send(command):
            if command in ('io.getMaxDinGrp()','io.getMaxDoutGrp()'):return '16'
            if command.startswith('io.getDinGrp('):return '1'
            if command.startswith('io.getDoutGrp('):return '0'
            raise ControllerError(123,command)
        driver.send_cmd=send
        state,io=driver.telemetry()
        self.assertEqual(io['di_count'],64)
        self.assertEqual(io['di_total_count'],512)
        self.assertEqual(io['di'],1+(1<<32))
        self.assertEqual(io['do'],0)

    def test_read_error_stays_unknown_not_zero(self):
        driver=HuashuSocketClient('invalid')
        def send(command):raise ControllerError(123,command)
        driver.send_cmd=send
        state,io=driver.telemetry()
        self.assertIsNone(state['joint_angles']);self.assertIsNone(state['emergency_stop']);self.assertIsNone(io['do'])
        self.assertEqual(state['status'],'unknown')

if __name__=='__main__':unittest.main()
