/**
*   Copyright (C) 2018 华数机器人
*
*   @file       MdlVision.h
*   @brief      华数III型二次开发接口 - 业务接口 - 视觉模块
*   @details    封装了III型控制器视觉模块。
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
#ifdef _LINUX_
#define DLL_EXPORT __attribute__((visibility("default")))
#else
#define DLL_EXPORT __declspec(dllexport)
#endif

#if _MSC_VER == 1500
#include "stdint_vc9.h"
#else
#include <stdint.h>
#endif

#include <string>

namespace Hsc3 {

    namespace Vision {

        /**
        *   @class      Position
        *   @brief      位置数据
        */
        struct DLL_EXPORT Position
        {
            Position();
            std::string toString() const;

            double x;   ///< x轴坐标
            double y;   ///< y轴坐标
            double z;   ///< z轴坐标
            double a;   ///< a轴坐标
            double b;   ///< b轴坐标
            double c;   ///< c轴坐标
        };

        /**
        *   @class      Target
        *   @brief      跟踪目标数据
        */
        struct DLL_EXPORT Target
        {
            Target();
            std::string toString() const;

            Position pos;   ///< 目标位置
            int32_t type;   ///< 目标类型（一般来说，不同类型的目标应设置不同值，由具体跟踪应用项目定义）
        };

        struct MdlVisionPrivate;

        /**
        *   @class      MdlVision
        *   @brief      业务接口 - 视觉模块
        *   @details    封装了视觉模块。
        *   @date       2018/10/27
        */
        class DLL_EXPORT MdlVision
        {
        public:
            /**
            *   @brief  收到机器人控制器消息时，执行的回调函数句柄
            */
            typedef void (*HandlerGetControllerMsg_t)(const std::string & strMsg);

            /**
             * @brief   构造函数
             * @details 注：确保传入已构造的通信客户端。
             * @param   handler    回调函数句柄（默认不指定，建议使用，并将内容通知到用户）
             * @param   b4Test     测试标志（默认为false）
                                    <em>true</em>  - 可脱离机器人控制器模拟测试
             *                      <em>false</em> - 需连接机器人控制器使用
             */
            MdlVision(HandlerGetControllerMsg_t handler = NULL, bool b4Test = false);

            ~MdlVision();

            /** 
             * @brief   获取版本信息
             * @return  版本信息字符串
             */
            static std::string getVersionStr();

            /**
             * @brief   连接机器人控制器
             * @param   strIp    IP
             * @return  返回
             *           <em>true</em>  - 连接成功
             *           <em>false</em> - 连接失败
             * @see     disconnectController isConnected
             */
            bool connectController(const std::string & strIp);

            /**
             * @brief   配置工作环境参数
             * @param   gpId        目标机器人轴组号（0..n-1）
             * @param   trackId     目标跟踪号（0..n-1）
             */
            void configEnvironment(int8_t gpId, int8_t trackId);

            /**
             * @brief   与机器人控制器断连
             * @see     connectController
             */
            void disconnectController();

            /** 
             * @brief   查询是否已连接机器人控制器
             * @return  返回
             *           <em>true</em>  - 已连接
             *           <em>false</em> - 未连接
             */
            bool isConnected();

            /**
             * @brief   获取机器人控制器回发消息
             * @param[out]     strMsg     消息字符串
             * @return  返回
             *           <em>true</em>  - 获取到消息
             *           <em>false</em> - 没有消息
             */
            bool getControllerMsg(std::string & strMsg);

            /**
             * @brief:  获取当前硬件触发编号
             * @return  触发编号（1≤编号≤255为正常）
             */
            int32_t getHardTrig();

            /**
             * @brief:  获取当前硬件触发编号
             * @param   trackId     目标跟踪号（0..n-1）
             * @return  触发编号（1≤编号≤255为正常）
             */
            int32_t getHardTrig(int trackId);

            /**
             * @brief:  查询是否需要软件触发
             * @details 注：如果由机器人控制器控制触发时机，则应以适当周期调用此接口；当返回true时，调用createSoftTrig接口启动一轮软件触发。
             * @return  返回
             *           <em>true</em>  - 需要
             *           <em>false</em> - 不需要
             * @see     createSoftTrig
             */
            bool needToCreateSoftTrig();

            /**
             * @brief:  构造软件触发项
             * @details 注：构造后拍照，拍照后需立即调用updateSoftTrig，机器人控制系统内部会补偿通信延时导致的误差。
             * @return  触发编号（1≤编号≤255为正常）
             * @see     updateSoftTrig
             */
            int32_t createSoftTrig();

            /**
             * @brief:  更新软件触发项
             * @param   trigId  触发编号（1≤编号≤255为正常）
             * @return  返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     createSoftTrig
             */
            bool updateSoftTrig(int32_t trigId);

            /**
             * @brief:  添加跟踪目标
             * @param   target      跟踪目标数据
             * @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
             * @return  返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             */
            bool addTarget(const Target & target, int32_t trigId);

            /**
             * @brief:  添加跟踪目标
             * @param   trackId     目标跟踪号（0..n-1）
             * @param   target      跟踪目标数据
             * @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
             * @return  返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             */
            bool addTarget(int trackId, const Target & target, int32_t trigId);

			/**
            * @brief:  添加跟踪目标
			* @param   target      跟踪目标数据
			* @param   offset      跟踪目标数据的偏移值
			* @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
			* @return  返回
			*           <em>true</em>  - 成功
			*           <em>false</em> - 失败
			*/
			bool addTargetWithOffset(const Target & target, const Target & offset, int32_t trigId);

            /**
            * @brief:  添加跟踪目标
            * @param   trackId     目标跟踪号（0..n-1）
            * @param   target      跟踪目标数据
            * @param   offset      跟踪目标数据的偏移值
            * @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
            * @return  返回
            *           <em>true</em>  - 成功
            *           <em>false</em> - 失败
            */
            bool addTargetWithOffset(int trackId, const Target & target, const Target & offset, int32_t trigId);

            /**
             * @brief:  获取位置
             * @details 注：对于传送带上某一位置P，机器人也许够不着；为获取其坐标，需做如下步骤：
             *           ①在P处调用createSoftTrig接口，记录触发编号trigId；
             *           ②移动传送带直至机器人可够得着P，操作机器人对准P；
             *           ③调用本接口（需提供trigId），返回位置数据即为（在传送带移动前的）P相对于机器人的坐标。
             *           本接口可用于手眼标定等功能中。
             * @param   trigId      触发编号（通过createSoftTrig接口获得）
             * @param[out]  pos     位置数据
             * @return 返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     createSoftTrig
             */
            bool getPosition(int32_t trigId, Position & pos);

            /**
             * @brief:  获取位置
             * @details 注：对于传送带上某一位置P，机器人也许够不着；为获取其坐标，需做如下步骤：
             *           ①在P处调用createSoftTrig接口，记录触发编号trigId；
             *           ②移动传送带直至机器人可够得着P，操作机器人对准P；
             *           ③调用本接口（需提供trigId），返回位置数据即为（在传送带移动前的）P相对于机器人的坐标。
             *           本接口可用于手眼标定等功能中。
             * @param   trackId     目标跟踪号（0..n-1）
             * @param   trigId      触发编号（通过createSoftTrig接口获得）
             * @param[out]  pos     位置数据
             * @return 返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     createSoftTrig
             */
            bool getPosition(int trackId, int32_t trigId, Position & pos);

        private:
            MdlVisionPrivate * m_p;
        };


        //////////////////////////////////////////////////////////////////////////

        namespace C_Api {

#ifdef __cplusplus
            extern "C"
            {
#endif

            /**
             * @brief   创建视觉模块
             * @param   thiz     对象ID
             * @param   b4Test     测试标志（默认为false）
                                    <em>true</em>  - 可脱离机器人控制器模拟测试
             *                      <em>false</em> - 需连接机器人控制器使用
             * @return  返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     deleteMdlVision
             */
            DLL_EXPORT bool _stdcall createMdlVision(uint8_t thiz, bool b4Test);

            /**
             * @brief   删除视觉模块
             * @param   thiz     对象ID
             * @see     createMdlVision
             */
            DLL_EXPORT void _stdcall deleteMdlVision(uint8_t thiz);

            /** 
             * @brief   获取版本信息
             * @param[out]   cstr     版本信息字符串
             * @param   len      允许字符串长度
             */
            DLL_EXPORT void _stdcall getVersionStr(char * cstr, uint16_t len);

            /**
             * @brief   连接机器人控制器
             * @param   thiz     对象ID
             * @param   cstrIp   IP
             * @param[out]   bRet     返回
             *           <em>true</em>  - 连接成功
             *           <em>false</em> - 连接失败
             * @see     disconnectController isConnected
             */
            DLL_EXPORT void _stdcall connectController(uint8_t thiz, char * cstrIp, bool * bRet);

            /**
             * @brief   配置工作环境参数
             * @param   thiz     对象ID
             * @param   gpId        目标机器人轴组号（0..n-1）
             * @param   trackId     目标跟踪号（0..n-1）
             */
            DLL_EXPORT void _stdcall configEnvironment(uint8_t thiz, int8_t gpId, int8_t trackId);

            /**
             * @brief   与机器人控制器断连
             * @param   thiz     对象ID
             * @see     connectController
             */
            DLL_EXPORT void _stdcall disconnectController(uint8_t thiz);

            /** 
             * @brief   查询是否已连接机器人控制器
             * @param   thiz     对象ID
             * @param[out]   bRet     返回
             *           <em>true</em>  - 已连接
             *           <em>false</em> - 未连接
             */
            DLL_EXPORT void _stdcall isConnected(uint8_t thiz, bool * bRet);

            /**
             * @brief   获取机器人控制器回发消息
             * @param   thiz     对象ID
             * @param[out]   cstr     消息字符串
             * @param   len      允许字符串长度
             * @param[out]   bRet     返回
             *           <em>true</em>  - 获取到消息
             *           <em>false</em> - 没有消息
             */
            DLL_EXPORT void _stdcall getControllerMsg(uint8_t thiz, char * cstr, uint16_t len, bool * bRet);

            /**
             * @brief:  获取当前硬件触发编号
             * @param   thiz     对象ID
             * @param[out]   trigId   触发编号（1≤编号≤255为正常）
             */
            DLL_EXPORT void _stdcall getHardTrig(uint8_t thiz, int32_t * trigId);

            /**
             * @brief:  查询是否需要软件触发
             * @details 注：如果由机器人控制器控制触发时机，则应以适当周期调用此接口；当返回true时，调用createSoftTrig接口启动一轮软件触发。
             * @param   thiz     对象ID
             * @param[out]   bRet     返回
             *           <em>true</em>  - 需要
             *           <em>false</em> - 不需要
             * @see     createSoftTrig
             */
            DLL_EXPORT void _stdcall needToCreateSoftTrig(uint8_t thiz, bool * bRet);

            /**
             * @brief:  构造软件触发项
             * @details 注：构造后拍照，拍照后需立即调用updateSoftTrig，机器人控制系统内部会补偿通信延时导致的误差。
             * @param   thiz     对象ID
             * @param[out]   trigId   触发编号（1≤编号≤255为正常）
             * @see     updateSoftTrig
             */
            DLL_EXPORT void _stdcall createSoftTrig(uint8_t thiz, int32_t * trigId);

            /**
             * @brief:  更新软件触发项
             * @param   thiz     对象ID
             * @param   trigId  触发编号（1≤编号≤255为正常）
             * @param[out]   bRet     返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     createSoftTrig
             */
            DLL_EXPORT void _stdcall updateSoftTrig(uint8_t thiz, int32_t trigId, bool * bRet);

			/**
			* @brief:  添加跟踪目标
			* @param   thiz     对象ID
			* @param   x, y, z, a, b, c     跟踪目标数据
			* @param   type        目标类型（一般来说，不同类型的目标应设置不同值，由具体跟踪应用项目定义）
			* @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
			* @param[out]   bRet     返回
			*           <em>true</em>  - 成功
			*           <em>false</em> - 失败
			*/
			DLL_EXPORT void _stdcall addTarget(uint8_t thiz, double x, double y, double z, double a, double b, double c, int32_t type, int32_t trigId, bool * bRet);

            /**
             * @brief:  添加跟踪目标
             * @param   thiz     对象ID
             * @param   x, y, z, a, b, c     跟踪目标数据
			 * @param   offset_x, offset_y, offset_z, offset_a, offset_b, offset_c     跟踪目标数据的偏移值
             * @param   type        目标类型（一般来说，不同类型的目标应设置不同值，由具体跟踪应用项目定义）
             * @param   trigId      触发编号（通过getHardTrig/createSoftTrig接口获得）
             * @param[out]   bRet     返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             */
            DLL_EXPORT void _stdcall addTargetWithOffset(uint8_t thiz, double x, double y, double z, double a, double b, double c, double offset_x, double offset_y, double offset_z, double offset_a, double offset_b, double offset_c, int32_t type, int32_t trigId, bool * bRet);

            /**
             * @brief:  获取位置
             * @details 注：对于传送带上某一位置P，机器人也许够不着；为获取其坐标，需做如下步骤：
             *           ①在P处调用createSoftTrig接口，记录触发编号trigId；
             *           ②移动传送带直至机器人可够得着P，操作机器人对准P；
             *           ③调用本接口（需提供trigId），返回位置数据即为（在传送带移动前的）P相对于机器人的坐标。
             *           本接口可用于手眼标定等功能中。
             * @param   thiz     对象ID
             * @param   trigId      触发编号（通过createSoftTrig接口获得）
             * @param[out]  x, y, z, a, b, c     位置数据
             * @param[out]   bRet     返回
             *           <em>true</em>  - 成功
             *           <em>false</em> - 失败
             * @see     createSoftTrig
             */
            DLL_EXPORT void _stdcall getPosition(uint8_t thiz, int32_t trigId, double * x, double * y, double * z, double * a, double * b, double * c, bool * bRet);

#ifdef __cplusplus
            }
#endif

        }

    }

}
