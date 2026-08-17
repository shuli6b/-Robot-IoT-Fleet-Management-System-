/**
*   Copyright (C) 2018 华数机器人
*
*   @file       MdlExtDef.h
*   @brief      华数III型控制器外部运行业务相关定义
*   @details    
*
*   @author     
*   @date       2018/10/27
*   @version    
*   
*/

#pragma once

#if _MSC_VER == 1500
#include "stdint_vc9.h"
#else
#include <stdint.h>
#endif

#include <string>


namespace Hsc3 {

	namespace Ext {

        /**
        *   @struct     HookExtIn
        *   @brief      输入信号配置信息
        *   @details    
        */
        struct HookExtIn
        {
	        int16_t iDin;
	        std::string sig;
        };

        /**
        *   @struct     HookExtOut
        *   @brief      输出信号配置信息
        *   @details    
        */
        struct HookExtOut
        {
	        int16_t iDout;
	        std::string sig;
        };

        /**
        *   @struct     RefRegData
        *   @brief      引用寄存器数据
        *   @details    
        */
        struct RefRegData
        {
            int16_t iRef;           // 引用信号索引
            int8_t iGroup;          // 绑定组号
            std::string typeReg;	// 绑定寄存器类型 "JR"/"LR"
            int32_t iReg;           // 绑定寄存器索引
            double precision;		// 精度 "1.0"
        };

        /**
        *   @struct     RefRegDataModData
        *   @brief      引用寄存器数据修改数据
        *   @details    
        */
        struct RefRegModData
        {
            int16_t iRef;
            RefRegData data;
        };

		/**
        *   @struct     EnCoderData
        *   @brief      编码数据
        *   @details    
        */
        struct EnCoderData
        {
			int16_t iDout;           // 输出索引
			int8_t iLen;          // 长度
			int32_t iR;           // 绑定寄存器索引"
        };

		/**
        *   @struct     DeCoderData
        *   @brief      解码数据
        *   @details    
        */
        struct DeCoderData
        {
			int16_t iDin;           // 输入索引
			int8_t iLen;          // 长度
			int32_t iR;           // 绑定寄存器索引"
        };
	}

}