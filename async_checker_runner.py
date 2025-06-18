from PySide6.QtCore import QObject, Signal
from loguru import logger
import asyncio

class AsyncCheckerRunner(QObject):
    """运行异步检查器的包装类"""
    progress_updated = Signal(int, int, int)
    status_updated = Signal(str)
    finished = Signal(list)
    
    def __init__(self, checker, streams):
        super().__init__()
        self.checker = checker
        self.streams = streams
        
    def run(self):
        """运行异步检查"""
        # 设置回调
        self.checker.set_callbacks(
            progress_callback=self._progress_callback,
            status_callback=self._status_callback
        )
        
        # 创建并运行事件循环
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            results = loop.run_until_complete(self.checker.check_all_streams(self.streams))
            self.finished.emit(results)
        except Exception as e:
            logger.error(f"异步检查错误: {str(e)}")
            self.finished.emit([])
            
    def _progress_callback(self, progress, current, total):
        """进度回调"""
        self.progress_updated.emit(progress, current, total)
        
    def _status_callback(self, message):
        """状态回调"""
        self.status_updated.emit(message) 