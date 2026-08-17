/**
*   Copyright (C) 2018 华数机器人
*
*   @file       ProxyTrack.h
*   @brief      华数III型二次开发接口 - 业务接口 - 跟踪功能代理
*   @details    提供了III型控制器跟踪相关业务接口。
*
*   @author
*   @date       2018/10/27
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

#include "CommDef.h"
#include "Hsc3Def.h"

namespace Hsc3 {
    namespace Comm {
        class CommApi;
    }

    namespace Proxy {
        /**
        *   @class      ProxyTrack
        *   @brief      业务接口 - 跟踪功能代理
        *   @details    提供接口包含：控制器跟踪操作接口。
        *   @date       2018/07/03
        */
        class DLL_EXPORT ProxyTrack
        {
        public:
            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   pNet    通信客户端
             */
            ProxyTrack(Hsc3::Comm::CommApi * pNet);

            ~ProxyTrack();

            /**
             * @brief:  获取当前硬件触发编号
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param[out]  trigId  触发编号（1≤编号≤255为正常）
             */
            Hsc3::Comm::HMCErrCode getHardTrig(int8_t gpId, int8_t trackId, int32_t & trigId);

            /**
             * @brief:  构造软件触发项
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param[out]  trigId  触发编号（1≤编号≤255为正常）
             */
            Hsc3::Comm::HMCErrCode createSoftTrig(int8_t gpId, int8_t trackId, int32_t & trigId);

            /**
             * @brief:  更新软件触发项
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param   trigId  触发编号（1≤编号≤255为正常）
             */
            Hsc3::Comm::HMCErrCode updateSoftTrig(int8_t gpId, int8_t trackId, int32_t trigId);

            /**
             * @brief:  添加目标
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param   data        目标位置（xyzabc）
             * @param   type        目标类型
             * @param   trigId      触发编号
             */
            Hsc3::Comm::HMCErrCode addTarget(int8_t gpId, int8_t trackId, const LocData & data, int32_t type, int32_t trigId);

			/**
			* @brief:  添加目标
			* @param   gpId        组号（0..n-1）
			* @param   trackId     跟踪号（0..n-1）
			* @param   data        目标位置（xyzabc）
			* @param   offsetData        目标位置偏移（xyzabc）
			* @param   type        目标类型
			* @param   trigId      触发编号
			*/
			Hsc3::Comm::HMCErrCode addTargetWithOffset(int8_t gpId, int8_t trackId, const LocData & data, const LocData & offsetData, int32_t type, int32_t trigId);

            /**
             * @brief:  获取位置
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param   trigId      触发编号
             * @param[out]  data    目标位置（xyzabc）
             */
            Hsc3::Comm::HMCErrCode getPosition(int8_t gpId, int8_t trackId, int32_t trigId, LocData & data);

			/**
             * @brief:  获取当前编码器位置
             * @param   gpId        组号（0..n-1）
             * @param   trackId     跟踪号（0..n-1）
             * @param[out]  enCodePos    编码器位置
             */
			Hsc3::Comm::HMCErrCode getCurrentEncoder(int8_t gpId, int8_t trackId, double & enCodePos);

        private:
            Hsc3::Comm::CommApi * m_pNet;
        };
    }
}
