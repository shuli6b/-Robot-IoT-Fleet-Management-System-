/************************************************************************/
/* 
* @brief 演示控制机器人单轴点动。
*/
/************************************************************************/
#pragma once
#include <iostream>
#include <Windows.h>
#include "CommApi.h"
#include "proxy/ProxyMotion.h"

bool connectIPC(Hsc3::Comm::CommApi &cmApi,std::string strIP,uint16_t uPort);
bool disconnectIPC(Hsc3::Comm::CommApi & cmApi);
void axisJog(Hsc3::Proxy::ProxyMotion & pMot, int8_t axis,DirectType direct);
bool setEn(Hsc3::Proxy::ProxyMotion & pMot, bool en);
void waitDone(Hsc3::Proxy::ProxyMotion & pMot);

int main()
{
    Hsc3::Comm::CommApi cmApi("");
    Hsc3::Proxy::ProxyMotion pMot(&cmApi);

    if (connectIPC(cmApi,"10.10.56.214",23234))
    {
        //设置手动模式
        pMot.setOpMode(OP_T1);
        //设置手动增量模式
        pMot.setManualMode(MANUAL_CONTINUE);
        //设置坐标系
        pMot.setWorkFrame(0,FRAME_JOINT);
        if (setEn(pMot,true))
        {
            while(1)
            {
                std::string strCmd;
                std::cout<<"请输入命令"<<std::endl;
                std::cin>>strCmd;
                if (strCmd=="quit")
                {
                    break;
                }
                else
                {
                    for(int8_t axis=0;axis<6;axis++)
                    {
                        axisJog(pMot,axis,POSITIVE);
                        Sleep(1000);
                        axisJog(pMot,axis,NEGATIVE);
                        Sleep(1000);
                    }
                }
            }
        }
        else
        {
            std::cout<<"使能失败"<<std::endl;
        }
    }
    setEn(pMot,false);
    disconnectIPC(cmApi);
    system("pause");
    return 0;
}

/************************************************************************/
/*            
* @brief 连接IPC
* @param cmApi:通信客户端对象，建议在自定义的函数中如果需要传递客户端对象，都使用引用传递。
* @param strIP:IP，控制器默认IP是"10.10.56.214"
* @param uPort:端口号,固定端口号:23234
*/
/************************************************************************/
bool connectIPC(Hsc3::Comm::CommApi &cmApi,std::string strIP,uint16_t uPort)
{
    //1.设置非自动重连模式,连接前调用。
    cmApi.setAutoConn(false);
    //2.连接
    Hsc3::Comm::HMCErrCode ret=cmApi.connect(strIP,uPort);
    if (ret!=0)
    {
        printf("CommApi::connect :ret=%lld\n",ret);
    }
    //3.查询是否连接
    if(cmApi.isConnected())
    {
        std::cout<<"连接成功"<<std::endl;
        return true;
    }
    else
    {
        std::cout<<"连接失败"<<std::endl;
        return false;
    }
}

/************************************************************************/
/* 
* @brief 断开与IPC的连接
* @param cmApi:通信客户端对象
*/
/************************************************************************/
bool disconnectIPC(Hsc3::Comm::CommApi & cmApi)
{
    Hsc3::Comm::HMCErrCode ret=cmApi.disconnect();
    Sleep(500);
    if (cmApi.isConnected())
    {
        return false;
    }
    else
    {
        return true;
    }
}

/************************************************************************/
/* 
* @brief 指定轴向指定方向运动4s,仅限演示用
* @param pMot:运动功能代理对象
* @param axis:指定轴
* @param direct:指定方向
*/
/************************************************************************/
void axisJog(Hsc3::Proxy::ProxyMotion & pMot, int8_t axis,DirectType direct)
{
    //1.单轴正向运动
    pMot.startJog(0,axis,direct);
    Sleep(4000);
    //2.停止运动,startJog()后必须有调用stopJog()，否则机器人将不断运动下去。
    pMot.stopJog(0);
    waitDone(pMot);
    Sleep(4000);
}

/************************************************************************/
/* 
* @brief 等待运动停止，只能用于手动模式下用于检测是否处于静止状态或错误状态。
* @param pMot:运动功能代理
*/
/************************************************************************/
void waitDone(Hsc3::Proxy::ProxyMotion & pMot)
{
    ManState manualState=MAN_STATE_MAX;
    while(1)
    {
        pMot.getManualStat(manualState);
        if (manualState == MAN_STATE_WAIT || manualState == MAN_STATE_ERROR)
        {
            break;
        }
    }
}

/************************************************************************/
/*      
* @brief 设置使能
* @param pMot:运动功能代理
* @param en:使能状态
*/
/************************************************************************/
bool setEn(Hsc3::Proxy::ProxyMotion & pMot, bool en)
{
    bool gpEn=false;
    //先获取使能状态，如果使能状态是要设置的状态，则无需再此设置。
    pMot.getGpEn(0,gpEn);
    if (gpEn == en)
    {
        return true;
    }
    else
    {
        //1.使能
        pMot.setGpEn(0,en);
        Sleep(500);
        pMot.getGpEn(0,gpEn);
        if (gpEn==en)
        {
            return true;
        }
        else
        {
            return false;
        }
    }
}