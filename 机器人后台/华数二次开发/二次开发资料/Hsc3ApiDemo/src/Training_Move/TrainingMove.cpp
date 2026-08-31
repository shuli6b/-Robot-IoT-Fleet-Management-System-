/************************************************************************/
/* 
* @brief 演示运动到制定位置
*/
/************************************************************************/
#pragma once

#include <iostream>
#include <Windows.h>
#include "process.h"
#include "CommApi.h"
#include "proxy/ProxyMotion.h"

bool connectIPC(Hsc3::Comm::CommApi & cmApi, std::string strIP, uint16_t uPort);
bool disconnectIPC(Hsc3::Comm::CommApi & cmApi);
void loadPosData(GeneralPos & generalPos,double axis0, double axis1, double axis2, double axis3, double axis4, double axis5,bool isJoint);
void waitDone(Hsc3::Proxy::ProxyMotion & pMot);

int main()
{
    GeneralPos targetPos1,targetPos2;
    Hsc3::Comm::CommApi cmApi("");
    Hsc3::Proxy::ProxyMotion pMot(&cmApi);
    
    /************************************************************************/
    /* 
    *  {0,-90,180,0,90,0}{27.6,-77.8,197.0,-8.0,73.7,62}
    *  {376.5,0.0,331.0,130.0,-120.0,30.0}{376.5,0.0,331.0,-50.0,-60.0,-150.0}
    */
    /************************************************************************/
    loadPosData(targetPos1,27.6,-77.8,197.0,-8.0,73.7,62,true);
    /*loadPosData(targetPos2,376.5,0.0,331.0,-50.0,-60.0,-150.0,false);*/

    if (connectIPC(cmApi,"10.10.56.214",23234))
    {
        pMot.setOpMode(OP_T1);
        /*pMot.setManualMode(MANUAL_INCREMENT);*/
        pMot.setWorkFrame(0,FRAME_JOINT);
        pMot.setGpEn(0,true);
        Sleep(1000);
        pMot.moveTo(0,targetPos1,false);
        waitDone(pMot);
        Sleep(1000);
        /*pMot.moveTo(0,targetPos2,false);
        waitDone(pMot);
        Sleep(1000);*/
    }
    else
    {
        std::cout<<"连接失败"<<std::endl;
    }
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
bool connectIPC(Hsc3::Comm::CommApi & cmApi, std::string strIP,uint16_t uPort)
{
    //1.设置非自动重连模式,连接前调用。
    cmApi.setAutoConn(false);
    //2.连接
    Hsc3::Comm::HMCErrCode ret = cmApi.connect(strIP,uPort);
    if (ret!=0)
    {
        printf("CommApi::connect() : ret = %lld\n",ret);
    }
    //3.查询是否连接
    if (cmApi.isConnected())
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
* @brief 装载数据
*/
/************************************************************************/
void loadPosData(GeneralPos & generalPos,double axis0, double axis1, double axis2, double axis3, double axis4, double axis5,bool isJoint)
{
    generalPos.config=1048576;
    generalPos.isJoint=isJoint;
    generalPos.ufNum=-1;
    generalPos.utNum=-1;
    generalPos.vecPos.push_back(axis0);
    generalPos.vecPos.push_back(axis1);
    generalPos.vecPos.push_back(axis2);
    generalPos.vecPos.push_back(axis3);
    generalPos.vecPos.push_back(axis4);
    generalPos.vecPos.push_back(axis5);
    generalPos.vecPos.push_back(0);
    generalPos.vecPos.push_back(0);
    generalPos.vecPos.push_back(0);
}

/************************************************************************/
/* 
* @brief 等待运动停止，只能用于手动模式下运动到点，用于检测是否处于静止或错误状态
* @param pMot:运动功能代理
*/
/************************************************************************/
void waitDone(Hsc3::Proxy::ProxyMotion & pMot)
{
    ManState manualState=MAN_STATE_MAX;
    //此延时是为了防止机器人还未进入运动状态
    Sleep(1000);
    while(1)
    {
        pMot.getManualStat(manualState);
        if (manualState == MAN_STATE_WAIT || manualState == MAN_STATE_ERROR)
        {
            if (manualState == MAN_STATE_ERROR)
            {
                std::cout<<"错误"<<std::endl;
            }
            break;
        }
    }
}