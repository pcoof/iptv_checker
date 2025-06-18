#!/usr/bin/env python3
import os
import sys
import tempfile
from loguru import logger
import json
# 常规应用程序设置
APP_NAME = "IPTV 检查器"
APP_VERSION = "1.0.0"
# 连接和超时设置
CONNECTION_TIMEOUT = 3  # 用于基本连接测试的秒数
STREAM_CHECK_TIMEOUT = 10  #流验证所需的秒数
OPENCV_TIMEOUT = 5  # OpenCV操作所需的秒数
# 性能设置
MAX_WORKERS = 10  # 同时检查线程的最大数量
# UI 和行为设置
CONCURRENT_CHECKS = 10  # 并发检查数量
REQUEST_TIMEOUT = 5  # 超时时间设置（秒）
AUTO_CLEAR_INVALID_STREAMS = False  # 是否自动清除无效的流
SAVE_STREAM_LIST = True  # 是否保存流列表
HIGH_CONCURRENCY_MODE = False  # 是否使用高并发模式（>1000流时推荐）
SKIP_SAME_DOMAIN_INVALID = False  # 检测到同一域名下多个源无效时，跳过该域名下剩余源的检测
# 界面主题设置
DEFAULT_THEME = 0  # 默认主题索引：0=深蓝主题, 1=紫罗兰主题, 2=深绿主题, 3=暗橙主题, 4=深灰主题
# 日志目录
LOG_DIR = os.path.join(tempfile.gettempdir(), "iptv-checker")
CONFIG_FILE = os.path.join(LOG_DIR, "settings.json") # 配置文件路径
STREAM_LIST_FILE = os.path.join(LOG_DIR, "stream_list.json") # 流列表文件路径
def setup_logging():
    """设置应用程序日志记录"""
    # 如果日志目录不存在，则创建它
    global LOG_DIR
    if not os.path.exists(LOG_DIR):
        try:
            os.makedirs(LOG_DIR)
        except Exception as e:
            print(f"警告：无法创建日志目录: {e}")
            # 回退到使用当前目录
            LOG_DIR = "."
    # 定义日志文件路径
    log_file = os.path.join(LOG_DIR, "iptv_checker.log")
    # 配置日志记录器
    logger.remove()  # 移除默认处理程序
    # 添加文件处理程序
    logger.add(
        log_file,
        rotation="500 KB",  # 当日志文件达到时进行轮换 500 KB
        retention="10 days",  # 保留日志10天
        compression="zip",  # 压缩旋转日志
        level="DEBUG"
    )
    # 添加控制台处理程序
    logger.add(
        sys.stderr,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="DEBUG"
    )
    logger.info(f"已开始 {APP_NAME} v{APP_VERSION}")
    logger.info(f"日志文件: {log_file}")
    logger.info(f"使用 {MAX_WORKERS} 工作线程")
    load_settings() # 加载用户设置
    # Check for OpenCV
    try:
        import cv2
        logger.info(f"OpenCV已找到且能正常工作 (版本 {cv2.__version__})")
    except Exception as e:
        logger.error(f"OpenCV检查失败: {e}. IPTV检查可能无法正常工作.")

def load_settings():
    """Load settings from config file"""
    global CONCURRENT_CHECKS, REQUEST_TIMEOUT, AUTO_CLEAR_INVALID_STREAMS, SAVE_STREAM_LIST, HIGH_CONCURRENCY_MODE, SKIP_SAME_DOMAIN_INVALID, DEFAULT_THEME
    
    try:
        # Try to load config file
        with open(CONFIG_FILE, 'r') as f:
                settings = json.load(f)
        
        # Apply settings
                CONCURRENT_CHECKS = settings.get('concurrent_checks', CONCURRENT_CHECKS)
                REQUEST_TIMEOUT = settings.get('request_timeout', REQUEST_TIMEOUT)
                AUTO_CLEAR_INVALID_STREAMS = settings.get('auto_clear_invalid_streams', AUTO_CLEAR_INVALID_STREAMS)
        SAVE_STREAM_LIST = settings.get('save_stream_list', SAVE_STREAM_LIST)
        HIGH_CONCURRENCY_MODE = settings.get('high_concurrency_mode', HIGH_CONCURRENCY_MODE)
        SKIP_SAME_DOMAIN_INVALID = settings.get('skip_same_domain_invalid', SKIP_SAME_DOMAIN_INVALID)
        DEFAULT_THEME = settings.get('default_theme', DEFAULT_THEME)
        
        logger.debug("配置已从文件加载")
    except FileNotFoundError:
        # Create default config file if not exists
        save_settings()
        logger.debug("配置文件不存在，已创建默认配置文件")
    except json.JSONDecodeError:
        logger.error("配置文件格式错误，使用默认配置")
        # Create default config file
        save_settings()
    except Exception as e:
        logger.error(f"加载配置时出错: {str(e)}")

def save_settings():
    """Save settings to config file"""
    try:
        settings = {
            'concurrent_checks': CONCURRENT_CHECKS,
            'request_timeout': REQUEST_TIMEOUT,
            'auto_clear_invalid_streams': AUTO_CLEAR_INVALID_STREAMS,
            'save_stream_list': SAVE_STREAM_LIST,
            'high_concurrency_mode': HIGH_CONCURRENCY_MODE,
            'skip_same_domain_invalid': SKIP_SAME_DOMAIN_INVALID,
            'default_theme': DEFAULT_THEME,
        }
        
        # Ensure config directory exists
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        
        # Save settings
        with open(CONFIG_FILE, 'w') as f:
            json.dump(settings, f, indent=4)
            
        logger.debug("配置已保存到文件")
    except Exception as e:
        logger.error(f"保存配置时出错: {str(e)}")

def save_stream_list(streams):
    """保存流列表到JSON文件"""
    if not SAVE_STREAM_LIST:
        logger.info("流列表保存功能已禁用，不保存列表")
        return False
    
    try:
        if not os.path.exists(LOG_DIR):
            os.makedirs(LOG_DIR)
        with open(STREAM_LIST_FILE, 'w', encoding='utf-8') as f:
            json.dump(streams, f, ensure_ascii=False, indent=4)
        logger.info(f"已保存 {len(streams)} 个流到 {STREAM_LIST_FILE}")
        return True
    except Exception as e:
        logger.error(f"保存流列表到 {STREAM_LIST_FILE} 时发生错误: {e}")
        return False

def load_stream_list():
    """从JSON文件加载流列表"""
    if not SAVE_STREAM_LIST:
        logger.info("流列表保存功能已禁用，不加载列表")
        return []
    
    try:
        if os.path.exists(STREAM_LIST_FILE):
            with open(STREAM_LIST_FILE, 'r', encoding='utf-8') as f:
                streams = json.load(f)
                logger.info(f"从 {STREAM_LIST_FILE} 加载了 {len(streams)} 个流")
                return streams
        else:
            logger.info(f"流列表文件 {STREAM_LIST_FILE} 不存在，返回空列表")
            return []
    except json.JSONDecodeError:
        logger.error(f"解析流列表文件 {STREAM_LIST_FILE} 失败，返回空列表")
        return []
    except Exception as e:
        logger.error(f"加载流列表时发生错误: {e}，返回空列表")
        return []

# 在模块加载时尝试加载设置
# setup_logging() 函数中已调用 load_settings()，此处无需重复调用
# load_settings() # 确保在应用程序启动时加载设置