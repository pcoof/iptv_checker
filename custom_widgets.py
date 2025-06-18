#!/usr/bin/env python3
from PySide6.QtWidgets import QTableWidgetItem
from PySide6.QtCore import Qt

class URLTableWidgetItem(QTableWidgetItem):
    """自定义表格项，用于URL单元格的自动缩略显示"""
    def __init__(self, url):
        super().__init__()
        self.full_url = url
        self.setText(url)  # 初始设置完整URL
        
    def data(self, role):
        """重写data方法以支持自动缩略显示"""
        if role == Qt.ItemDataRole.DisplayRole:
            # 获取单元格的宽度
            if self.tableWidget():
                column_width = self.tableWidget().columnWidth(self.column())
                font_metrics = self.tableWidget().fontMetrics()
                # 计算文本在当前宽度下是否需要缩略
                text_width = font_metrics.horizontalAdvance(self.full_url)
                if text_width > column_width - 10:  # 留出一些边距
                    # 计算可以显示的字符数
                    visible_length = 0
                    for i in range(len(self.full_url)):
                        if font_metrics.horizontalAdvance(self.full_url[:i]) > column_width - 30:  # 为"..."留出空间
                            visible_length = i - 1
                            break
                    if visible_length <= 0:
                        visible_length = 1  # 至少显示一个字符
                    # 返回缩略后的文本
                    return self.full_url[:visible_length] + "..."
                return self.full_url
            return self.full_url
        # 对于其他角色，使用默认行为
        return super().data(role) 