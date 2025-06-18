#!/usr/bin/env python3
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QSpinBox, QCheckBox, 
    QDialogButtonBox, QComboBox
)
from PySide6.QtCore import Qt
from loguru import logger
from config import (
    CONCURRENT_CHECKS, REQUEST_TIMEOUT, 
    AUTO_CLEAR_INVALID_STREAMS, SAVE_STREAM_LIST, HIGH_CONCURRENCY_MODE, 
    SKIP_SAME_DOMAIN_INVALID, DEFAULT_THEME, save_settings
)

class SettingsDialog(QDialog):
    """设置对话框"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        # 1. 并发检查数量
        self.concurrent_checks_spinbox = QSpinBox()
        self.concurrent_checks_spinbox.setRange(1, 100) # 假设最大100个并发
        self.concurrent_checks_spinbox.setValue(CONCURRENT_CHECKS)
        form_layout.addRow("并发检查数量:", self.concurrent_checks_spinbox)
        # 2. 超时时间设置（秒）
        self.request_timeout_spinbox = QSpinBox()
        self.request_timeout_spinbox.setRange(1, 300) # 假设最大300秒超时
        self.request_timeout_spinbox.setValue(REQUEST_TIMEOUT)
        form_layout.addRow("超时时间设置 (秒):", self.request_timeout_spinbox)
        
        # 3. 界面主题选择
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["深蓝主题", "紫罗兰主题", "深绿主题", "暗橙主题", "深灰主题"])
        self.theme_combo.setCurrentIndex(DEFAULT_THEME)
        form_layout.addRow("界面主题:", self.theme_combo)
        
        # 4. 自动清空无效源开关
        self.auto_clear_checkbox = QCheckBox()
        self.auto_clear_checkbox.setChecked(AUTO_CLEAR_INVALID_STREAMS)
        form_layout.addRow("自动清空无效源:", self.auto_clear_checkbox)
        # 5. 保存流列表开关
        self.save_stream_list_checkbox = QCheckBox()
        self.save_stream_list_checkbox.setChecked(SAVE_STREAM_LIST)
        form_layout.addRow("保存流列表状态:", self.save_stream_list_checkbox)
        # 6. 高并发模式 (>1000流):
        self.high_concurrency_checkbox = QCheckBox()
        self.high_concurrency_checkbox.setChecked(HIGH_CONCURRENCY_MODE)
        form_layout.addRow("高并发模式 (>1000流):", self.high_concurrency_checkbox)

        # 7. 检测到同域名下多个无效源时跳过剩余检测
        self.skip_same_domain_invalid_checkbox = QCheckBox()
        self.skip_same_domain_invalid_checkbox.setChecked(SKIP_SAME_DOMAIN_INVALID)
        form_layout.addRow("同域名多个源均无效时跳过检测:", self.skip_same_domain_invalid_checkbox)

        layout.addLayout(form_layout)
        # 按钮
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def accept(self):
        """保存设置"""
        global CONCURRENT_CHECKS, REQUEST_TIMEOUT, AUTO_CLEAR_INVALID_STREAMS, SAVE_STREAM_LIST, HIGH_CONCURRENCY_MODE, SKIP_SAME_DOMAIN_INVALID, DEFAULT_THEME
        # 更新全局变量
        import config
        config.CONCURRENT_CHECKS = self.concurrent_checks_spinbox.value()
        config.REQUEST_TIMEOUT = self.request_timeout_spinbox.value()
        config.AUTO_CLEAR_INVALID_STREAMS = self.auto_clear_checkbox.isChecked()
        config.SAVE_STREAM_LIST = self.save_stream_list_checkbox.isChecked()
        config.HIGH_CONCURRENCY_MODE = self.high_concurrency_checkbox.isChecked()
        config.SKIP_SAME_DOMAIN_INVALID = self.skip_same_domain_invalid_checkbox.isChecked()
        config.DEFAULT_THEME = self.theme_combo.currentIndex()

        save_settings() # 保存到配置文件
        logger.info("设置已更新并保存。")
        # 通知主窗口更新其行为（如果需要立即生效）
        if self.parent():
            self.parent().apply_settings_changes()
        super().accept()

    def reject(self):
        """取消设置"""
        logger.info("设置更改已取消。")
        super().reject() 