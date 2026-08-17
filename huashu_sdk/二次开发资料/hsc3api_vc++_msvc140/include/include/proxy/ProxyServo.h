/**
*   Copyright (C) 2019 华数机器人
*
*   @file       ProxyServo.h
*   @brief      华数III型二次开发接口 - 业务接口 - 伺服参数操作代理
*   @details    提供了III型控制器伺服参数相关业务接口。
*
*   @author     
*   @date       2019/12/17
*   @version    
*   
*/

#pragma once
/**
*   @skip DLL_EXPORT
*/
#if defined( _LINUX_ ) || defined( __MINGW32__ )
#define DLL_EXPORT __attribute__((visibility("default")))
#else
#define DLL_EXPORT __declspec(dllexport)
#endif

#include "Hsc3Def.h"
#include "CommDef.h"

namespace Hsc3 {

    namespace Comm {
        class CommApi;
    }

    namespace Proxy {

        /**
        *   @class      ProxyServo
        *   @brief      业务接口 - 伺服参数操作代理
        *   @details    提供接口包含：伺服参数操作接口。
        *   @date       2020/12/17
        */
        class DLL_EXPORT ProxyServo
        {
        public:
            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   pNet    通信客户端
             */
            ProxyServo(Hsc3::Comm::CommApi * pNet);

            ~ProxyServo();

            /**
             * @brief   获取指定轴对应伺服的伺服参数名字列表
             * @param   gpId    类型：int8_t； 含义：组号（0..n-1）
             * @param   axIndex 类型：int8_t； 含义：组内轴索引（0..n-1）
             * @param[out]  nameList 名字列表，升序排序
             */
            Hsc3::Comm::HMCErrCode getServoParaNameList(int8_t gpId, int8_t axIndex, std::vector<std::string> & nameList);

            /**
             * @brief   获取指定轴对应伺服、指定伺服参数的格式化信息
             * @param   gpId； 类型：int8_t； 含义：组号（0..n-1）
             * @param   axIndex； 类型：String； 含义：组内轴索引（0..n-1）
             * @param   paraName； 类型：String； 含义：参数名字
             * @param[out]     paraInfo 信息（格式：例“name="P005",chName="参数",unitName="mm",minValue=1.0,maxValue=1000.0”，其中“name”是参数英文名，“chName”是参数中文名，“unitName”是单位名，“minValue”是最小值，“maxValue”是最大值）
             */
            Hsc3::Comm::HMCErrCode getServoParaInfoFormat(int8_t gpId, int8_t axIndex, std::string paraName, ServoParaInfo & paraInfo);

            /**
             * @brief   读指定轴对应伺服的各参数
             * @param   gpId； 类型：int8_t； 含义：组号（0..n-1）
             * @param   axIndex； 类型：int8_t； 含义：组内轴索引（0..n-1）
             * @param[out]  valueList   值数列，对应参数按名字升序排序
             */
            Hsc3::Comm::HMCErrCode readServoPara(int8_t gpId, int8_t axIndex, std::vector<double> & valueList);

            /**
             * @brief   读指定轴对应伺服的指定伺服参数
             * @param   gpId； 类型：int8_t； 含义：组号（0..n-1）
             * @param   axIndex； 类型：String； 含义：组内轴索引（0..n-1）
             * @param   paraName； 类型：String； 含义：参数名字
             * @param[out]  value   值； 类型：double
             */
            Hsc3::Comm::HMCErrCode readServoPara(int8_t gpId, int8_t axIndex, std::string paraName, double & value);

            /**
             * @brief   写指定轴对应伺服的指定伺服参数
             * @param   gpId； 类型：int8_t； 含义：组号（0..n-1）
             * @param   axIndex； 类型：String； 含义：组内轴索引（0..n-1）
             * @param   paraName； 类型：String； 含义：参数名字
             * @param   value； 值； 类型：double
             */
            Hsc3::Comm::HMCErrCode writeServoPara(int8_t gpId, int8_t axIndex, std::string paraName, double value);


        private:
            Hsc3::Comm::CommApi * m_pNet;
        };
    }

}
