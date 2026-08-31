using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;
using System.Threading.Tasks;

namespace HsDemo
{
    class Program
    {
        static void Main(string[] args)
        {
            //demo.ProxyVarDemo proxyVar = new demo.ProxyVarDemo();
            //proxyVar.TestGetRegister("10.4.0.191");
            //demo.ProxyMotionDemo proxyMotionDemo = new demo.ProxyMotionDemo ();
            //proxyMotionDemo.TestProxyMotion("10.4.0.191");
            demo.ProxyCollectDemo proxy1CollectDemo = new demo.ProxyCollectDemo();
            proxy1CollectDemo.TestProxyCollect("10.4.0.191");
        }
    }
}
