from __future__ import annotations

import json
import queue
import threading
import tempfile
import time
import tkinter as tk
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from .delete import SEND2TRASH_INSTALL_MESSAGE, delete_path, send2trash_available
from .excel_export import export_scan_results
from .history import clear_scan_history, load_scan_history, save_scan_history
from .models import RISK_CAUTION, RISK_NOT_RECOMMENDED, RISK_RECOMMENDED, ScanItem, format_size, scan_item_key
from .safety import validate_scan_root
from .scanner import CleanerScanner


class CleanerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Windows 本地电脑清理助手")
        self.geometry("1100x720")
        self.minsize(960, 620)

        self.items: list[ScanItem] = []
        self.scan_root = default_scan_root()
        self.report_text = ""
        self.last_action_summary = ""
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.tree_items: dict[str, ScanItem] = {}
        self.checked_paths: set[str] = set()
        self.preset_buttons: list[ttk.Button] = []
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

        presets = ttk.LabelFrame(root, text="常用扫描预设", padding=10)
        presets.pack(fill=tk.X, pady=(10, 8))
        self.add_preset_button(presets, "下载目录", lambda: self.set_preset_path(Path.home() / "Downloads"))
        self.add_preset_button(presets, "桌面", lambda: self.set_preset_path(Path.home() / "Desktop"))
        self.add_preset_button(presets, "文档", lambda: self.set_preset_path(Path.home() / "Documents"))
        self.add_preset_button(presets, "视频", lambda: self.set_preset_path(Path.home() / "Videos"))
        self.add_preset_button(presets, "图片", lambda: self.set_preset_path(Path.home() / "Pictures"))
        self.add_preset_button(presets, "Python 项目目录", self.choose_python_project_preset)
        self.add_preset_button(presets, "系统临时目录", lambda: self.set_preset_path(Path(tempfile.gettempdir())))
        self.add_preset_button(
            presets,
            "NVIDIA 缓存",
            lambda: self.set_preset_path(Path.home() / "AppData" / "Local" / "NVIDIA" / "DXCache"),
        )

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
        ttk.Button(actions, text="查看扫描历史", command=self.show_scan_history).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(actions, text="查看扫描历史", command=self.show_scan_history).pack(side=tk.LEFT, padx=(8, 0))
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
        ttk.Button(selection_frame, text="查看重复文件分组", command=self.show_duplicate_groups).pack(
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

    def add_preset_button(self, parent: ttk.Frame, text: str, command: object) -> None:
        button = ttk.Button(parent, text=text, command=command)
        button.pack(side=tk.LEFT, padx=(0, 8), pady=2)
        self.preset_buttons.append(button)

    def set_preset_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showinfo("目录不存在", "该目录不存在，请手动选择目录。")
            return
        self.path_var.set(str(path))

    def choose_python_project_preset(self) -> None:
        default_path = Path(r"D:\py xiangmu")
        if default_path.exists():
            self.path_var.set(str(default_path))
            return

        folder = filedialog.askdirectory(title="选择 Python 项目目录", initialdir=str(Path.home()))
        if folder:
            self.path_var.set(folder)

    def set_directory_controls_state(self, state: str) -> None:
        self.choose_button.configure(state=state)
        for button in self.preset_buttons:
            button.configure(state=state)

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
        if is_c_drive_root(root):
            should_continue = messagebox.askyesno(
                "不建议扫描整个 C 盘",
                "不建议直接扫描整个 C 盘，建议先扫描下载目录、桌面或缓存目录。是否继续？",
            )
            if not should_continue:
                return

        self.scan_root = root
        self.items = []
        self.checked_paths.clear()
        self.last_action_summary = ""
        self.pause_event.clear()
        self.stop_event.clear()
        self.scan_active = True
        self.refresh_results()
        self.set_report("正在扫描，请稍候。")
        self.status_var.set("正在扫描。默认只扫描，不会删除任何文件。")
        self.last_scan_status = "正在扫描。默认只扫描，不会删除任何文件。"
        self.scan_button.configure(state=tk.DISABLED)
        self.set_directory_controls_state(tk.DISABLED)
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
        self.set_directory_controls_state(tk.NORMAL)
        self.pause_button.configure(state=tk.DISABLED)
        self.resume_button.configure(state=tk.DISABLED)
        self.stop_button.configure(state=tk.DISABLED)
        self.export_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        self.delete_button.configure(state=tk.NORMAL if items else tk.DISABLED)
        if stopped:
            self.status_var.set("扫描已停止，已保留当前结果")
        else:
            save_scan_history(items, self.scan_root)
            try:
                save_scan_history(items, self.scan_root)
            except OSError as exc:
                messagebox.showwarning("历史记录保存失败", str(exc))
            self.status_var.set(f"扫描完成，共发现 {len(items)} 条结果。默认未删除任何文件。")

    def show_scan_history(self) -> None:
        records = load_scan_history()
        window = tk.Toplevel(self)
        window.title("扫描历史记录")
        window.geometry("1180x520")
        window.minsize(980, 420)

        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="清空历史记录", command=lambda: self.clear_scan_history(window, tree)).pack(
            side=tk.LEFT
        )

        frame = ttk.Frame(window, padding=(8, 0, 8, 8))
        frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "scan_time",
            "scan_dir",
            "result_count",
            "total_size",
            "recommended",
            "caution",
            "not_recommended",
            "duplicate_groups",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "scan_time": "扫描时间",
            "scan_dir": "扫描目录",
            "result_count": "结果数量",
            "total_size": "总大小",
            "recommended": "推荐清理",
            "caution": "谨慎处理",
            "not_recommended": "不建议删除",
            "duplicate_groups": "重复文件组",
        }
        widths = {
            "scan_time": 160,
            "scan_dir": 360,
            "result_count": 80,
            "total_size": 100,
            "recommended": 150,
            "caution": 150,
            "not_recommended": 150,
            "duplicate_groups": 90,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=60, anchor=tk.W)

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.populate_scan_history_tree(tree, records)

    def populate_scan_history_tree(self, tree: ttk.Treeview, records: list[dict[str, object]]) -> None:
        tree.delete(*tree.get_children())
        for index, record in enumerate(reversed(records)):
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    record.get("scan_time", ""),
                    record.get("scan_dir", ""),
                    record.get("result_count", 0),
                    record.get("total_size", ""),
                    f"{record.get('recommended_count', 0)} 个 / {record.get('recommended_size', '0 B')}",
                    f"{record.get('caution_count', 0)} 个 / {record.get('caution_size', '0 B')}",
                    f"{record.get('not_recommended_count', 0)} 个 / {record.get('not_recommended_size', '0 B')}",
                    record.get("duplicate_group_count", 0),
                ),
            )

    def clear_scan_history(self, window: tk.Toplevel, tree: ttk.Treeview) -> None:
        if not messagebox.askyesno("清空历史记录", "确定清空所有扫描历史记录吗？", parent=window):
            return
        save_history_records([])
        self.populate_scan_history_tree(tree, [])
        messagebox.showinfo("已清空", "扫描历史记录已清空。", parent=window)

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
        return scan_item_key(item)

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
        self.refresh_report_summary()
        return "break"

    def check_all_visible(self) -> None:
        for item in self.get_visible_items():
            self.checked_paths.add(self.item_key(item))
        self.refresh_results()
        self.refresh_report_summary()

    def uncheck_all_visible(self) -> None:
        for item in self.get_visible_items():
            self.checked_paths.discard(self.item_key(item))
        self.refresh_results()
        self.refresh_report_summary()

    def check_recommended_items(self) -> None:
        self.checked_paths.clear()
        for item in self.items:
            if item.risk_level == "推荐清理":
                self.checked_paths.add(self.item_key(item))
        self.refresh_results()
        self.refresh_report_summary()

    def show_duplicate_groups(self) -> None:
        groups = duplicate_groups(self.items)
        if not groups:
            messagebox.showinfo("没有重复文件", "当前扫描结果中没有重复文件分组。")
            return

        window = tk.Toplevel(self)
        window.title("重复文件分组")
        window.geometry("1180x640")
        window.minsize(980, 520)

        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="只勾选重复副本", command=lambda: self.check_duplicate_copies(tree, groups)).pack(
            side=tk.LEFT
        )
        ttk.Button(toolbar, text="清空重复文件勾选", command=lambda: self.clear_duplicate_checks(tree, groups)).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(toolbar, text="复制重复组信息", command=lambda: self.copy_duplicate_group_info(groups)).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        frame = ttk.Frame(window, padding=(8, 0, 8, 8))
        frame.pack(fill=tk.BOTH, expand=True)
        columns = ("selected", "group", "keep", "count", "path", "size", "modified", "risk", "suggestion")
        tree = ttk.Treeview(frame, columns=columns, show="headings", selectmode="browse")
        headings = {
            "selected": "选择",
            "group": "重复组编号",
            "keep": "推荐保留",
            "count": "组内数量",
            "path": "完整路径",
            "size": "文件大小",
            "modified": "修改时间",
            "risk": "风险等级",
            "suggestion": "处理建议",
        }
        widths = {
            "selected": 60,
            "group": 110,
            "keep": 110,
            "count": 80,
            "path": 460,
            "size": 100,
            "modified": 150,
            "risk": 100,
            "suggestion": 260,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=60, anchor=tk.W)

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        tree.item_keys = {}  # type: ignore[attr-defined]
        tree.bind("<Button-1>", lambda event: self.on_duplicate_tree_click(event, tree, groups))
        self.refresh_duplicate_tree(tree, groups)

    def refresh_duplicate_tree(self, tree: ttk.Treeview, groups: dict[str, list[ScanItem]]) -> None:
        tree.delete(*tree.get_children())
        tree.item_keys = {}  # type: ignore[attr-defined]
        for group_id in sorted(groups):
            group_items = sorted(groups[group_id], key=lambda item: str(item.path).lower())
            recommended = recommended_duplicate_keep(group_items)
            for item in group_items:
                iid = f"{group_id}:{len(tree.item_keys)}"  # type: ignore[attr-defined]
                key = self.item_key(item)
                tree.item_keys[iid] = key  # type: ignore[attr-defined]
                tree.insert(
                    "",
                    tk.END,
                    iid=iid,
                    values=(
                        "☑" if key in self.checked_paths else "☐",
                        group_id,
                        "是" if recommended is not None and self.item_key(recommended) == key else "请手动确认"
                        if recommended is None
                        else "",
                        len(group_items),
                        str(item.path),
                        item.display_size,
                        format_modified_time(item.path),
                        item.risk_level,
                        item.suggestion,
                    ),
                )

    def on_duplicate_tree_click(
        self, event: tk.Event, tree: ttk.Treeview, groups: dict[str, list[ScanItem]]
    ) -> str | None:
        if tree.identify_region(event.x, event.y) != "cell" or tree.identify_column(event.x) != "#1":
            return None
        row_id = tree.identify_row(event.y)
        if not row_id:
            return "break"
        key = tree.item_keys.get(row_id)  # type: ignore[attr-defined]
        if not key:
            return "break"
        if key in self.checked_paths:
            self.checked_paths.remove(key)
        else:
            self.checked_paths.add(key)
        self.refresh_results()
        self.refresh_report_summary()
        self.refresh_duplicate_tree(tree, groups)
        return "break"

    def check_duplicate_copies(self, tree: ttk.Treeview, groups: dict[str, list[ScanItem]]) -> None:
        for group_items in groups.values():
            recommended = recommended_duplicate_keep(group_items)
            if recommended is None:
                continue
            recommended_key = self.item_key(recommended)
            for item in group_items:
                if self.item_key(item) == recommended_key:
                    continue
                if item.risk_level == RISK_RECOMMENDED:
                    self.checked_paths.add(self.item_key(item))
        self.refresh_results()
        self.refresh_report_summary()
        self.refresh_duplicate_tree(tree, groups)

    def clear_duplicate_checks(self, tree: ttk.Treeview, groups: dict[str, list[ScanItem]]) -> None:
        for group_items in groups.values():
            for item in group_items:
                self.checked_paths.discard(self.item_key(item))
        self.refresh_results()
        self.refresh_report_summary()
        self.refresh_duplicate_tree(tree, groups)

    def copy_duplicate_group_info(self, groups: dict[str, list[ScanItem]]) -> None:
        text = build_duplicate_group_text(groups, self.checked_paths)
        self.clipboard_clear()
        self.clipboard_append(text)
        messagebox.showinfo("已复制", "重复组信息已复制到剪贴板。")

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

    def refresh_report_summary(self) -> None:
        if not self.items or self.scan_active:
            return
        self.report_text = build_report(
            self.items,
            self.scan_root,
            0,
            checked_items=self.get_checked_items(),
            extra_text=self.last_action_summary,
        )
        self.set_report(self.report_text)

    def set_report(self, content: str) -> None:
        self.report.configure(state=tk.NORMAL)
        self.report.delete("1.0", tk.END)
        self.report.insert("1.0", content)
        self.report.configure(state=tk.DISABLED)

    def show_scan_history(self) -> None:
        window = tk.Toplevel(self)
        window.title("扫描历史记录")
        window.geometry("1120x520")
        window.minsize(920, 420)

        toolbar = ttk.Frame(window, padding=8)
        toolbar.pack(fill=tk.X)
        ttk.Button(toolbar, text="清空历史记录", command=lambda: self.clear_history_window(tree)).pack(side=tk.LEFT)

        frame = ttk.Frame(window, padding=(8, 0, 8, 8))
        frame.pack(fill=tk.BOTH, expand=True)
        columns = (
            "scan_time",
            "scan_root",
            "result_count",
            "total_size",
            "recommended",
            "caution",
            "not_recommended",
            "duplicate_groups",
        )
        tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {
            "scan_time": "扫描时间",
            "scan_root": "扫描目录",
            "result_count": "结果数量",
            "total_size": "总大小",
            "recommended": "推荐清理",
            "caution": "谨慎处理",
            "not_recommended": "不建议删除",
            "duplicate_groups": "重复文件组",
        }
        widths = {
            "scan_time": 150,
            "scan_root": 360,
            "result_count": 80,
            "total_size": 100,
            "recommended": 150,
            "caution": 150,
            "not_recommended": 150,
            "duplicate_groups": 90,
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=widths[column], minwidth=70, anchor=tk.W)

        y_scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        x_scroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self.refresh_history_tree(tree)

    def refresh_history_tree(self, tree: ttk.Treeview) -> None:
        tree.delete(*tree.get_children())
        for index, record in enumerate(reversed(load_scan_history())):
            tree.insert(
                "",
                tk.END,
                iid=str(index),
                values=(
                    record.get("scan_time", ""),
                    record.get("scan_root", ""),
                    record.get("result_count", 0),
                    record.get("total_size", ""),
                    f"{record.get('recommended_count', 0)} / {record.get('recommended_size', '')}",
                    f"{record.get('caution_count', 0)} / {record.get('caution_size', '')}",
                    f"{record.get('not_recommended_count', 0)} / {record.get('not_recommended_size', '')}",
                    record.get("duplicate_group_count", 0),
                ),
            )

    def clear_history_window(self, tree: ttk.Treeview) -> None:
        if not messagebox.askyesno("清空历史记录", "确定要清空所有扫描历史记录吗？"):
            return
        try:
            clear_scan_history()
        except OSError as exc:
            messagebox.showerror("清空失败", str(exc))
            return
        self.refresh_history_tree(tree)

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
            export_scan_results(Path(output), items_to_export, self.scan_root, report_text, self.checked_paths)
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
        self.last_action_summary = (
            "最近处理结果："
            f"\n- 操作：移动勾选项到回收站"
            f"\n- 勾选数量：{checked_count}"
            f"\n- 可处理数量：{processable_count}"
            f"\n- 被安全策略拦截数量：{blocked_count}"
            f"\n- 成功移动数量：{len(deleted_paths)}"
            f"\n- 失败数量：{len(failures)}"
            f"\n- 预计释放空间：{format_size(total_size)}"
        )
        self.report_text = build_report(
            self.items,
            self.scan_root,
            0,
            after_delete=True,
            checked_items=self.get_checked_items(),
            extra_text=self.last_action_summary,
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


def build_report(
    items: list[ScanItem],
    root: Path,
    elapsed: float,
    after_delete: bool = False,
    checked_items: list[ScanItem] | None = None,
    extra_text: str = "",
) -> str:
    counts = Counter(item.category for item in items)
    risk_counts = Counter(item.risk_level for item in items)
    total_size = sum(item.size_bytes for item in items)
    duplicate_groups = len({item.duplicate_group for item in items if item.duplicate_group})
    checked_items = checked_items or []
    risk_sizes = risk_size_totals(items)
    checked_size = sum(item.size_bytes for item in checked_items)
    advice = build_cleaning_advice(items)

    lines = [
        "清理建议汇总",
        f"扫描时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"扫描目录：{root}",
        f"总结果数量：{len(items)}",
        f"总文件大小：{format_size(total_size)}",
        f"推荐清理：{risk_counts.get('推荐清理', 0)} 个，合计 {format_size(risk_sizes.get('推荐清理', 0))}",
        f"谨慎处理：{risk_counts.get('谨慎处理', 0)} 个，合计 {format_size(risk_sizes.get('谨慎处理', 0))}",
        f"不建议删除：{risk_counts.get('不建议删除', 0)} 个，合计 {format_size(risk_sizes.get('不建议删除', 0))}",
        f"重复文件组数量：{duplicate_groups}",
        f"已勾选数量：{len(checked_items)}",
        f"已勾选预计释放空间：{format_size(checked_size)}",
        "",
        "清理建议：",
    ]
    lines.extend(f"- {message}" for message in advice)
    lines.extend(
        [
            "",
            "Windows 本地电脑清理助手报告",
        ]
    )
    lines.extend(
        [
        f"扫描目录：{root}",
        f"结果数量：{len(items)}",
        f"结果总大小：{format_size(total_size)}",
        ]
    )
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
    if extra_text:
        lines.extend(["", extra_text])
    return "\n".join(lines)


def risk_size_totals(items: list[ScanItem]) -> dict[str, int]:
    totals = {"推荐清理": 0, "谨慎处理": 0, "不建议删除": 0}
    for item in items:
        totals[item.risk_level] = totals.get(item.risk_level, 0) + item.size_bytes
    return totals


def build_cleaning_advice(items: list[ScanItem]) -> list[str]:
    paths = [str(item.path).lower().replace("/", "\\") for item in items]
    categories = {item.category for item in items}
    advice: list[str] = []

    if "Python 缓存" in categories or any("__pycache__" in path or path.endswith(".pyc") for path in paths):
        advice.append("存在 Python 缓存，建议优先清理 Python 缓存。")
    if any("temp" in path for path in paths):
        advice.append("存在 Temp 临时文件，建议优先清理临时文件。")
    if any("dxcache" in path for path in paths):
        advice.append("存在 NVIDIA DXCache，缓存可以清理，但下次启动游戏可能重新生成。")
    if any("graphicscache" in path for path in paths):
        advice.append("存在 GraphicsCache，游戏图形缓存可以清理，但游戏可能重新生成。")
    if any(keyword in path for path in paths for keyword in ("tencent", "wechat", "wxwork", "qq")):
        advice.append("存在 Tencent、WeChat、WXWork 或 QQ 目录，聊天软件数据需谨慎处理。")
    if any(keyword in path for path in paths for keyword in ("pagefile.sys", "windows", "program files")):
        advice.append("存在 pagefile.sys、Windows 或 Program Files 相关路径，系统关键文件不建议处理。")

    if not advice:
        advice.append("未发现明确路径建议，请结合风险等级人工判断。")
    advice.append("清理建议只做提示，不会自动勾选或自动处理文件。")
    return advice


def duplicate_groups(items: list[ScanItem]) -> dict[str, list[ScanItem]]:
    groups: dict[str, list[ScanItem]] = {}
    for item in items:
        if item.duplicate_group:
            groups.setdefault(item.duplicate_group, []).append(item)
    return {group_id: group_items for group_id, group_items in groups.items() if len(group_items) > 1}


def recommended_duplicate_keep(items: list[ScanItem]) -> ScanItem | None:
    if any(path_requires_manual_duplicate_review(item.path) for item in items):
        return None
    return sorted(items, key=lambda item: (-modified_timestamp(item.path), len(str(item.path)), str(item.path).lower()))[0]


def path_requires_manual_duplicate_review(path: Path) -> bool:
    normalized = str(path).lower().replace("/", "\\")
    keywords = (
        "windows",
        "program files",
        "programdata",
        "appdata\\roaming\\tencent",
        "wechat",
        "wxwork",
        "qq",
    )
    return any(keyword in normalized for keyword in keywords)


def modified_timestamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except (OSError, PermissionError):
        return 0.0


def format_modified_time(path: Path) -> str:
    timestamp = modified_timestamp(path)
    if not timestamp:
        return "无法读取"
    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def build_duplicate_group_text(groups: dict[str, list[ScanItem]], checked_keys: set[str]) -> str:
    lines: list[str] = ["重复文件分组信息"]
    for group_id in sorted(groups):
        group_items = groups[group_id]
        recommended = recommended_duplicate_keep(group_items)
        lines.append("")
        lines.append(f"{group_id}（{len(group_items)} 个文件）")
        if recommended is None:
            lines.append("推荐保留文件：请手动确认")
        else:
            lines.append(f"推荐保留文件：{recommended.path}")
        for item in sorted(group_items, key=lambda value: str(value.path).lower()):
            keep = recommended is not None and scan_item_key(item) == scan_item_key(recommended)
            checked = scan_item_key(item) in checked_keys
            lines.append(
                f"- 路径：{item.path} | 大小：{item.display_size} | 修改时间：{format_modified_time(item.path)} "
                f"| 推荐保留：{'是' if keep else '否'} | 已勾选：{'是' if checked else '否'} "
                f"| 风险等级：{item.risk_level} | 建议：{item.suggestion}"
            )
    return "\n".join(lines)


def history_path() -> Path:
    return Path.cwd() / "history.json"


def load_scan_history() -> list[dict[str, object]]:
    path = history_path()
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [record for record in data if isinstance(record, dict)]


def save_history_records(records: list[dict[str, object]]) -> None:
    with history_path().open("w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)


def save_scan_history(items: list[ScanItem], root: Path) -> None:
    records = load_scan_history()
    records.append(build_history_record(items, root))
    try:
        save_history_records(records)
    except OSError:
        return


def build_history_record(items: list[ScanItem], root: Path) -> dict[str, object]:
    risk_counts = Counter(item.risk_level for item in items)
    risk_sizes = risk_size_totals(items)
    total_size = sum(item.size_bytes for item in items)
    return {
        "scan_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "scan_dir": str(root),
        "result_count": len(items),
        "total_size_bytes": total_size,
        "total_size": format_size(total_size),
        "recommended_count": risk_counts.get("推荐清理", 0),
        "recommended_size_bytes": risk_sizes.get("推荐清理", 0),
        "recommended_size": format_size(risk_sizes.get("推荐清理", 0)),
        "caution_count": risk_counts.get("谨慎处理", 0),
        "caution_size_bytes": risk_sizes.get("谨慎处理", 0),
        "caution_size": format_size(risk_sizes.get("谨慎处理", 0)),
        "not_recommended_count": risk_counts.get("不建议删除", 0),
        "not_recommended_size_bytes": risk_sizes.get("不建议删除", 0),
        "not_recommended_size": format_size(risk_sizes.get("不建议删除", 0)),
        "duplicate_group_count": len(duplicate_groups(items)),
    }


def default_scan_root() -> Path:
    downloads = Path.home() / "Downloads"
    if downloads.exists():
        return downloads
    return Path.home()


def is_c_drive_root(path: Path) -> bool:
    normalized = str(path.expanduser().resolve(strict=False)).replace("/", "\\").rstrip("\\").lower()
    return normalized == "c:"


def main() -> None:
    app = CleanerApp()
    app.mainloop()
