#!/usr/bin/env python3
import re
import time
from urllib.parse import unquote
import pandas as pd
import numpy as np
def parse_m3u(file_path, progress_callback=None, chunk_size=1000):
    """
    解析 M3U/M3U8 播放列表文件为一个流列表。
    参数：
        file_path（文件路径）：M3U 文件的路径。
        progress_callback：可选的回调函数，用于报告进度。
        chunk_size：每次处理的行数，用于大文件分块处理。
    返回值：包含流信息的字典列表。
    """
    streams = []
    current_stream = None
    total_lines = 0
    processed_lines = 0
    
    # 首先获取文件总行数，用于进度计算
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 快速计算行数
            for _ in f:
                total_lines += 1
    except UnicodeDecodeError:
        # 如果 UTF-8 编码失败，尝试使用不同的编码
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                for _ in f:
                    total_lines += 1
        except Exception as e:
            raise ValueError(f"未能统计文件中的行数: {str(e)}")
    # 如果文件为空，直接返回
    if total_lines == 0:
        return streams
    # 读取和处理文件内容
    try:
        encoding = 'utf-8'
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                first_line = f.readline().strip()
                if not first_line.startswith('#EXTM3U'):
                    raise ValueError("不是有效的M3U文件，缺少#EXTM3U头")
        except UnicodeDecodeError:
            encoding = 'latin-1'
            with open(file_path, 'r', encoding=encoding) as f:
                first_line = f.readline().strip()
                if not first_line.startswith('#EXTM3U'):
                    raise ValueError("不是有效的M3U文件，缺少#EXTM3U头")
        # 重新打开文件进行分块处理
        with open(file_path, 'r', encoding=encoding) as f:
            # 跳过已经读取的第一行
            f.readline()
            processed_lines = 1
            # 报告初始进度
            if progress_callback:
                progress_callback(0, processed_lines, total_lines)
            lines_buffer = []
            for line in f:
                lines_buffer.append(line.strip())
                processed_lines += 1
                # 当缓冲区达到指定大小或读取完所有行时处理数据
                if len(lines_buffer) >= chunk_size or processed_lines >= total_lines:
                    # 处理缓冲区中的行
                    for line in lines_buffer:
                        if not line:
                            continue
                        if line.startswith('#EXTINF:'):
                            # 新的流条目的开始
                            current_stream = {'status': '未检测', 'resolution': 'N/A', 'response_time': -1}
                            # 提取流名称和任何其他属性
                            info_line = line[8:]  # Remove #EXTINF: prefix
                            # 提取持续时间（在第一个逗号之前）
                            if ',' in info_line:
                                duration_part, name_part = info_line.split(',', 1)
                                try:
                                    current_stream['duration'] = float(duration_part)
                                except:
                                    current_stream['duration'] = -1
                                current_stream['name'] = name_part.strip()
                            else:
                                # 未找到逗号，使用整行作为名称
                                current_stream['name'] = info_line.strip()
                            # 提取属性
                            attributes = re.findall(r'(\w+)="([^"]*)"', line)
                            for key, value in attributes:
                                current_stream[key.lower()] = value
                            # 特别检查tvg-logo属性
                            logo_match = re.search(r'tvg-logo="([^"]*)"', line)
                            if logo_match:
                                current_stream['tvg-logo'] = logo_match.group(1)
                            # 特别检查group-title属性
                            group_match = re.search(r'group-title="([^"]*)"', line)
                            if group_match:
                                current_stream['group'] = group_match.group(1)
                                current_stream['group-title'] = group_match.group(1)  # 保持兼容性
                        elif line.startswith('#EXTVLCOPT:') and current_stream:
                            # VLC 选项行——可能包含有用信息
                            if 'http-user-agent' in line:
                                agent = line.split('http-user-agent=')[-1].strip()
                                if agent.startswith('"') and agent.endswith('"'):
                                    agent = agent[1:-1]
                                current_stream['user_agent'] = agent
                        elif line.startswith('#') or not line:
                            # 其他注释或空行，忽略
                            continue
                        elif current_stream is not None:
                            # 这应该是网址
                            current_stream['url'] = line
                            streams.append(current_stream)
                            current_stream = None
                    # 清空缓冲区
                    lines_buffer = []
                    # 报告进度
                    if progress_callback:
                        progress = int((processed_lines / total_lines) * 100)
                        progress_callback(progress, processed_lines, total_lines)
    except Exception as e:
        raise ValueError(f"解析M3U文件时出错: {str(e)}")
    return streams
def parse_txt(file_path, progress_callback=None, chunk_size=1000):
    """
    解析带有流 URL 的文本文件到流列表中。支持各种常见格式：
    - 名称，URL。
    - URL，名称。
    - URL #名称。
    - URL中包含#号分隔的多个地址。例如：名称,http://url1#http://url2#http://url3
    - 只有 URL（名称从 URL 派生）。
    - 分类,#genre#（表示频道分类标记）。
    参数：
    file_path：文本文件的路径。
    progress_callback：可选的回调函数，用于报告进度。
    chunk_size：每次处理的行数，用于大文件分块处理。
    返回：
    带有流信息的字典列表。
    """
    streams = []
    total_lines = 0
    processed_lines = 0
    # 首先获取文件总行数，用于进度计算
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # 快速计算行数
            for _ in f:
                total_lines += 1
    except UnicodeDecodeError:
        # 如果 UTF-8 编码失败，尝试使用不同的编码
        try:
            with open(file_path, 'r', encoding='latin-1') as f:
                for _ in f:
                    total_lines += 1
        except Exception as e:
            raise ValueError(f"未能统计文件中的行数: {str(e)}")
    
    # 如果文件为空，直接返回
    if total_lines == 0:
        return streams
    
    # 读取和处理文件内容
    try:
        encoding = 'utf-8'
        try:
            # 尝试以UTF-8打开文件
            with open(file_path, 'r', encoding=encoding) as f:
                f.readline()  # 测试是否可以读取
        except UnicodeDecodeError:
            encoding = 'latin-1'
        
        # 重新打开文件进行分块处理
        with open(file_path, 'r', encoding=encoding) as f:
            # 报告初始进度
            if progress_callback:
                progress_callback(0, 0, total_lines)
            
            lines_buffer = []
            current_group = None  # 当前频道分类
            
            for i, line in enumerate(f):
                lines_buffer.append(line.strip())
                processed_lines += 1
                
                # 当缓冲区达到指定大小或读取完所有行时处理数据
                if len(lines_buffer) >= chunk_size or processed_lines >= total_lines:
                    # 处理缓冲区中的行
                    for line in lines_buffer:
                        if not line or (line.startswith('#') and ' ' not in line):
                            # 空行或简单注释
                            continue
                        
                        # 检查是否是分类标记行 "分类,#genre#"
                        if ',' in line and line.endswith('#genre#'):
                            current_group = line.split(',')[0].strip()
                            continue
                        
                        stream = {'status': '未检测', 'resolution': 'N/A', 'response_time': -1}
                        
                        # 如果有当前分类，添加到流信息中
                        if current_group:
                            stream['group'] = current_group
                            stream['group-title'] = current_group  # 保持兼容性
                        
                        # 检查常见格式
                        if ',' in line:
                            # 可能是名称、网址或网址、名称的格式
                            parts = [p.strip() for p in line.split(',', 1)]
                            
                            # 检查第一部分是否是一个 URL
                            if parts[0].startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
                                # URL在前面，名称在后面
                                stream['url'] = parts[0]
                                stream['name'] = parts[1] if len(parts) > 1 else _extract_name_from_url(parts[0])
                            else:
                                # 名称在前面，URL在后面
                                stream['name'] = parts[0]
                                # 检查是否有#分割的多URL (支持 名称,URL1#URL2 格式)
                                if len(parts) > 1:
                                    stream['url'] = parts[1]
                                else:
                                    stream['url'] = ''
                        
                        elif '#' in line and not line.startswith('#'):
                            # 检查是否是"URL #名称"格式或是包含多个URL的格式
                            parts = line.split('#')
                            # 如果第一个部分是URL，并且后面的部分也是URL，则这是多URL格式
                            if parts[0].startswith(('http://', 'https://', 'rtmp://', 'rtsp://')) and \
                               any(p.strip().startswith(('http://', 'https://', 'rtmp://', 'rtsp://')) for p in parts[1:]):
                                # 这是多URL格式，但没有名称，需要从URL提取名称
                                stream['url'] = line  # 保持整行作为URL（包含#）
                                stream['name'] = _extract_name_from_url(parts[0])
                            else:
                                # 传统的"URL #名称"格式
                                stream['url'] = parts[0]
                                stream['name'] = parts[1] if len(parts) > 1 else _extract_name_from_url(parts[0])
                        else:
                            # 只是一个 URL 或未知格式
                            if line.startswith('#'):
                                # 注释行，可能包含名称
                                stream['name'] = line[1:].strip()
                                continue
                            elif line.startswith(('http://', 'https://', 'rtmp://', 'rtsp://')):
                                stream['url'] = line
                                stream['name'] = _extract_name_from_url(line)
                            else:
                                # 不是可识别的 URL 格式，用作名称
                                stream['name'] = line
                                continue
                        
                        # 只有当流有URL时才添加
                        if stream.get('url'):
                            stream['id'] = len(streams) + 1  # 使用流列表长度+1作为ID
                            streams.append(stream)
                    
                    # 清空缓冲区
                    lines_buffer = []
                    # 报告进度
                    if progress_callback:
                        progress = int((processed_lines / total_lines) * 100)
                        progress_callback(progress, processed_lines, total_lines)
    except Exception as e:
        raise ValueError(f"解析TXT文件时出错: {str(e)}")
    return streams

def export_m3u(streams, file_path):
    """
    将流导出为 M3U 格式。
    参数：streams（流的列表，其中每个流是一个字典），file_path（保存 M3U 文件的路径）。
    返回值：无。
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        # Write M3U header 写入M3U头
        f.write("#EXTM3U\n")
        for stream in streams:
            name = stream.get('name', '未命名 Stream')
            url = stream.get('url', '')
            if not url:
                continue
            # 编写带有元数据的EXTINF行
            f.write(f'#EXTINF:-1 tvg-id="{stream.get("id", "")}" tvg-name="{name}"')
            # 如果可用则添加分辨率
            # resolution = stream.get('resolution', 'N/A') # 注释掉获取分辨率
            # if resolution != 'N/A': # 注释掉判断分辨率
            #     f.write(f' tvg-resolution="{resolution}"') # 注释掉写入分辨率
            # 如果可用，添加组标题
            group_title = stream.get('group', stream.get('group-title', 'IPTV'))
            # 如果可用则添加位置信息
            # location = stream.get('location', '')
            # if location:
            #     f.write(f' tvg-country="{location}"')
            # 如果有可用的标志则添加标志
            logo = stream.get('tvg-logo', '')
            if logo:
                f.write(f' tvg-logo="{logo}"')
            f.write(f' group-title="{group_title}",{name}\n')
            # 添加任何自定义的用户代理
            if 'user_agent' in stream:
                f.write(f'#EXTVLCOPT:http-user-agent={stream["user_agent"]}\n')
            # Write the URL
            f.write(f'{url}\n')
def export_txt(streams, file_path):
    """
    导出流为 TXT 格式
    参数：
        streams：流字典列表
        file_path：保存 TXT 文件的路径
    返回： 无
    """
    with open(file_path, 'w', encoding='utf-8') as f:
        # Write header comment
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"# IPTV Stream 列表 - 生成时间 {now}\n")
        f.write(f"# 总数: {len(streams)}\n\n")
        # 按分组整理流
        groups = {}
        ungrouped = []
        for stream in streams:
            name = stream.get('name', '未命名')
            url = stream.get('url', '')
            group = stream.get('group', stream.get('group-title'))
            if not url:
                continue
            if group:
                if group not in groups:
                    groups[group] = []
                groups[group].append((name, url))
            else:
                ungrouped.append((name, url))
        # 先写入分组的流
        for group, group_streams in groups.items():
            # 写入分组标记
            f.write(f"{group},#genre#\n")
            # 写入该分组下的所有流
            for name, url in group_streams:
                f.write(f"{name},{url}\n")
            # 分组之间添加空行
            f.write("\n")
        # 写入未分组的流
        if ungrouped:
            for name, url in ungrouped:
                f.write(f"{name},{url}\n")
def _extract_name_from_url(url):
    """
    从 URL 中提取一个合理的名称。
    参数：
        url：流 URL。
    返回：
        提取的名称或"未命名流"。
    """
    try:
        # 尝试从路径中提取有意义的部分。
        from urllib.parse import urlparse
        parsed = urlparse(url)
        path = unquote(parsed.path)
        # 检查路径是否有可识别的部分
        if path:
            # 删除扩展名和前导斜杠
            path = path.rstrip('/').split('/')[-1]
            if '.' in path:
                path = path.rsplit('.', 1)[0]
            # 用空格替换下划线和破折号
            path = path.replace('_', ' ').replace('-', ' ')
            # 如果全部是小写或全部是大写，则转换为标题大小写
            if path.islower() or path.isupper():
                path = path.title()
            if len(path) > 3:  # 只有在内容不太简短的情况下才返回
                return path
        # 回退：使用网络位置
        netloc = parsed.netloc
        if netloc:
            if ':' in netloc:
                netloc = netloc.split(':', 1)[0]  # Remove port
            return f"Stream from {netloc}"
    except:
        pass
    return "Unnamed Stream"

def merge_duplicate_channels(self):
    """使用Pandas优化的频道合并函数"""
    if not self.streams:
        return []
    
    # 转换为DataFrame以实现高效操作
    df = pd.DataFrame(self.streams)
    
    # 填充缺失值
    df['name'] = df['name'].fillna('')
    df['status'] = df['status'].fillna('')
    df['resolution'] = df['resolution'].fillna('N/A')
    df['response_time'] = df['response_time'].fillna(-1)
    
    # 创建用于排序的辅助列
    df['status_rank'] = df['status'].apply(lambda s: 0 if s == '正常' else 1)
    df['resolution_pixels'] = df['resolution'].apply(self._resolution_to_pixels)
    
    # 分组并按优先级排序
    result = []
    for name, group in df.groupby('name'):
        if not name:
            continue
            
        # 按状态、分辨率和响应时间排序
        sorted_group = group.sort_values(
            by=['status_rank', 'resolution_pixels', 'response_time'],
            ascending=[True, False, True]
        )
        
        # 获取最佳流
        best_stream = sorted_group.iloc[0].to_dict()
        
        # 添加备选URL
        if len(sorted_group) > 1:
            best_stream['alternative_urls'] = []
            for _, row in sorted_group.iloc[1:].iterrows():
                best_stream['alternative_urls'].append({
                    'url': row.get('url', ''),
                    'status': row.get('status', ''),
                    'resolution': row.get('resolution', ''),
                    'response_time': row.get('response_time', -1)
                })
        
        result.append(best_stream)
    
    return result