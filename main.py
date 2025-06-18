import sys
from PySide6.QtWidgets import QApplication
from gui import IPTVCheckerGUI
from config import setup_logging

def main():
    """IPTV 流检查器应用程序的入口点"""
    # 设置日志记录
    setup_logging()
    
    # 创建并启动应用程序
    app = QApplication(sys.argv)
    app.setOrganizationName("ccy")
    app.setApplicationName("IPTV 流检测器")
    app.setStyle("Fusion")
    
    # 创建并显示主窗口
    IPTVCheckerGUI().show()
    
    # 启动应用程序事件循环
    sys.exit(app.exec())
    
if __name__ == "__main__":
    main()