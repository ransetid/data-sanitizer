"""
GUI 主窗口模块
使用 tkinter 构建简洁的脱敏工具界面
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path

from sanitizer.engine import SanitizeEngine
from sanitizer.entity_map import EntityMap
from sanitizer.parsers import get_parser_for_file
from sanitizer.utils import (
    ensure_output_structure,
    get_file_type_stats,
    get_output_folder,
    scan_folder,
    compute_output_path,
)

logger = logging.getLogger(__name__)


class SanitizerApp:
    """
    财务数据脱敏工具 GUI 主窗口

    流程：
    1. 用户点击"选择文件夹"按钮
    2. 显示源路径、输出路径、文件统计
    3. 用户点击"开始脱敏"
    4. 进度条 + 当前文件名实时更新
    5. 完成后显示结果摘要
    """

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("财务数据脱敏工具")
        self.root.geometry("720x900")
        self.root.resizable(True, True)

        # 状态变量
        self.source_folder = None
        self.output_folder = None
        self.file_list = []
        self.is_processing = False

        self._build_ui()

    def _build_ui(self):
        """构建界面布局（带滚动条）"""
        # === 外层：Canvas + Scrollbar 实现整体滚动 ===
        outer_frame = ttk.Frame(self.root)
        outer_frame.pack(fill=tk.BOTH, expand=True)

        self._canvas = tk.Canvas(outer_frame, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer_frame, orient=tk.VERTICAL, command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self._canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 内部容器（所有控件放在这里）
        main_frame = ttk.Frame(self._canvas, padding=15)
        self._canvas_window = self._canvas.create_window((0, 0), window=main_frame, anchor=tk.NW)

        # 让内部容器宽度跟随 Canvas
        def _on_canvas_configure(event):
            self._canvas.itemconfig(self._canvas_window, width=event.width)
        self._canvas.bind("<Configure>", _on_canvas_configure)

        # 内容变化时更新滚动范围
        def _on_frame_configure(event):
            self._canvas.configure(scrollregion=self._canvas.bbox("all"))
        main_frame.bind("<Configure>", _on_frame_configure)

        # 鼠标滚轮支持
        def _on_mousewheel(event):
            # macOS 用 event.delta，Linux 用 event.num
            if event.delta:
                self._canvas.yview_scroll(int(-event.delta), "units")
            elif event.num == 4:
                self._canvas.yview_scroll(-3, "units")
            elif event.num == 5:
                self._canvas.yview_scroll(3, "units")

        self._canvas.bind_all("<MouseWheel>", _on_mousewheel)       # macOS / Windows
        self._canvas.bind_all("<Button-4>", _on_mousewheel)          # Linux scroll up
        self._canvas.bind_all("<Button-5>", _on_mousewheel)          # Linux scroll down

        # === 标题 ===
        title_label = ttk.Label(
            main_frame,
            text="财务数据脱敏工具",
            font=("Helvetica", 18, "bold"),
        )
        title_label.pack(pady=(0, 10))

        # === Ollama 设置区域 ===
        ollama_frame = ttk.LabelFrame(main_frame, text="Ollama 设置（NER 实体识别）", padding=10)
        ollama_frame.pack(fill=tk.X, pady=(0, 10))

        # 启用开关
        self.ollama_enabled = tk.BooleanVar(value=True)
        enable_check = ttk.Checkbutton(
            ollama_frame,
            text="启用本地 LLM NER（关闭则仅用正则规则）",
            variable=self.ollama_enabled,
            command=self._on_ollama_toggle,
        )
        enable_check.pack(anchor=tk.W)

        # URL 和模型设置行
        settings_row = ttk.Frame(ollama_frame)
        settings_row.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(settings_row, text="地址：").pack(side=tk.LEFT)
        self.ollama_url_var = tk.StringVar(value="http://127.0.0.1:16578")
        self.ollama_url_entry = ttk.Entry(settings_row, textvariable=self.ollama_url_var, width=30)
        self.ollama_url_entry.pack(side=tk.LEFT, padx=(0, 15))

        ttk.Label(settings_row, text="模型：").pack(side=tk.LEFT)
        self.ollama_model_var = tk.StringVar(value="gemma-4-e2b-it-4bit")
        self.ollama_model_entry = ttk.Entry(settings_row, textvariable=self.ollama_model_var, width=22)
        self.ollama_model_entry.pack(side=tk.LEFT, padx=(0, 10))

        # 测试连接按钮
        self.test_btn = ttk.Button(settings_row, text="测试连接", command=self._on_test_ollama)
        self.test_btn.pack(side=tk.LEFT)

        # API Key 行
        key_row = ttk.Frame(ollama_frame)
        key_row.pack(fill=tk.X, pady=(6, 0))

        ttk.Label(key_row, text="API Key：").pack(side=tk.LEFT)
        self.api_key_var = tk.StringVar(value="")
        self.api_key_entry = ttk.Entry(key_row, textvariable=self.api_key_var, width=40, show="•")
        self.api_key_entry.pack(side=tk.LEFT, padx=(0, 10))
        ttk.Label(key_row, text="（留空则不发送）", foreground="gray").pack(side=tk.LEFT)

        # 提示和状态
        hint_label = ttk.Label(
            ollama_frame,
            text="支持 Ollama / OMLX / LM Studio 等，地址末尾有无 /v1 均可",
            foreground="gray",
            font=("Helvetica", 11),
        )
        hint_label.pack(anchor=tk.W, pady=(4, 0))

        self.ollama_status_var = tk.StringVar(value="")
        self.ollama_status_label = ttk.Label(
            ollama_frame,
            textvariable=self.ollama_status_var,
            foreground="gray",
        )
        self.ollama_status_label.pack(anchor=tk.W, pady=(2, 0))

        # === 脱敏关键词库 ===
        dict_frame = ttk.LabelFrame(main_frame, text="脱敏关键词库（公司名、人名等）", padding=10)
        dict_frame.pack(fill=tk.X, pady=(0, 10))

        # 顶部：提示 + 按钮行
        dict_top = ttk.Frame(dict_frame)
        dict_top.pack(fill=tk.X, pady=(0, 4))

        dict_hint = ttk.Label(
            dict_top,
            text="每行一个。默认=公司名，前缀：[人名] [银行] [地址] [签字]，# =注释",
            foreground="gray",
            font=("Helvetica", 11),
        )
        dict_hint.pack(side=tk.LEFT)

        self.save_dict_btn = ttk.Button(dict_top, text="保存词库", command=self._on_save_keywords)
        self.save_dict_btn.pack(side=tk.RIGHT, padx=(5, 0))

        self.reload_dict_btn = ttk.Button(dict_top, text="重新加载", command=self._on_reload_keywords)
        self.reload_dict_btn.pack(side=tk.RIGHT)

        # 词库文件路径显示
        self.keywords_path = self._get_keywords_path()
        path_label = ttk.Label(
            dict_frame,
            text=f"词库文件：{self.keywords_path}",
            foreground="gray",
            font=("Helvetica", 10),
        )
        path_label.pack(anchor=tk.W, pady=(0, 4))

        # 文本编辑框
        self.dict_text = tk.Text(dict_frame, height=6, width=70, font=("Courier", 12))
        self.dict_text.pack(fill=tk.X)

        # 加载词库
        self._load_keywords()

        # === 数值缩放模式 ===
        scale_frame = ttk.LabelFrame(main_frame, text="数值缩放模式", padding=10)
        scale_frame.pack(fill=tk.X, pady=(0, 10))

        self.unified_scale_var = tk.BooleanVar(value=True)

        ttk.Radiobutton(
            scale_frame,
            text="统一缩放 — 所有文件和 Sheet 使用同一个缩放系数（推荐：保持跨表加和关系）",
            variable=self.unified_scale_var,
            value=True,
        ).pack(anchor=tk.W, pady=(0, 4))

        ttk.Radiobutton(
            scale_frame,
            text="独立缩放 — 每个文件的每个 Sheet 各自使用不同的缩放系数",
            variable=self.unified_scale_var,
            value=False,
        ).pack(anchor=tk.W, pady=(0, 8))

        # 缩放范围设置
        range_row = ttk.Frame(scale_frame)
        range_row.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(range_row, text="缩放范围：最小").pack(side=tk.LEFT)
        self.scale_min_var = tk.StringVar(value="0.01")
        ttk.Entry(range_row, textvariable=self.scale_min_var, width=6).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(range_row, text=" 倍   最大").pack(side=tk.LEFT, padx=(8, 0))
        self.scale_max_var = tk.StringVar(value="100")
        ttk.Entry(range_row, textvariable=self.scale_max_var, width=6).pack(side=tk.LEFT, padx=(4, 0))

        ttk.Label(range_row, text=" 倍").pack(side=tk.LEFT)

        # 预设快捷按钮
        preset_row = ttk.Frame(scale_frame)
        preset_row.pack(fill=tk.X)

        ttk.Label(preset_row, text="快速选择：", foreground="gray").pack(side=tk.LEFT)
        for label, lo, hi in [
            ("±30%", "0.7", "1.3"),
            ("±50%", "0.5", "2.0"),
            ("10倍", "0.1", "10"),
            ("100倍", "0.01", "100"),
        ]:
            ttk.Button(
                preset_row,
                text=label,
                width=6,
                command=lambda l=lo, h=hi: (
                    self.scale_min_var.set(l),
                    self.scale_max_var.set(h),
                ),
            ).pack(side=tk.LEFT, padx=(4, 0))

        # === 文件夹选择区域 ===
        folder_frame = ttk.LabelFrame(main_frame, text="文件夹", padding=10)
        folder_frame.pack(fill=tk.X, pady=(0, 10))

        # ── 源文件夹行 ──
        source_row = ttk.Frame(folder_frame)
        source_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(source_row, text="源文件夹：").pack(side=tk.LEFT)
        self.source_var = tk.StringVar(value="未选择")
        ttk.Label(
            source_row,
            textvariable=self.source_var,
            foreground="gray",
            wraplength=480,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
        self.select_btn = ttk.Button(
            source_row, text="选择文件夹", command=self._on_select_folder,
        )
        self.select_btn.pack(side=tk.RIGHT)

        # ── 输出文件夹行 ──
        output_row = ttk.Frame(folder_frame)
        output_row.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(output_row, text="输出文件夹：").pack(side=tk.LEFT)
        self.output_var = tk.StringVar(value="")
        self.output_entry = ttk.Entry(
            output_row, textvariable=self.output_var, width=52, state=tk.DISABLED,
        )
        self.output_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8))
        self.output_browse_btn = ttk.Button(
            output_row, text="浏览", command=self._on_browse_output, state=tk.DISABLED,
        )
        self.output_browse_btn.pack(side=tk.RIGHT)

        output_hint = ttk.Label(
            folder_frame,
            text="默认为源文件夹同级的 {名称}_脱敏 目录。多批文件使用同一输出目录可保持缩放系数一致。",
            foreground="gray",
            font=("Helvetica", 10),
            wraplength=650,
        )
        output_hint.pack(anchor=tk.W)

        # === 文件统计区域 ===
        stats_frame = ttk.LabelFrame(main_frame, text="扫描结果", padding=10)
        stats_frame.pack(fill=tk.X, pady=(0, 10))

        self.stats_var = tk.StringVar(value="请先选择文件夹")
        stats_label = ttk.Label(
            stats_frame,
            textvariable=self.stats_var,
            wraplength=600,
        )
        stats_label.pack(anchor=tk.W)

        # === 进度区域 ===
        progress_frame = ttk.LabelFrame(main_frame, text="处理进度", padding=10)
        progress_frame.pack(fill=tk.X, pady=(0, 10))

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate",
        )
        self.progress_bar.pack(fill=tk.X, pady=(0, 5))

        self.current_file_var = tk.StringVar(value="等待开始...")
        current_file_label = ttk.Label(
            progress_frame,
            textvariable=self.current_file_var,
            foreground="gray",
            wraplength=600,
        )
        current_file_label.pack(anchor=tk.W)

        # === 按钮区域 ===
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=(10, 0))

        self.start_btn = ttk.Button(
            btn_frame,
            text="开始脱敏",
            command=self._on_start,
            state=tk.DISABLED,
        )
        self.start_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.incremental_var = tk.BooleanVar(value=False)
        self.incremental_check = ttk.Checkbutton(
            btn_frame,
            text="增量模式（仅处理包含新增关键词的文件）",
            variable=self.incremental_var,
        )
        self.incremental_check.pack(side=tk.LEFT, padx=(0, 10))

        self.close_btn = ttk.Button(
            btn_frame,
            text="关闭",
            command=self._on_close,
        )
        self.close_btn.pack(side=tk.RIGHT)

    @staticmethod
    def _get_keywords_path() -> str:
        """
        获取关键词库文件路径

        打包后（PyInstaller）：
          - macOS/Windows 都使用用户数据目录，保证可编辑、可持久化
          - 首次启动时将内置默认 keywords.txt 复制过去

        开发模式（直接 python run.py）：
          - 使用项目根目录下的 keywords.txt
        """
        import sys

        if getattr(sys, "frozen", False):
            # --- 打包后：使用用户数据目录 ---
            if sys.platform == "darwin":
                user_data = Path.home() / "Library" / "Application Support" / "DataSanitizer"
            elif sys.platform == "win32":
                user_data = Path(os.environ.get("APPDATA", Path.home())) / "DataSanitizer"
            else:
                user_data = Path.home() / ".datasanitizer"

            user_data.mkdir(parents=True, exist_ok=True)
            user_keywords = user_data / "keywords.txt"

            # 首次运行：从打包内的默认文件复制过来
            if not user_keywords.exists():
                bundled = Path(sys._MEIPASS) / "keywords.txt"
                if bundled.exists():
                    import shutil
                    shutil.copy(bundled, user_keywords)

            return str(user_keywords)
        else:
            # --- 开发模式：项目根目录 ---
            app_dir = Path(__file__).resolve().parent.parent  # data-sanitizer/
            return str(app_dir / "keywords.txt")

    def _load_keywords(self):
        """从 keywords.txt 加载关键词库到文本框"""
        path = self.keywords_path
        if Path(path).exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.dict_text.delete("1.0", tk.END)
                self.dict_text.insert("1.0", content)
            except Exception as e:
                logger.warning(f"加载关键词库失败: {e}")
        else:
            # 文件不存在，填入示例
            example = "# 在这里添加要脱敏的名称，每行一个\n# 默认当作公司名，[人名] 前缀标记为人名\n\nAcme Corporation\nGlobal Trading Co.\n[人名] 张三\n"
            self.dict_text.delete("1.0", tk.END)
            self.dict_text.insert("1.0", example)

    def _on_save_keywords(self):
        """保存文本框内容到 keywords.txt"""
        content = self.dict_text.get("1.0", tk.END).rstrip("\n") + "\n"
        try:
            with open(self.keywords_path, "w", encoding="utf-8") as f:
                f.write(content)
            messagebox.showinfo("保存成功", f"关键词库已保存到：\n{self.keywords_path}")
        except Exception as e:
            messagebox.showerror("保存失败", f"无法保存：{e}")

    def _on_reload_keywords(self):
        """从文件重新加载关键词库"""
        self._load_keywords()

    def _on_ollama_toggle(self):
        """LLM 启用/禁用切换"""
        enabled = self.ollama_enabled.get()
        state = tk.NORMAL if enabled else tk.DISABLED
        self.ollama_url_entry.config(state=state)
        self.ollama_model_entry.config(state=state)
        self.api_key_entry.config(state=state)
        self.test_btn.config(state=state)
        if not enabled:
            self.ollama_status_var.set("已禁用，仅使用正则规则脱敏")
            self.ollama_status_label.config(foreground="gray")
        else:
            self.ollama_status_var.set("")

    # 关键词前缀 → entity_type 映射（支持中英文方括号）
    _PREFIX_MAP = {
        "[人名]": "person",   "[人名]": "person",
        "[公司]": "company",  "[公司]": "company",
        "[地址]": "address",  "[地址]": "address",
        "[银行]": "bank_name", "[银行]": "bank_name",
        "[签字]": "person",   "[签字]": "person",      # 审批人/签字人归入人名
    }

    def _parse_custom_entities(self) -> dict:
        """
        解析自定义脱敏名单文本框的内容

        格式：
          Acme Corporation    → company（默认）
          [公司] Global Trading → company
          [人名] 张三         → person
          [银行] 招商银行     → bank_name
          [地址] 中关村大街1号 → address
          [签字] 制表人：李四  → person

        Returns:
            {"company": [...], "person": [...], "bank_name": [...], "address": [...]}
        """
        text = self.dict_text.get("1.0", tk.END).strip()
        if not text:
            return {}

        entities: dict[str, list[str]] = {}

        for line in text.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # 检查是否有前缀标记
            matched_type = None
            for prefix, etype in self._PREFIX_MAP.items():
                if line.startswith(prefix):
                    name = line.split("]", 1)[-1].strip()
                    # 处理中文全角 ] 的情况
                    if name.startswith("】"):
                        name = name[1:].strip()
                    matched_type = etype
                    break

            if matched_type and name:
                entities.setdefault(matched_type, []).append(name)
            elif line:
                # 无前缀 → 默认当作公司名
                entities.setdefault("company", []).append(line)

        # 去掉空列表
        return {k: v for k, v in entities.items() if v}

    def _on_test_ollama(self):
        """测试本地 LLM 连接（自动识别 Ollama / OpenAI 兼容 API）"""
        self.ollama_status_var.set("正在检测...")
        self.ollama_status_label.config(foreground="gray")
        self.root.update()

        # 借用引擎的检测逻辑
        import tempfile, os
        tmp_dir = tempfile.mkdtemp()
        tmp_db = os.path.join(tmp_dir, "_test.db")
        try:
            from sanitizer.entity_map import EntityMap
            test_map = EntityMap(tmp_db)
            test_engine = SanitizeEngine(
                test_map,
                ollama_url=self.ollama_url_var.get().strip(),
                ollama_model=self.ollama_model_var.get().strip(),
                api_key=self.api_key_var.get(),
                use_ollama=True,
            )
            ok = test_engine.check_ollama()
            if ok:
                api_type = test_engine.get_api_type()
                api_label = "Ollama API" if api_type == "ollama" else "OpenAI 兼容 API"
                self.ollama_status_var.set(
                    f"✅ 已连接（{api_label}），模型: {self.ollama_model_var.get()}"
                )
                self.ollama_status_label.config(foreground="green")
            else:
                self.ollama_status_var.set(
                    f"❌ 无法连接或未找到模型。请检查地址和模型名。"
                )
                self.ollama_status_label.config(foreground="red")
        except Exception as e:
            self.ollama_status_var.set(f"❌ 错误: {str(e)}")
            self.ollama_status_label.config(foreground="red")
        finally:
            if os.path.exists(tmp_db):
                os.remove(tmp_db)
            os.rmdir(tmp_dir)

    def _on_select_folder(self):
        """处理源文件夹选择"""
        folder = filedialog.askdirectory(title="选择要脱敏的文件夹")
        if not folder:
            return

        self.source_folder = folder
        self.file_list = scan_folder(folder)

        # 更新显示
        self.source_var.set(folder)

        # 启用输出文件夹选择（必须先选源文件夹）
        self.output_entry.config(state=tk.NORMAL)
        self.output_browse_btn.config(state=tk.NORMAL)

        # 设置默认输出路径（仅当用户没有手动修改过时才覆盖）
        default_output = get_output_folder(folder)
        current_output = self.output_var.get().strip()
        if not current_output or current_output == get_output_folder(
            getattr(self, '_prev_source_folder', '')
        ):
            self.output_var.set(default_output)
        self._prev_source_folder = folder

        # 同步 output_folder 属性
        self.output_folder = self.output_var.get().strip()

        # 统计信息
        if self.file_list:
            type_stats = get_file_type_stats(self.file_list)
            stats_parts = [f"共扫描到 {len(self.file_list)} 个支持的文件"]
            for type_name, count in sorted(type_stats.items()):
                stats_parts.append(f"  {type_name}: {count} 个")
            self.stats_var.set("\n".join(stats_parts))
            self.start_btn.config(state=tk.NORMAL)
        else:
            self.stats_var.set("未扫描到支持的文件类型")
            self.start_btn.config(state=tk.DISABLED)

        # 重置进度
        self.progress_var.set(0)
        self.current_file_var.set("等待开始...")

    def _on_browse_output(self):
        """浏览选择输出文件夹"""
        # 初始目录：如果当前输出路径有效就从那里开始，否则从源文件夹的上级目录开始
        initial_dir = None
        current = self.output_var.get().strip()
        if current and Path(current).parent.exists():
            initial_dir = str(Path(current).parent)
        elif self.source_folder:
            initial_dir = str(Path(self.source_folder).parent)

        folder = filedialog.askdirectory(
            title="选择输出文件夹",
            initialdir=initial_dir,
        )
        if folder:
            self.output_var.set(folder)

    def _on_start(self):
        """开始脱敏处理"""
        if self.is_processing:
            return

        if not self.file_list:
            messagebox.showwarning("提示", "没有可处理的文件")
            return

        # 从输入框读取用户可能手动修改过的输出路径
        output = self.output_var.get().strip()
        if not output:
            messagebox.showwarning("提示", "请指定输出文件夹")
            return
        self.output_folder = output

        # 防止输出目录等于源目录（会覆盖原文件）
        if Path(self.output_folder).resolve() == Path(self.source_folder).resolve():
            messagebox.showerror(
                "错误", "输出文件夹不能与源文件夹相同，否则会覆盖原文件！"
            )
            return

        # 检查输出目录是否已存在
        if Path(self.output_folder).exists():
            result = messagebox.askyesno(
                "确认",
                f"输出目录已存在：\n{self.output_folder}\n\n继续将覆盖已有文件，是否继续？",
            )
            if not result:
                return

        self.is_processing = True
        self.start_btn.config(state=tk.DISABLED)
        self.select_btn.config(state=tk.DISABLED)
        self.output_browse_btn.config(state=tk.DISABLED)
        self.output_entry.config(state=tk.DISABLED)

        # 在后台线程中执行脱敏
        thread = threading.Thread(target=self._run_sanitization, daemon=True)
        thread.start()

    def _run_sanitization(self):
        """在后台线程中执行脱敏处理"""
        try:
            # 创建输出目录结构
            ensure_output_structure(self.source_folder, self.output_folder)

            # 解析自定义脱敏词典
            custom_entities = self._parse_custom_entities()

            # 初始化映射表和引擎
            db_path = os.path.join(self.output_folder, "_mapping.db")
            entity_map = EntityMap(db_path)
            # 解析缩放范围
            try:
                scale_min = float(self.scale_min_var.get())
                scale_max = float(self.scale_max_var.get())
                if scale_min <= 0 or scale_max <= 0 or scale_min >= scale_max:
                    raise ValueError
            except (ValueError, AttributeError):
                scale_min, scale_max = 0.01, 100.0  # 解析失败则用默认值

            engine = SanitizeEngine(
                entity_map,
                ollama_url=self.ollama_url_var.get().strip(),
                ollama_model=self.ollama_model_var.get().strip(),
                api_key=self.api_key_var.get(),
                use_ollama=self.ollama_enabled.get(),
                custom_entities=custom_entities,
                unified_scale=self.unified_scale_var.get(),
                scale_min=scale_min,
                scale_max=scale_max,
            )

            # 显示词典统计
            dict_count = sum(len(v) for v in custom_entities.values())
            if dict_count:
                self.root.after(0, self.current_file_var.set,
                    f"已加载 {dict_count} 个自定义脱敏名称，检测 LLM...")

            # 检测 Ollama 并更新状态
            if engine.use_llm:
                ollama_ok = engine.check_ollama()
                status = "Ollama NER ✅" if ollama_ok else "Ollama 不可用，仅用正则"
            else:
                status = "仅正则模式"

            # ── 增量模式：计算需要处理的文件列表 ──────────────────────────
            incremental = self.incremental_var.get()
            files_to_process = list(self.file_list)  # 默认全量
            skipped_count = 0

            # 提取当前所有关键词的纯文本集合（用于存快照和扫描）
            all_keyword_texts = set()
            for names in custom_entities.values():
                all_keyword_texts.update(names)

            if incremental:
                prev_keywords = entity_map.load_keywords_snapshot()

                # ── 检测遗留 DB：有实体映射但没有关键词快照 ──
                # 说明 _mapping.db 来自增量功能上线前的全量运行，
                # 无法判断哪些关键词是"新增"的。
                # 处理方式：保存当前关键词作为基线，本次按全量模式运行。
                if not prev_keywords:
                    # 没有关键词快照——要么是旧版 DB，要么是首次运行
                    # 两种情况都无法做增量差分，降级为全量并建立基线
                    has_mappings = entity_map.has_real_mappings()
                    if has_mappings:
                        reason = "检测到旧版 DB（有映射但无关键词快照）"
                    else:
                        reason = "首次运行，尚无关键词基线"

                    logger.info(
                        "增量模式：%s，已保存当前 %d 个关键词作为基线，本次按全量模式运行",
                        reason, len(all_keyword_texts),
                    )
                    entity_map.save_keywords_snapshot(all_keyword_texts)
                    # 降级为全量模式
                    incremental = False
                    self.root.after(0, self.current_file_var.set,
                        f"{status} | 首次增量：已建立关键词基线（{len(all_keyword_texts)} 个），"
                        "本次全量处理")
                    self.root.after(0, messagebox.showinfo, "增量模式",
                        f"{'检测到这是增量功能上线后的首次运行' if has_mappings else '首次运行'}。\n"
                        f"已将当前 {len(all_keyword_texts)} 个关键词保存为基线。\n"
                        f"本次将按全量模式处理所有文件。\n\n"
                        f"下次添加新关键词后再勾选「增量模式」，\n"
                        f"即可只处理包含新关键词的文件。")

            if incremental:
                new_keywords = all_keyword_texts - prev_keywords

                if not new_keywords:
                    # 没有新增关键词
                    self.root.after(0, self.current_file_var.set,
                        "增量模式：未发现新增关键词，无需重新处理")
                    self.root.after(0, messagebox.showinfo, "增量模式",
                        "关键词库与上次运行完全一致，没有新增关键词。\n"
                        "如需全量重跑，请取消勾选「增量模式」。")
                    return

                logger.info(f"增量模式：发现 {len(new_keywords)} 个新增关键词: "
                            f"{', '.join(sorted(new_keywords)[:10])}"
                            f"{'...' if len(new_keywords) > 10 else ''}")

                self.root.after(0, self.current_file_var.set,
                    f"增量模式：发现 {len(new_keywords)} 个新增关键词，扫描文件中...")

                # 扫描源文件，筛选出包含新关键词的文件
                files_to_process = []
                new_kw_lower = {kw.lower() for kw in new_keywords}

                for file_info in self.file_list:
                    input_path = file_info["path"]
                    try:
                        # 读取原始字节并搜索关键词
                        # xlsx/docx 是 ZIP，文本在 XML 中，关键词字符串仍在裸字节里可见
                        raw = Path(input_path).read_bytes()
                        # 尝试多种编码解码以匹配中英文关键词
                        text_repr = ""
                        for enc in ("utf-8", "gbk", "utf-16-le"):
                            try:
                                text_repr += raw.decode(enc, errors="ignore").lower()
                            except Exception:
                                pass

                        if any(kw in text_repr for kw in new_kw_lower):
                            files_to_process.append(file_info)
                        else:
                            skipped_count += 1
                    except Exception:
                        # 读取失败的文件保守处理——纳入重跑列表
                        files_to_process.append(file_info)

                logger.info(f"增量模式：{len(files_to_process)} 个文件包含新关键词，"
                            f"{skipped_count} 个文件跳过")
                self.root.after(0, self.current_file_var.set,
                    f"{status} | 增量模式：处理 {len(files_to_process)} 个文件，"
                    f"跳过 {skipped_count} 个")
            else:
                self.root.after(0, self.current_file_var.set, f"{status}，开始处理...")

            total = len(files_to_process)
            processed = 0
            errors = []

            if total == 0 and incremental:
                self.root.after(0, self.current_file_var.set,
                    "增量模式：所有文件均不包含新增关键词，无需处理")
                self.root.after(0, messagebox.showinfo, "增量模式",
                    f"新增了 {len(new_keywords)} 个关键词，但扫描后发现：\n"
                    f"所有 {len(self.file_list)} 个源文件中均不包含这些关键词。\n\n"
                    f"无需重新处理。")
                # 仍然保存关键词快照
                entity_map.save_keywords_snapshot(all_keyword_texts)
                return

            for file_info in files_to_process:
                input_path = file_info["path"]
                relative = file_info["relative"]

                # 更新当前文件显示
                self.root.after(0, self.current_file_var.set, f"正在处理: {relative}")

                try:
                    # 获取合适的解析器
                    parser = get_parser_for_file(input_path)
                    if parser is None:
                        logger.warning(f"无法找到解析器: {relative}")
                        errors.append(f"{relative}: 无合适的解析器")
                        continue

                    # 计算输出路径（同时对文件名/文件夹名进行脱敏）
                    output_path = compute_output_path(
                        input_path, self.source_folder, self.output_folder, engine
                    )

                    # 执行脱敏
                    parser.sanitize(input_path, output_path, engine)
                    engine.stats["files"] += 1

                except Exception as e:
                    logger.error(f"处理文件出错 {relative}: {e}")
                    errors.append(f"{relative}: {str(e)}")

                # 更新进度
                processed += 1
                progress = (processed / total) * 100
                self.root.after(0, self.progress_var.set, progress)

            # 保存本次关键词快照（供下次增量对比）
            entity_map.save_keywords_snapshot(all_keyword_texts)

            # 处理完成 — 导出映射报告
            report_path = os.path.join(self.output_folder, "_映射报告.csv")
            try:
                entity_map.export_report(report_path)
            except Exception as e:
                logger.warning(f"导出映射报告失败: {e}")

            mapping_stats = entity_map.get_stats()
            self._show_completion(
                engine.stats, mapping_stats, errors,
                skipped=skipped_count if incremental else 0,
            )

        except Exception as e:
            logger.error(f"脱敏处理出错: {e}")
            self.root.after(
                0,
                messagebox.showerror,
                "错误",
                f"处理过程中发生错误：\n{str(e)}",
            )
        finally:
            self.root.after(0, self._reset_ui_state)

    def _show_completion(self, stats: dict, mapping_stats: dict, errors: list, skipped: int = 0):
        """显示完成结果"""
        msg_parts = [
            f"处理完成！",
            f"共处理 {stats['files']} 个文件",
        ]
        if skipped > 0:
            msg_parts.append(f"增量模式跳过 {skipped} 个文件（不含新关键词）")
        msg_parts.extend([
            f"发现敏感实体 {stats['entities_found']} 个",
            f"完成替换 {stats['entities_replaced']} 个",
            f"",
            f"映射表统计：{mapping_stats['total']} 个实体",
        ])

        for entity_type, count in mapping_stats.get("by_type", {}).items():
            msg_parts.append(f"  {entity_type}: {count}")

        msg_parts.append(f"")
        msg_parts.append(f"📄 映射报告已导出到输出文件夹：")
        msg_parts.append(f"  _映射报告.csv")
        msg_parts.append(f"  （用 Excel 打开可查看所有替换对照和缩放倍数）")

        if errors:
            msg_parts.append(f"\n处理出错的文件（{len(errors)} 个）：")
            for err in errors[:10]:  # 最多显示10条错误
                msg_parts.append(f"  {err}")
            if len(errors) > 10:
                msg_parts.append(f"  ... 还有 {len(errors) - 10} 个错误")

        result_text = "\n".join(msg_parts)

        self.root.after(0, self.current_file_var.set, f"处理完成！共处理 {stats['files']} 个文件")
        self.root.after(0, messagebox.showinfo, "完成", result_text)

    def _reset_ui_state(self):
        """重置 UI 状态"""
        self.is_processing = False
        self.start_btn.config(state=tk.NORMAL)
        self.select_btn.config(state=tk.NORMAL)
        self.output_browse_btn.config(state=tk.NORMAL)
        self.output_entry.config(state=tk.NORMAL)

    def _on_close(self):
        """关闭窗口"""
        if self.is_processing:
            result = messagebox.askyesno("确认", "正在处理中，确定要关闭吗？")
            if not result:
                return
        self.root.destroy()

    def run(self):
        """启动 GUI 主循环"""
        import sys
        from logging.handlers import RotatingFileHandler

        # 日志文件位置
        # 打包后写入用户数据目录（app bundle 内部可能只读）
        # 开发模式写在项目根目录
        if getattr(sys, "frozen", False):
            if sys.platform == "darwin":
                log_dir = Path.home() / "Library" / "Application Support" / "DataSanitizer"
            elif sys.platform == "win32":
                log_dir = Path(os.environ.get("APPDATA", Path.home())) / "DataSanitizer"
            else:
                log_dir = Path.home() / ".datasanitizer"
        else:
            log_dir = Path(__file__).resolve().parent.parent  # data-sanitizer/

        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "sanitizer.log"

        # RotatingFileHandler：单文件最大 2MB，保留最近 3 个，共占用不超过 8MB
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=2 * 1024 * 1024,  # 2 MB
            backupCount=3,
            encoding="utf-8",
        )

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            handlers=[
                logging.StreamHandler(),  # 终端
                file_handler,             # 文件（自动滚动）
            ],
        )
        logger.info(f"========== 启动 ==========")
        logger.info(f"日志文件：{log_file}（单文件 2MB，保留 3 个，共 ≤8MB）")
        self.root.mainloop()


def main():
    """入口函数"""
    app = SanitizerApp()
    app.run()
