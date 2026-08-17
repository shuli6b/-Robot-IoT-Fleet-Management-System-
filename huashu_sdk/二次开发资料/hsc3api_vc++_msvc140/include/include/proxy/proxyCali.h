/**
*   Copyright (C) 2020 华数机器人
*
*   @file       ProxyCali.h
*   @brief      华数III型二次开发接口 - 业务接口 - 标定操作代理
*   @details    提供了III型控制器IO相关业务接口。
*
*   @author
*   @date       2021/02/22
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
        *   @class      ProxyCali
        *   @brief      业务接口 - 标定操作代理
        *   @details    提供接口包含：IO操作接口。
        *   @date       2020/08/11
        */
        class DLL_EXPORT ProxyCali
        {
        public:
            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   pNet    通信客户端
             */
            ProxyCali(Hsc3::Comm::CommApi * pNet);

            ~ProxyCali();

            /**
             * @brief   协同组标定
			 * @param   gpId		组号（0..n-1）
			 * @param   num			协同组号（<em>-1</em> - 默认，<em>0~2</em> - 可用协同组）
			 * @param   type        标定方法编号（<em>5</em> - 5点法， <em>3</em> - 3点法）
			 * @param   strData		标定数据（格式：半角分号分隔的点数据队列，例“{1,2,};{3,4,};{5,6,}”）
			 * @param[out]   strResult 标定结果（格式：例“ret=0x0, data={{7,8,},{9,10,}}”，其中“ret”是标定返回值，“data”是标定结果，是一个二维矩阵）
             */
	        Hsc3::Comm::HMCErrCode CoordCalibrate(int8_t gpId, int8_t num, int8_t type, const std::string & strData, std::string & strResult);

			/**
			 * @brief   外部轴减速比标定
			 * @param   isLine		是否直线轴（<em>true</em>-直线轴，<em>false</em>-旋转轴）
			 * @param   strCali		标定数据（格式：半角分号分隔的点数据队列，例“{1,2,};{3,4,};{5,6,}”）
			 * @param   strEnc		编码器数据（格式：半角分号分隔的点数据队列，例“{1,2,3}”）
			 * @param[out]   dExtAxisRatio 减速比
             */
            Hsc3::Comm::HMCErrCode caliExtAxisRatio(bool isLine, const std::string & strCali, const std::string  & strEnc, double & dExtAxisRatio);

			/**
			 * @brief   外部工具标定
             * @param	strCali		标定数据（格式：半角分号分隔的点数据队列，例“{1,2,};{3,4,};{5,6,}”）
			 * @param[out]	strResult		标定结果（格式：例“ret=0x0, data={7,8,}”，其中“ret”是标定返回值，“data”是标定结果）
             */
			Hsc3::Comm::HMCErrCode caliExtTool(const std::string & strCali, std::string & strResult);

			/**
			 * @brief   外部工件标定
			 * @param	strCali		标定数据（格式：半角分号分隔的点数据队列，例“{1,2,};{3,4,};{5,6,};{7,8,}”）
			 *								 <em>{1,2,}</em> - 空间点1
			 *								 <em>{3,4,}</em> - 空间点2
			 *								 <em>{5,6,}</em> - 空间点3
			 *								 <em>{7,8,}</em> - 外部工具标定值（XYZABC）
			 * @param[out]	strResult		标定结果（格式：例“ret=0x0, data={9,10,}”，其中“ret”是标定返回值，“data”是标定结果）
			 */
			Hsc3::Comm::HMCErrCode caliExtWorkPiece(const std::string & strCali, std::string & strResult);

        private:
            Hsc3::Comm::CommApi * m_pNet;
        };
    }
}
