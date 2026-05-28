# Windows 本地电脑清理助手

一个面向新手的 Windows 本地电脑清理工具，使用 Python 和 Tkinter 编写。

项目默认只扫描和生成报告，不会自动删除文件。删除操作需要用户手动选择，并进行二次确认，适合用于电脑空间整理、Python 项目缓存清理、重复文件检查和隐私风险文件名排查。

## 功能特性

* 扫描大文件
* 扫描重复文件
* 扫描 Python 项目缓存
* 扫描疑似隐私文件名
* 扫描时按文件名关键词搜索文件
* 在扫描结果列表中继续搜索和过滤
* 生成清理报告
* 支持导出扫描结果为 Excel 文件
* 删除前二次确认
* 自动跳过 Windows、Program Files、ProgramData、回收站等系统目录
* 默认只扫描，不会主动删除任何文件

## 项目背景

日常使用 Windows 电脑时，下载目录、桌面、Python 项目缓存、临时文件和重复文件容易不断堆积。

普通清理工具可能直接删除文件，存在误删重要资料的风险。本项目的目标是做一个更安全、更透明的本地电脑清理助手。

程序会先扫描文件并生成结果列表，用户可以查看文件路径、大小、修改时间和风险类型，再决定是否删除。

## 技术栈

* Python 3.10+
* Tkinter
* pathlib
* hashlib
* os
* shutil
* tempfile
* zipfile
* PowerShell

## 主要功能说明

### 1. 大文件扫描

扫描指定目录中的大文件，帮助用户快速发现占用空间较多的文件。

适合检查：

* 下载目录中的安装包
* 桌面上的压缩包
* 视频素材
* 长期未整理的大型文件

### 2. 重复文件扫描

通过文件大小和哈希值判断重复文件，减少误判。

适合检查：

* 重复下载的安装包
* 多次保存的压缩包
* 重复图片或文档
* 重复项目备份

### 3. Python 项目缓存清理

识别 Python 项目中常见的缓存文件和临时目录。

可识别内容包括：

* `__pycache__`
* `.pyc`
* `.pytest_cache`
* `build`
* `dist`
* 临时日志文件
* 空文件夹

### 4. 隐私文件名扫描

扫描疑似包含隐私信息的文件名，但不会读取或上传文件内容。

可识别关键词包括：

* `.env`
* `cookie`
* `cookies`
* `token`
* `api_key`
* `apikey`
* `secret`
* `password`
* `passwd`
* `authorization`

这个功能适合在上传 GitHub 前检查项目，降低误传敏感文件的风险。

### 5. 文件搜索

界面提供两种搜索：

* 扫描选项里的“文件搜索”：按文件名关键词扫描磁盘，支持普通关键词，也支持 `*` 和 `?` 通配符。
* 扫描结果页里的“结果内搜索”：扫描完成后，在当前结果列表里按分类、原因或路径快速过滤。

结果内搜索不会重新扫描磁盘，也不会删除文件。

### 6. 报告导出

扫描完成后，可以将结果导出为 Excel 文件，方便查看和归档。

报告内容包括：

* 文件路径
* 文件大小
* 修改时间
* 文件类型
* 风险提示
* 建议处理方式

## 安全策略

本项目以安全为优先目标，默认不会自动删除文件。

安全机制包括：

* 默认行为是扫描和生成报告
* 删除前需要用户手动选择文件
* 删除前会弹出确认窗口
* 删除确认需要输入指定文字
* 自动跳过系统目录
* 自动跳过无权限访问的目录
* 隐私扫描只检查文件名，不读取文件内容
* 不会上传任何本地文件
* 不会连接远程服务器

默认跳过的目录包括：

```text
C:\Windows
C:\Program Files
C:\Program Files (x86)
C:\ProgramData
$Recycle.Bin
System Volume Information
```

## 安装环境

需要 Python 3.10 或更高版本。

查看 Python 版本：

```bash
python --version
```

## 运行方法

在项目根目录打开终端，运行：

```bash
python run.py
```

也可以使用模块方式启动：

```bash
python -m windows_cleaner_assistant
```

## 项目结构

```text
windows_cleaner_assistant/
  __init__.py
  __main__.py
  app.py
  scanner.py
  safety.py
  delete.py
  excel_export.py
  models.py

run.py
README.md
pyproject.toml
.gitignore

Find-DuplicateFiles.ps1
Scan-CleanableItems.ps1
Scan-LargeFilesReport.ps1
privacy_scan.ps1
clean_python_project_cache.py
```

## 文件说明

| 文件                              | 说明                   |
| ------------------------------- | -------------------- |
| `run.py`                        | 程序启动入口               |
| `app.py`                        | Tkinter 图形界面         |
| `scanner.py`                    | 文件扫描逻辑               |
| `safety.py`                     | 系统目录保护和安全判断          |
| `delete.py`                     | 删除确认逻辑               |
| `excel_export.py`               | Excel 报告导出           |
| `models.py`                     | 扫描结果数据模型             |
| `privacy_scan.ps1`              | PowerShell 隐私文件名扫描脚本 |
| `Find-DuplicateFiles.ps1`       | PowerShell 重复文件扫描脚本  |
| `Scan-LargeFilesReport.ps1`     | PowerShell 大文件扫描脚本   |
| `Scan-CleanableItems.ps1`       | PowerShell 可清理项目扫描脚本 |
| `clean_python_project_cache.py` | Python 项目缓存清理脚本      |

## 使用建议

第一次使用时，建议只扫描，不删除。

推荐流程：

```text
1. 选择需要扫描的目录
2. 执行扫描
3. 查看扫描结果
4. 导出报告
5. 手动判断是否需要删除
6. 再执行删除操作
```

不建议直接扫描整个 C 盘。更推荐从下面这些目录开始：

```text
下载
桌面
文档
视频
Python 项目目录
```

## 适合场景

* Windows 电脑空间整理
* 下载文件夹清理
* 桌面文件整理
* Python 项目缓存清理
* GitHub 上传前隐私检查
* 重复文件检查
* 简历项目展示
* Python 桌面工具练习

## 项目亮点

* 使用 Python 标准库完成主要功能
* 图形界面对新手更友好
* 默认只扫描，降低误删风险
* 删除前二次确认
* 支持导出 Excel 报告
* 兼顾电脑清理和隐私检查
* 适合作为 Python 自动化和桌面工具项目展示

## 后续计划

* 增加单元测试
* 增加扫描任务取消按钮
* 增加扫描进度条
* 增加文件预览功能
* 增加重复文件分组展示
* 增加将删除文件移动到回收站的功能
* 增加打包版本，例如 PyInstaller
* 增加英文 README

## 注意事项

本项目不会主动判断某个文件是否一定可以删除。扫描结果只提供参考，用户需要根据自己的实际情况决定是否删除。

涉及微信、QQ、浏览器、系统目录、工作资料、代码项目和个人文档时，请谨慎处理。

## 免责声明

本项目仅用于本地文件扫描和辅助清理。使用者应自行确认删除内容是否重要。由于误删文件造成的数据损失，需要使用者自行承担。

## License

MIT License
