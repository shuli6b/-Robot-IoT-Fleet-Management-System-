/**
*   Copyright (C) 2019 华数机器人
*
*   @file       ProxyAio.h
*   @brief      华数III型二次开发接口 - 业务接口 - 模拟IO操作代理
*   @details    提供了III型控制器模拟IO相关业务接口。
*
*   @author     
*   @date       2019/06/14
*   @version    
*   
*/

#pragma once
/**
*   @skip DLL_EXPORT
*/
#ifdef _LINUX_
#define DLL_EXPORT __attribute__((visibility("default")))
#else
#define DLL_EXPORT _declspec(dllexport) 
#endif

#include "Hsc3Def.h"
#include "CommDef.h"
#include <stdint.h>

namespace Hsc3 {

    namespace Comm {
        class CommApi;
    }

    namespace Proxy {

        /**
        *   @class      ProxyAio
        *   @brief      业务接口 - 模拟IO操作代理
        *   @details    提供接口包含：模拟IO操作接口。
        *   @date       2019/06/14
        */
        class DLL_EXPORT ProxyAio
        {
        public:
            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   pNet    通信客户端
             * @param   strProxyName    代理名字（“ain”或“aout”）
             */
            ProxyAio(Hsc3::Comm::CommApi * pNet, const std::string & strProxyName);

            ~ProxyAio();

            /**
             * @brief  获取IO变量数量
             * @details    注：变量框架支持的最大数量。
             * @param[out]   num     数量
             */
            Hsc3::Comm::HMCErrCode getSize(int32_t & num);

            /**
             * @brief  获取真实IO端口数量
             * @param[out]   num     数量
             */
            Hsc3::Comm::HMCErrCode getRealSize(int32_t & num);

            /**
             * @brief  获取模拟IO端口值
             * @param   portIndex   端口号（0..n-1）
             * @param[out]   value  值
             * @see    setValue
             */
            Hsc3::Comm::HMCErrCode getValue(int32_t portIndex, float & value);

            /**
             * @brief  设置模拟IO端口值
             * @param  portIndex   端口号（0..n-1）
             * @param  value    数量
             * @see    getValue
             */
            Hsc3::Comm::HMCErrCode setValue(int32_t portIndex, float value);

            /**
             * @brief   获取模拟IO端口状态
             * @details 状态为“虚拟”时，通过setValue设置的值存放在进程内存中。
                        状态为“真实”时，通过setValue设置的值存放在变量框架（共享内存）中。
             * @param   portIndex   端口号（0..n-1）
             * @param[out]   stat        状态：<em>true</em> - 虚拟；<em>false</em> - 真实
             * @see     setMask
             */
            Hsc3::Comm::HMCErrCode getMask(int32_t portIndex, bool & stat);

            /**
             * @brief   设置模拟IO端口状态
             * @details 状态为“虚拟”时，通过setValue设置的值存放在进程内存中。
                        状态为“真实”时，通过setValue设置的值存放在变量框架（共享内存）中。
             * @param   portIndex   端口号（0..n-1）
             * @param   stat        状态：<em>true</em> - 虚拟；<em>false</em> - 真实
             * @see     getMask setValue
             */
            Hsc3::Comm::HMCErrCode setMask(int32_t portIndex, bool stat);

            /**
             * @brief   获取模拟IO分组状态
             * @details 32个端口为1组。
             * @param   grpIndex    分组号（0..n-1）
             * @param[out]   grpStat      分组状态（32位无符号整数，最低位代表分组中端口0的状态，最高位代表端口31的状态，状态：<em>true</em> - 虚拟；<em>false</em> - 真实）
             * @see     setMaskGrp
             */
            Hsc3::Comm::HMCErrCode getMaskGrp(int32_t grpIndex, uint32_t & grpStat);

        private:
            inline Hsc3::Comm::HMCErrCode getGlobalCommand(std::string cmd, std::string & ret);
            inline Hsc3::Comm::HMCErrCode getGroupCommand(std::string cmd, int8_t gpId, std::string & ret);

        private:
            Hsc3::Comm::CommApi * m_pNet;
            std::string m_strProxyName;
        };
    }

}