/**
*   Copyright (C) 2020 华数机器人
*
*   @file       ProxyHome.h
*   @brief      华数III型二次开发接口 - 业务接口 - home操作代理
*   @details    提供了III型控制器IO相关业务接口。
*
*   @author
*   @date       2020/08/11
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
        *   @class      ProxyIO
        *   @brief      业务接口 - IO操作代理
        *   @details    提供接口包含：IO操作接口。
        *   @date       2020/08/11
        */
        class DLL_EXPORT ProxyHome
        {
        public:
            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   pNet    通信客户端
             */
            ProxyHome(Hsc3::Comm::CommApi * pNet);

            ~ProxyHome();

            /**
			 *@version	1.6.1
             * @brief   设置零点
			 * @param   gpId		组号（0..n-1）
			 * @param   homePos     零点设定值
			 * @param   mask		掩码，低9位有效，最低位代表组中第1个轴，第9位代表组中第9个轴。
             */
	        Hsc3::Comm::HMCErrCode setHome(int8_t gpId, const JntData& homePos, int32_t mask);

			/**
			 *@version	1.6.1
			 * @brief   获取零点
			 * @param   gpId		组号（0..n-1）
             * @brief	homePos		零点设定值
             */
            Hsc3::Comm::HMCErrCode getHome(int8_t gpId, JntData & homePos);

			/**
			 *@version	1.6.1
			 * @brief   通过零点偏差计算零点
			 * @param   gpId    组号（0..n-1）
             * @param	homePos		零点设定值
			 * @param	offset		零点偏移
			 * @param   mask		掩码，低9位有效，最低位代表组中第1个轴，第9位代表组中第9个轴。
             */
			Hsc3::Comm::HMCErrCode setHomeByOffset(int8_t gpId,const JntData & homePos, const JntData & offset, int32_t mask);

			/**
			 *@version	1.6.1
			 * @brief   获取零点偏移
			 * @param   gpId		组号（0..n-1）
			 * @param	offset		零点偏移
             */
			Hsc3::Comm::HMCErrCode getHomeOffset(int8_t gpId,JntData & offset);

			/**
			 *@version	1.6.1
			 * @brief   通过编码器值计算零点
			 * @param   gpId		组号（0..n-1）
             * @param	homePos		零点设定值
			 * @param   mask		掩码，低9位有效，最低位代表组中第1个轴，第9位代表组中第9个轴。
             */
			Hsc3::Comm::HMCErrCode setHomeByEncoder(int8_t gpId,const JntData & homePos, int32_t mask);

        private:
            Hsc3::Comm::CommApi * m_pNet;
        };
    }
}
