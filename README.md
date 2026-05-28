# Windows 本地电脑清理助手

一个面向新手的 Windows 本地电脑清理工具，使用 Python 和 Tkinter 编写。默认只扫描，不会自动删除文件。

## 功能

- 扫描大文件
- 扫描重复文件
- 扫描 Python 项目缓存
- 扫描疑似隐私文件名，例如 `.env`、密钥、凭据、钱包文件
- 生成清理报告
- 导出所有扫描结果为 Excel `.xlsx`
- 删除前二次确认
- 自动跳过 Windows、Program Files、ProgramData、回收站等系统目录

## 运行

需要 Python 3.10 或更高版本。

```powershell
python run.py
```

也可以用模块方式启动：

```powershell
python -m windows_cleaner_assistant
```

## 安全策略

- 默认行为是扫描和生成报告，不删除任何文件。
- 删除必须先在结果列表中手动选择项目。
- 删除前会弹出确认框，并要求输入“删除”两个字。
- 扫描根目录不能是系统目录。
- 遍历过程中遇到系统目录、系统保护目录、符号链接或无权限目录会跳过。
- 隐私文件扫描只根据文件名模式识别，不读取文件内容。

## 项目结构

```text
windows_cleaner_assistant/
  app.py          # Tkinter 图形界面
  scanner.py      # 大文件、重复文件、缓存、隐私文件扫描逻辑
  safety.py       # 系统目录保护
  delete.py       # 删除保护
  excel_export.py # 标准库 xlsx 导出
  models.py       # 扫描结果数据模型
run.py            # 启动入口
```

## GitHub 建议

这个项目不依赖第三方包，适合直接放到 GitHub。后续可以添加：

- 单元测试
- 打包脚本，例如 PyInstaller
- 将删除改为移动到回收站
- 扫描任务取消按钮
