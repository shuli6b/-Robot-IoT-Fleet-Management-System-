/************************************************************************/
/* 
* @brief 演示如何通过接口与IPC建立通信连接。并获取到系统版本信息，和调用基本的执行命令接口。
*/
/************************************************************************/
#pragma once
#include <iostream>
#include <Windows.h>
#include <vector>
#include "CommApi.h"
#include "proxy/ProxyVar.h"

int main()
{
    //1.构造通讯客户端
    Hsc3::Comm::CommApi cmApi("./log/test");
    //2.设置非自动重连模式，此接口应该在连接前调用。
    cmApi.setAutoConn(false);
    //3.连接，控制器默认连接IP是"10.10.56.214"  - (std::string)。端口号是固定值：23234 -（int）
    Hsc3::Comm::HMCErrCode ret=cmApi.connect("127.0.0.1",23234);
    if (ret!=0)
    {
        printf("CommApi::connect :ret=%lld\n",ret);
    }
    //4.查询是否连接,连接后通过此接口确认连接状态。
    if(cmApi.isConnected())
    {
        std::cout<<"连接成功"<<std::endl;
        std::cout<<"版本信息:"<<cmApi.getVersionStr()<<std::endl;  //获取版本信息。
        while(1)
        {
            std::string strCmd;
            std::cout<<"请输入命令:"<<std::endl;
            std::cin>>strCmd;
            if (strCmd=="quit")
            {
                break;
            }
            else
            {
                std::string strRet;
                //执行命令接口
                //第一个参数:strCmd可用命令和格式可通过业务层接口命令文档查询。
                //第二个参数是命令执行结果，是由一对双引号包裹的字符串。解析此结果时要注意字符串中还有一对双引号。
                //第三个参数命令优先级建议使用命令优先级枚举值。
                cmApi.execCmd(strCmd,strRet,Hsc3::Comm::PRIORITY_HIGH);
                std::cout<<strRet<<std::endl;
            }
        }
    }
    system("pause");
    return 0;
}

