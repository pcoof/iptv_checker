#!/usr/bin/env python3
# 修改记录：
# 1. 合并了"导入流"和"导入TXT"按钮，统一使用"导入流"按钮，支持M3U和TXT格式
# 2. 在列表视图右键菜单中添加了"从剪贴板导入"选项，带有edit-paste图标
# 3. 改进了剪贴板导入功能的错误处理，添加了URL验证和友好的错误提示
# 4. 增强了剪贴板导入功能，支持自动识别M3U和TXT格式的内容
# 5. 禁用了列表视图中右键菜单的自动弹出，改为使用F10键或菜单键触发
# 6. 改进了检测流程，支持实时更新列表视图，提供即时反馈
# 7. 进一步优化了实时更新机制，确保每个流检测完成后立即更新UI
# 8. 将停止检测按钮的样式改为红色，使其更加醒目
import os
import time
import json
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar, QLabel, 
    QFileDialog, QMessageBox, QAbstractItemView, QMenu, QLineEdit, 
    QGroupBox, QSplitter, QToolButton, QTextEdit, QSizePolicy, QDialog, 
    QFormLayout, QCheckBox, QDialogButtonBox, QSpinBox, QComboBox, QTabWidget,
    QStyle
)
from PySide6.QtCore import Qt, QUrl, QTimer, QStandardPaths, QSize
from PySide6.QtGui import QColor, QIcon, QGuiApplication, QAction, QKeySequence, QDesktopServices, QIntValidator, QPalette
from loguru import logger
from iptv_checker import IPTVChecker
from config import (
    MAX_WORKERS, APP_NAME, APP_VERSION, CONNECTION_TIMEOUT, 
    STREAM_CHECK_TIMEOUT, OPENCV_TIMEOUT, setup_logging, 
    save_settings, load_settings, CONCURRENT_CHECKS, REQUEST_TIMEOUT, 
    AUTO_CLEAR_INVALID_STREAMS, CONFIG_FILE, 
    save_stream_list, load_stream_list, HIGH_CONCURRENCY_MODE, SAVE_STREAM_LIST,
    SKIP_SAME_DOMAIN_INVALID, DEFAULT_THEME
)
from utils import get_url_from_clipboard, is_valid_url, create_temp_directory, clean_temp_directory
import requests
from async_iptv_checker import AsyncIPTVChecker

# 导入拆分后的模块
from stream_formats import parse_m3u, parse_txt
from custom_widgets import URLTableWidgetItem
from thread_classes import ImportUrlThread, ImportFileThread, StreamCheckThread
from async_checker_runner import AsyncCheckerRunner
from settings_dialog import SettingsDialog

class IPTVCheckerGUI(QMainWindow):
    """IPTV流检查器应用程序的主窗口"""
    def __init__(self):
        super().__init__()
        self.checker = IPTVChecker()
        self.import_thread = None # 用于URL导入的线程实例
        self.check_thread = None
        self.streams = []
        self.clipboard_timer = None
        self.last_clipboard_content = None
        self._is_updating_from_code = False # 添加标志以防止递归更新
        self.temp_directory = create_temp_directory() # 创建临时目录并存储路径
        self.is_checking = False # 检测状态标志
        
        self.load_app_settings() # 加载应用设置
        self.init_ui() # 初始化用户界面
        self.setup_clipboard_monitoring() # 设置剪贴板监控
        self.apply_stylesheet() # 应用样式表
        self.setWindowTitle("IPTV 流检测器")
        self.resize(800, 800)
        self.center_window() # 居中窗口
        # 设置键盘快捷键
        self.setup_shortcuts()
        # 启用拖放功能
        self.setAcceptDrops(True)
        
        # 启动时加载之前的流列表
        self.load_stream_list_on_startup()
    
    def apply_settings_changes(self):
        """应用通过设置对话框更改的设置"""
        self.checker.update_settings(CONCURRENT_CHECKS, REQUEST_TIMEOUT)
        
        logger.info(f"主窗口应用新设置: 并发={CONCURRENT_CHECKS}, 超时={REQUEST_TIMEOUT}, 高并发模式={HIGH_CONCURRENCY_MODE}")
        
        # 如果当前主题与默认主题不同，则应用默认主题
        if not hasattr(self, 'current_theme_index') or self.current_theme_index != DEFAULT_THEME:
            self.current_theme_index = DEFAULT_THEME - 1  # 设为前一个主题，以便switch_theme能切换到正确的主题
            self.switch_theme()  # 切换到默认主题
        
    def load_app_settings(self):
        """加载并应用配置设置"""
        load_settings() # 从config.py加载或创建配置文件
        self.checker.update_settings(CONCURRENT_CHECKS, REQUEST_TIMEOUT)
        # 其他设置的应用可以在这里添加，例如影响UI或行为的设置
        logger.info(f"应用设置: 并发数={CONCURRENT_CHECKS}, 超时={REQUEST_TIMEOUT}")
    
    def clear_invalid_streams(self, silent=False):
        """清除所有标记为无效的流"""
        if not self.streams:
            if not silent:
                QMessageBox.information(self, "信息", "列表中没有流可清除。")
            return
        initial_count = len(self.streams)
        # 过滤掉无效的流 ('无效源', '错误', 或者任何非 '正常' 的状态)
        # 我们需要更精确地定义什么是"无效"。通常是 '无效源' 或包含 '错误' 的状态。
        valid_streams = [s for s in self.streams if s.get('status', '').lower() == '正常']
        num_removed = initial_count - len(valid_streams)
        if num_removed > 0:
            self.streams = valid_streams
            self.update_table(self.streams) # 假设 self.streams 是表格的数据源
            if not silent:
                QMessageBox.information(self, "操作完成", f"已移除 {num_removed} 个无效源。")
            logger.info(f"已自动/手动移除 {num_removed} 个无效源。")
            self.update_status_bar(f"已移除 {num_removed} 个无效源。")
        elif not silent:
            QMessageBox.information(self, "信息", "未找到无效源进行清除。")
        # 如果有自动清除功能，并且表格正在显示，可能需要更新表格视图
        if hasattr(self, 'stream_table'):
            self.stream_table.viewport().update()
            
    def open_settings_dialog(self):
        """打开设置对话框"""
        dialog = SettingsDialog(self)
        if dialog.exec():
            logger.info("设置对话框已接受")
            # 主窗口可能需要根据新设置更新其UI或行为
            # self.apply_settings_changes() # 已在SettingsDialog.accept()中调用
        else:
            logger.info("设置对话框已取消")
            
    def init_ui(self):
        """初始化用户界面"""
        # 创建中心部件和布局
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        # 创建一个用于可调整大小部分的拆分器
        splitter = QSplitter(Qt.Orientation.Vertical)
        main_layout.addWidget(splitter)
        # 上部 - 流表及控件
        upper_widget = QWidget()
        upper_layout = QVBoxLayout(upper_widget)
        upper_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(upper_widget)
        # 创建控件布局
        controls_layout = QHBoxLayout()
        
        # 进出口管制
        file_group = QGroupBox("文件操作")
        file_layout = QHBoxLayout(file_group)
        self.import_button = QPushButton("导入流")
        self.import_button.setIcon(QIcon.fromTheme("document-open"))
        self.import_button.setToolTip("导入IPTV流文件，支持M3U和TXT格式")
        self.import_button.clicked.connect(self.open_import_dialog)
        file_layout.addWidget(self.import_button)
        
        # 添加带有下拉菜单的剪贴板按钮
        self.clipboard_button = QToolButton()
        self.clipboard_button.setText("剪贴板")
        self.clipboard_button.setIcon(QIcon.fromTheme("edit-paste"))
        self.clipboard_button.setToolTip("从剪贴板导入URL (Ctrl+V)")
        self.clipboard_button.clicked.connect(self.import_from_clipboard)
        file_layout.addWidget(self.clipboard_button)
        self.export_m3u_button = QPushButton("导出 M3U")
        self.export_m3u_button.setIcon(QIcon.fromTheme("document-save"))
        self.export_m3u_button.clicked.connect(lambda: self.export_streams("m3u"))
        file_layout.addWidget(self.export_m3u_button)
        self.export_txt_button = QPushButton("导出 TXT")
        self.export_txt_button.setIcon(QIcon.fromTheme("document-save-as"))
        self.export_txt_button.clicked.connect(lambda: self.export_streams("txt"))
        file_layout.addWidget(self.export_txt_button)
        controls_layout.addWidget(file_group)
        # 设置按钮
        self.settings_button = QToolButton()
        self.settings_button.setIcon(QIcon.fromTheme("preferences-system")) # 使用系统主题图标
        if self.settings_button.icon().isNull(): # 如果主题图标不可用，尝试备用图标
            # 在Windows上，可以尝试使用QStyle的标准图标
            style = QApplication.style()
            self.settings_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.settings_button.setToolTip("打开设置")
        self.settings_button.clicked.connect(self.open_settings_dialog)
        
        # 添加主题切换按钮
        self.theme_button = QToolButton()
        self.theme_button.setIcon(QIcon.fromTheme("preferences-desktop-theme"))
        if self.theme_button.icon().isNull():
            style = QApplication.style()
            self.theme_button.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DesktopIcon))
        self.theme_button.setToolTip("切换主题")
        self.theme_button.clicked.connect(self.switch_theme)
        
        # 将 controls_layout 和 top_right_layout 包含在一个垂直布局中，或者直接将 top_right_layout 添加到 main_layout
        # 这里我们创建一个包含原 controls_layout 和新 top_right_layout 的容器
        header_layout = QHBoxLayout()
        header_layout.addLayout(controls_layout)
        header_layout.addStretch(1)
        header_layout.addWidget(self.theme_button)
        header_layout.addWidget(self.settings_button)
        upper_layout.addLayout(header_layout) # 替换原来的 upper_layout.addLayout(controls_layout)

        # 导入进度条和取消按钮
        self.progress_layout = QHBoxLayout()
        self.import_progress_bar = QProgressBar()
        self.import_progress_bar.setVisible(False) # 初始隐藏
        self.import_progress_bar.setRange(0, 100)
        self.import_progress_bar.setValue(0)
        self.progress_layout.addWidget(self.import_progress_bar)

        self.cancel_import_button = QPushButton("取消导入")
        self.cancel_import_button.setIcon(QIcon.fromTheme("process-stop"))
        self.cancel_import_button.setVisible(False) # 初始隐藏
        self.cancel_import_button.clicked.connect(self.cancel_current_import)
        self.progress_layout.addWidget(self.cancel_import_button)
        upper_layout.addLayout(self.progress_layout)

        # 检查控件
        check_group = QGroupBox("检测操作")
        check_layout = QHBoxLayout(check_group)
        self.check_button = QPushButton("检测所有流")
        self.check_button.setIcon(QIcon.fromTheme("view-refresh"))
        self.check_button.clicked.connect(self.check_streams)
        check_layout.addWidget(self.check_button)
        self.check_selected_button = QPushButton("检测选中项")
        self.check_selected_button.setIcon(QIcon.fromTheme("view-filter"))
        self.check_selected_button.clicked.connect(self.check_selected_streams)
        check_layout.addWidget(self.check_selected_button)
        self.stop_button = QPushButton("停止检测")
        self.stop_button.setIcon(QIcon.fromTheme("process-stop"))
        self.stop_button.clicked.connect(self.stop_checking)
        self.stop_button.setEnabled(False)
        check_layout.addWidget(self.stop_button)
        self.auto_clear_invalid_checkbox = QCheckBox("自动清除无效源")
        self.auto_clear_invalid_checkbox.setToolTip("检测期间自动去掉URL无效的数据")
        check_layout.addWidget(self.auto_clear_invalid_checkbox)
        self.clear_invalid_button = QPushButton("清除无效源")
        self.clear_invalid_button.setIcon(QIcon.fromTheme("edit-delete"))
        self.clear_invalid_button.clicked.connect(self.clear_invalid_button_clicked)

        check_layout.addWidget(self.clear_invalid_button)
        controls_layout.addWidget(check_group)
        # 筛选控件
        filter_group = QGroupBox("筛选选项")
        filter_layout = QHBoxLayout(filter_group)
        filter_layout.addWidget(QLabel("状态:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["全部", "正常", "错误", "未检测"])
        self.status_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addWidget(QLabel("最低分辨率:"))
        self.resolution_filter = QComboBox()
        self.resolution_filter.addItems(["全部", "4K", "FHD", "HD", "SD"])
        self.resolution_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.resolution_filter)
        filter_layout.addWidget(QLabel("最大响应时间:"))
        self.response_filter = QComboBox()
        self.response_filter.addItems(["全部", "500毫秒", "1000毫秒", "2000毫秒", "5000毫秒"])
        self.response_filter.currentTextChanged.connect(self.apply_filters)
        filter_layout.addWidget(self.response_filter)
        self.merge_checkbox = QCheckBox("合并相似频道")
        filter_layout.addWidget(self.merge_checkbox)
        controls_layout.addWidget(filter_group)
        # 创建流列表的表
        self.create_stream_table()
        upper_layout.addWidget(self.stream_table)
        # 下部 - 状态与进展
        lower_widget = QWidget()
        lower_layout = QVBoxLayout(lower_widget)
        lower_layout.setContentsMargins(0, 0, 0, 0)
        splitter.addWidget(lower_widget)
        # 为状态/日志和流详细信息添加选项卡
        tabs = QTabWidget()
        lower_layout.addWidget(tabs)
        # 状态选项卡
        status_widget = QWidget()
        status_layout = QVBoxLayout(status_widget)
        # 进度条和标签
        progress_layout = QHBoxLayout()
        self.status_label = QLabel("就绪")
        progress_layout.addWidget(self.status_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar)
        status_layout.addLayout(progress_layout)
        # Log display
        self.log_display = QTextEdit()
        self.log_display.setReadOnly(True)
        status_layout.addWidget(self.log_display)
        tabs.addTab(status_widget, "状态 & 日志")
        # 流详情选项卡
        details_widget = QWidget()
        details_layout = QVBoxLayout(details_widget)
        self.details_display = QTextEdit()
        self.details_display.setReadOnly(True)
        details_layout.addWidget(self.details_display)
        tabs.addTab(details_widget, "流详情")
        # 设置分割器比例
        splitter.setSizes([500, 200])
        # 为表格设置右键上下文菜单
        self.stream_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.stream_table.customContextMenuRequested.connect(self.show_context_menu)
        # 初始日志消息
        self.add_log_message("应用已启动")

    def add_log_message(self, message):
        """在日志显示中添加一条消息"""
        timestamp = time.strftime("%H:%M:%S")
        self.log_display.append(f"[{timestamp}] {message}")

    def update_status_bar(self, message):
        """更新状态栏显示的消息（兼容旧代码）"""
        self.status_label.setText(message)
        self.add_log_message(message)
        
    def setup_clipboard_monitoring(self):
        """Set up clipboard monitoring for automatic URL detection"""
        # 不再监控剪贴板，仅初始化相关变量
        self.clipboard_timer = None
        self.last_clipboard_content = None
        
    def create_stream_table(self):
        """创建并配置用于显示流数据的表格"""
        # 创建自定义表格类，重写鼠标释放事件
        class CustomTableWidget(QTableWidget):
            def __init__(self, parent=None):
                super().__init__(parent)
                self.parent_gui = parent
                
            def mouseReleaseEvent(self, event):
                # 调用原始的鼠标释放事件处理
                super().mouseReleaseEvent(event)
                
                # 右键点击不自动弹出菜单，而是由F10或菜单键触发
                # 这里不做任何处理，让默认的contextMenuEvent来处理
        
        # 使用自定义表格类
        self.stream_table = CustomTableWidget(self)
        self.stream_table.setColumnCount(8)
        self.stream_table.setHorizontalHeaderLabels([
            "选择", "      名称      ", "URL", "分类", "归属地", "分辨率", "响应时间 (毫秒)", "状态"
        ])
        # 配置表格外观
        header = self.stream_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)  # 选择
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)  # Name - 可调整但不自动拉伸
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)  # URL - 自动拉伸占用更多空间
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)  # 分类
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)  # 归属地
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)  # 分辨率
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)  # 响应时间
        header.setSectionResizeMode(7, QHeaderView.ResizeMode.ResizeToContents)  # 状态
        
        # 设置列宽度
        self.stream_table.setColumnWidth(1, 100)  # 名称列宽度设为150像素
        # 启用双击编辑功能，但仅限于名称列
        self.stream_table.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked)
        # 添加双击事件处理
        self.stream_table.cellDoubleClicked.connect(self.handle_cell_double_click)
        # 添加编辑完成事件处理
        self.stream_table.itemChanged.connect(self.handle_item_changed)
        # 启用排序
        self.stream_table.setSortingEnabled(True)
        # 启用多项选择
        self.stream_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        # 连接选择更改信号
        self.stream_table.itemSelectionChanged.connect(self.update_stream_details)
        # 启用隔行背景色
        self.stream_table.setAlternatingRowColors(True)
        # 设置表格大小调整时自动调整列宽
        self.stream_table.horizontalHeader().setStretchLastSection(False)
        self.stream_table.resizeColumnsToContents()
        
        # 禁用右键菜单自动弹出，改为使用菜单键或F10触发
        self.stream_table.setContextMenuPolicy(Qt.ContextMenuPolicy.DefaultContextMenu)
        
    def setup_shortcuts(self):
        """设置键盘快捷键"""
        # 添加Ctrl+V快捷键导入剪贴板数据
        from PySide6.QtGui import QKeySequence, QShortcut
        paste_shortcut = QShortcut(QKeySequence("Ctrl+V"), self)
        paste_shortcut.activated.connect(self.import_from_clipboard)
        
        # 添加F10快捷键显示上下文菜单
        menu_shortcut = QShortcut(QKeySequence("F10"), self)
        menu_shortcut.activated.connect(self.show_menu_at_cursor)
        
    def import_from_clipboard(self):
        """当按钮被点击时，从剪贴板导入内容。
        
        支持自动识别以下格式：
        1. M3U格式：以#EXTM3U开头的内容
        2. TXT格式：包含#genre#或URL+逗号格式的内容
        3. 单个或多个URL：从文本中提取URL
        """
        clipboard_content = QGuiApplication.clipboard().text()
        if not clipboard_content:
            QMessageBox.information(self, "剪贴板导入", "剪贴板中未检测到内容。")
            return
            
        # 检查剪贴板内容是否包含URL或是有效的M3U/TXT格式
        from utils import is_valid_url
        
        # 检查是否是URL或包含URL
        contains_url = False
        lines = clipboard_content.split('\n')
        for line in lines:
            line = line.strip()
            if is_valid_url(line) or 'http://' in line or 'https://' in line:
                contains_url = True
                break
                
        if not contains_url:
            QMessageBox.information(self, "剪贴板导入", "剪贴板内容不包含有效的URL或流数据。\n请确保内容包含http://或https://开头的链接。")
            return
            
        # 内容看起来有效，继续导入
        self.import_url_from_clipboard(clipboard_content)
            
    def open_import_dialog(self):
        """打开文件选择对话框以导入流文件"""
        # 调用import_streams方法，不传递参数，让它自己打开文件对话框
        self.import_streams()
        
    def open_import_txt_dialog(self):
        """专门打开TXT格式文件导入对话框"""
        dialog_title = "选择TXT格式IPTV流文件"
        file_filter = "文本文件 (*.txt);;所有文件 (*.*)"
        download_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        file_path, _ = QFileDialog.getOpenFileName(self, dialog_title, download_dir, file_filter)
        if file_path:  # 用户选择了文件
            self.import_streams(file_path)
        
    def center_window(self):
        """将窗口居中显示在屏幕上"""
        QTimer.singleShot(0, self._adjust_window_position)
        
    def _adjust_window_position(self):
        """调整窗口位置到屏幕中央"""
        # 获取屏幕几何信息
        screen_geometry = QGuiApplication.primaryScreen().availableGeometry()
        # 计算窗口居中位置
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        # 移动窗口到居中位置
        self.move(x, y)
        
    def apply_stylesheet(self):
        """应用自定义样式表以改善用户界面外观"""
        # 随机选择一个主题颜色方案
        import random
        
        # 定义几种不同的主题配色
        themes = [
            # 深蓝主题
            {
                "bg": "#002933", 
                "secondary_bg": "#002900",
                "text": "#ffffff",
                "accent": "#999800",
                "button_bg": "#0C897D",
                "button_hover": "#1E534C",
                "border": "#3386ab",
                "header": "#156C8C",
                "progress": "#99ffff",
                "success": "#00c8ff",
                "error": "#f44336",
                "name": "深蓝主题"
            },
            # 紫罗兰主题
            {
                "bg": "#4a148c",
                "secondary_bg": "#6a1b9a",
                "text": "#ffffff",
                "accent": "#00e5ff",
                "button_bg": "#7b1fa2",
                "button_hover": "#9c27b0",
                "border": "#ba68c8",
                "header": "#6a1b9a",
                "progress": "#00e5ff",
                "success": "#00e676",
                "error": "#ff1744",
                "name": "紫罗兰主题"
            },
            # 深绿主题
            {
                "bg": "#1b5e20",
                "secondary_bg": "#2e7d32",
                "text": "#ffffff",
                "accent": "#ffeb3b",
                "button_bg": "#388e3c",
                "button_hover": "#43a047",
                "border": "#66bb6a",
                "header": "#2e7d32",
                "progress": "#ffeb3b",
                "success": "#76ff03",
                "error": "#ff5722",
                "name": "深绿主题"
            },
            # 暗橙主题
            {
                "bg": "#bf360c",
                "secondary_bg": "#d84315",
                "text": "#ffffff",
                "accent": "#00bcd4",
                "button_bg": "#e64a19",
                "button_hover": "#f4511e",
                "border": "#ff5722",
                "header": "#d84315",
                "progress": "#00bcd4",
                "success": "#64dd17",
                "error": "#d50000",
                "name": "暗橙主题"
            },
            # 深灰主题
            {
                "bg": "#212121",
                "secondary_bg": "#424242",
                "text": "#f5f5f5",
                "accent": "#03a9f4",
                "button_bg": "#616161",
                "button_hover": "#757575",
                "border": "#9e9e9e",
                "header": "#424242",
                "progress": "#03a9f4",
                "success": "#00e676",
                "error": "#f44336",
                "name": "深灰主题"
            }
        ]
        
        # 如果已经有当前主题索引，则使用下一个主题，否则使用默认主题
        if hasattr(self, 'current_theme_index'):
            self.current_theme_index = (self.current_theme_index + 1) % len(themes)
            theme = themes[self.current_theme_index]
        else:
            self.current_theme_index = DEFAULT_THEME
            theme = themes[self.current_theme_index]
        
        # 应用选择的主题
        self.setStyleSheet(f"""
          QMainWindow, QDialog {{ background-color: {theme["bg"]}; color: {theme["text"]}; }}
QWidget {{ background-color: {theme["bg"]}; color: {theme["text"]}; }}
QGroupBox {{ border: 1px solid {theme["border"]}; border-radius: 6px; margin-top: 1.5ex; font-weight: bold; color: {theme["text"]}; padding: 2px; }}
QGroupBox::title {{ subcontrol-origin: margin; subcontrol-position: top center; padding: 0 8px; color: {theme["text"]}; }}
QPushButton {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_bg"]}, stop:1 {theme["button_bg"]}); color: {theme["text"]}; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold;  }}
QPushButton:hover {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_hover"]}, stop:1 {theme["button_hover"]}); }}
QPushButton:pressed {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_bg"]}, stop:1 {theme["button_hover"]}); }}
QPushButton:disabled {{ background-color: #444444; color: #888888; }}
QTableWidget {{ border: 1px solid {theme["border"]}; border-radius: 6px; alternate-background-color: {theme["secondary_bg"]}; gridline-color: {theme["border"]}; color: {theme["text"]}; selection-background-color: {theme["accent"]}; selection-color: {theme["bg"]}; }}
QTableWidget::item {{ border-bottom: 1px solid {theme["border"]}; padding: 6px; }}
QHeaderView::section {{ background-color: {theme["header"]}; padding: 6px; border: 1px solid {theme["border"]}; font-weight: bold; color: {theme["text"]}; }}
QProgressBar {{ border: 1px solid {theme["border"]}; border-radius: 6px; text-align: center; color: {theme["text"]}; background-color: {theme["secondary_bg"]}; height: 20px; }}
QProgressBar::chunk {{ background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {theme["progress"]}, stop:1 {theme["accent"]}); border-radius: 5px; }}
QTabWidget::pane {{ border: 1px solid {theme["border"]}; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background-color: {theme["secondary_bg"]}; border: 1px solid {theme["border"]}; border-bottom: none; border-top-left-radius: 6px; border-top-right-radius: 6px; padding: 8px 16px; color: {theme["text"]}; margin-right: 2px; }}
QTabBar::tab:selected {{ background-color: {theme["bg"]}; border-bottom: 2px solid {theme["accent"]}; }}
QTabBar::tab:hover {{ background-color: {theme["button_hover"]}; }}
QToolButton {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_bg"]}, stop:1 {theme["button_bg"]}); color: {theme["text"]}; border: none; border-radius: 6px; padding: 8px 16px; font-weight: bold;  }}
QToolButton:hover {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_hover"]}, stop:1 {theme["button_hover"]}); }}
QToolButton:pressed {{ background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {theme["button_bg"]}, stop:1 {theme["button_hover"]}); }}
QLineEdit, QComboBox, QSpinBox {{ background-color: {theme["secondary_bg"]}; border: 1px solid {theme["border"]}; border-radius: 6px; padding: 6px; color: {theme["text"]}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border: 1px solid {theme["accent"]}; }}
QComboBox::drop-down {{ border: none; background-color: {theme["accent"]}; border-top-right-radius: 6px; border-bottom-right-radius: 6px; width: 20px; }}
QComboBox::down-arrow {{ image: url(down_arrow.png); width: 12px; height: 12px; }}
QComboBox QAbstractItemView {{ background-color: {theme["secondary_bg"]}; border: 1px solid {theme["border"]}; color: {theme["text"]}; selection-background-color: {theme["accent"]}; border-radius: 6px; }}
QCheckBox {{ color: {theme["text"]}; spacing: 8px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border: 2px solid {theme["text"]}; border-radius: 4px; background-color: {theme["secondary_bg"]}; }}
QCheckBox::indicator:checked {{ background-color: {theme["accent"]}; border-color: {theme["accent"]}; }}
QTextEdit {{ background-color: {theme["secondary_bg"]}; color: {theme["text"]}; border: 1px solid {theme["border"]}; border-radius: 6px; padding: 6px; }}
QMenu {{ background-color: {theme["secondary_bg"]}; color: {theme["text"]}; border: 1px solid {theme["border"]}; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 32px 6px 20px; border-radius: 4px; margin: 2px; }}
QMenu::item:selected {{ background-color: {theme["accent"]}; color: {theme["bg"]}; }}
QScrollBar:vertical {{ border: none; background-color: {theme["secondary_bg"]}; width: 12px; margin: 0; }}
QScrollBar::handle:vertical {{ background-color: {theme["border"]}; border-radius: 6px; min-height: 20px; }}
QScrollBar::handle:vertical:hover {{ background-color: {theme["accent"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
QScrollBar:horizontal {{ border: none; background-color: {theme["secondary_bg"]}; height: 12px; margin: 0; }}
QScrollBar::handle:horizontal {{ background-color: {theme["border"]}; border-radius: 6px; min-width: 20px; }}
QScrollBar::handle:horizontal:hover {{ background-color: {theme["accent"]}; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}
        """)
        
        # 记录当前使用的主题
        logger.info(f"应用了主题: {theme['name']}")
        self.update_status_bar(f"已应用主题: {theme['name']}")

    def import_url_from_clipboard(self, url_content):
        """从剪贴板导入URL内容"""
        if not url_content:
            return
        
        # 显示导入进度条
        self.import_progress_bar.setVisible(True)
        self.import_progress_bar.setValue(0)
        self.cancel_import_button.setVisible(True)
        
        try:
            # 创建并启动导入线程
            self.import_thread = ImportUrlThread(url_content, self)
            self.import_thread.finished_signal.connect(self.handle_import_finished)
            self.import_thread.progress_signal.connect(self.update_import_progress)
            self.import_thread.start()
            logger.info(f"开始从剪贴板导入 URL，内容长度: {len(url_content)}")
            self.update_status_bar("正在从剪贴板导入...")
        except Exception as e:
            # 隐藏进度条和取消按钮
            self.import_progress_bar.setVisible(False)
            self.cancel_import_button.setVisible(False)
            error_msg = f"导入过程中发生错误: {str(e)}"
            QMessageBox.critical(self, "导入错误", error_msg)
            logger.error(error_msg)
            self.update_status_bar("导入失败。")
    
    def import_streams(self, file_path=None):
        """导入流媒体数据，如果没有提供文件路径，则打开文件选择器"""
        if not file_path:
            dialog_title = "选择IPTV流文件"
            file_filter = "所有支持的文件 (*.m3u *.txt);;M3U文件 (*.m3u);;文本文件 (*.txt);;所有文件 (*.*)"
            download_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            file_path, _ = QFileDialog.getOpenFileName(self, dialog_title, download_dir, file_filter)
            if not file_path:  # 用户取消了文件选择
                return
        
        # 显示导入进度
        self.import_progress_bar.setVisible(True)
        self.import_progress_bar.setValue(0)
        self.cancel_import_button.setVisible(True)
        
        # 创建并启动导入线程
        self.import_thread = ImportFileThread(file_path, self)
        self.import_thread.finished_signal.connect(self.handle_import_finished)
        self.import_thread.progress_signal.connect(self.update_import_progress)
        self.import_thread.start()
        logger.info(f"开始从文件导入: {file_path}")
        self.update_status_bar(f"正在导入 {os.path.basename(file_path)}...")
    
    def update_import_progress(self, progress, current, total):
        """更新进度条和状态信息"""
        self.import_progress_bar.setValue(progress)
        self.status_label.setText(f"导入进度: {progress}% ({current}/{total})")
    
    def handle_import_finished(self, streams, error_msg):
        """处理导入完成信号"""
        # 隐藏进度条和取消按钮
        self.import_progress_bar.setVisible(False)
        self.cancel_import_button.setVisible(False)
        
        if error_msg:  # 如果有错误
            QMessageBox.critical(self, "导入错误", error_msg)
            self.update_status_bar(f"导入失败: {error_msg}")
            return
        
        if not streams:  # 如果没有流
            QMessageBox.information(self, "导入结果", "没有找到可用的流。")
            self.update_status_bar("导入完成，但未找到流。")
            return
        
        # 将新流添加到现有流列表中
        current_stream_count = len(self.streams)
        self.streams.extend(streams)
        
        # 更新表格
        self.update_table(self.streams)
        
        success_msg = f"成功导入 {len(streams)} 个流。"
        logger.info(success_msg)
        self.update_status_bar(success_msg)
        
    def clear_invalid_button_clicked(self):
        """响应清除无效源按钮的点击事件"""
        self.clear_invalid_streams()
            
    def update_table(self, streams):
        """使用流媒体数据更新表格"""
        self._is_updating_from_code = True  # 设置标志以防止递归触发
        self.stream_table.setSortingEnabled(False)  # 临时禁用排序
        self.stream_table.setRowCount(len(streams))
        
        for row, stream in enumerate(streams):
            # 选择列 - 添加复选框
            checkbox = QTableWidgetItem()
            checkbox.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            checkbox.setCheckState(Qt.CheckState.Unchecked)
            self.stream_table.setItem(row, 0, checkbox)
            
            # 名称列
            name_item = QTableWidgetItem(stream.get('name', '未知'))
            self.stream_table.setItem(row, 1, name_item)
            
            # URL列 - 使用自定义的可缩略显示的TableItem
            url = stream.get('url', '')
            url_item = URLTableWidgetItem(url)  # 自定义的TableWidgetItem
            self.stream_table.setItem(row, 2, url_item)
            
            # 分类
            group_item = QTableWidgetItem(stream.get('group', ''))
            self.stream_table.setItem(row, 3, group_item)
            
            # 归属地
            country_item = QTableWidgetItem(stream.get('country', ''))
            self.stream_table.setItem(row, 4, country_item)
            
            # 分辨率
            resolution_item = QTableWidgetItem(stream.get('resolution', ''))
            self.stream_table.setItem(row, 5, resolution_item)
            
            # 响应时间
            response_time = stream.get('response_time', '')
            if response_time:
                response_time_item = QTableWidgetItem(str(response_time))
                response_time_item.setData(Qt.ItemDataRole.DisplayRole, response_time) # 设置为数值以便正确排序
            else:
                response_time_item = QTableWidgetItem('')
            self.stream_table.setItem(row, 6, response_time_item)
            
            # 状态
            status_item = QTableWidgetItem(stream.get('status', '未检测'))
            # 根据状态设置颜色
            status = stream.get('status', '').lower()
            if status == '正常':
                status_item.setForeground(QColor(0, 200, 0))  # 绿色
            elif status in ['无效源', '错误']:
                status_item.setForeground(QColor(255, 0, 0))  # 红色
            elif status == '未检测':
                status_item.setForeground(QColor(128, 128, 128)) # 灰色
            self.stream_table.setItem(row, 7, status_item)
        
        self.stream_table.setSortingEnabled(True)  # 重新启用排序
        self._is_updating_from_code = False  # 重置标志
        
        # 调整列宽以适应内容
        self.stream_table.resizeColumnsToContents()
        
        # 更新状态栏显示流的总数
        self.update_status_bar(f"当前共有 {len(streams)} 个流。")
        
    def handle_cell_double_click(self, row, column):
        """处理单元格双击事件"""
        if column == 2:  # URL列，打开播放器
            url = self.stream_table.item(row, column).full_url  # 获取完整URL
            if url:
                self.play_stream(url)
                
    def handle_item_changed(self, item):
        """处理表格项更改事件"""
        if self._is_updating_from_code:
            return  # 如果是代码在更新表格，不响应事件
            
        row = item.row()
        column = item.column()
        
        if column == 1:  # 名称列
            new_name = item.text()
            if 0 <= row < len(self.streams):
                self.streams[row]['name'] = new_name
                logger.info(f"流名称已更改为: {new_name}")
                
    def update_stream_details(self):
        """当选择更改时，更新流详情显示"""
        selected_rows = set(item.row() for item in self.stream_table.selectedItems())
        if not selected_rows:
            self.details_display.clear()
            return
            
        # 如果只选择了一个流，显示详细信息
        if len(selected_rows) == 1:
            row = next(iter(selected_rows))
            if row < len(self.streams):
                stream = self.streams[row]
                details = "流详情：\n\n"
                details += f"名称: {stream.get('name', '未知')}\n"
                details += f"URL: {stream.get('url', '无')}\n"
                details += f"分类: {stream.get('group', '无')}\n"
                details += f"归属地: {stream.get('country', '未知')}\n"
                details += f"状态: {stream.get('status', '未检测')}\n"
                details += f"分辨率: {stream.get('resolution', '未知')}\n"
                details += f"帧率: {stream.get('fps', '未知')}\n"
                details += f"视频码率: {stream.get('video_bitrate', '未知')}\n"
                details += f"音频码率: {stream.get('audio_bitrate', '未知')}\n"
                details += f"响应时间: {stream.get('response_time', '未知')} 毫秒\n"
                details += f"编码器: {stream.get('codec', '未知')}\n"
                details += f"最后检测: {stream.get('last_checked', '从未')}\n"
                
                if stream.get('error_info'):
                    details += f"\n错误信息: {stream.get('error_info')}\n"
                    
                self.details_display.setText(details)
        else:
            # 多选，显示摘要信息
            self.details_display.setText(f"已选择 {len(selected_rows)} 个流。")
            
    def show_context_menu(self, position):
        """显示右键上下文菜单"""
        menu = QMenu(self)
        
        # 获取所有选中的行
        selected_rows = set(item.row() for item in self.stream_table.selectedItems())
        if not selected_rows:
            # 如果没有选中行，显示导入和清空选项
            paste_action = menu.addAction(QIcon.fromTheme("edit-paste"), "从剪贴板导入")
            menu.addSeparator()
            clear_all_action = menu.addAction("清空列表")
            action = menu.exec(self.stream_table.viewport().mapToGlobal(position))
            if action == clear_all_action:
                self.clear_all_streams()
            elif action == paste_action:
                self.import_from_clipboard()
            return
            
        # 添加菜单项
        play_action = menu.addAction("播放视频")
        check_action = menu.addAction("检测流")
        menu.addSeparator()
        copy_url_action = menu.addAction("复制 URL")
        copy_name_action = menu.addAction("复制名称")
        rename_action = menu.addAction("重命名")
        menu.addSeparator()
        paste_action = menu.addAction(QIcon.fromTheme("edit-paste"), "从剪贴板导入")
        menu.addSeparator()
        remove_action = menu.addAction("删除")
        menu.addSeparator()
        clear_all_action = menu.addAction("清空列表")
        
        # 如果只选择了一行，启用所有操作
        single_selection = len(selected_rows) == 1
        play_action.setEnabled(single_selection)
        rename_action.setEnabled(single_selection)
        
        # 执行菜单并获取选择的操作
        action = menu.exec(self.stream_table.viewport().mapToGlobal(position))
        
        if not action:
            return  # 用户没有选择任何操作
            
        # 处理菜单动作
        if action == play_action and single_selection:
            row = next(iter(selected_rows))
            url = self.stream_table.item(row, 2).full_url
            self.play_stream(url)
        elif action == check_action:
            self.check_selected_streams()
        elif action == copy_url_action:
            self.copy_selected_urls()
        elif action == copy_name_action:
            self.copy_selected_names()
        elif action == rename_action and single_selection:
            row = next(iter(selected_rows))
            self.stream_table.editItem(self.stream_table.item(row, 1))
        elif action == paste_action:
            self.import_from_clipboard()
        elif action == remove_action:
            self.remove_selected_streams()
        elif action == clear_all_action:
            self.clear_all_streams()
            
    def play_stream(self, url):
        """播放指定的流URL"""
        from player import VideoPlayer
        self.player = VideoPlayer()
        self.player.play_video(url)
        self.player.show()
        
    def copy_selected_urls(self):
        """复制所选流的URL到剪贴板"""
        selected_rows = sorted(set(item.row() for item in self.stream_table.selectedItems()))
        if not selected_rows:
            return
        
        urls = []
        for row in selected_rows:
            url = self.stream_table.item(row, 2).full_url
            urls.append(url)
        
        # 将URL复制到剪贴板
        QGuiApplication.clipboard().setText('\n'.join(urls))
        self.update_status_bar(f"已复制 {len(urls)} 个URL到剪贴板")
        
    def remove_selected_streams(self):
        """删除选中的流"""
        selected_rows = sorted(set(item.row() for item in self.stream_table.selectedItems()), reverse=True)
        if not selected_rows:
            return
            
        # 确认删除
        reply = QMessageBox.question(
            self, "确认删除", 
            f"确定要删除选择的 {len(selected_rows)} 个流吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            # 从高索引到低索引删除，以避免索引偏移问题
            for row in selected_rows:
                if row < len(self.streams):
                    del self.streams[row]
            
            # 更新表格
            self.update_table(self.streams)
            self.update_status_bar(f"已删除 {len(selected_rows)} 个流")
            
    def check_streams(self):
        """检测所有流"""
        if not self.streams:
            QMessageBox.information(self, "无可检测流", "没有流可供检测。")
            return
            
        # 初始化检测前的界面
        self.progress_bar.setValue(0)
        self.stop_button.setEnabled(True)
        self.check_button.setEnabled(False)
        self.check_selected_button.setEnabled(False)
        
        # 设置检测状态标志
        self.is_checking = True
        
        # 获取当前的自动清除选项状态
        auto_clear = self.auto_clear_invalid_checkbox.isChecked()
        
        # 创建并启动检测线程
        self.check_thread = StreamCheckThread(
            self.streams, 
            auto_clear=auto_clear,
            skip_same_domain_invalid=SKIP_SAME_DOMAIN_INVALID,
            parent=self
        )
        self.check_thread.progress_signal.connect(self.update_check_progress)
        self.check_thread.stream_updated_signal.connect(self.update_stream_status)
        self.check_thread.finished_signal.connect(self.handle_check_finished)
        self.check_thread.start()
        
        self.update_status_bar(f"开始检测 {len(self.streams)} 个流...")
        
    def check_selected_streams(self):
        """检测选中的流"""
        selected_rows = set(item.row() for item in self.stream_table.selectedItems())
        if not selected_rows:
            QMessageBox.information(self, "未选择流", "请选择要检测的流。")
            return
            
        # 从流列表中提取选中的流
        selected_streams = [self.streams[row] for row in selected_rows if row < len(self.streams)]
        if not selected_streams:
            return
            
        # 初始化检测前的界面
        self.progress_bar.setValue(0)
        self.stop_button.setEnabled(True)
        self.check_button.setEnabled(False)
        self.check_selected_button.setEnabled(False)
        
        # 设置检测状态标志
        self.is_checking = True
        
        # 获取当前的自动清除选项状态
        auto_clear = self.auto_clear_invalid_checkbox.isChecked()
        
        # 创建并启动检测线程
        self.check_thread = StreamCheckThread(
            selected_streams, 
            auto_clear=auto_clear,
            skip_same_domain_invalid=SKIP_SAME_DOMAIN_INVALID,
            parent=self
        )
        self.check_thread.progress_signal.connect(self.update_check_progress)
        self.check_thread.stream_updated_signal.connect(self.update_stream_status)
        self.check_thread.finished_signal.connect(self.handle_check_finished)
        self.check_thread.start()
        
        self.update_status_bar(f"开始检测 {len(selected_streams)} 个选中的流...")
        
    def update_check_progress(self, progress, current, total):
        """更新检测进度"""
        self.progress_bar.setValue(progress)
        self.status_label.setText(f"检测进度: {progress}% ({current}/{total})")
        
    def update_stream_status(self, index, stream_info):
        """更新流的状态信息"""
        # 在流列表中更新对应的流
        if 0 <= index < len(self.streams):
            # 保存原始的分类和归属地信息
            original_group = self.streams[index].get('group', '')
            original_country = self.streams[index].get('country', '')
            
            # 更新流信息
            self.streams[index].update(stream_info)
            
            # 如果新的流信息中没有分类或归属地，但原始信息有，则保留原始信息
            if not self.streams[index].get('group') and original_group:
                self.streams[index]['group'] = original_group
            if not self.streams[index].get('country') and original_country:
                self.streams[index]['country'] = original_country
            
            # 查找表格中对应的行
            url = self.streams[index].get('url', '')
            row_to_update = -1
            
            # 遍历表格查找匹配的URL
            for row in range(self.stream_table.rowCount()):
                if hasattr(self.stream_table.item(row, 2), 'full_url'):
                    table_url = self.stream_table.item(row, 2).full_url
                    if table_url == url:
                        row_to_update = row
                        break
            
            logger.debug(f"更新流状态: 索引={index}, URL={url}, 行={row_to_update}, 状态={stream_info.get('status', '')}")
            
            if row_to_update >= 0:
                # 暂时禁用排序，以防止更新时表格行顺序改变
                was_sorting_enabled = self.stream_table.isSortingEnabled()
                if was_sorting_enabled:
                    self.stream_table.setSortingEnabled(False)
                
                try:
                    # 更新分类
                    group = self.streams[index].get('group', '')
                    group_item = QTableWidgetItem(group)
                    self.stream_table.setItem(row_to_update, 3, group_item)
                    
                    # 更新归属地
                    country = self.streams[index].get('country', '')
                    country_item = QTableWidgetItem(country)
                    self.stream_table.setItem(row_to_update, 4, country_item)
                    
                    # 更新分辨率
                    resolution = stream_info.get('resolution', '')
                    resolution_item = QTableWidgetItem(resolution)
                    self.stream_table.setItem(row_to_update, 5, resolution_item)
                    
                    # 更新响应时间
                    response_time = stream_info.get('response_time', '')
                    if response_time:
                        response_time_item = QTableWidgetItem(str(response_time))
                        response_time_item.setData(Qt.ItemDataRole.DisplayRole, response_time)
                    else:
                        response_time_item = QTableWidgetItem('')
                    self.stream_table.setItem(row_to_update, 6, response_time_item)
                    
                    # 更新状态并设置颜色
                    status = stream_info.get('status', '')
                    status_item = QTableWidgetItem(status)
                    if status.lower() == '正常':
                        status_item.setForeground(QColor(0, 200, 0))  # 绿色
                    elif status.lower() in ['无效源', '错误']:
                        status_item.setForeground(QColor(255, 0, 0))  # 红色
                    self.stream_table.setItem(row_to_update, 7, status_item)
                    
                    # 强制更新表格视图
                    self.stream_table.viewport().update()
                    
                    # 确保应用程序处理所有待处理的事件，立即更新UI
                    QApplication.processEvents()
                    
                finally:
                    # 恢复排序状态
                    if was_sorting_enabled:
                        self.stream_table.setSortingEnabled(True)
            else:
                # 如果找不到对应的行，可能是因为过滤器隐藏了这一行
                # 记录一下日志
                logger.debug(f"无法在表格中找到URL为 {url} 的行进行更新")
        
    def handle_check_finished(self):
        """处理检测完成事件"""
        # 检测完成后更新界面
        self.stop_button.setEnabled(False)
        self.check_button.setEnabled(True)
        self.check_selected_button.setEnabled(True)
        
        # 重置检测状态标志
        self.is_checking = False
        
        self.update_status_bar("流检测完成")
        
        # 如果需要，自动清除无效源
        if AUTO_CLEAR_INVALID_STREAMS:
            self.clear_invalid_streams(silent=True)
            
    def stop_checking(self):
        """停止当前的检测进程"""
        if self.check_thread and self.check_thread.isRunning():
            self.check_thread.stop()
            # 重置检测状态标志
            self.is_checking = False
            # 恢复按钮状态
            self.stop_button.setEnabled(False)
            self.check_button.setEnabled(True)
            self.check_selected_button.setEnabled(True)
            self.update_status_bar("已停止检测")
            
    def cancel_current_import(self):
        """取消当前的导入进程"""
        if self.import_thread and self.import_thread.isRunning():
            self.import_thread.is_cancelled = True  # 设置取消标志
            self.update_status_bar("正在取消导入...")
            # 导入线程会自行结束，并触发finished_signal
            
    def apply_filters(self):
        """应用筛选条件，更新表格显示"""
        status_filter = self.status_filter.currentText()
        resolution_filter = self.resolution_filter.currentText()
        response_filter = self.response_filter.currentText()
        
        # 如果所有过滤器都是"全部"，显示所有流
        if status_filter == "全部" and resolution_filter == "全部" and response_filter == "全部":
            self.update_table(self.streams)
            return
            
        # 用于符合筛选条件的流
        filtered_streams = []
        
        # 应用状态筛选
        if status_filter == "全部":
            status_streams = self.streams
        else:
            status_streams = [s for s in self.streams if s.get('status', '').lower() == status_filter.lower()]
            
        # 应用分辨率筛选
        if resolution_filter == "全部":
            resolution_streams = status_streams
        else:
            # 根据分辨率区分，可能需要更详细的逻辑
            resolution_streams = []
            for s in status_streams:
                res = s.get('resolution', '').lower()
                if resolution_filter == "4K" and '4k' in res:
                    resolution_streams.append(s)
                elif resolution_filter == "FHD" and ('1080' in res or 'fhd' in res):
                    resolution_streams.append(s)
                elif resolution_filter == "HD" and ('720' in res or 'hd' in res) and '1080' not in res:
                    resolution_streams.append(s)
                elif resolution_filter == "SD" and any(x in res for x in ['480', '576', 'sd']):
                    resolution_streams.append(s)
                    
        # 应用响应时间筛选
        if response_filter == "全部":
            filtered_streams = resolution_streams
        else:
            # 解析响应时间限制
            time_limit = int(response_filter.split('毫秒')[0])
            filtered_streams = [s for s in resolution_streams if s.get('response_time', 999999) <= time_limit]
            
        # 合并相似频道
        if self.merge_checkbox.isChecked():
            # 实现合并相似频道的逻辑，这里简单处理
            # 实际上可能需要更复杂的字符串相似度检测
            name_groups = {}
            for s in filtered_streams:
                name = s.get('name', '').strip()
                if name:
                    key = name.lower()
                    if key not in name_groups:
                        name_groups[key] = []
                    name_groups[key].append(s)
            
            merged_streams = []
            for name, streams in name_groups.items():
                # 按状态排序，优先选择"正常"的流
                sorted_streams = sorted(streams, key=lambda s: 0 if s.get('status', '').lower() == '正常' else 1)
                merged_streams.append(sorted_streams[0])
        else:
            merged_streams = filtered_streams
            
        # 更新表格
        self.update_table(merged_streams)
        
    def export_streams(self, format_type):
        """导出流到指定格式的文件"""
        if not self.streams:
            QMessageBox.information(self, "导出", "没有流可供导出。")
            return
            
        # 确定默认文件名
        default_name = time.strftime("iptv_export_%Y%m%d_%H%M%S")
        if format_type.lower() == "m3u":
            filter_str = "M3U Files (*.m3u)"
            default_name += ".m3u"
        else:  # txt格式
            filter_str = "Text Files (*.txt)"
            default_name += ".txt"
            
        # 打开保存文件对话框
        downloads_dir = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
        file_path, _ = QFileDialog.getSaveFileName(
            self, "导出流", os.path.join(downloads_dir, default_name), filter_str)
            
        if not file_path:  # 用户取消了文件选择
            return
            
        try:
            if format_type.lower() == "m3u":
                # 导出为M3U格式
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write("#EXTM3U\n")
                    for stream in self.streams:
                        name = stream.get('name', 'Unknown')
                        group = stream.get('group', '')
                        country = stream.get('country', '')
                        logo = stream.get('logo', '')
                        url = stream.get('url', '')
                        
                        # 添加扩展信息
                        f.write(f'#EXTINF:-1 tvg-name="{name}"')
                        if group:
                            f.write(f' group-title="{group}"')
                        if country:
                            f.write(f' tvg-country="{country}"')
                        if logo:
                            f.write(f' tvg-logo="{logo}"')
                        f.write(f',{name}\n')
                        
                        # 添加URL
                        f.write(f'{url}\n')
            else:
                # 导出为TXT格式
                with open(file_path, 'w', encoding='utf-8') as f:
                    for stream in self.streams:
                        name = stream.get('name', 'Unknown')
                        url = stream.get('url', '')
                        f.write(f'{name},{url}\n')
                        
            QMessageBox.information(
                self, "导出成功", 
                f"成功导出 {len(self.streams)} 个流到文件:\n{file_path}"
            )
            logger.info(f"已导出 {len(self.streams)} 个流到 {file_path}")
            self.update_status_bar(f"已导出 {len(self.streams)} 个流。")
            
        except Exception as e:
            error_msg = f"导出失败: {str(e)}"
            QMessageBox.critical(self, "导出错误", error_msg)
            logger.error(error_msg)
            self.update_status_bar(error_msg)
            
    def load_stream_list_on_startup(self):
        """在程序启动时加载之前保存的流列表"""
        if not SAVE_STREAM_LIST:
            return
            
        try:
            streams = load_stream_list()
            if streams:
                self.streams = streams
                self.update_table(self.streams)
                logger.info(f"成功加载 {len(streams)} 个流")
                self.update_status_bar(f"从配置文件加载了 {len(streams)} 个流。")
        except Exception as e:
            logger.error(f"加载流列表失败: {str(e)}")
            # 不向用户显示错误，因为这只是启动功能
            
    def closeEvent(self, event):
        """当窗口关闭时调用，用于保存设置和清理资源"""
        # 保存流列表（如果配置了保存）
        if SAVE_STREAM_LIST and self.streams:
            try:
                save_stream_list(self.streams)
                logger.info(f"关闭时保存了 {len(self.streams)} 个流到配置文件")
            except Exception as e:
                logger.error(f"保存流列表失败: {str(e)}")
                
        # 保存设置
        save_settings()
        
        # 清理临时目录
        if hasattr(self, 'temp_directory') and self.temp_directory:
            clean_temp_directory(self.temp_directory)
        
        # 停止任何正在运行的线程
        if self.check_thread and self.check_thread.isRunning():
            self.check_thread.stop()
            self.check_thread.wait()
            
        if self.import_thread and self.import_thread.isRunning():
            self.import_thread.is_cancelled = True
            self.import_thread.wait()
            
        # 接受关闭事件，继续关闭窗口
        event.accept()

    def copy_selected_names(self):
        """复制所选流的名称到剪贴板"""
        selected_rows = sorted(set(item.row() for item in self.stream_table.selectedItems()))
        if not selected_rows:
            return
        
        names = []
        for row in selected_rows:
            name = self.stream_table.item(row, 1).text()
            names.append(name)
        
        # 将名称复制到剪贴板
        QGuiApplication.clipboard().setText('\n'.join(names))
        self.update_status_bar(f"已复制 {len(names)} 个名称到剪贴板")

    def clear_all_streams(self):
        """清空所有流"""
        if not self.streams:
            QMessageBox.information(self, "清空列表", "列表已经为空。")
            return

        # 确认清空
        reply = QMessageBox.question(
            self, "确认清空", 
            f"确定要清空列表中的所有 {len(self.streams)} 个流吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self.streams = []
            self.update_table(self.streams)
            self.update_status_bar("已清空所有流")

    def contextMenuEvent(self, event):
        """处理菜单键或F10触发的上下文菜单事件"""
        # 只有当鼠标在表格上时才显示菜单
        if self.stream_table.underMouse():
            # 获取表格中的位置
            pos = self.stream_table.mapFromGlobal(event.globalPos())
            self.show_context_menu(pos)
        else:
            # 如果鼠标不在表格上，调用父类的处理方法
            super().contextMenuEvent(event)

    def show_menu_at_cursor(self):
        """在当前光标位置显示上下文菜单"""
        if self.stream_table.hasFocus():
            # 获取当前选中的单元格
            current_item = self.stream_table.currentItem()
            if current_item:
                # 获取单元格的全局坐标
                rect = self.stream_table.visualItemRect(current_item)
                pos = self.stream_table.viewport().mapToGlobal(rect.center())
                # 显示菜单
                self.show_context_menu(self.stream_table.mapFromGlobal(pos))
            else:
                # 如果没有选中单元格，在表格中心显示菜单
                center = self.stream_table.viewport().rect().center()
                self.show_context_menu(center)

    def switch_theme(self):
        """切换到下一个主题"""
        self.apply_stylesheet()

