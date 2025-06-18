import asyncio
import aiohttp
import time
from loguru import logger
import concurrent.futures
import signal
import os
import threading

class AsyncIPTVChecker:
    """异步IPTV流检查器，用于高并发场景"""
    
    def __init__(self, request_timeout=5, max_concurrency=100):
        self.request_timeout = request_timeout
        self.max_concurrency = max_concurrency
        self._stop_requested = False
        self.progress_callback = None
        self.status_callback = None
        self._running_tasks = set()
        self._running_threads = []
    
    def set_callbacks(self, progress_callback=None, status_callback=None):
        """设置进度和状态回调"""
        self.progress_callback = progress_callback
        self.status_callback = status_callback
    
    async def check_stream(self, stream, session):
        """异步检查单个流"""
        if self._stop_requested:
            return stream
            
        url = stream.get('url', '')
        if not url:
            stream['status'] = '无效源'
            stream['resolution'] = 'N/A'
            stream['response_time'] = -1
            return stream
            
        start_time = time.time()
        
        try:
            # 快速检查URL是否可访问
            try:
                # 使用更短的超时快速检查可访问性
                check_timeout = min(1.0, self.request_timeout / 2)
                async with session.head(
                    url, 
                    timeout=check_timeout,
                    allow_redirects=True
                ) as response:
                    if response.status != 200:
                        # 如果HEAD请求失败，尝试GET请求
                        try:
                            async with session.get(
                                url, 
                                timeout=check_timeout,
                                allow_redirects=True
                            ) as get_response:
                                if get_response.status != 200:
                                    stream['status'] = '无效源'
                                    stream['resolution'] = 'N/A'
                                    stream['response_time'] = round((time.time() - start_time) * 1000)
                                    return stream
                                # 仅读取少量数据确认
                                await get_response.content.read(1024)
                        except Exception:
                            stream['status'] = '无效源'
                            stream['resolution'] = 'N/A'
                            stream['response_time'] = round((time.time() - start_time) * 1000)
                            return stream
            except Exception:
                # 如果所有HTTP检查都失败，尝试直接获取流信息
                pass
            
            # 使用线程池执行器运行获取流信息的任务
            try:
                # 创建一个事件用于超时控制
                done_event = threading.Event()
                result_container = {"resolution": "N/A", "status": "TIMEOUT"}
                
                # 创建一个线程执行阻塞操作
                thread = threading.Thread(
                    target=self._thread_get_stream_info,
                    args=(url, self.request_timeout, result_container, done_event)
                )
                thread.daemon = True
                self._running_threads.append(thread)
                thread.start()
                
                # 等待线程完成或超时
                timeout = min(self.request_timeout, 3.0)  # 最多等待3秒
                await asyncio.sleep(0.01)  # 让出控制权给事件循环
                
                # 使用asyncio创建超时任务
                try:
                    # 创建一个超时任务
                    async def wait_for_thread():
                        for _ in range(int(timeout * 100)):  # 转为100毫秒的检查间隔
                            if done_event.is_set() or self._stop_requested:
                                break
                            await asyncio.sleep(0.01)  # 小间隔检查，保持响应性
                        return done_event.is_set()
                    
                    # 等待线程完成或超时
                    thread_completed = await wait_for_thread()
                    
                    if not thread_completed:
                        # 超时，标记结果
                        result_container["status"] = "TIMEOUT"
                        # 线程会自行终止（它是daemon线程）
                        if thread in self._running_threads:
                            self._running_threads.remove(thread)
                    else:
                        # 线程已完成，使用其结果
                        if thread in self._running_threads:
                            self._running_threads.remove(thread)
                
                except Exception as e:
                    logger.error(f"等待线程时出错: {str(e)}")
                    result_container["status"] = f"错误: {str(e)[:30]}"
                
                # 更新流数据
                resolution = result_container["resolution"]
                status = result_container["status"]
                
            except Exception as e:
                logger.error(f"获取流信息时出错 {url}: {str(e)}")
                resolution = "N/A"
                status = f"错误: {str(e)[:30]}"
            
            # 更新流数据
            stream['resolution'] = resolution
            stream['status'] = '正常' if status == "OK" else '无效源'
            stream['response_time'] = round((time.time() - start_time) * 1000)
            
            return stream
        except Exception as e:
            logger.error(f"异步检查流错误 {url}: {str(e)}")
            stream['status'] = '无效源'
            stream['resolution'] = 'N/A'
            stream['response_time'] = round((time.time() - start_time) * 1000)
            return stream
    
    def _thread_get_stream_info(self, url, timeout, result_container, done_event):
        """在线程中获取流信息"""
        try:
            # 导入这里以避免全局污染
            from iptv_player import IPTVPlayer
            player = IPTVPlayer()
            # 获取流信息
            resolution, status = player.get_stream_info(url, timeout=timeout)
            # 存储结果
            result_container["resolution"] = resolution
            result_container["status"] = status
        except Exception as e:
            logger.error(f"线程中获取流信息错误: {str(e)}")
            result_container["status"] = f"错误: {str(e)[:30]}"
        finally:
            # 标记完成
            done_event.set()
    
    async def check_all_streams(self, streams):
        """异步并发检查所有流"""
        if not streams:
            return []
            
        self._stop_requested = False
        self._running_tasks = set()
        self._running_threads = []
        
        # 创建一个用于限制并发的信号量
        semaphore = asyncio.Semaphore(self.max_concurrency)
        
        # 定义包装的检查函数
        async def check_with_semaphore(stream, session):
            async with semaphore:
                return await self.check_stream(stream, session)
        
        # 优化的TCP连接器
        conn = aiohttp.TCPConnector(
            limit=0,  # 无连接数限制
            ttl_dns_cache=300,  # DNS缓存时间
            force_close=True,  # 强制关闭连接
            enable_cleanup_closed=True  # 清理已关闭连接
        )
        
        # 客户端会话超时设置
        timeout = aiohttp.ClientTimeout(
            total=self.request_timeout,
            connect=min(2.0, self.request_timeout),
            sock_connect=min(2.0, self.request_timeout),
            sock_read=self.request_timeout
        )
        
        # 创建客户端会话
        async with aiohttp.ClientSession(
            connector=conn, 
            timeout=timeout
        ) as session:
            # 提交所有任务
            tasks = []
            for stream in streams:
                task = asyncio.create_task(check_with_semaphore(stream, session))
                tasks.append(task)
                self._running_tasks.add(task)
                task.add_done_callback(self._running_tasks.discard)
            
            # 等待所有任务完成或任务被取消
            results = []
            for i, task_future in enumerate(asyncio.as_completed(tasks)):
                if self._stop_requested:
                    # 取消剩余任务
                    for task in tasks:
                        if not task.done():
                            task.cancel()
                    # 终止所有运行中的线程
                    self._terminate_running_threads()
                    break
                
                try:
                    result = await task_future
                    results.append(result)
                    
                    # 更新进度
                    if self.progress_callback and not self._stop_requested:
                        progress = int(len(results) / len(streams) * 100)
                        self.progress_callback(progress, len(results), len(streams))
                    
                    # 更新状态
                    if self.status_callback and not self._stop_requested:
                        self.status_callback(f"已检查 {len(results)}/{len(streams)} 流")
                    
                    # 定期让出控制权，保持UI响应
                    if i % 10 == 0:  # 每10个任务
                        await asyncio.sleep(0.001)  # 短暂让出控制权
                        
                except asyncio.CancelledError:
                    logger.debug("任务被取消")
                    continue
                except Exception as e:
                    logger.error(f"任务错误: {str(e)}")
                    continue
            
            return results
    
    def _terminate_running_threads(self):
        """终止所有运行中的线程"""
        # 注意: 这并不总是安全的，但在这里我们确保所有线程都是daemon线程
        for thread in self._running_threads[:]:
            # 线程是daemon线程，当主程序退出时会自动终止
            # 这里只从列表中移除
            if thread in self._running_threads:
                self._running_threads.remove(thread)
    
    def stop_check(self):
        """停止检查"""
        self._stop_requested = True
        
        # 取消所有正在运行的任务
        for task in self._running_tasks:
            if not task.done():
                task.cancel()
        
        # 终止所有运行中的线程
        self._terminate_running_threads()
        
        if self.status_callback:
            self.status_callback("停止流检查...")
