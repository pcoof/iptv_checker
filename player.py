# Compare this snippet from main.py:
import sys
from PySide6.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, QPushButton, QSlider, QLabel, QWidget, QStyle, QSizePolicy)  # 添加QSizePolicy到导入列表
# 添加Qt日志模块
from PySide6.QtCore import Qt, QUrl, QSize  # 添加QUrl导入和QSize
# 添加QVideoWidget导入
from PySide6.QtMultimediaWidgets import QVideoWidget  # 新增此行
# 添加QMediaPlayer和QAudioOutput的导入
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput  # 新增此行

class VideoPlayer(QMainWindow):
    """
    视频播放器类
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPTV 播放器") # 设置窗口标题
        self.setGeometry(100, 100, 800, 600)  # 设置初始大小
        
        # 创建媒体播放器和音频输出
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        
        # 创建视频窗口，并设置为保持宽高比
        self.video_widget = QVideoWidget()
        self.video_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.video_widget.setAspectRatioMode(Qt.KeepAspectRatio)  # 确保视频按原始比例显示
        
        # 多地址播放支持
        self.url_list = []
        self.current_url_index = 0
        
        # 创建控制按钮
        self.toggle_play_btn = QPushButton("播放")
        self.stop_btn = QPushButton("停止")
        
        # 添加"播放下一个"按钮
        self.next_url_btn = QPushButton("播放下一个地址")
        self.next_url_btn.setEnabled(False)  # 默认禁用，只有当有多个URL时才启用
        
        # 音量控制布局
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(50)
        volume_layout = QHBoxLayout()
        volume_icon = QLabel()
        volume_icon.setPixmap(self.style().standardIcon(QStyle.SP_MediaVolume).pixmap(16,16))
        volume_layout.addWidget(volume_icon)
        volume_layout.addWidget(self.volume_slider)
        
        # 进度条和时间标签
        self.position_slider = QSlider(Qt.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setTracking(True)
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        
        # URL计数标签
        self.url_counter_label = QLabel("")
        
        # 初始化播放按钮图标
        self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self.stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self.next_url_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaSkipForward))
        
        # 布局设置
        control_layout = QHBoxLayout()
        control_layout.addWidget(self.toggle_play_btn)
        control_layout.addWidget(self.stop_btn)
        control_layout.addWidget(self.next_url_btn)  # 添加"播放下一个"按钮
        control_layout.addLayout(volume_layout)
        control_layout.addStretch()
        control_layout.addWidget(self.url_counter_label)  # 添加URL计数标签
        control_layout.addWidget(self.time_label)
    
        # 创建控制面板并设置固定高度
        control_container = QWidget()
        control_container.setLayout(control_layout)
        control_container.setFixedHeight(40)
    
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.video_widget)
        main_layout.addWidget(self.position_slider)
        main_layout.addWidget(control_container)
        
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)
        
        # 连接信号槽
        self.media_player.setVideoOutput(self.video_widget)
        self.toggle_play_btn.clicked.connect(self.toggle_play_pause)
        self.stop_btn.clicked.connect(self.media_player.stop)
        self.next_url_btn.clicked.connect(self.play_next_url)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.position_slider.sliderMoved.connect(self.set_position)
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.mediaStatusChanged.connect(self.handle_media_status)
        
        self.is_stream = False
        self.update_toggle_button()

    def toggle_play_pause(self):
        # 切换播放和暂停状态
        if self.media_player.isPlaying():
            self.media_player.pause()
            self.toggle_play_btn.setText("播放")
            self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        else:
            self.media_player.play()
            self.toggle_play_btn.setText("暂停")
            self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))

    def update_toggle_button(self):
        # 根据播放状态更新播放按钮的文本和图标
        if self.media_player.isPlaying():
            self.toggle_play_btn.setText("暂停")
            self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPause))
        else:
            self.toggle_play_btn.setText("播放")
            self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

    def play_video(self, video_url: str):
        # 支持多个URL，用#分割
        if '#' in video_url:
            self.url_list = video_url.split('#')
            self.current_url_index = 0
            self.next_url_btn.setEnabled(len(self.url_list) > 1)
            self.update_url_counter()
            # 播放第一个URL
            self.media_player.setSource(QUrl(self.url_list[0]))
        else:
            # 单一URL
            self.url_list = [video_url]
            self.current_url_index = 0
            self.next_url_btn.setEnabled(False)
            self.update_url_counter()
            self.media_player.setSource(QUrl(video_url))
            
        self.media_player.play()
    
    def play_next_url(self):
        """播放下一个URL"""
        if not self.url_list or self.current_url_index >= len(self.url_list) - 1:
            return
            
        self.current_url_index += 1
        self.update_url_counter()
        self.media_player.setSource(QUrl(self.url_list[self.current_url_index]))
        self.media_player.play()
    
    def update_url_counter(self):
        """更新URL计数标签"""
        if len(self.url_list) > 1:
            self.url_counter_label.setText(f"地址 {self.current_url_index + 1}/{len(self.url_list)}")
        else:
            self.url_counter_label.setText("")

    def set_volume(self, value):
        # 使用音频输出对象设置音量
        self.audio_output.setVolume(value / 100)  # 需要将值转换为0.0-1.0范围

    def set_position(self, position):
        # 只有在不是流的情况下才设置位置
        self.media_player.setPosition(position)  

    def position_changed(self, position):
        # 只有在不是流的情况下才更新滑块和标签
        if not self.is_stream:
            self.position_slider.setValue(position)
            self.time_label.setText(f"{self.format_time(position)} / {self.format_time(self.media_player.duration())}")

    def duration_changed(self, duration):
        # 只有在不是流的情况下才更新滑块范围
        if not self.is_stream:
            self.position_slider.setRange(0, duration)

    def handle_media_status(self, status):
        # 处理媒体状态变化
        if status == QMediaPlayer.EndOfMedia:
            self.position_slider.setValue(0)
            self.time_label.setText("00:00 / 00:00")
            self.toggle_play_btn.setText("播放")
            self.toggle_play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
            
            # 如果有下一个URL，自动播放
            if len(self.url_list) > 1 and self.current_url_index < len(self.url_list) - 1:
                self.play_next_url()

    def format_time(self, ms):
        # 将毫秒转换为时间字符串
        s = ms // 1000
        return f"{s//60:02d}:{s%60:02d}"

    def closeEvent(self, event):
        """窗口关闭事件处理：确保停止播放和释放资源"""
        # 停止播放器
        self.media_player.stop()
        # 将音量设为0
        self.audio_output.setVolume(0)
        # 释放源
        self.media_player.setSource(QUrl())
        # 确保先暂停再释放资源
        self.media_player.pause()
        # 调用父类方法继续处理关闭事件
        super().closeEvent(event)

    def resizeEvent(self, event):
        """处理窗口调整大小事件，确保视频窗口保持比例"""
        super().resizeEvent(event)
        # 视频小部件已配置为保持纵横比，这里可以添加其他调整大小的逻辑

if __name__ == "__main__":
    app = QApplication(sys.argv)
    player = VideoPlayer()
    player.show()
    # 测试多URL功能
    # player.play_video("http://example.com/video1.mp4#http://example.com/video2.mp4")
    sys.exit(app.exec())





