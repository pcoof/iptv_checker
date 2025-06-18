#!/usr/bin/env python3
import cv2
import time
import subprocess
from loguru import logger
import os
import tempfile
import threading
import signal

class IPTVPlayer:
    """
    用于检查IPTV流的播放器类，提供流媒体信息检测功能。
    """
    def __init__(self):
        self.temp_dir = self._create_temp_dir()
        # 用于确保每个检测过程只执行一次
        self._running_process = None
        # 添加一个用于跟踪资源的标志
        self._resources_initialized = True
        
    def _create_temp_dir(self):
        """
        创建临时目录用于存储临时文件
        Returns:
            str: 临时目录路径
        """
        temp_dir = os.path.join(tempfile.gettempdir(), f"iptv_player_{os.getpid()}")
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
        return temp_dir
        
    def get_stream_info(self, url, timeout=5):
        """
        获取流媒体信息，包括分辨率和状态
        Args:
            url: 流媒体URL
            timeout: 超时时间（秒）
        Returns:
            tuple: (分辨率, 状态)
        """
        # 使用更短的超时时间，防止长时间阻塞
        effective_timeout = min(timeout, 3)
        
        # 创建一个线程安全的结果存储
        result = {"resolution": "N/A", "status": "TIMEOUT", "completed": False}
        
        # 创建一个单独的线程执行检测
        detection_thread = threading.Thread(
            target=self._run_detection,
            args=(url, effective_timeout, result)
        )
        detection_thread.daemon = True  # 设置为守护线程，确保主线程退出时它也会退出
        detection_thread.start()
        
        # 等待检测完成或超时
        detection_thread.join(effective_timeout)
        
        # 如果线程仍在运行，标记为超时
        if detection_thread.is_alive():
            # 尝试终止任何正在运行的进程
            self._kill_running_process()
            result["status"] = "TIMEOUT"
            
        return result["resolution"], result["status"]
        
    def _run_detection(self, url, timeout, result):
        """在单独的线程中运行检测逻辑"""
        try:
            logger.debug(f"开始检测流: {url}")
            
            # 首先尝试使用快速HTTP检查
            http_ok = self._quick_http_check(url)
            logger.debug(f"HTTP检查结果: {'成功' if http_ok else '失败'}")
            
            # 优先使用FFmpeg获取流信息
            try:
                resolution, status = self._get_info_ffmpeg(url, timeout)
                logger.debug(f"FFmpeg检测结果: 分辨率={resolution}, 状态={status}")
                
                # 如果FFmpeg成功获取到信息，直接使用结果
                if status == "OK" or resolution != "N/A":
                    result["resolution"] = resolution
                    result["status"] = "OK"
                    logger.debug(f"FFmpeg检测成功: {url}")
                    result["completed"] = True
                    return
            except Exception as e:
                logger.error(f"FFmpeg检测过程中发生错误: {str(e)}")
                resolution, status = "N/A", f"错误: FFmpeg异常 {str(e)[:20]}"
            
            # 如果FFmpeg未成功获取信息，尝试OpenCV
            if status != "OK" and resolution == "N/A":
                logger.debug(f"FFmpeg检测未成功，尝试OpenCV")
                try:
                    resolution, status = self._get_info_opencv(url, timeout/2)
                    logger.debug(f"OpenCV检测结果: 分辨率={resolution}, 状态={status}")
                except Exception as e:
                    logger.error(f"OpenCV检测过程中发生错误: {str(e)}")
                    resolution, status = "N/A", f"错误: OpenCV异常 {str(e)[:20]}"
            
            # 检查结果
            if resolution != "N/A" or status == "OK":
                # 如果获取到分辨率或状态为OK，则认为流是有效的
                result["resolution"] = resolution
                result["status"] = "OK"
                logger.debug(f"流检测成功: {url}")
            else:
                # 如果两种方法都失败，但HTTP检查成功，可能是可以播放的
                if http_ok:
                    logger.debug(f"虽然视频检测失败，但HTTP检查成功，认为流可能有效: {url}")
                    result["resolution"] = "未知"
                    result["status"] = "OK"
                else:
                    # 检查URL格式是否是典型的流媒体格式
                    is_stream_url = any(ext in url.lower() for ext in ['.m3u8', '.ts', '.mp4', '.flv', '.hls', 'rtmp://', 'rtsp://'])
                    if is_stream_url:
                        logger.debug(f"URL格式是典型的流媒体格式，尽管检测失败，仍认为可能有效: {url}")
                        result["resolution"] = "未知"
                        result["status"] = "OK"
                    else:
                        logger.debug(f"流检测失败: {url}")
                        result["resolution"] = "N/A"
                        result["status"] = f"错误: 检测失败"
            
            result["completed"] = True
            
        except Exception as e:
            logger.error(f"流检测线程错误: {str(e)}")
            result["status"] = f"错误: {str(e)[:30]}"
            result["completed"] = True
            
    def _quick_http_check(self, url):
        """快速检查URL是否可访问"""
        try:
            import requests
            from requests.exceptions import RequestException
            
            # 对m3u8和ts文件使用更宽松的检查
            is_m3u8 = url.endswith('.m3u8') or '.m3u8?' in url
            is_ts = url.endswith('.ts') or '.ts?' in url
            
            logger.debug(f"执行HTTP检查: {url}, 是M3U8: {is_m3u8}, 是TS: {is_ts}")
            
            # 仅发送HEAD请求，超时时间非常短
            try:
                response = requests.head(url, timeout=1.0, allow_redirects=True)
                status_code = response.status_code
                logger.debug(f"HEAD请求状态码: {status_code}")
                
                # 对于m3u8和ts文件，即使状态码不是200也可能是可用的
                if is_m3u8 or is_ts:
                    return status_code < 500  # 只要不是服务器错误，就认为可能有效
                
                return 200 <= status_code < 400
            except RequestException as e:
                logger.debug(f"HEAD请求失败: {str(e)}, 尝试GET请求")
                # 如果HEAD请求失败，尝试GET请求
                response = requests.get(url, timeout=1.0, stream=True)
                status_code = response.status_code
                logger.debug(f"GET请求状态码: {status_code}")
                
                # 对于m3u8和ts文件，即使状态码不是200也可能是可用的
                if is_m3u8 or is_ts:
                    response.close()
                    return status_code < 500  # 只要不是服务器错误，就认为可能有效
                
                # 仅读取少量数据，然后关闭连接
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        response.close()
                        return True
                response.close()
                return False
        except Exception as e:
            logger.debug(f"HTTP检查错误: {str(e)}")
            # 对于m3u8和ts文件，即使HTTP检查失败，也可能是可用的
            if is_m3u8 or is_ts:
                logger.debug(f"HTTP检查失败，但是是流媒体文件，可能仍然有效")
                return True
            return False
            
    def _get_info_ffmpeg(self, url, timeout):
        """
        使用FFmpeg获取流信息
        Args:
            url: 流媒体URL
            timeout: 超时时间（秒）
        Returns:
            tuple: (分辨率, 状态)
        """
        try:
            # 减少超时时间，确保不会长时间阻塞
            effective_timeout = min(timeout, 2)  # 最多2秒
            
            logger.debug(f"开始FFmpeg检测: {url}, 超时: {effective_timeout}秒")
            
            # 使用python-ffmpeg库获取流信息
            import ffmpeg
            
            # 设置超时（通过子线程实现）
            import threading
            from functools import wraps
            
            def timeout_handler(seconds):
                def decorator(func):
                    @wraps(func)
                    def wrapper(*args, **kwargs):
                        result = [None, "TIMEOUT"]
                        
                        def target():
                            nonlocal result
                            try:
                                result[0] = func(*args, **kwargs)
                                result[1] = "OK"
                            except Exception as e:
                                logger.debug(f"FFmpeg线程内错误: {str(e)}")
                                result[1] = f"错误: {str(e)[:30]}"
                        
                        thread = threading.Thread(target=target)
                        thread.daemon = True
                        thread.start()
                        thread.join(seconds)
                        return result
                    return wrapper
                return decorator
            
            @timeout_handler(effective_timeout)
            def probe_stream(url):
                probe = ffmpeg.probe(url)
                return probe
            
            # 获取流信息
            probe_result, status = probe_stream(url)
            
            if status == "TIMEOUT":
                logger.debug(f"FFmpeg检测超时: {url}")
                return "N/A", "TIMEOUT"
            
            if status.startswith("错误"):
                logger.debug(f"FFmpeg检测错误: {status}")
                
                # 对于某些流媒体，即使返回错误，也可能是可用的
                if "eof" in status.lower() or "end of file" in status.lower() or "network" in status.lower() or "timeout" in status.lower():
                    logger.debug("FFmpeg检测到EOF或网络错误，但流可能仍然有效")
                    return "未知", "OK"
                
                return "N/A", status
            
            if not probe_result or 'streams' not in probe_result:
                logger.debug(f"FFmpeg未返回有效的流信息: {url}")
                return "N/A", "错误: 未找到流信息"
            
            # 查找视频流
            video_stream = next((stream for stream in probe_result['streams'] if stream['codec_type'] == 'video'), None)
            
            # 查找音频流
            audio_stream = next((stream for stream in probe_result['streams'] if stream['codec_type'] == 'audio'), None)
            
            logger.debug(f"解析结果: 视频流={video_stream is not None}, 音频流={audio_stream is not None}")
            
            if video_stream:
                # 获取视频分辨率
                width = video_stream.get('width', 0)
                height = video_stream.get('height', 0)
                codec_name = video_stream.get('codec_name', 'unknown')
                
                logger.debug(f"视频流信息: 编解码器={codec_name}, 宽={width}, 高={height}")
                
                if width and height:
                    resolution = f"{width}x{height}"
                    return resolution, "OK"
                else:
                    logger.debug(f"视频流没有分辨率信息")
                    return "未知", "OK"
            elif audio_stream:
                # 如果只有音频流，也认为是有效的
                codec_name = audio_stream.get('codec_name', 'unknown')
                logger.debug(f"只检测到音频流，编解码器={codec_name}，标记为有效")
                return "音频", "OK"
            elif probe_result['streams']:
                # 如果有任何类型的流，也可能是有效的
                stream = probe_result['streams'][0]
                codec_name = stream.get('codec_name', 'unknown')
                logger.debug(f"检测到未知类型流，编解码器={codec_name}，可能是有效的")
                return "未知", "OK"
            else:
                return "N/A", "错误：未找到视频/音频流"
                
        except Exception as e:
            logger.debug(f"FFmpeg 信息提取错误: {str(e)}")
            return "N/A", f"错误: {str(e)[:30]}"
            
    def _get_info_opencv(self, url, timeout):
        """
        使用OpenCV获取流信息
        Args:
            url: 流媒体URL
            timeout: 超时时间（秒）
        Returns:
            tuple: (分辨率, 状态)
        """
        cap = None
        try:
            # 减少超时时间，确保不会长时间阻塞
            effective_timeout = min(timeout, 1)  # 最多1秒
            
            # 设置OpenCV参数以加快连接速度
            cap = cv2.VideoCapture(url)
            
            # 设置读取超时
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, effective_timeout * 1000)  # 毫秒为单位
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, effective_timeout * 1000)  # 毫秒为单位
            
            # 检查是否成功打开
            if not cap.isOpened():
                if cap:
                    cap.release()
                return "N/A", "错误: 无法打开流"
                
            # 设置超时时间
            start_time = time.time()
            
            # 尝试读取第一帧，带有超时检查
            ret, frame = cap.read()
            
            if ret:
                # 获取分辨率
                height, width = frame.shape[:2]
                resolution = f"{width}x{height}"
                # 释放资源
                cap.release()
                return resolution, "OK"
                
            # 如果读取失败，检查是否超时
            if time.time() - start_time >= effective_timeout:
                if cap:
                    cap.release()
                return "N/A", "TIMEOUT"
                
            # 其他原因的失败
            if cap:
                cap.release()
            return "N/A", "错误: 无法读取帧"
            
        except Exception as e:
            # 确保资源被释放
            if cap:
                try:
                    cap.release()
                except:
                    pass
            logger.debug(f"OpenCV 信息提取错误: {str(e)}")
            return "N/A", f"错误: {str(e)[:30]}"
            
    def _kill_running_process(self):
        """终止任何正在运行的进程"""
        if self._running_process:
            self._kill_process(self._running_process)
            self._running_process = None
            
    def _kill_process(self, process):
        """安全地终止一个进程"""
        try:
            if os.name == 'nt':  # Windows
                # Windows下终止进程
                process.terminate()
            else:  # Unix/Linux
                # 在Unix系统中发送SIGKILL信号
                os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except Exception as e:
            logger.debug(f"终止进程错误: {str(e)}")
        finally:
            # 确保process.returncode被设置
            try:
                process.kill()
            except:
                pass
            
    def __del__(self):
        """清理临时文件"""
        try:
            # 确保资源已被初始化
            if not hasattr(self, '_resources_initialized'):
                return
                
            # 确保任何正在运行的进程被终止
            if hasattr(self, '_running_process') and self._running_process:
                self._kill_running_process()
            
            # 清理临时目录
            import shutil
            if hasattr(self, 'temp_dir') and self.temp_dir and os.path.exists(self.temp_dir):
                try:
                    shutil.rmtree(self.temp_dir)
                except (PermissionError, OSError) as e:
                    # 无法清理临时文件夹，忽略错误
                    logger.debug(f"无法清理临时目录: {str(e)}")
                
        except Exception as e:
            logger.error(f"清理资源时出错: {str(e)}")