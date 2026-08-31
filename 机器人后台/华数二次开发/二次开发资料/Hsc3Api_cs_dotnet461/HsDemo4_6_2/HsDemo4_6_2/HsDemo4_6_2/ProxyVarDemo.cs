using System;
using System.Collections.Generic;
using System.Threading;
using Hsc3.Comm;
using Hsc3.Proxy;
using Newtonsoft.Json;
namespace demo
{
    public class ProxyVarDemo
    {
	
		private  CommApi cmApi = new CommApi();
        public void TestGetRegister(string ip)
        {

            if (!cmApi.IsConnected())
                connectIPC(cmApi, ip, 23234);

            if (cmApi.IsConnected())
            {
                ProxyVar proVar = new ProxyVar(cmApi);
                double retr = 0;

                //R寄存器
                var returnVal = proVar.SetR(100, 5);
                Console.WriteLine($"ret:{returnVal} set R[100]:{5}");

                returnVal = proVar.GetR(100, ref retr);
                Console.WriteLine($"ret:{returnVal} get R[100]:{retr}");

                //JR寄存器
                List<double> Jrlist2 = new List<double>();
                returnVal=proVar.GetJR(0,5,  ref Jrlist2);
                Console.WriteLine($"ret:{returnVal} get JR[5]:{JsonConvert.SerializeObject(Jrlist2)}");

                returnVal = proVar.SetJR(0, 5, Jrlist2);
                Console.WriteLine($"ret:{returnVal} set JR[5]:{JsonConvert.SerializeObject(Jrlist2)}");
                //LR寄存器
                LocPos locPos = new LocPos();
                locPos.config = 0;
                locPos.ufNum = -1;
                locPos.utNum = -1;
                locPos.vecPos.Add(100);
                locPos.vecPos.Add(101);
                locPos.vecPos.Add(102);
                locPos.vecPos.Add(103);
                locPos.vecPos.Add(104);
                locPos.vecPos.Add(105);
                returnVal = proVar.SetLR(0, 5, locPos);
                Console.WriteLine($"ret:{returnVal} set LR[5]:{JsonConvert.SerializeObject(locPos)}");

                LocPos locPos2 = new LocPos();
                returnVal = proVar.GetLR(0,5,ref locPos2);
                Console.WriteLine($"ret:{returnVal} set LR[5]:{JsonConvert.SerializeObject(locPos)}");
            }

            disconnectIPC(cmApi);
        }

         bool connectIPC(Hsc3.Comm.CommApi cmApi, string strIP, ushort uPort)
        {
            ulong conn;
            conn = cmApi.Connect(strIP, uPort);
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

         bool disconnectIPC(Hsc3.Comm.CommApi cmApi)
        {
            ulong ret = cmApi.Disconnect();
            Thread.Sleep(500);
            if (cmApi.IsConnected())
            {
                Console.WriteLine("断开失败");
                return false;
            }
            else
            {
                Console.WriteLine("断开成功");
                return true;
            }
        }
    }
}
