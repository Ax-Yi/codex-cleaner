from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import traceback
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .delete import delete_path
from .excel_export import export_scan_results
from .models import ScanItem, format_size
from .safety import validate_scan_root
from .scanner import CleanerScanner


class CleanerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Windows 本地电脑清理助手")
        self.geometry("1100x720")
        self.minsize(960, 620)

        self.items: list[ScanItem] = []
        self.scan_root = Path.home()
        self.report_text = ""
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.tree_items: dict[str, ScanItem] = {}

        self.path_var = tk.StringVar(value=str(self.scan_root))
        self.large_var = tk.BooleanVar(value=True)
        self.duplicate_var = tk.BooleanVar(value=True)
        self.python_cache_var = tk.BooleanVar(value=True)
        self.privacy_var = tk.BooleanVar(value=True)
        self.min_size_var = tk.IntVar(value=100)
        self.status_var = tk.StringVar(value="请选择目录后开始扫描。默认只扫描，不删除。")

        self.create_widgets()

    def create_widgets(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)
        ttk.Label(top, text="扫描目录").pack(side=tk.LEFT)
        path_entry = ttk.Entry(top, textvariable=self.path_var)
        path_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 8))
        ttk.Button(top, text="选择目录", command=self.choose_folder).pack(side=tk.LEFT)

        options = ttk.LabelFrame(root, text="扫描选项", padding=10)
        options.pack(fill=tk.X, pady=(10, 8))
        ttk.Checkbutton(options, text="大文件", variable=self.large_var).pack(side=tk.LEFT)
        ttk.Label(options, text="阈值 MB").pack(side=tk.LEFT, padx=(18, 4))
        ttk.Spinbox(options, from_=1, to=102400, width=8, textvariable=self.min_size_var).pack(side=tk.LEFT)
        ttk.Checkbutton(options, text="重复文件", variable=self.duplicate_var).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Checkbutton(options, text="Python 项目缓存", variable=self.python_cache_var).pack(side=tk.LEFT, padx=(18, 0))
        ttk.Checkbutton(options, text="隐私文件", variable=self.privacy_var).pack(side=tk.LEFT, padx=(18, 0))

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(0, 8))
        self.scan_button = ttk.Button(actions, text="开始扫描", command=self.start_scan)
        self.scan_button.pack(side=tk.LEFT)
        self.export_button = ttk.Button(actions, text="导出 Excel 报告", command=self.export_excel, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=(8, 0))
        self.delete_button = ttk.Button(actions, text="删除选中项（需确认）", command=self.delete_selected, state=tk.DISABLED)
        self.delete_button.pack(side=tk.LEFT, padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side=tk.RIGHT)

        ttk.Label(root, textvariable=self.status_var).pack(fill=tk.X, pady=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        result_frame = ttk.Frame(notebook, padding=6)
        report_frame = ttk.Frame(notebook, padding=6)
        notebook.add(result_frame, text="扫描结果")
        notebook.add(report_frame, text="清理报告")

        columns = ("category", "type", "size", "reason", "group", "path")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "category": "分类",
            "type": "类型",
            "size": "大小",
            "reason": "原因",
            "group": "重复组",
            "path": "路径",
        }
        widths = {
            "category": 100,
            "type": 70,
            "size": 100,
            "reason": 260,
            "group": 90,
            "path": 520,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, anchor=tk.W)

        y_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        result_frame.rowconfigure(0, weight=1)
        result_frame.columnconfigure(0, weight=1)

        self.report = tk.Text(report_frame, wrap=tk.WORD, height=12)
        report_scroll = ttk.Scrollbar(report_frame, orient=tk.VERTICAL, command=self.report.yview)
        self.report.configure(yscrollcommand=report_scroll.set)
        self.report.grid(row=0, column=0, sticky="nsew")
        report_scroll.grid(row=0, column=1, sticky="ns")
        report_frame.rowconfigure(0, weight=1)
        report_frame.columnconfigure(0, weight=1)
        self.set_report("尚未扫描。")

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="选择要扫描的目录", initialdir=self.path_var.get())
        if folder:
            self.path_var.set(folder)

    def start_scan(self) -> None:
        options = {
            "large": self.large_var.get(),
            "duplicate": self.duplicate_var.get(),
            "python_cache": self.python_cache_var.get(),
            "privacy": self.privacy_var.get(),
        }
        if not any(options.values()):
            messagebox.showwarning("未选择扫描项", "请至少选择一个扫描项。")
            return

        try:
            root = validate_scan_root(Path(self.path_var.get()))
        except ValueError as exc:
            messagebox.showerror("目录不可扫描", str(exc))
            return

        self.scan_root = root
        self.items = []
        self.refresh_results()
        self.set_report("正在扫描，请稍候。")
        self.status_var.set("正在扫描。默认只扫描，不会删除任何文件。")
        self.scan_button.configure(state=tk.DISABLED)
        self.export_button.configure(state=tk.DISABLED)
        self.delete_button.configure(state=tk.DISABLED)
        self.progress.start(12)

        worker = threading.Thread(
            target=self.scan_worker,
            args=(root, options, self.min_size_var.get()),
            daemon=True,
        )
        worker.start()
        self.after(100, self.process_worker_queue)

    def scan_worker(self, root: Path, options: dict[str, bool], min_size_mb: int) -> None:
        started = time.time()
        scanner = CleanerScanner(progress=lambda message: self.worker_queue.put(("status", message)))
        found: list[ScanItem] = []
        try:
            if options["large"]:
                self.worker_queue.put(("status", "正在扫描大文件..."))
                found.extend(scanner.scan_large_files(root, min_size_mb=min_size_mb))
            if options["duplicate"]:
                self.worker_queue.put(("status", "正在扫描重复文件，这一步会读取候选文件哈希..."))
                found.extend(scanner.scan_duplicate_files(root))
            if options["python_cache"]:
                self.worker_queue.put(("status", "正在扫描 Python 项目缓存..."))
                found.extend(scanner.scan_python_caches(root))
            if options["privacy"]:
                self.worker_queue.put(("status", "正在扫描隐私文件名特征..."))
                found.extend(scanner.scan_privacy_files(root))

            report = build_report(found, root, time.time() - started)
            self.worker_queue.put(("done", (found, report)))
        except Exception:
            self.worker_queue.put(("error", traceback.format_exc()))

    def process_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "done":
                    items, report = payload
                    self.finish_scan(items, report)
                    return
                elif kind == "error":
                    self.finish_scan([], "扫描失败。")
                    messagebox.showerror("扫描失败", str(payload))
                    return
        except queue.Empty:
            self.after(100, self.process_worker_queue)

    def finish_scan(self, items: list[ScanItem], report: str) -> None:
        self.progress.stop()
        self.items = items
        self.report_text = report
        self.refresh_results()
        self.set_report(report)
        self.scan_button.configure(state=tk.NORMAL)
        self.export_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        self.delete_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        self.status_var.set(f"扫描完成，共发现 {len(items)} 条结果。默认未删除任何文件。")

    def refresh_results(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree_items.clear()
        for index, item in enumerate(self.items):
            iid = str(index)
            self.tree_items[iid] = item
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    item.category,
                    item.item_type,
                    item.display_size,
                    item.reason,
                    item.duplicate_group,
                    str(item.path),
                ),
            )

    def set_report(self, content: str) -> None:
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", content)
        self.report.configure(state=tk.DISABLED)

    def export_excel(self) -> None:
        if not self.items:
            messagebox.showinfo("没有结果", "当前没有可导出的扫描结果。")
            return
        default_name = f"cleaner-report-{time.strftime('%Y%m%d-%H%M%S')}.xlsx"
        output = filedialog.asksaveasfilename(
            title="保存 Excel 报告",
            defaultextension=".xlsx",
            initialfile=default_name,
            filetypes=[("Excel 工作簿", "*.xlsx")],
        )
        if not output:
            return
        try:
            export_scan_results(Path(output), self.items, self.scan_root, self.report_text)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", f"已导出：{output}")

    def delete_selected(self) -> None:
        selection = self.tree.selection()
        if not selection:
            messagebox.showinfo("未选择", "请先在扫描结果中选择要删除的项目。")
            return

        selected_items = [self.tree_items[iid] for iid in selection if iid in self.tree_items]
        if not selected_items:
            return

        total_size = sum(item.size_bytes for item in selected_items)
        first_confirm = messagebox.askyesno(
            "第一次确认",
            f"将永久删除 {len(selected_items)} 个选中项，总大小约 {format_size(total_size)}。\n\n"
            "建议先导出 Excel 报告。确定继续吗？",
        )
        if not first_confirm:
            return

        typed = simpledialog.askstring(
            "第二次确认",
            "删除不可撤销。请输入“删除”两个字确认：",
            parent=self,
        )
        if typed != "删除":
            messagebox.showinfo("已取消", "未输入确认文字，删除已取消。")
            return

        deleted_paths: set[str] = set()
        failures: list[str] = []
        for item in selected_items:
            ok, message = delete_path(item.path)
            if ok:
                deleted_paths.add(str(item.path))
            else:
                failures.append(f"{item.path}：{message}")

        self.items = [item for item in self.items if str(item.path) not in deleted_paths]
        self.report_text = build_report(self.items, self.scan_root, 0, after_delete=True)
        self.refresh_results()
        self.set_report(self.report_text)
        self.export_button.configure(state=tk.NORMAL if self.items else tk.DISABLED)
        self.delete_button.configure(state=tk.NORMAL if self.items else tk.DISABLED)

        if failures:
            messagebox.showwarning(
                "部分删除失败",
                f"已删除 {len(deleted_paths)} 项，失败 {len(failures)} 项。\n\n" + "\n".join(failures[:10]),
            )
        else:
            messagebox.showinfo("删除完成", f"已删除 {len(deleted_paths)} 项。")


def build_report(items: list[ScanItem], root: Path, elapsed: float, after_delete: bool = False) -> str:
    counts = Counter(item.category for item in items)
    total_size = sum(item.size_bytes for item in items)
    duplicate_groups = len({item.duplicate_group for item in items if item.duplicate_group})

    lines = [
        "Windows 本地电脑清理助手报告",
        f"扫描目录：{root}",
        f"结果数量：{len(items)}",
        f"结果总大小：{format_size(total_size)}",
    ]
    if elapsed:
        lines.append(f"扫描耗时：{elapsed:.1f} 秒")
    if after_delete:
        lines.append("状态：已根据删除操作刷新剩余结果")

    lines.extend(
        [
            "",
            "分类统计：",
            f"- 大文件：{counts.get('大文件', 0)}",
            f"- 重复文件：{counts.get('重复文件', 0)}",
            f"- Python 缓存：{counts.get('Python 缓存', 0)}",
            f"- 隐私文件：{counts.get('隐私文件', 0)}",
            f"- 重复文件组：{duplicate_groups}",
            "",
            "安全说明：",
            "- 默认只扫描，不会自动删除。",
            "- 删除选中项前需要两次确认。",
            "- 系统目录、系统保护目录和符号链接会被跳过。",
            "- 隐私文件扫描只检查文件名特征，不读取文件内容。",
            "- 建议删除前先导出 Excel 报告。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    app = CleanerApp()
    app.mainloop()
