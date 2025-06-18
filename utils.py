#!/usr/bin/env python3
import os
import shutil
from urllib.parse import urlparse
from loguru import logger
def create_temp_directory(prefix="iptv_checker_"):
    """
    创建一个用于工作文件的临时目录。
    参数：
    prefix：目录名称的前缀
    返回：
    str：创建的目录的路径
    """
    import tempfile
    temp_dir = os.path.join(tempfile.gettempdir(), f"{prefix}{os.getpid()}")
    if not os.path.exists(temp_dir):
        try:
            os.makedirs(temp_dir)
        except Exception as e:
            logger.error(f"Failed to create temporary directory: {e}")
            return None
    return temp_dir

def clean_temp_directory(dir_path):
    """
    清理临时目录。
    参数：
    dir_path：要清理的目录的路径。
    """
    if dir_path and os.path.exists(dir_path):
        try:
            shutil.rmtree(dir_path)
            return True
        except Exception as e:
            logger.error(f"Failed to clean temporary directory: {e}")
            return False
    return False
def is_valid_url(url):
    """
    检查一个 URL 是否有效。
    参数：
    url：要检查的 URL
    返回：
    bool：如果是有效的 URL 则为真，否则为假。
    """
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def sanitize_filename(filename):
    """
    清理文件名以删除非法字符。
    参数：
    filename：要清理的文件名
    返回：
    str：清理后的文件名
    """
    # 将非法字符替换为下划线。
    illegal_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    # “尝试从URL中提取名称，并限制长度以避免路径过长错误”。
    if len(filename) > 200:
        base, ext = os.path.splitext(filename)
        filename = base[:196] + ext
    return filename

def format_bytes(size):
    """
    将字节格式化为人类可读的格式。
    参数：
    size：以字节为单位的大小。
    返回：
    str：人类可读的大小。
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{size:.2f} PB"

def extract_resolution_from_string(text):
    """
    尝试从字符串中提取分辨率信息。
    参数：
    text：可能包含分辨率信息的字符串。
    返回：
    元组：(宽度, 高度)；如果未找到，则返回(None, None)。
    """
    import re
    # 查找常见的分辨率模式，如 1920x1080、1280×720 等。
    resolution_pattern = r'(\d+)\s*[x×]\s*(\d+)'
    match = re.search(resolution_pattern, text)
    if match:
        try:
            width = int(match.group(1))
            height = int(match.group(2))
            return width, height
        except:
            pass
    # “尝试找到常见的分辨率名称。”
    if '4k' in text.lower() or '2160p' in text.lower():
        return 3840, 2160
    elif '1080p' in text.lower() or 'full hd' in text.lower() or 'fhd' in text.lower():
        return 1920, 1080
    elif '720p' in text.lower() or 'hd' in text.lower():
        return 1280, 720
    elif '480p' in text.lower() or 'sd' in text.lower():
        return 854, 480
    elif '360p' in text.lower():
        return 640, 360
    return None, None
def get_url_from_clipboard():
    """
    从剪贴板获取内容，其可能是一个URL、M3U数据或TXT数据
    Returns:
        str: 剪贴板中的内容，如果剪贴板为空则为 None
    """
    try:
        import pyperclip
        clipboard_content = pyperclip.paste()
        """
        检查剪贴板内容有效性
        判断内容是否为空或仅包含空白字符
        """
        if not clipboard_content or clipboard_content.isspace():
            return None
        """
        清理剪贴板内容
        移除首尾空白字符以获得纯净数据
        """
        clipboard_content = clipboard_content.strip()
        """
        返回预处理后的剪贴板内容
        保留原始格式以便后续处理M3U/TXT等格式数据
        """
        return clipboard_content
    except Exception as e:
        """
        异常处理
        记录剪贴板读取错误信息并返回None
        """
        logger.error(f"从剪贴板获取内容时出错: {str(e)}")
        return None