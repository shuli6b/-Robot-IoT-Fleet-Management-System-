using System;
using System.Collections.Generic;
using System.Threading;
using Hsc3.Comm;
using Hsc3.Proxy;

namespace demo
{
    public class ProxyMotionDemo
    {
        public void TestProxyMotion(string ip)
        {
            CommApi cmApi = new CommApi();
            ProxyMotion proMot = new ProxyMotion(cmApi);

            if (connectIPC(cmApi, ip, 23234))
            {
                ulong conn;
                sbyte gpId = 0;
                bool en = false;

                //获取运动层版本信息
                string Var = string.Empty;
                conn = proMot.GetMotionVer(ref Var);

                //设置操作模式
                OpMode opMode = OpMode.OP_T1;
                conn = proMot.SetOpMode(opMode);

                //获取操作模式
                conn = proMot.GetOpMode(ref opMode);
                

                //设置手动运行增量距离
                double length = 0.1;
                conn = proMot.SetInchLen(length);

                //获取手动运行增量距离
                conn = proMot.GetInchLen(ref length);
                

                //设置自动运行倍率
                int vord = 50;
                conn = proMot.SetVord(vord);

                //获取自动运行倍率
                conn = proMot.GetVord(ref vord);

                //设置手动运行倍率
                vord = 50;
                conn = proMot.SetJogVord(vord);

                //获取手动运行倍率
                conn = proMot.GetJogVord(ref vord);

                //获取是否处于使能状态
                conn = proMot.GetGpEn(gpId, ref en);
                

                //单轴手动运动
                //gpId = 0;
                //sbyte axId = 0;
                //DirectType direc = DirectType.POSITIVE;
                //conn = proMot.StartJog(gpId, axId, direc);

                //停止手动运动
                //conn = proMot.StopJog(gpId);

                
                gpId = 0;
                GeneralPos point = new GeneralPos()
                {
                    isJoint = true,
                    ufNum = -1,
                    utNum = -1,
                    config = 0,
                    vecPos = new List<double>(),
                };
                //运动到点
                //point.vecPos.Add(0);
                //point.vecPos.Add(-90);
                //point.vecPos.Add(180);
                //point.vecPos.Add(0);
                //point.vecPos.Add(90);
                //point.vecPos.Add(0);
                //point.vecPos.Add(0);
                //point.vecPos.Add(0);
                //point.vecPos.Add(0);
                //bool isLinear = false;
                //conn = proMot.MoveTo(gpId, point, isLinear);


                //获取工作坐标系
                FrameType ft = FrameType.FRAME_BASE;
                conn = proMot.GetWorkFrame(0, ref ft);

                //获取内部轴数
                gpId = 0;
                int cnt = 0;
                conn = proMot.GetRobAxisCount(0, ref cnt);

                //获取附加轴数
                gpId = 0;
                cnt = 0;
                conn = proMot.GetAuxAxisCount(0, ref cnt);

                //获取关节坐标点数据
                List<double> test = new List<double>();
                conn = proMot.GetJntData(gpId, ref test);
                

                //获取笛卡尔坐标点数据
                conn = proMot.GetLocData(gpId, ref test);

                //获取形态
                int config = 0;
                conn = proMot.GetConfig(gpId, ref config);

                //获取工具坐标数据
                gpId = 0;
                int index = 0;
                List<double> data = new List<double>();
                conn = proMot.GetTool(gpId, index, ref data);

                //获取工件坐标数据
                var pos = new List<double>();
                conn = proMot.GetWorkpiece(gpId, 0, ref pos);
                

                //获取工具号
                sbyte num = 0;
                conn = proMot.GetToolNum(0, ref num);

                //获取工件号
                num = 0;
                conn = proMot.GetWorkpieceNum(0, ref num);
                
                
            }
            //完成所有操作后，务必断开与控制器的连接
            disconnectIPC(cmApi);
        }

        static bool connectIPC(Hsc3.Comm.CommApi cmApi, string strIP, ushort uPort)
        {
            ulong conn;
            conn = cmApi.Connect(strIP, uPort);
            if (conn != 0)
            {
                Console.WriteLine("CommApi::connect() : ret = " + conn);
            }
            //Thread.Sleep(1000);
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
