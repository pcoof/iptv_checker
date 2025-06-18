## IPTV 流检测器

## 项目简介

IPTV 流检测器是一个用于检测、管理和播放IPTV流的桌面应用程序。它提供了友好的图形界面，支持导入、导出、检测和播放IPTV流媒体源。

## 主要功能

*   **流导入**：支持从M3U/M3U8和TXT格式文件导入IPTV流
*   **流检测**：检测流的有效性、分辨率和响应时间
*   **分类显示**：显示频道的group-title分类信息
*   **归属地**：显示流媒体服务器的地理位置
*   **简易播放器**：双击URL地址可使用OpenCV播放视频流
*   **导出功能**：支持导出为M3U和TXT格式
*   **筛选功能**：可按状态、分辨率和响应时间筛选频道
*   **暗黑主题**：美观的深色界面，减轻眼睛疲劳



### 检测流

1.  点击「检测所有流」按钮检测所有导入的流
2.  或选择特定流后点击「检测选中项」

### 播放流

*   双击流列表中的URL地址，将使用内置的OpenCV播放器播放视频
*   按ESC键可退出播放器

### 导出流

*   点击「导出M3U」将流导出为M3U格式
*   点击「导出TXT」将流导出为TXT格式（格式为：频道名称,URL）

## 技术栈

*   **GUI框架**：PySide6 (Qt for Python)
*   **视频处理**：OpenCV
*   **网络请求**：Requests
*   **并发处理**：Python Threading和concurrent.futures
*   **日志记录**：Loguru

## 系统要求

*   Python 3.6+
*   OpenCV 4.5.0+
*   PySide6
*   其他依赖见requirements.txt

## 安装

```plaintext
# 安装依赖
pip install -r requirements.txt

# 运行应用
python main.py
```

## 注意事项

*   流检测功能需要网络连接
*   播放功能需要安装OpenCV
*   某些流可能需要特定的解码器才能正常播放

# IPTV流检测器升级说明

## 1. 播放器升级
- 视频现在按比例缩放播放，提供更好的观看体验
- 支持播放用`#`分割的多URL地址
- 添加了"播放下一个"按钮，支持在多个URL地址间切换
- 显示当前正在播放的URL索引（例如：1/3）

## 2. TXT格式导入升级
- 支持导入带有`#`分割的双URL地址，例如：`CCTV-1,http://url1#http://url2#http://url3`
- 改进了文本解析逻辑，能正确识别和处理包含多URL的格式

## 3. 代码结构优化
为减小gui.py文件的体积，将代码拆分为多个模块：

- `custom_widgets.py`: 包含自定义UI组件（如URLTableWidgetItem）
- `settings_dialog.py`: 设置对话框和相关功能
- `thread_classes.py`: 线程相关类（ImportUrlThread, ImportFileThread, StreamCheckThread等）
- `gui.py`: 主GUI类，更简洁清晰

这些改进提高了代码的可维护性，减少了单个文件的复杂度，同时提升了用户体验。

## 使用方法

### 播放多URL流
当遇到包含多URL的流时（由`#`分隔），播放器将显示"播放下一个地址"按钮，可以点击切换到下一个URL源。

### 导入带有多URL的TXT文件
系统现在可以正确解析并导入类似以下格式的TXT文件：
```
CCTV-1,http://tvbox.netsite.cc/proxy/753065176/753065176.m3u8#https://pi.0472.org/live/cctv1.m3u8?token=162210
CCTV-2,http://121.24.98.99:8090/hls/10/index.m3u8#http://tvbox.netsite.cc/proxy/1231349557/1231349557.m3u8#https://pi.0472.org/live/cctv2.m3u8?token=162210
```

## 4. 最新代码优化
最新版本进行了多项代码优化，提高了程序的性能和可维护性：

- **移除冗余文件**：删除了冗余的`config_fixed.py`和`gui.py.bak`备份文件
- **代码结构重构**：
  - 将`AsyncCheckerRunner`类从`thread_classes.py`移到单独的`async_checker_runner.py`模块
  - 更新了相关导入以保持一致性
- **代码清理**：
  - 简化了`main.py`中的冗余注释，增强可读性
  - 移除了GUI中未使用的库导入（pandas, dask, numpy等）
  - 统一了线程处理的异常和状态管理方式
  
这些优化使代码更加整洁，减少了项目体积，同时提高了运行效率。