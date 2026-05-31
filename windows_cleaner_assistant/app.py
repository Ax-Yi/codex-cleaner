from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
import traceback
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .delete import SEND2TRASH_INSTALL_MESSAGE, delete_path, send2trash_available
from .excel_export import export_scan_results
from .models import RISK_NOT_RECOMMENDED, ScanItem, format_size
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
        self.checked_paths: set[str] = set()
        self.sort_size_desc = False
        self.pause_event = threading.Event()
        self.stop_event = threading.Event()
        self.scan_active = False
        self.last_scan_status = ""

        self.path_var = tk.StringVar(value=str(self.scan_root))
        self.result_filter_var = tk.StringVar(value="")
        self.risk_filter_var = tk.StringVar(value="全部")
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
        self.choose_button = ttk.Button(top, text="选择目录", command=self.choose_folder)
        self.choose_button.pack(side=tk.LEFT)

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
        self.pause_button = ttk.Button(actions, text="暂停扫描", command=self.pause_scan, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=(8, 0))
        self.resume_button = ttk.Button(actions, text="继续扫描", command=self.resume_scan, state=tk.DISABLED)
        self.resume_button.pack(side=tk.LEFT, padx=(8, 0))
        self.stop_button = ttk.Button(actions, text="停止扫描", command=self.stop_scan, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.export_button = ttk.Button(actions, text="导出 Excel 报告", command=self.export_excel, state=tk.DISABLED)
        self.export_button.pack(side=tk.LEFT, padx=(8, 0))
        self.progress = ttk.Progressbar(actions, mode="indeterminate", length=180)
        self.progress.pack(side=tk.RIGHT)

        ttk.Label(root, textvariable=self.status_var).pack(fill=tk.X, pady=(0, 8))

        notebook = ttk.Notebook(root)
        notebook.pack(fill=tk.BOTH, expand=True)

        result_frame = ttk.Frame(notebook, padding=6)
        report_frame = ttk.Frame(notebook, padding=6)
        notebook.add(result_frame, text="扫描结果")
        notebook.add(report_frame, text="清理报告")

        filter_frame = ttk.Frame(result_frame)
        filter_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Label(filter_frame, text="扫描结果搜索").pack(side=tk.LEFT)
        ttk.Entry(filter_frame, textvariable=self.result_filter_var, width=42).pack(side=tk.LEFT, padx=(8, 8))
        ttk.Label(filter_frame, text="在已扫描结果中搜索路径或文件名").pack(side=tk.LEFT)
        ttk.Label(filter_frame, text="风险等级").pack(side=tk.LEFT)
        risk_filter = ttk.Combobox(
            filter_frame,
            textvariable=self.risk_filter_var,
            values=("全部", "推荐清理", "谨慎处理", "不建议删除"),
            width=12,
            state="readonly",
        )
        risk_filter.pack(side=tk.LEFT, padx=(8, 8))
        risk_filter.bind("<<ComboboxSelected>>", self.on_result_filter_changed)
        ttk.Button(filter_frame, text="只显示推荐清理", command=self.show_recommended_only).pack(side=tk.LEFT)
        ttk.Button(filter_frame, text="按大小从大到小", command=self.sort_results_by_size_desc).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(filter_frame, text="清空", command=self.clear_result_filter).pack(side=tk.LEFT)
        ttk.Label(filter_frame, text="筛选只影响界面显示").pack(side=tk.LEFT, padx=(8, 0))

        selection_frame = ttk.Frame(result_frame)
        selection_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Button(selection_frame, text="全选", command=self.check_all_visible).pack(side=tk.LEFT)
        ttk.Button(selection_frame, text="取消全选", command=self.uncheck_all_visible).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(selection_frame, text="只选择推荐清理", command=self.check_recommended_items).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        self.delete_button = ttk.Button(
            selection_frame,
            text="移动勾选项到回收站",
            command=self.delete_selected,
            state=tk.DISABLED,
        )
        self.delete_button.pack(side=tk.LEFT, padx=(16, 0))

        columns = ("selected", "category", "type", "risk", "suggestion", "size", "reason", "group", "path")
        self.tree = ttk.Treeview(result_frame, columns=columns, show="headings", selectmode="extended")
        headings = {
            "selected": "选择",
            "category": "分类",
            "type": "类型",
            "risk": "风险等级",
            "suggestion": "处理建议",
            "size": "大小",
            "reason": "原因",
            "group": "重复组",
            "path": "路径",
        }
        widths = {
            "selected": 60,
            "category": 100,
            "type": 70,
            "risk": 100,
            "suggestion": 260,
            "size": 100,
            "reason": 260,
            "group": 90,
            "path": 520,
        }
        for column in columns:
            self.tree.heading(column, text=headings[column])
            self.tree.column(column, width=widths[column], minwidth=60, anchor=tk.W)
        self.tree.heading("size", text=headings["size"], command=self.sort_results_by_size_desc)
        self.tree.bind("<Button-1>", self.on_tree_click)

        y_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=self.tree.yview)
        x_scroll = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        self.tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.tree.grid(row=2, column=0, sticky="nsew")
        y_scroll.grid(row=2, column=1, sticky="ns")
        x_scroll.grid(row=3, column=0, sticky="ew")
        result_frame.rowconfigure(2, weight=1)
        result_frame.columnconfigure(0, weight=1)
        self.result_filter_var.trace_add("write", self.on_result_filter_changed)

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

    def pause_scan(self) -> None:
        if not self.scan_active:
            return
        self.pause_event.set()
        self.status_var.set("扫描已暂停")
        self.pause_button.configure(state=tk.DISABLED)
        self.resume_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.NORMAL)

    def resume_scan(self) -> None:
        if not self.scan_active:
            return
        self.pause_event.clear()
        self.status_var.set(self.last_scan_status or "正在扫描：继续扫描中")
        self.pause_button.configure(state=tk.NORMAL)
        self.resume_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)

    def stop_scan(self) -> None:
        if not self.scan_active:
            return
        self.stop_event.set()
        self.pause_event.clear()
        self.status_var.set("正在停止扫描...")
        self.pause_button.configure(state=tk.DISABLED)
        self.resume_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.DISABLED)

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
        self.checked_paths.clear()
        self.pause_event.clear()
        self.stop_event.clear()
        self.scan_active = True
        self.refresh_results()
        self.set_report("正在扫描，请稍候。")
        self.status_var.set("正在扫描。默认只扫描，不会删除任何文件。")
        self.last_scan_status = "正在扫描。默认只扫描，不会删除任何文件。"
        self.scan_button.configure(state=tk.DISABLED)
        self.choose_button.configure(state=tk.DISABLED)
        self.pause_button.configure(state=tk.NORMAL)
        self.resume_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.NORMAL)
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
        found: list[ScanItem] = []

        def on_result(item: ScanItem) -> None:
            found.append(item)
            self.worker_queue.put(("partial", item))

        scanner = CleanerScanner(
            progress=lambda message: self.worker_queue.put(("status", message)),
            pause_event=self.pause_event,
            stop_event=self.stop_event,
            result_callback=on_result,
        )
        try:
            if options["large"]:
                self.worker_queue.put(("status", "正在扫描大文件..."))
                scanner.scan_large_files(root, min_size_mb=min_size_mb)
            if options["duplicate"] and not self.stop_event.is_set():
                self.worker_queue.put(("status", "正在扫描重复文件，这一步会读取候选文件哈希..."))
                scanner.scan_duplicate_files(root)
            if options["python_cache"] and not self.stop_event.is_set():
                self.worker_queue.put(("status", "正在扫描 Python 项目缓存..."))
                scanner.scan_python_caches(root)
            if options["privacy"] and not self.stop_event.is_set():
                self.worker_queue.put(("status", "正在扫描隐私文件名特征..."))
                scanner.scan_privacy_files(root)

            report = build_report(found, root, time.time() - started)
            self.worker_queue.put(("done", (found, report, self.stop_event.is_set())))
        except Exception:
            self.worker_queue.put(("error", traceback.format_exc()))

    def process_worker_queue(self) -> None:
        try:
            while True:
                kind, payload = self.worker_queue.get_nowait()
                if kind == "status":
                    status = str(payload)
                    self.last_scan_status = status
                    self.status_var.set(status)
                elif kind == "partial":
                    self.items.append(payload)
                    self.refresh_results()
                elif kind == "done":
                    items, report, stopped = payload
                    self.finish_scan(items, report, stopped=stopped)
                    return
                elif kind == "error":
                    self.finish_scan([], "扫描失败。")
                    messagebox.showerror("扫描失败", str(payload))
                    return
        except queue.Empty:
            self.after(100, self.process_worker_queue)

    def finish_scan(self, items: list[ScanItem], report: str, stopped: bool = False) -> None:
        self.progress.stop()
        self.scan_active = False
        self.pause_event.clear()
        self.items = items
        self.report_text = report
        self.refresh_results()
        self.set_report(report)
        self.scan_button.configure(state=tk.NORMAL)
        self.choose_button.configure(state=tk.NORMAL)
        self.pause_button.configure(state=tk.DISABLED)
        self.resume_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.DISABLED)
        self.export_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        self.delete_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        if stopped:
            self.status_var.set("扫描已停止，已保留当前结果")
        else:
            self.status_var.set(f"扫描完成，共发现 {len(items)} 条结果。默认未删除任何文件。")

    def refresh_results(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.tree_items.clear()
        for index, item in self.get_visible_indexed_items():
            iid = str(index)
            self.tree_items[iid] = item
            self.tree.insert(
                "",
                tk.END,
                iid=iid,
                values=(
                    "☑" if self.item_key(item) in self.checked_paths else "☐",
                    item.category,
                    item.item_type,
                    item.risk_level,
                    item.suggestion,
                    item.display_size,
                    item.reason,
                    item.duplicate_group,
                    str(item.path),
                ),
            )

    def item_key(self, item: ScanItem) -> str:
        return "\0".join(
            [
                str(item.path),
                item.category,
                item.reason,
                item.duplicate_group,
                item.checksum,
            ]
        )

    def on_tree_click(self, event: tk.Event) -> str | None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return None
        if self.tree.identify_column(event.x) != "#1":
            return None

        row_id = self.tree.identify_row(event.y)
        if not row_id or row_id not in self.tree_items:
            return "break"

        item = self.tree_items[row_id]
        key = self.item_key(item)
        if key in self.checked_paths:
            self.checked_paths.remove(key)
        else:
            self.checked_paths.add(key)
        self.refresh_results()
        return "break"

    def check_all_visible(self) -> None:
        for item in self.get_visible_items():
            self.checked_paths.add(self.item_key(item))
        self.refresh_results()

    def uncheck_all_visible(self) -> None:
        for item in self.get_visible_items():
            self.checked_paths.discard(self.item_key(item))
        self.refresh_results()

    def check_recommended_items(self) -> None:
        self.checked_paths.clear()
        for item in self.items:
            if item.risk_level == "推荐清理":
                self.checked_paths.add(self.item_key(item))
        self.refresh_results()

    def get_visible_indexed_items(self) -> list[tuple[int, ScanItem]]:
        filter_text = self.result_filter_var.get().strip().lower()
        risk_filter = self.risk_filter_var.get()
        visible: list[tuple[int, ScanItem]] = []

        for index, item in enumerate(self.items):
            if filter_text and filter_text not in str(item.path).lower():
                continue
            if risk_filter != "全部" and item.risk_level != risk_filter:
                continue
            visible.append((index, item))

        if self.sort_size_desc:
            visible.sort(key=lambda pair: pair[1].size_bytes, reverse=True)
        return visible

    def get_visible_items(self) -> list[ScanItem]:
        return [item for _index, item in self.get_visible_indexed_items()]

    def get_checked_items(self) -> list[ScanItem]:
        return [item for item in self.items if self.item_key(item) in self.checked_paths]

    def clear_result_filter(self) -> None:
        self.result_filter_var.set("")
        self.risk_filter_var.set("全部")
        self.sort_size_desc = False
        self.refresh_results()

    def show_recommended_only(self) -> None:
        self.risk_filter_var.set("推荐清理")
        self.refresh_results()

    def sort_results_by_size_desc(self) -> None:
        self.sort_size_desc = True
        self.refresh_results()

    def on_result_filter_changed(self, *_args: object) -> None:
        if hasattr(self, "tree"):
            self.refresh_results()

    def set_report(self, content: str) -> None:
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", content)
        self.report.configure(state=tk.DISABLED)

    def export_excel(self) -> None:
        if not self.items:
            messagebox.showinfo("没有结果", "当前没有可导出的扫描结果。")
            return
        export_all = messagebox.askyesnocancel(
            "选择导出范围",
            "选择“是”导出全部扫描结果。\n"
            "选择“否”只导出当前勾选的结果。\n"
            "选择“取消”放弃导出。",
        )
        if export_all is None:
            return

        items_to_export = self.items if export_all else self.get_checked_items()
        if not items_to_export:
            messagebox.showinfo("没有可导出结果", "当前没有勾选任何结果。")
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
            report_text = self.report_text if export_all else build_report(items_to_export, self.scan_root, 0)
            export_scan_results(Path(output), items_to_export, self.scan_root, report_text)
        except OSError as exc:
            messagebox.showerror("导出失败", str(exc))
            return
        messagebox.showinfo("导出完成", f"已导出：{output}")

    def delete_selected(self) -> None:
        selected_items = self.get_checked_items()
        if not selected_items:
            messagebox.showinfo("未勾选", "请先勾选需要处理的项目。")
            return

        if not send2trash_available():
            messagebox.showerror(
                "缺少依赖",
                "移动到回收站需要安装 send2trash。\n\n"
                f"{SEND2TRASH_INSTALL_MESSAGE}",
            )
            return

        blocked_items = [item for item in selected_items if item.risk_level == RISK_NOT_RECOMMENDED]
        processable_items = [item for item in selected_items if item.risk_level != RISK_NOT_RECOMMENDED]
        checked_count = len(selected_items)
        blocked_count = len(blocked_items)
        processable_count = len(processable_items)

        if not processable_items:
            preview = "\n".join(str(item.path) for item in blocked_items[:8])
            if len(blocked_items) > 8:
                preview += f"\n... 还有 {len(blocked_items) - 8} 项"
            messagebox.showwarning(
                "已阻止移动",
                "勾选项全部为“不建议删除”的文件或文件夹，已默认禁止处理。\n\n"
                f"{preview}",
            )
            return

        total_size = sum(item.size_bytes for item in processable_items)
        first_confirm = messagebox.askyesno(
            "第一次确认",
            f"本次勾选数量：{checked_count}\n"
            f"可处理数量：{processable_count}\n"
            f"被安全策略拦截数量：{blocked_count}\n"
            f"预计释放空间：{format_size(total_size)}\n\n"
            "风险等级为“不建议删除”的项目不会被移动到回收站。\n"
            "建议先导出 Excel 报告。确定继续吗？",
        )
        if not first_confirm:
            return

        typed = simpledialog.askstring(
            "第二次确认",
            "将把可处理项目移动到回收站。请输入“移动”两个字确认：",
            parent=self,
        )
        if typed != "移动":
            messagebox.showinfo("已取消", "未输入确认文字，操作已取消。")
            return

        deleted_paths: set[str] = set()
        attempted_paths: set[str] = set()
        failures: list[str] = []
        for item in processable_items:
            path_text = str(item.path)
            if path_text in attempted_paths:
                continue
            attempted_paths.add(path_text)
            ok, message = delete_path(item.path)
            if ok:
                deleted_paths.add(path_text)
                self.checked_paths.discard(self.item_key(item))
            else:
                failures.append(f"{item.path}：{message}")

        self.items = [item for item in self.items if str(item.path) not in deleted_paths]
        self.checked_paths = {self.item_key(item) for item in self.items if self.item_key(item) in self.checked_paths}
        self.report_text = build_report(self.items, self.scan_root, 0, after_delete=True)
        self.report_text += (
            "\n\n最近处理结果："
            f"\n- 操作：移动勾选项到回收站"
            f"\n- 勾选数量：{checked_count}"
            f"\n- 可处理数量：{processable_count}"
            f"\n- 被安全策略拦截数量：{blocked_count}"
            f"\n- 成功移动数量：{len(deleted_paths)}"
            f"\n- 失败数量：{len(failures)}"
            f"\n- 预计释放空间：{format_size(total_size)}"
        )
        self.refresh_results()
        self.set_report(self.report_text)
        self.export_button.configure(state=tk.NORMAL if self.items else tk.DISABLED)
        self.delete_button.configure(state=tk.NORMAL if self.items else tk.DISABLED)

        if failures:
            messagebox.showwarning(
                "部分移动失败",
                f"已移动 {len(deleted_paths)} 项，失败 {len(failures)} 项。\n\n" + "\n".join(failures[:10]),
            )
        else:
            messagebox.showinfo("移动完成", f"已移动 {len(deleted_paths)} 项到回收站。")


def build_report(items: list[ScanItem], root: Path, elapsed: float, after_delete: bool = False) -> str:
    counts = Counter(item.category for item in items)
    risk_counts = Counter(item.risk_level for item in items)
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
            f"- 文件搜索：{counts.get('文件搜索', 0)}",
            f"- 重复文件组：{duplicate_groups}",
            "",
            "风险统计：",
            f"- 推荐清理：{risk_counts.get('推荐清理', 0)}",
            f"- 谨慎处理：{risk_counts.get('谨慎处理', 0)}",
            f"- 不建议删除：{risk_counts.get('不建议删除', 0)}",
            "",
            "安全说明：",
            "- 默认只扫描，不会自动删除。",
            "- 删除选中项前需要两次确认。",
            "- 不建议删除的项目默认禁止删除。",
            "- 系统目录、系统保护目录和符号链接会被跳过。",
            "- 隐私文件扫描只检查文件名特征，不读取文件内容。",
            "- 建议删除前先导出 Excel 报告。",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    app = CleanerApp()
    app.mainloop()
