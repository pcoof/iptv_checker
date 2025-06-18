#!/usr/bin/env python3
import os
import requests
from PySide6.QtCore import QThread, Signal
from loguru import logger
from utils import create_temp_directory, clean_temp_directory, is_valid_url
from stream_formats import parse_m3u, parse_txt
from config import REQUEST_TIMEOUT, CONCURRENT_CHECKS

class ImportUrlThread(QThread):
    """URL导入线程类
    
    支持多种导入方式：
    1. 从URL链接导入：自动下载内容并识别格式
    2. 从剪贴板直接导入M3U格式：自动识别#EXTM3U开头的内容
    3. 从剪贴板直接导入TXT格式：自动识别包含#genre#或URL+逗号格式的内容
    4. 从剪贴板提取URL：如果以上方式都失败，尝试从文本中提取URL
    """
    # 定义信号，参数可以是解析到的流列表和错误信息
    finished_signal = Signal(list, str) # streams, error_message
    progress_signal = Signal(int, int, int) # 进度百分比, 当前处理行数, 总行数
    
    def __init__(self, url_content, parent=None):
        super().__init__(parent)
        self.url_content = url_content
        self.streams_to_add = []
        self.error_message = ""
        self.is_cancelled = False
        
    def run(self):
        try:
            # 检查是否为URL链接
            if is_valid_url(self.url_content):
                logger.info(f"Thread: Starting import from URL: {self.url_content}")
                try:
                    # 设置超时，避免长时间等待
                    response = requests.get(self.url_content, timeout=REQUEST_TIMEOUT) # 使用配置的超时
                    response.raise_for_status() # 检查HTTP请求错误
                    url_text_content = response.text
                    logger.info(f"Thread: Successfully fetched content from URL.")
                    
                    # 检查是否已取消
                    if self.is_cancelled:
                        self.error_message = "导入操作已取消"
                        self.finished_signal.emit([], self.error_message)
                        return
                    
                    # 检查内容是否为M3U或TXT格式
                    is_m3u = url_text_content.strip().startswith('#EXTM3U')
                    # 更可靠的TXT格式判断：包含 "://"，并且可能包含 ","，但不是M3U
                    is_txt = (('#genre#' in url_text_content or 
                                (',' in url_text_content and ('http://' in url_text_content or 'https://' in url_text_content)))) \
                               and not is_m3u
                    
                    # 定义进度回调函数
                    def progress_callback(progress, current, total):
                        if self.is_cancelled:
                            raise InterruptedError("导入操作已取消")
                        self.progress_signal.emit(progress, current, total)
                    
                    if is_m3u or is_txt:
                        logger.info(f"Thread: URL content detected as {'M3U' if is_m3u else 'TXT'} playlist.")
                        temp_dir = create_temp_directory()
                        if not temp_dir:
                            self.error_message = "无法创建临时目录"
                            self.finished_signal.emit([], self.error_message)
                            return
                        
                        # 检查是否已取消
                        if self.is_cancelled:
                            clean_temp_directory(temp_dir)
                            self.error_message = "导入操作已取消"
                            self.finished_signal.emit([], self.error_message)
                            return
                            
                        if is_m3u:
                            temp_file = os.path.join(temp_dir, "temp_playlist.m3u")
                            parse_function = parse_m3u
                        else:
                            temp_file = os.path.join(temp_dir, "temp_playlist.txt")
                            parse_function = parse_txt
                            
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            f.write(url_text_content)
                            
                        # 使用进度回调解析文件
                        parsed_streams = parse_function(temp_file, progress_callback=progress_callback)
                        
                        # 检查是否已取消
                        if self.is_cancelled:
                            clean_temp_directory(temp_dir)
                            self.error_message = "导入操作已取消"
                            self.finished_signal.emit([], self.error_message)
                            return
                            
                        if parsed_streams:
                            self.streams_to_add = parsed_streams
                        else:
                            self.error_message = "解析后未找到有效的流 (来自URL内容)"
                        clean_temp_directory(temp_dir)
                    else:
                        logger.info("Thread: URL content is not a playlist, importing as single stream.")
                        # 如果不是播放列表，直接导入URL作为单个流
                        self.streams_to_add = [{
                            'name': f"Stream from {self.url_content}", # 自动生成一个名字
                            'url': self.url_content,
                            'status': '待检测',
                            'response_time': -1,
                            'resolution': 'N/A'
                        }]
                except InterruptedError as e:
                    self.error_message = str(e)
                    logger.info(self.error_message)
                    self.finished_signal.emit([], self.error_message)
                except requests.exceptions.RequestException as e:
                    self.error_message = f"获取URL内容时出错: {str(e)}，将直接导入URL作为单个流"
                    logger.warning(self.error_message)
                    # 回退到直接导入URL作为单个流
                    self.streams_to_add = [{
                        'name': f"Stream from {self.url_content}",
                        'url': self.url_content,
                        'status': '待检测',
                        'response_time': -1,
                        'resolution': 'N/A'
                    }]
                except Exception as e:
                    self.error_message = f"处理URL时发生未知错误: {str(e)}"
                    logger.error(self.error_message)
            else:
                # 如果剪贴板内容不是有效URL，尝试直接解析内容
                content = self.url_content.strip()
                
                # 检查是否为M3U格式
                is_m3u = content.startswith('#EXTM3U')
                
                # 检查是否为TXT格式 (#genre# 格式或包含URL和逗号的行)
                is_txt = ('#genre#' in content or 
                          (',' in content and ('http://' in content or 'https://' in content)))
                
                if is_m3u or is_txt:
                    logger.info(f"剪贴板内容识别为 {'M3U' if is_m3u else 'TXT'} 格式")
                    
                    # 创建临时目录和文件
                    temp_dir = create_temp_directory()
                    if not temp_dir:
                        self.error_message = "无法创建临时目录"
                        self.finished_signal.emit([], self.error_message)
                        return
                    
                    # 选择解析函数和临时文件名
                    if is_m3u:
                        temp_file = os.path.join(temp_dir, "temp_clipboard.m3u")
                        parse_function = parse_m3u
                    else:
                        temp_file = os.path.join(temp_dir, "temp_clipboard.txt")
                        parse_function = parse_txt
                    
                    # 写入临时文件
                    try:
                        with open(temp_file, 'w', encoding='utf-8') as f:
                            f.write(content)
                        
                        # 定义进度回调函数
                        def progress_callback(progress, current, total):
                            if self.is_cancelled:
                                raise InterruptedError("导入操作已取消")
                            self.progress_signal.emit(progress, current, total)
                        
                        # 解析文件
                        parsed_streams = parse_function(temp_file, progress_callback=progress_callback)
                        
                        # 检查解析结果
                        if parsed_streams:
                            self.streams_to_add = parsed_streams
                            logger.info(f"从剪贴板内容解析到 {len(parsed_streams)} 个流")
                        else:
                            # 如果解析失败，尝试提取URL
                            self.error_message = "无法从剪贴板内容解析到流，尝试提取URL"
                            logger.warning(self.error_message)
                            self.error_message = ""  # 清除错误信息，因为我们会尝试其他方法
                    except Exception as e:
                        logger.error(f"解析剪贴板内容时出错: {str(e)}")
                        self.error_message = f"解析剪贴板内容时出错: {str(e)}"
                    finally:
                        # 清理临时文件
                        clean_temp_directory(temp_dir)
                
                # 如果没有成功解析为M3U或TXT，或者解析失败，尝试提取URL
                if not self.streams_to_add:
                    lines = self.url_content.split('\n')
                    extracted_urls = []
                    
                    for line in lines:
                        line = line.strip()
                        # 检查行是否包含URL
                        if 'http://' in line or 'https://' in line:
                            # 尝试提取URL
                            import re
                            url_match = re.search(r'(https?://[^\s,]+)', line)
                            if url_match:
                                extracted_urls.append(url_match.group(1))
                    
                    if extracted_urls:
                        logger.info(f"从文本中提取到 {len(extracted_urls)} 个URL")
                        # 将提取的URL作为单独的流添加
                        for i, url in enumerate(extracted_urls):
                            self.streams_to_add.append({
                                'name': f"Stream {i+1} from clipboard",
                                'url': url,
                                'status': '待检测',
                                'response_time': -1,
                                'resolution': 'N/A'
                            })
                    else:
                        self.error_message = "剪贴板内容不包含有效的流数据或URL"
                        logger.warning(self.error_message)
                
            # 检查是否已取消
            if self.is_cancelled:
                self.error_message = "导入操作已取消"
                self.finished_signal.emit([], self.error_message)
                return
                
            self.finished_signal.emit(self.streams_to_add, self.error_message)
        except Exception as e:
            logger.error(f"Thread execution error: {str(e)}")
            self.error_message = f"线程执行时发生严重错误: {str(e)}"
            self.finished_signal.emit([], self.error_message)
    
    def cancel(self):
        """取消导入操作"""
        self.is_cancelled = True

class ImportFileThread(QThread):
    """文件导入线程类"""
    # 定义信号，参数可以是解析到的流列表和错误信息
    finished_signal = Signal(list, str) # streams, error_message
    progress_signal = Signal(int, int, int) # 进度百分比, 当前处理行数, 总行数
    
    def __init__(self, file_path, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.streams = []
        self.error_message = ""
        self.is_cancelled = False
    
    def run(self):
        try:
            if not os.path.exists(self.file_path):
                self.error_message = f"文件未找到: {self.file_path}"
                self.finished_signal.emit([], self.error_message)
                return
            
            # 定义进度回调函数
            def progress_callback(progress, current, total):
                if self.is_cancelled:
                    raise InterruptedError("导入操作已取消")
                self.progress_signal.emit(progress, current, total)
                
            try:
                file_ext = os.path.splitext(self.file_path)[1].lower()
                if file_ext == '.m3u' or file_ext == '.m3u8':
                    self.streams = parse_m3u(self.file_path, progress_callback=progress_callback)
                    logger.info(f"导入的 {len(self.streams)} 来自M3U文件的流")
                elif file_ext == '.txt':
                    self.streams = parse_txt(self.file_path, progress_callback=progress_callback)
                    logger.info(f"导入的 {len(self.streams)} 来自文本文件的流")
                else:
                    self.error_message = f"不支持的文件格式: {file_ext}"
                    self.finished_signal.emit([], self.error_message)
                    return
                
                # 检查是否已取消
                if self.is_cancelled:
                    self.error_message = "导入操作已取消"
                    self.finished_signal.emit([], self.error_message)
                    return
                    
                # Add IDs to all streams if they don't have one
                for i, stream in enumerate(self.streams):
                    if 'id' not in stream:
                        stream['id'] = i + 1
                
                self.finished_signal.emit(self.streams, "")
            except InterruptedError as e:
                self.error_message = str(e)
                logger.info(self.error_message)
                self.finished_signal.emit([], self.error_message)
            except Exception as e:
                self.error_message = f"导入流时出错: {str(e)}"
                logger.error(self.error_message)
                self.finished_signal.emit([], self.error_message)
        except Exception as e:
            logger.error(f"严重错误: {str(e)}")
            self.error_message = f"线程执行时发生严重错误: {str(e)}"
            self.finished_signal.emit([], self.error_message)
    
    def cancel(self):
        """取消导入操作"""
        self.is_cancelled = True

class StreamCheckThread(QThread):
    """用于在后台检查流的线程"""
    progress_signal = Signal(int, int, int)  # 进度百分比, 当前处理行数, 总行数
    stream_updated_signal = Signal(int, dict)  # 流索引和更新后的流信息
    finished_signal = Signal()  # 检查完成信号
    
    def __init__(self, streams, auto_clear=False, skip_same_domain_invalid=False, parent=None):
        super().__init__(parent)
        self.streams = streams
        self.auto_clear = auto_clear
        self.skip_same_domain_invalid = skip_same_domain_invalid
        self.is_running = False
        self.checker = None
        # 创建IPTVChecker实例
        from iptv_checker import IPTVChecker
        self.checker = IPTVChecker()
        
    def run(self):
        """运行检查流程"""
        # 标记正在运行
        self.is_running = True
        
        try:
            # 定义进度回调函数
            def progress_callback(progress, current, total):
                if not self.is_running:
                    return False  # 返回False来停止检查过程
                self.progress_signal.emit(progress, current, total)
                return True  # 继续检查
            
            # 设置回调函数
            self.checker.set_callbacks(progress_callback=progress_callback)
            
            # 设置跳过同域名无效源选项
            self.checker.skip_same_domain_invalid = self.skip_same_domain_invalid
            
            # 使用线程池执行流检查
            from concurrent.futures import ThreadPoolExecutor, as_completed
            
            max_workers = min(CONCURRENT_CHECKS, len(self.streams))
            
            # 创建流索引映射，用于跟踪每个流在原始列表中的位置
            stream_indices = {}
            for i, stream in enumerate(self.streams):
                stream_id = id(stream)  # 使用对象ID作为唯一标识
                stream_indices[stream_id] = i
            
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                # 提交所有任务
                futures = {executor.submit(self.checker.check_stream, stream): stream for stream in self.streams}
                
                # 处理完成的任务
                completed = 0
                total = len(self.streams)
                
                for future in as_completed(futures):
                    if not self.is_running:
                        # 取消所有未完成的任务
                        for f in futures:
                            if not f.done():
                                f.cancel()
                        break
                    
                    try:
                        # 获取检测结果
                        original_stream = futures[future]
                        updated_stream = future.result()
                        
                        # 找到流在原始列表中的索引
                        stream_idx = stream_indices.get(id(original_stream), -1)
                        
                        # 发送流更新信号
                        if stream_idx >= 0:
                            self.stream_updated_signal.emit(stream_idx, updated_stream)
                        
                        # 更新进度
                        completed += 1
                        progress = int(completed / total * 100)
                        self.progress_signal.emit(progress, completed, total)
                        
                    except Exception as e:
                        import traceback
                        traceback.print_exc()
                        logger.error(f"流检查线程错误: {str(e)}")
            
            # 如果需要自动清除无效源
            if self.auto_clear and self.is_running:
                # 过滤掉无效的流
                valid_streams = [s for s in self.streams if s.get('status', '').lower() == '正常']
                
                # 如果有无效源被移除，发出信号
                if len(valid_streams) < len(self.streams):
                    logger.info(f"自动移除了 {len(self.streams) - len(valid_streams)} 个无效源")
                    
                    # 更新结果
                    self.streams = valid_streams
        except Exception as e:
            import traceback
            traceback.print_exc()
            logger.error(f"流检查线程错误: {str(e)}")
        finally:
            # 完成后，发出完成信号
            self.is_running = False
            self.finished_signal.emit()
    
    def stop(self):
        """停止检查流程"""
        # 标记为不再运行，这将通过progress_callback的返回值停止检查过程
        self.is_running = False 