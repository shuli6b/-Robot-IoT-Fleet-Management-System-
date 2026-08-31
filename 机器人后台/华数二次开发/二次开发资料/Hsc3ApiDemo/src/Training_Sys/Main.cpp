/************************************************************************/
/* 
* @brief 演示获取系统报警
*/
/************************************************************************/
#pragma once

#include <iostream>
#include <Windows.h>
#include "process.h"
#include "CommApi.h"
#include "proxy/ProxyMotion.h"
#include "proxy/ProxySys.h"
//////////////////////////////////////////////////////////////////////////
#define IP "10.10.56.214"

/////////////////////////////////函数声明/////////////////////////////////////////
unsigned int WINAPI messageThread(void *pParam);

bool connectIPC(Hsc3::Comm::CommApi & cmApi, std::string strIP, uint16_t uPort);
bool disconnectIPC(Hsc3::Comm::CommApi & cmApi);
void waitDone(Hsc3::Proxy::ProxyMotion & pMot);
void loadPosData(GeneralPos & generalPos,double axis0, double axis1, double axis2, double axis3, double axis4, double axis5,bool isJoint);
//////////////////////////////////变量声明////////////////////////////////////////
std::string Cmd;

//////////////////////////////////////////////////////////////////////////

int main()
{
    HANDLE hthread;
    unsigned int threadId;
    DWORD dw;
    Hsc3::Comm::CommApi cmApi("");
    Hsc3::Proxy::ProxyMotion pMot(&cmApi);
    GeneralPos targetPos1,targetPod2;

    loadPosData(targetPos1,0,90,-180,0,90,0,true);
    loadPosData(targetPod2,90,90,-180,0,90,0,true);

    if (connectIPC(cmApi,IP,23234))
    {
        //创建子线程来处理系统报警
        hthread=(HANDLE)_beginthreadex(NULL, NULL, messageThread, NULL, 0, &threadId);
        if(hthread==0)
        {
            std::cout<<"fail to creat a thread"<<std::endl;
        }
        pMot.setGpEn(0,true);
        Sleep(2000);
        while(Cmd != "quit" || Cmd != "stop")
        {
            /*pMot.moveTo(0,targetPos1,false);
            waitDone(pMot);
            Sleep(1000);
            pMot.moveTo(0,targetPod2,false);
            waitDone(pMot);
            Sleep(1000);
            std::cout<<"是否继续"<<std::endl;
            std::cin>>Cmd;*/
            Sleep(2000);
        }
        dw = WaitForSingleObject(hthread,INFINITE);
        switch(dw)
        {
        case WAIT_OBJECT_0:
            std::cout<<"线程结束\n";
            break;
        case WAIT_TIMEOUT:
            std::cout<<"等待时间超时\n";
            break;
        case WAIT_FAILED:
            std::cout<<"函数调用失败\n";
            break;
        }
    }
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
bool connectIPC(Hsc3::Comm::CommApi & cmApi, std::string strIP,uint16_t uPort)
{
    cmApi.setAutoConn(false);
    //连接
    Hsc3::Comm::HMCErrCode ret = cmApi.connect(strIP,uPort);
    if (ret!=0)
    {
        printf("CommApi::connect() : ret = %lld\n",ret);
    }
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
            if (manualState == MAN_STATE_ERROR)
            {
                std::cout<<"错误"<<std::endl;
            }
            break;
        }
    }
}

/************************************************************************/
/* 
* @brief 装载数据
*/
/************************************************************************/
void loadPosData(GeneralPos & generalPos,double axis0, double axis1, double axis2, double axis3, double axis4, double axis5,bool isJoint)
{
    generalPos.config=0x100000;
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
* @brief UTF-8转GBK编码
* @param src_str:待转UTF-8编码字符串
*/
/************************************************************************/
std::string Utf8ToGbk(const char *src_str)
{
    int len = MultiByteToWideChar(CP_UTF8, 0, src_str, -1, NULL, 0);
    wchar_t* wszGBK = new wchar_t[len + 1];
    memset(wszGBK, 0, len * 2 + 2);
    MultiByteToWideChar(CP_UTF8, 0, src_str, -1, wszGBK, len);
    len = WideCharToMultiByte(CP_ACP, 0, wszGBK, -1, NULL, 0, NULL, NULL);
    char* szGBK = new char[len + 1];
    memset(szGBK, 0, len + 1);
    WideCharToMultiByte(CP_ACP, 0, wszGBK, -1, szGBK, len, NULL, NULL);
    std::string strTemp(szGBK);
    if (wszGBK) delete[] wszGBK;
    if (szGBK) delete[] szGBK;
    return strTemp;
}

/************************************************************************/
/* 
* @brief 报警信息线程处理函数，建议创建单独的线程来处理报警信息，防止报警信息得不到及时响应和处理。
*/
/************************************************************************/
unsigned int WINAPI messageThread(void *pParam)
{
    Hsc3::Comm::CommApi tcmApi("");
    Hsc3::Proxy::ProxySys pSys(& tcmApi);
    ErrLevel errLevel;
    uint64_t errCode;
    std::string errMessage;

    if (connectIPC(tcmApi,IP,23234))
    {
        Hsc3::Comm::HMCErrCode ret=1;
        while(Cmd != "stop" || Cmd != "quit")
        {
            ret=pSys.getMessage(errLevel,errCode,errMessage,2000);
            if (ret == 0)
            {
                printf("errCode = %lld\n",errCode);
                switch(errLevel)
                {
                case ERR_LEVEL_INFO:
                    std::cout<<"ERR_LEVEL_INFO";
                    break;
                case ERR_LEVEL_NOTE:
                    std::cout<<"ERR_LEVEL_NOTE";
                    break;
                case ERR_LEVEL_WARNING:
                    std::cout<<"ERR_LEVEL_WARNING";
                    break;
                case ERR_LEVEL_ERROR:
                    std::cout<<"ERR_LEVEL_ERROR";
                    break;
                case ERR_LEVEL_FATAL:
                    std::cout<<"ERR_LEVEL_FATAL";
                    break;
                default:
                    std::cout<<"UNKNOWN_ERR_LEVEL";
                }
                std::cout<<", ErrCode : "<<errCode<<std::endl;
                //通过接口获取到的报警信息是UTF-8编码格式
                std::cout<< Utf8ToGbk(errMessage.c_str()) <<std::endl;
            }
        }
    }
    disconnectIPC(tcmApi);
    return 0;
}
