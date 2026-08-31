using System;
using System.Collections.Generic;
using System.Threading;
using Hsc3.Comm;
using Hsc3.Proxy;
using Newtonsoft.Json;
namespace demo
{
    public class ProxyCollectDemo
    { 
        public void TestProxyCollect(string ip)
        {
            CommApi cmApi = new CommApi();
            ProxyCollect proCollect = new ProxyCollect(cmApi);
            cmApi.SetUseHeartBeat(true);
            cmApi.SetUseUdp(true);
            if (connectIPC(cmApi, ip, 23234))
            {
                ulong conn;

                //添加采集任务
                int tid = 1;
                int iSampleKT = 2;
                string strVarList = "var.axis[0].pfb,var.axis[1].pfb,";
                
                //添加采集任务
                conn = proCollect.AddTask(tid, iSampleKT, strVarList);
                Console.WriteLine($"AddTask ret:{conn}");

                //启动采集任务
                conn = proCollect.Start(tid);
                Console.WriteLine($"Start ret:{conn}");


                //获取存在的采集任务列表
                int SessionId = 0;
                cmApi.GetUdpClient().getUdpSessionId(ref SessionId);
                List<int> listTask = new List<int>();
                conn = proCollect.GetExistTasks(SessionId, ref listTask);
                Console.WriteLine($"exist tasks:{JsonConvert.SerializeObject(listTask)}");
                //获取正在运行的采集任务列表
                listTask = new List<int>();
                conn = proCollect.GetRunningTasks(SessionId, ref listTask);
                Console.WriteLine($"Running tasks:{JsonConvert.SerializeObject(listTask)}");
                //获取控制系统当前时间戳
                int timestamp = 0;
                conn = proCollect.GetCurTimestamp(ref timestamp);
                Console.WriteLine($"CurTimestamp:{timestamp}");
                int count = 0;
                string msg = null;
                while (true)
                {
                    msg = null;
                    conn = cmApi.GetUdpClient().getUdpMsg(UdpDataType.UDP_DATA_TYPE_COLL, ref msg);
                    if (conn != 0)
                        break;
                    if (!string.IsNullOrEmpty(msg))
                        Console.WriteLine(msg);
                    Thread.Sleep(4);
                }

                //停止采集任务
                conn = proCollect.Stop(tid);

                //删除采集任务
                conn = proCollect.DelTask(tid);
            }
            //完成所有操作后，务必断开与控制器的连接
            disconnectIPC(cmApi);
        }

        static bool connectIPC(Hsc3.Comm.CommApi cmApi, string strIP, ushort uPort)
        {
            ulong conn;
            conn = cmApi.Connect(strIP, uPort);
            string backStr = "";
            conn = cmApi.ExecCmd("mot.getRobTypeName(0)", ref backStr, 0);
            if (conn != 0)
            {
                Console.WriteLine("CommApi::connect() : ret = " + conn);
            }
            if (cmApi.IsConnected())
            {
                Console.WriteLine("连接成功");
                return true;
            }
            else
            {
                Console.WriteLine("连接失败");
                return false;
            }
        }

        static bool disconnectIPC(Hsc3.Comm.CommApi cmApi)
        {
            ulong ret = cmApi.Disconnect();
            Thread.Sleep(500);
            if (cmApi.IsConnected())
            {
                return false;
            }
            else
            {
                return true;
            }
        }
    }
}
