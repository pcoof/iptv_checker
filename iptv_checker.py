#!/usr/bin/env python3
# 修改记录：
# 1. 添加了对中文地理位置信息的支持，通过lang=zh-CN参数获取中文地理位置
import os
import time
import json
import requests
import threading
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
from tqdm import tqdm
from urllib.parse import urlparse
from config import ( CONNECTION_TIMEOUT, MAX_WORKERS, OPENCV_TIMEOUT ) # OPENCV_TIMEOUT 将被 self.request_timeout 替代, MAX_WORKERS 被 self.concurrent_checks 替代
import numpy as np
import numba

@numba.jit(nopython=True)
def _resolution_to_pixels_fast(width, height):
    """使用Numba加速的分辨率计算函数"""
    return width * height

class IPTVChecker:
    def __init__(self):
        self.concurrent_checks = MAX_WORKERS  # 默认值，将被配置覆盖
        self.request_timeout = OPENCV_TIMEOUT # 默认值，将被配置覆盖
        self._stop_requested = threading.Event() # 初始化停止请求事件
        self.streams = []  # 初始化流列表
        self.progress_callback = None # 初始化进度回调
        self.status_callback = None # 初始化状态回调
        self._invalid_domains = {}  # 存储无效域名计数
        self.skip_same_domain_invalid = False # 是否跳过同一域名下的无效源
    def update_settings(self, concurrent_checks, request_timeout):
        """更新检查器的设置"""
        self.concurrent_checks = concurrent_checks
        self.request_timeout = request_timeout
        # 从设置中加载skip_same_domain_invalid选项
        try:
            from config import SKIP_SAME_DOMAIN_INVALID
            self.skip_same_domain_invalid = SKIP_SAME_DOMAIN_INVALID
        except ImportError:
            self.skip_same_domain_invalid = False
        logger.info(f"IPTVChecker 设置已更新: 并发数={self.concurrent_checks}, 超时={self.request_timeout}, 跳过同域名无效源={self.skip_same_domain_invalid}")
    """核心的用于检查网络电视流的类。"""
    def set_callbacks(self, progress_callback=None, status_callback=None):
        """设置用于 GUI 更新的进度和状态回调。"""
        self.progress_callback = progress_callback
        self.status_callback = status_callback
    def import_streams(self, file_path):
        """
        从文件导入流 (M3U 或 TXT 格式)
        Args:
            file_path: 流列表文件的路径
        Returns:
            导入的流列表
        """
        from stream_formats import parse_m3u, parse_txt
        if not os.path.exists(file_path):
            logger.error(f"文件未找到: {file_path}")
            return []
        try:
            file_ext = os.path.splitext(file_path)[1].lower()
            if file_ext == '.m3u' or file_ext == '.m3u8':
                imported_streams = parse_m3u(file_path)
                logger.info(f"导入的 {len(imported_streams)} 来自M3U文件的流")
            elif file_ext == '.txt':
                imported_streams = parse_txt(file_path)
                logger.info(f"Imported {len(imported_streams)} 来自文本文件的流")
            else:
                logger.error(f"不支持的文件格式: {file_ext}")
                return []
            # Add IDs to all streams if they don't have one
            for i, stream in enumerate(imported_streams):
                if 'id' not in stream:
                    stream['id'] = i + 1
            self.streams = imported_streams
            return imported_streams
        except Exception as e:
            logger.error(f"导入流时出错: {str(e)}")
            return []
    # 添加批量更新缓冲区和计时器
    _status_update_buffer = {}
    _last_status_update_time = 0
    _status_update_interval = 0.1  # 100毫秒更新一次
    def _update_stream_status(self, stream):
        """
        实时更新流的状态，通过回调函数通知GUI更新
        Args:
            stream: 包含流数据的字典
        """
        # 如果设置了状态回调函数，则将更新添加到缓冲区
        if self.status_callback:
            # 创建一个包含流ID和更新状态的消息
            message = {k: stream[k] for k in ['id', 'status', 'resolution', 'response_time'] if k in stream}
            # 将消息添加到缓冲区
            stream_id = stream.get('id')
            self._status_update_buffer[stream_id] = message
            # 检查是否应该发送批量更新
            current_time = time.time()
            if (current_time - self._last_status_update_time >= self._status_update_interval) or len(self._status_update_buffer) >= 10:
                # 发送所有缓冲的更新
                for buffered_message in self._status_update_buffer.values():
                    self.status_callback(f"stream_update:{json.dumps(buffered_message)}")
                # 清空缓冲区并更新时间戳
                self._status_update_buffer.clear()
                self._last_status_update_time = current_time
    def check_stream(self, stream):
        """
        检查单个流的有效性并获取其详细信息
        Args:
            stream: 包含流数据的字典
        Returns:
            使用检查结果更新流字典
        """
        # 检查是否已经请求停止
        if self._stop_requested.is_set():
            return stream
        
        # 保存原始分类和归属地信息
        original_group = stream.get('group', '')
        original_country = stream.get('country', '')
        
        # 如果流已经标记为无效源，跳过检测
        current_status = stream.get('status', '')
        if current_status == '无效源':
            logger.debug(f"跳过无效源检测: {stream.get('name', 'Unknown')}")
            return stream
        
        # 初始状态为待检测
        if 'status' not in stream:
            stream['status'] = '待检测'
        
        # 获取URL，如果为空则标记为无效
        url = stream.get('url', '')
        if not url:
            stream['status'] = '无效源'
            stream['resolution'] = 'N/A'
            stream['response_time'] = -1
            self._update_stream_status(stream)
            return stream
        
        # 记录开始时间
        start_time = time.time()
        
        try:
            # 解析URL获取域名
            parsed_url = urlparse(url)
            domain = parsed_url.netloc
            
            # 检查是否需要跳过同域名下的流
            if self.skip_same_domain_invalid and domain:
                if domain in self._invalid_domains and self._invalid_domains[domain] >= 3:
                    # 如果同域名已有3个以上无效源，直接标记为无效并跳过检测
                    stream['status'] = '无效源(已跳过)'
                    stream['resolution'] = 'N/A'
                    stream['response_time'] = -1
                    
                    # 获取地理位置并同时更新location和country字段
                    location = self._get_location(domain) if domain else "Unknown"
                    stream['location'] = location
                    stream['country'] = location
                    
                    # 实时更新状态
                    self._update_stream_status(stream)
                    logger.debug(f"域名 {domain} 已检测到多个无效源，跳过检测: {stream.get('name', 'Unknown')}")
                    return stream
            
            # 检查连接是否可用
            try:
                connection_ok = self._test_connection(domain, timeout=0.5)
                
                # 尝试获取位置信息（使用缓存）
                if domain:
                    location = self._get_location(domain)
                    if location:
                        # 同时更新location和country字段
                        stream['location'] = location
                        stream['country'] = location
                
                # 保留原始分类和归属地信息
                if original_group:
                    stream['group'] = original_group
                if original_country:
                    stream['country'] = original_country
                    
                # 即使连接测试失败，也尝试获取流信息
                if not connection_ok:
                    logger.debug(f"连接测试失败，但继续检测流: {url}")
            except Exception as e:
                logger.debug(f"URL解析或连接测试错误 {url}: {str(e)}")
            
            # 获取流信息
            resolution, status = self._get_stream_info(url)
            
            # 对超时错误进行一次重试
            if status == "TIMEOUT":
                logger.info(f"流 {url} 检测超时，将在0.5秒后重试...")
                time.sleep(0.5)
                resolution, status = self._get_stream_info(url)
                logger.info(f"流 {url} 重试检测结果 - 状态: {status}, 分辨率: {resolution}")
            
            # 判断流是否有效
            is_valid = (status == "OK" or resolution != "N/A")
            
            # 对于特定格式的URL，即使检测失败也可能是有效的
            if not is_valid and url:
                # 检查是否是典型的流媒体URL格式
                is_stream_url = any(ext in url.lower() for ext in ['.m3u8', '.ts', '.mp4', '.flv', '.hls', 'rtmp://', 'rtsp://'])
                if is_stream_url:
                    logger.debug(f"URL格式是典型的流媒体格式，认为可能有效: {url}")
                    is_valid = True
                    resolution = "未知"
                    status = "OK"
            
            # 更新流数据
            stream['resolution'] = resolution
            
            # 判断流是否有效
            stream['status'] = '正常' if is_valid else '无效源'
            stream['response_time'] = round((time.time() - start_time) * 1000)  # 毫秒
            
            # 如果流无效且启用了域名跳过功能，更新域名无效计数
            if not is_valid and domain and self.skip_same_domain_invalid:
                self._invalid_domains[domain] = self._invalid_domains.get(domain, 0) + 1
            
            # 实时更新状态
            self._update_stream_status(stream)
            return stream
            
        except Exception as e:
            # 处理整体异常
            logger.error(f"检查流错误 {url}: {str(e)}")
            stream['status'] = '无效源'
            stream['resolution'] = 'N/A'
            stream['response_time'] = round((time.time() - start_time) * 1000)
            
            # 保留原始分类和归属地信息
            if original_group:
                stream['group'] = original_group
            if original_country:
                stream['country'] = original_country
                
            self._update_stream_status(stream)
            
            # 获取域名并更新无效域名计数
            try:
                domain = urlparse(url).netloc
                if domain and self.skip_same_domain_invalid:
                    self._invalid_domains[domain] = self._invalid_domains.get(domain, 0) + 1
            except:
                pass
                
            return stream
    def check_all_streams(self, streams=None):
        """优化后的流检查函数，使用更高效的ThreadPoolExecutor配置"""
        if streams is None:
            streams = self.streams
        if not streams:
            return []
        
        # 重置停止标志
        self._stop_requested.clear()
        
        # 优化线程池配置
        import concurrent.futures
        from concurrent.futures import ThreadPoolExecutor
        
        # 为网络I/O密集型任务设置最佳线程池大小
        # CPU核心数 * (1 + 网络I/O等待时间/CPU处理时间)
        import os
        import psutil
        
        cpu_count = os.cpu_count() or 4
        io_ratio = 10  # 网络I/O等待时间是CPU处理时间的10倍(估计值)
        optimal_workers = min(32, cpu_count * (1 + io_ratio))
        
        # 使用调整过的线程池大小
        max_workers = min(self.concurrent_checks, optimal_workers)
        
        # 优化线程池配置，使用ThreadPoolExecutor的更多选项
        with ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="IPTVCheck",
            initializer=lambda: None  # 可以添加线程初始化函数
        ) as executor:
            # 提交所有任务
            futures = [executor.submit(self.check_stream, stream) for stream in streams]
            
            # 使用迭代器处理结果，减少内存占用
            results = []
            for future in concurrent.futures.as_completed(futures):
                if self._stop_requested.is_set():
                    # 取消所有未完成的任务
                    for f in futures:
                        if not f.done():
                            f.cancel()
                    break
                
                try:
                    stream = future.result()
                    results.append(stream)
                    
                    # 更新进度
                    if self.progress_callback:
                        progress = int(len(results) / len(streams) * 100)
                        self.progress_callback(progress, len(results), len(streams))
                except Exception as e:
                    logger.error(f"线程错误: {str(e)}")
            
        return results
    def stop_check(self):
        """向线程发出停止检查的信号."""
        self._stop_requested.set()
        if self.status_callback:
            self.status_callback("停止流检查...")

    def filter_streams(self, min_resolution=None, max_response_time=None, status=None):
        """优化后的流过滤函数"""
        if not self.streams:
            return []
        
        # 转换为NumPy数组以实现向量化操作
        streams_array = np.array(self.streams, dtype=object)
        mask = np.ones(len(streams_array), dtype=bool)
        
        if min_resolution:
            min_pixels = self._resolution_to_pixels(min_resolution)
            resolutions = np.array([self._resolution_to_pixels(s.get('resolution', '0x0')) for s in self.streams])
            mask &= (resolutions >= min_pixels)
        
        if max_response_time and max_response_time > 0:
            response_times = np.array([s.get('response_time', 999999) for s in self.streams])
            mask &= (response_times <= max_response_time)
        
        if status:
            status_mask = np.array([s.get('status', '') == status for s in self.streams])
            mask &= status_mask
        
        return streams_array[mask].tolist()
    def export_streams(self, file_path, streams=None, export_format=None):
        """
        Export streams to a file
        Args:
            file_path: Path to save the exported file
            streams: Optional list of streams to export; if None, uses self.streams
            export_format: Format to export (m3u, txt, or None to infer from file extension)
        Returns:
            True if export was successful, False otherwise
        """
        from stream_formats import export_m3u, export_txt
        if streams is None:
            streams = self.streams
        if not streams:
            logger.warning("没有要导出的流")
            return False
        try:
            if export_format is None:
                # 从文件扩展名推断格式
                file_ext = os.path.splitext(file_path)[1].lower()
                if file_ext in ['.m3u', '.m3u8']:
                    export_format = 'm3u'
                elif file_ext == '.txt':
                    export_format = 'txt'
                else:
                    logger.error(f"不支持的导出格式: {file_ext}")
                    return False
            # 以指定格式导出
            if export_format == 'm3u':
                export_m3u(streams, file_path)
            elif export_format == 'txt':
                export_txt(streams, file_path)
            else:
                logger.error(f"不支持的导出格式: {export_format}")
                return False
            logger.info(f"导出的 {len(streams)} 到 {file_path}")
            return True
        except Exception as e:
            logger.error(f"导出时出错: {str(e)}")
            return False
    def _get_stream_info(self, url):
        """
        使用玩家模块检查一个流并获取其详细信息
        Args:
            url: 要检查的流URL
        Returns:
            （分辨率，状态）元组
        """
        try:
            # 使用IPTV播放器模块获取流信息
            from iptv_player import IPTVPlayer
            player = IPTVPlayer()
            resolution, status = player.get_stream_info(url, timeout=self.request_timeout)
            return resolution, status
        except Exception as e:
            logger.debug(f"流检查错误，原因是 {url}: {str(e)}")
            return "N/A", f"错误: {str(e)[:30]}"
    def _test_connection(self, host_str, timeout=None):
        """
        测试是否可以连接到主机
        Args:
            host_str: 主机字符串（可以是 "hostname" 或 "hostname:port"）
            timeout: 连接超时时间（秒），如果为None则使用默认超时时间
        Returns:
            布尔值，表示是否可以连接
        """
        try:
            # 提取主机和端口
            if ':' in host_str:
                host, port_str = host_str.split(':', 1)
                try:
                    port = int(port_str)
                except ValueError:
                    port = 80
            else:
                host = host_str
                port = 80
                
            # 使用提供的超时时间或默认值
            actual_timeout = timeout if timeout is not None else CONNECTION_TIMEOUT
            
            # 尝试建立连接
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(actual_timeout)
            result = sock.connect_ex((host, port))
            sock.close()
            return result == 0
        except Exception as e:
            logger.debug(f"连接测试错误，原因是 {host_str}: {str(e)}")
            return False
    # 添加位置缓存字典，避免重复请求相同的IP
    _location_cache = {}
    def _get_location(self, host):
        """
        尝试确定主机的地理位置
        Args:
            host: 主机名或IP地址
        Returns:
            包含位置信息的字符串或"未知"
        """
        try:
            # 仅提取不带端口的主机名
            if ':' in host:
                host = host.split(':', 1)[0]
            # 如果是主机名，则尝试解析IP
            try:
                ip = socket.gethostbyname(host)
            except:
                ip = host
            # 检查它是否是一个私有IP
            if self._is_private_ip(ip):
                return "本地网络"
            # 检查缓存中是否已有此IP的位置信息
            if ip in self._location_cache:
                return self._location_cache[ip]
            # 尝试从ip-api.com获取位置数据（免费，无需API密钥）
            try:
                # 减少超时时间，避免长时间阻塞
                # 添加lang=zh-CN参数获取中文结果
                response = requests.get(f"http://ip-api.com/json/{ip}?lang=zh-CN", timeout=1)
                if response.status_code == 200:
                    data = response.json()
                    if data.get('status') == 'success':
                        country = data.get('country', '未知')
                        region = data.get('regionName', '')
                        city = data.get('city', '')
                        location_parts = []
                        if country:
                            location_parts.append(country)
                        if region and region != city:  # 避免重复信息
                            location_parts.append(region)
                        if city:
                            location_parts.append(city)
                        if location_parts:
                            location = ", ".join(location_parts)
                            # 缓存结果
                            self._location_cache[ip] = location
                            return location
            except Exception as e:
                logger.debug(f"获取位置信息时出错: {str(e)}")
                pass
            # 缓存未知结果，避免重复请求
            self._location_cache[ip] = "未知"
            return "未知"
        except Exception as e:
            logger.debug(f"获取位置时出错{host}: {str(e)}")
            return "未知"
    def _is_private_ip(self, ip):
        """检查一个IP地址是否在私有IP空间内"""
        try:
            # Convert string to IP object for easier comparison
            ip_obj = socket.inet_aton(ip)
            ip_int = int.from_bytes(ip_obj, byteorder='big')
            # Check private IP ranges
            private_ranges = [
                (socket.inet_aton('10.0.0.0'), socket.inet_aton('10.255.255.255')),
                (socket.inet_aton('172.16.0.0'), socket.inet_aton('172.31.255.255')),
                (socket.inet_aton('192.168.0.0'), socket.inet_aton('192.168.255.255')),
                (socket.inet_aton('127.0.0.0'), socket.inet_aton('127.255.255.255'))
            ]
            for start, end in private_ranges:
                start_int = int.from_bytes(start, byteorder='big')
                end_int = int.from_bytes(end, byteorder='big')
                if start_int <= ip_int <= end_int:
                    return True
            return False
        except:
            return False
    def _resolution_to_pixels(self, resolution):
        """优化后的分辨率解析函数"""
        # 提取分辨率数值
        if 'x' in resolution:
            try:
                width, height = map(int, resolution.split('x', 1))
                return _resolution_to_pixels_fast(width, height)
            except:
                pass
        return 0