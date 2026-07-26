import json
import os
import subprocess
import threading
import time
import sys
import winsound
import urllib.request
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from tkinter.scrolledtext import ScrolledText

# 兼容打包后路径（不再写死 d:\facai）
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
RESOURCE_DIR = getattr(sys, "_MEIPASS", APP_DIR)

def _is_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        test_file = os.path.join(path, ".write_test.tmp")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(test_file)
        return True
    except Exception:
        return False

USER_DATA_DIR = os.path.join(os.path.expanduser("~"), "Documents", "ShopAutomationGUI")
DATA_DIR = USER_DATA_DIR if getattr(sys, "frozen", False) else APP_DIR
os.makedirs(DATA_DIR, exist_ok=True)

BASE_DIR = APP_DIR
MAIN_SCRIPT = os.path.join(BASE_DIR, "main_automation.py")
RUNTIME_CONFIG = os.path.join(DATA_DIR, "runtime_config.json")
APP_DIR_RUNTIME_CONFIG = os.path.join(APP_DIR, "runtime_config.json")
LOG_FILE = os.path.join(DATA_DIR, "automation.log")
DROPDOWN_OPTIONS_FILE = os.path.join(DATA_DIR, "dropdown_options.json")
ASSET_DIR = os.path.join(RESOURCE_DIR, "assets")
APP_ICON_ICO = os.path.join(ASSET_DIR, "ae_icon.ico")
APP_ICON_PNG = os.path.join(ASSET_DIR, "ae_icon.png")

DEBUG_PORT = "9222"
DRAFT_URL = "https://www.dianxiaomi.com/web/smt/smtProductList/draft?pageType=0&shopId=8536828"
CHROME_PROFILE = os.path.join(DATA_DIR, "chrome-debug-profile")


class AutomationGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("店小秘自动化控制台")
        self.root.geometry("1080x820")
        self.root.minsize(920, 680)
        self.root.configure(bg="#f4f6fb")
        self._set_app_icon()

        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        app_bg = "#f4f6fb"
        panel_bg = "#ffffff"
        text_fg = "#1d2939"
        muted_fg = "#667085"
        border = "#d0d5dd"
        primary = "#ff4747"
        primary_dark = "#d92d20"
        primary_soft = "#fff1f0"
        secondary = "#344054"

        style.configure("TFrame", background=app_bg)
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Header.TLabel", background=app_bg, foreground=text_fg, font=("微软雅黑", 16, "bold"))
        style.configure("SubHeader.TLabel", background=app_bg, foreground=muted_fg, font=("微软雅黑", 9))
        style.configure("Section.TLabel", background=panel_bg, foreground=primary_dark, font=("微软雅黑", 10, "bold"))
        style.configure("Field.TLabel", background=panel_bg, foreground=secondary, font=("微软雅黑", 9))
        style.configure("Hint.TLabel", background=panel_bg, foreground=muted_fg, font=("微软雅黑", 8))
        style.configure("Info.TLabelframe", background=panel_bg, bordercolor=border, lightcolor=border, darkcolor=border, padding=8)
        style.configure("Info.TLabelframe.Label", background=panel_bg, foreground=secondary, font=("微软雅黑", 9, "bold"))
        style.configure("TLabelframe", background=app_bg, bordercolor=border, lightcolor=border, darkcolor=border, padding=8)
        style.configure("TLabelframe.Label", background=app_bg, foreground=text_fg, font=("微软雅黑", 10, "bold"))
        style.configure("TNotebook", background=app_bg, borderwidth=0)
        style.configure("TNotebook.Tab", background="#e9eef6", foreground=secondary, padding=(14, 7), font=("微软雅黑", 9))
        style.map(
            "TNotebook.Tab",
            background=[("selected", panel_bg), ("active", primary_soft)],
            foreground=[("selected", primary_dark), ("active", primary_dark)],
        )
        style.configure("TButton", padding=(12, 7), background=panel_bg, foreground=secondary, bordercolor=border, focusthickness=0)
        style.map("TButton", background=[("active", "#f2f4f7"), ("disabled", "#f2f4f7")], foreground=[("disabled", "#98a2b3")])
        style.configure("Primary.TButton", padding=(12, 7), background=primary, foreground="#ffffff", bordercolor=primary)
        style.map("Primary.TButton", background=[("active", primary_dark), ("disabled", "#f2b8b5")], foreground=[("disabled", "#ffffff")])
        style.configure("Ghost.TButton", padding=(12, 7), background="#f8fafc", foreground=secondary, bordercolor=border)
        style.configure("Danger.TButton", padding=(12, 7), background="#fff1f0", foreground=primary_dark, bordercolor="#fda29b")

        self.process = None
        self.browser_process = None
        self.log_watcher_running = False
        self.last_log_pos = 0
        self.recent_gui_log_lines = []

        self._build_form()
        self._build_control_panel()
        self._build_log_panel()
        self._set_defaults()
        self.load_runtime_config(silent=True)

        # 打开 GUI 后自动拉起可调试 Chrome，用户登录后即可点“开始程序”
        self.root.after(300, self.auto_launch_browser)

    def _set_app_icon(self):
        try:
            if os.path.exists(APP_ICON_ICO):
                self.root.iconbitmap(APP_ICON_ICO)
        except Exception:
            pass
        try:
            if os.path.exists(APP_ICON_PNG):
                self._app_icon_photo = tk.PhotoImage(file=APP_ICON_PNG)
                self.root.iconphoto(True, self._app_icon_photo)
        except Exception:
            pass

    def _build_form(self):
        outer = ttk.Frame(self.root, padding=(12, 10, 12, 0))
        outer.pack(fill="x", expand=False)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 8))
        ttk.Label(header, text="店小秘自动上架助手", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="按功能区配置参数：先选类目/模板，再配置海关与模板，需要时再开启 AI 文本或 AI 主图处理。",
            style="SubHeader.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        self.vars = {
            "category": tk.StringVar(),
            "template": tk.StringVar(),
            "stock": tk.StringVar(),
            "size": tk.StringVar(),
            "weight": tk.StringVar(),
            "retail_multiplier": tk.StringVar(),
            "value_multiplier": tk.StringVar(),
            "currency_template": tk.StringVar(),
            "service_template": tk.StringVar(),
            "customs_item": tk.StringVar(),
            "customs_material": tk.StringVar(),
            "customs_process_mode": tk.StringVar(),
            "customs_level1": tk.StringVar(),
            "customs_level2": tk.StringVar(),
            "customs_level3": tk.StringVar(),
            "customs_level4": tk.StringVar(),
            "tax_included": tk.StringVar(),
            "european_responsible": tk.StringVar(),
            "brand_manufacturer": tk.StringVar(),
            "publish_action": tk.StringVar(),
            "description_image_mode": tk.StringVar(),
            "description_image_count": tk.StringVar(),
            "translation_type": tk.StringVar(),
            "language_pair": tk.StringVar(),
            "max_items": tk.StringVar(),
            "delay_between_actions": tk.StringVar(),
            "draft_search_keyword": tk.StringVar(),
            "draft_search_type": tk.StringVar(),
            "product_video_action": tk.StringVar(),
            "enable_ai_text": tk.StringVar(),
            "ai_text_api_url": tk.StringVar(),
            "ai_text_api_key": tk.StringVar(),
            "ai_text_model": tk.StringVar(),
            "ai_text_prompt": tk.StringVar(),
            "enable_ai_image": tk.StringVar(),
            "ai_image_api_url": tk.StringVar(),
            "ai_image_api_key": tk.StringVar(),
            "ai_image_model": tk.StringVar(),
            "ai_image_prompt": tk.StringVar(),
            "ai_image_use_product_context": tk.StringVar(),
            "ai_image_size": tk.StringVar(),
            "ai_image_count": tk.StringVar(),
            "ai_image_timeout_sec": tk.StringVar(),
            "ai_image_poll_interval_sec": tk.StringVar(),
        }

        # 本地可选项（默认值；可通过“获取下拉框信息”动态覆盖）
        self.dropdown_values = {
            "category": ["黑人化纤蕾丝发套"],
            "template": ["假发"],
            "currency_template": ["不包邮2"],
            "service_template": ["预设好的"],
            "tax_included": ["含关税报价", "不含关税报价"],
            "european_responsible": ["预设好的", "GOLDENCLICK SL", "GOLDENCLIC SL"],
            "brand_manufacturer": ["预设好的", "Guangzhou Qingsu International Trade Co., Ltd"],
            "publish_action": ["立即发布", "保存并移入待发布"],
            "description_image_mode": ["保留前N张", "删除末尾N张", "不处理"],
            "draft_search_type": ["标题", "商品编码"],
            "product_video_action": ["删除", "保留"],
            "translation_type": ["普通翻译"],
            "language_pair": ["中文-英文"],
            "customs_level1": [],
            "customs_level2": [],
            "customs_level3": [],
            "customs_level4": [],
            "customs_item": [],
            "customs_material": [],
            "customs_process_mode": ["按预设下拉选择", "仅点击添加/更新", "跳过海关监管"],
            "enable_ai_text": ["否", "是"],
            "ai_text_model": ["deepseek-v4-flash", "deepseek-v4-pro"],
            "enable_ai_image": ["否", "是"],
            "ai_image_use_product_context": ["否", "是"],
            "ai_image_model": ["doubao-seedream-5-0-260128", "doubao-seedream-5-0-pro-260628", "gpt-image-2"],
        }

        basic_rows = [
            ("产品分类", "category", "combo"),
            ("属性信息模板", "template", "combo"),
            ("库存", "stock", "entry"),
            ("尺寸(如 26*16*6)", "size", "entry"),
            ("重量", "weight", "entry"),
            ("零售价倍率", "retail_multiplier", "entry"),
            ("货值倍率", "value_multiplier", "entry"),
            ("处理数量(max_items)", "max_items", "entry"),
            ("动作间隔秒", "delay_between_actions", "entry"),
            ("采集箱搜索词", "draft_search_keyword", "entry"),
            ("采集箱搜索类型", "draft_search_type", "combo"),
            ("产品视频处理", "product_video_action", "combo"),
            ("详情图处理方式", "description_image_mode", "combo"),
            ("详情图数量N", "description_image_count", "entry"),
        ]
        template_rows = [
            ("运费模板", "currency_template", "combo"),
            ("服务模板", "service_template", "combo"),
            ("税费设置", "tax_included", "combo"),
            ("欧盟责任人", "european_responsible", "combo"),
            ("品牌制造商", "brand_manufacturer", "combo"),
            ("完成方式", "publish_action", "combo"),
            ("翻译方式", "translation_type", "combo"),
            ("语言对", "language_pair", "combo"),
            ("海关处理方式", "customs_process_mode", "combo"),
            ("海关监管1", "customs_level1", "combo"),
            ("海关监管2", "customs_level2", "combo"),
            ("海关监管3", "customs_level3", "combo"),
            ("海关监管4", "customs_level4", "combo"),
            ("海关品名(兼容)", "customs_item", "combo"),
            ("海关材质(兼容)", "customs_material", "combo"),
        ]
        ai_text_rows = [
            ("AI标题/SKU", "enable_ai_text", "combo"),
            ("文本Base URL", "ai_text_api_url", "entry"),
            ("文本API Key", "ai_text_api_key", "entry"),
            ("文本模型", "ai_text_model", "combo"),
            ("文本提示词", "ai_text_prompt", "entry"),
        ]
        ai_image_rows = [
            ("AI主图处理", "enable_ai_image", "combo"),
            ("图片API地址", "ai_image_api_url", "entry"),
            ("图片API Key", "ai_image_api_key", "entry"),
            ("图片模型", "ai_image_model", "combo"),
            ("图片提示词", "ai_image_prompt", "entry"),
            ("使用车型参数", "ai_image_use_product_context", "combo"),
            ("图片尺寸", "ai_image_size", "entry"),
            ("处理主图数", "ai_image_count", "entry"),
            ("最长等待秒", "ai_image_timeout_sec", "entry"),
            ("轮询间隔秒", "ai_image_poll_interval_sec", "entry"),
        ]

        # 跳过标记：勾选=跳过该参数修改（默认不跳过）
        skip_rows = basic_rows + [row for row in template_rows if row[1] not in {"publish_action", "customs_process_mode"}]
        self.skip_vars = {k: tk.BooleanVar(value=False) for _, k, _ in skip_rows}

        self.combo_widgets = {}
        self.param_widgets = {}
        notebook = ttk.Notebook(outer)
        notebook.pack(fill="x", expand=False)

        def make_tab(title: str):
            shell = ttk.Frame(notebook, style="Panel.TFrame")
            notebook.add(shell, text=title)
            shell.rowconfigure(0, weight=1)
            shell.columnconfigure(0, weight=1)

            canvas = tk.Canvas(shell, height=420, highlightthickness=0, bg="#ffffff")
            vbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
            canvas.configure(yscrollcommand=vbar.set)
            canvas.grid(row=0, column=0, sticky="nsew")
            vbar.grid(row=0, column=1, sticky="ns")

            tab = ttk.Frame(canvas, style="Panel.TFrame", padding=(18, 14, 18, 14))
            window_id = canvas.create_window((0, 0), window=tab, anchor="nw")
            tab.columnconfigure(1, weight=1)

            def _sync_scroll_region(_event=None):
                canvas.configure(scrollregion=canvas.bbox("all"))

            def _sync_canvas_width(event):
                canvas.itemconfigure(window_id, width=event.width)

            def _wheel(event):
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

            tab.bind("<Configure>", _sync_scroll_region)
            canvas.bind("<Configure>", _sync_canvas_width)
            canvas.bind("<MouseWheel>", _wheel)
            tab.bind("<MouseWheel>", _wheel)
            return tab

        def add_section(frame, row, title, hint=""):
            ttk.Label(frame, text=title, style="Section.TLabel").grid(row=row, column=0, columnspan=3, sticky="w", pady=(0, 6))
            if hint:
                ttk.Label(frame, text=hint, style="Hint.TLabel").grid(row=row, column=1, columnspan=2, sticky="e", pady=(0, 6))
            return row + 1

        def add_field(frame, row, label, key, widget_type, allow_skip=True, password=False, wide=False):
            ttk.Label(frame, text=label, width=18, style="Field.TLabel").grid(row=row, column=0, padx=(0, 10), pady=5, sticky="e")
            if widget_type == "combo":
                combo = ttk.Combobox(
                    frame,
                    textvariable=self.vars[key],
                    values=self.dropdown_values.get(key, []),
                    width=42 if wide else 30,
                    state="normal",
                )
                combo.grid(row=row, column=1, padx=0, pady=5, sticky="ew")
                self.combo_widgets[key] = combo
                self.param_widgets[key] = combo
            else:
                entry = ttk.Entry(
                    frame,
                    textvariable=self.vars[key],
                    width=70 if wide else 34,
                    show="*" if password else "",
                )
                entry.grid(row=row, column=1, padx=0, pady=5, sticky="ew")
                self.param_widgets[key] = entry

            if allow_skip and key in self.skip_vars:
                ttk.Checkbutton(
                    frame,
                    text="跳过",
                    variable=self.skip_vars[key],
                    command=lambda k=key: self._on_toggle_skip(k)
                ).grid(row=row, column=2, padx=(12, 0), pady=5, sticky="w")
            else:
                ttk.Label(frame, text="", style="Field.TLabel").grid(row=row, column=2, padx=(12, 0), pady=5, sticky="w")
            return row + 1

        def add_info_box(frame, row, title, lines, height=5):
            box = ttk.LabelFrame(frame, text=title, style="Info.TLabelframe")
            box.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))
            box.columnconfigure(0, weight=1)
            text = tk.Text(
                box,
                height=height,
                wrap="word",
                bg="#f9fafb",
                fg="#475467",
                relief="flat",
                padx=10,
                pady=8,
                font=("微软雅黑", 9),
            )
            text.grid(row=0, column=0, sticky="ew")
            text.insert("1.0", "\n".join(lines))
            text.configure(state="disabled")
            return row + 1

        basic_tab = make_tab("基础参数")
        row = add_section(basic_tab, 0, "商品与价格", "类目、模板、SKU库存价格等核心参数")
        for label, key, widget_type in basic_rows:
            row = add_field(basic_tab, row, label, key, widget_type)
        row = add_info_box(
            basic_tab,
            row,
            "使用步骤",
            [
                "1. 打开浏览器并登录店小秘，进入采集箱页面。",
                "2. 先点“① 获取类目选项”，在产品分类里选择本批次要处理的类目。",
                "3. 再点“② 获取当前类目联动项”，选择该类目下的属性信息模板。",
                "4. 库存、尺寸、重量、倍率会批量写入 SKU；不想改某项就勾选右侧“跳过”。",
                "5. 处理数量 max_items 控制本次批量最多处理几条，建议先小批量测试。",
            ],
            height=5,
        )

        template_tab = make_tab("模板/海关")
        row = add_section(template_tab, 0, "模板与合规", "运费、服务、税费、欧盟责任人与海关监管")
        for label, key, widget_type in template_rows:
            row = add_field(template_tab, row, label, key, widget_type, allow_skip=key != "customs_process_mode")
        row = add_info_box(
            template_tab,
            row,
            "联动说明",
            [
                "1. 产品属性模板和海关监管会跟随类目变化，先选类目，再拉联动项。",
                "2. 海关处理方式：常规类目选“按预设下拉选择”；自动生成税率代码的类目选“仅点击添加/更新”；不处理则选“跳过海关监管”。",
                "3. 海关监管需要先选好类目和属性模板，再点“③ 获取海关监管选项”。",
                "4. 完成方式可选“立即发布”或“保存并移入待发布”，后者不会直接上架。",
                "5. 欧盟责任人、品牌制造商如果页面只有一个选项，通常保持默认即可。",
            ],
            height=5,
        )

        ai_text_tab = make_tab("AI 文本")
        row = add_section(ai_text_tab, 0, "标题与 SKU 优化", "开启后会在店小秘一键翻译后写回 AI 优化结果")
        for label, key, widget_type in ai_text_rows:
            row = add_field(
                ai_text_tab,
                row,
                label,
                key,
                widget_type,
                allow_skip=False,
                password=key.endswith("_api_key"),
                wide=key in {"ai_text_api_url", "ai_text_prompt"},
            )
        row = add_info_box(
            ai_text_tab,
            row,
            "AI 文本接入说明",
            [
                "1. DeepSeek：到 https://platform.deepseek.com 注册并创建 API Key。",
                "2. 文本 Base URL 一般填 https://api.deepseek.com；API Key 填自己的 sk 开头密钥。",
                "3. 模型建议使用 deepseek-v4-flash 或你中转站实际支持的模型名。",
                "4. 提示词用于约束标题和 SKU：英文、控制长度、保留必要车型/型号、避免侵权词。",
                "5. 打包给别人使用时不要附带你的 runtime_config.json；源码默认不会写入你的 Key。",
            ],
            height=5,
        )

        ai_image_tab = make_tab("AI 图片")
        row = add_section(ai_image_tab, 0, "主图换背景", "开启后会下载主图、调用图片 API、再上传到页面")
        for label, key, widget_type in ai_image_rows:
            row = add_field(
                ai_image_tab,
                row,
                label,
                key,
                widget_type,
                allow_skip=False,
                password=key.endswith("_api_key"),
                wide=key in {"ai_image_api_url", "ai_image_prompt"},
            )
        row = add_info_box(
            ai_image_tab,
            row,
            "AI 图片接入说明",
            [
                "1. 火山引擎：到火山方舟控制台开通图片生成能力，创建 API Key。",
                "2. 图片 API 地址当前为 https://ark.cn-beijing.volces.com/api/v3/images/generations。",
                "3. 图片模型填 doubao-seedream-5-0-260128；页面尺寸填 1K，程序请求火山用 2K 后本地压缩为 1024x1024。",
                "4. 处理主图数建议先填 1，确认效果稳定后再增加，避免不必要的生图费用。",
                "5. 使用车型参数默认关闭；打开后会把 AI 文本分析出的车型、年份、产品类型追加到图片提示词。",
                "6. 如改用 GeekNow 等中转站，就填中转站提供的图片 API 地址、Key 和模型名。",
                "7. 提示词建议固定统一背景，不要生成文字、logo、品牌标识、水印或边框。",
            ],
            height=5,
        )

    def _build_control_panel(self):
        frame = ttk.LabelFrame(self.root, text="运行控制")
        frame.pack(fill="x", padx=12, pady=(10, 6))

        canvas = tk.Canvas(frame, height=58, highlightthickness=0, bg="#f4f6fb")
        canvas.pack(side="top", fill="x", expand=True)
        hbar = ttk.Scrollbar(frame, orient="horizontal", command=canvas.xview)
        hbar.pack(side="top", fill="x", padx=(4, 4), pady=(0, 4))
        canvas.configure(xscrollcommand=hbar.set)

        controls = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=controls, anchor="nw")

        def _sync_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_canvas_width(event):
            canvas.itemconfigure(window_id, height=event.height)

        controls.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_canvas_width)
        canvas.bind("<Shift-MouseWheel>", lambda event: canvas.xview_scroll(int(-1 * (event.delta / 120)), "units"))

        self.open_browser_btn = ttk.Button(controls, text="打开浏览器并登录", command=self.auto_launch_browser, style="Ghost.TButton")
        self.open_browser_btn.pack(side="left", padx=(4, 6), pady=8)

        self.fetch_category_btn = ttk.Button(controls, text="① 获取类目选项", command=lambda: self.fetch_dropdown_info("categories"), style="Ghost.TButton")
        self.fetch_category_btn.pack(side="left", padx=6, pady=8)

        self.fetch_linked_dropdown_btn = ttk.Button(controls, text="② 获取当前类目联动项", command=lambda: self.fetch_dropdown_info("linked"), style="Ghost.TButton")
        self.fetch_linked_dropdown_btn.pack(side="left", padx=6, pady=8)

        self.fetch_customs_dropdown_btn = ttk.Button(controls, text="③ 获取海关监管选项", command=lambda: self.fetch_dropdown_info("customs"), style="Ghost.TButton")
        self.fetch_customs_dropdown_btn.pack(side="left", padx=6, pady=8)

        self.start_btn = ttk.Button(controls, text="开始程序", command=self.start_automation, style="Primary.TButton")
        self.start_btn.pack(side="left", padx=6, pady=8)

        self.publish_only_btn = ttk.Button(controls, text="仅执行发布当前页", command=self.start_publish_only, style="Ghost.TButton")
        self.publish_only_btn.pack(side="left", padx=6, pady=8)

        self.stop_btn = ttk.Button(controls, text="停止程序", command=self.stop_automation, state="disabled", style="Danger.TButton")
        self.stop_btn.pack(side="left", padx=6, pady=8)

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=8, pady=8)

        self.save_btn = ttk.Button(controls, text="保存参数", command=self.save_runtime_config, style="Ghost.TButton")
        self.save_btn.pack(side="left", padx=6, pady=8)

        self.load_btn = ttk.Button(controls, text="加载参数", command=self.load_runtime_config, style="Ghost.TButton")
        self.load_btn.pack(side="left", padx=6, pady=8)

        self.import_btn = ttk.Button(controls, text="导入参数文件", command=self.import_runtime_config, style="Ghost.TButton")
        self.import_btn.pack(side="left", padx=6, pady=8)

        self.status_var = tk.StringVar(value="状态：未运行")
        self.progress_var = tk.StringVar(value="进度：0 / 0")

        ttk.Separator(controls, orient="vertical").pack(side="left", fill="y", padx=10, pady=8)

        status_box = ttk.Frame(controls)
        status_box.pack(side="left", padx=(6, 12), pady=8)
        ttk.Label(status_box, textvariable=self.status_var, foreground="#175cd3").pack(anchor="w")
        ttk.Label(status_box, textvariable=self.progress_var, foreground="#067647").pack(anchor="w", pady=(3, 0))

    def _build_log_panel(self):
        frame = ttk.LabelFrame(self.root, text="运行日志")
        frame.pack(fill="both", expand=True, padx=12, pady=(4, 12))

        self.log_text = ScrolledText(
            frame,
            height=10,
            font=("Consolas", 10),
            bg="#101828",
            fg="#e6edf7",
            insertbackground="#e4e7ec",
            relief="flat",
            padx=10,
            pady=8,
        )
        self.log_text.pack(fill="both", expand=True)

    def _on_toggle_skip(self, key: str):
        self._update_field_enabled_state(key)

    def _update_field_enabled_state(self, key: str):
        widget = self.param_widgets.get(key)
        if not widget:
            return
        try:
            if self.skip_vars[key].get():
                widget.configure(state="disabled")
            else:
                widget.configure(state="normal")
        except Exception:
            pass

    def _set_defaults(self):
        defaults = {
            "category": "黑人化纤蕾丝发套",
            "template": "假发",
            "stock": "5000",
            "size": "26*16*6",
            "weight": "0.14",
            "retail_multiplier": "7.0",
            "value_multiplier": "2.0",
            "currency_template": "不包邮2",
            "service_template": "预设好的",
            "customs_item": "蕾丝假发",
            "customs_material": "高温纤维",
            "customs_process_mode": "按预设下拉选择",
            "customs_level1": "蕾丝假发",
            "customs_level2": "高温纤维",
            "customs_level3": "",
            "customs_level4": "",
            "tax_included": "含关税报价",
            "european_responsible": "预设好的",
            "brand_manufacturer": "预设好的",
            "publish_action": "立即发布",
            "translation_type": "普通翻译",
            "language_pair": "中文-英文",
            "max_items": "50",
            "delay_between_actions": "0.5",
            "draft_search_keyword": "",
            "draft_search_type": "标题",
            "product_video_action": "删除",
            "description_image_mode": "保留前N张",
            "description_image_count": "5",
            "enable_ai_text": "否",
            "ai_text_api_url": "https://api.deepseek.com",
            "ai_text_api_key": "",
            "ai_text_model": "deepseek-v4-flash",
            "ai_text_prompt": "Translate and optimize the AliExpress title and SKU names into compliant English. Keep accurate product type, compatible brand/model words when present, avoid trademark infringement claims, and return strict JSON.",
            "enable_ai_image": "否",
            "ai_image_api_url": "https://ark.cn-beijing.volces.com/api/v3/images/generations",
            "ai_image_api_key": "",
            "ai_image_model": "doubao-seedream-5-0-260128",
            "ai_image_prompt": "保持商品主体完全不变，去除原背景和水印，将产品放在统一的浅灰色电商棚拍背景中。不要添加文字、logo、品牌标识、边框或装饰元素。画面干净真实，产品居中，1:1正方形构图，适合速卖通主图。",
            "ai_image_use_product_context": "否",
            "ai_image_size": "1K",
            "ai_image_count": "1",
            "ai_image_timeout_sec": "1800",
            "ai_image_poll_interval_sec": "15",
        }
        for k, v in defaults.items():
            self.vars[k].set(v)

        # 默认全部不跳过，确保可编辑
        for k in self.skip_vars.keys():
            self._update_field_enabled_state(k)

    def _append_log(self, line: str):
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")

    def _notify_finished(self):
        """
        程序停止后语音/声音提示（Windows）
        """
        try:
            # 系统提示音（最稳妥，打包后也可用）
            winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)
        except Exception:
            try:
                self.root.bell()
            except Exception:
                pass

    def _build_runtime_config_data(self):
        customs_level1 = self.vars["customs_level1"].get().strip()
        customs_level2 = self.vars["customs_level2"].get().strip()
        customs_level3 = self.vars["customs_level3"].get().strip()
        customs_level4 = self.vars["customs_level4"].get().strip()

        data = {
            "category": self.vars["category"].get().strip(),
            "template": self.vars["template"].get().strip(),
            "stock": int(self.vars["stock"].get().strip()),
            "size": self.vars["size"].get().strip(),
            "weight": float(self.vars["weight"].get().strip()),
            "retail_multiplier": float(self.vars["retail_multiplier"].get().strip()),
            "value_multiplier": float(self.vars["value_multiplier"].get().strip()),
            "currency_template": self.vars["currency_template"].get().strip(),
            "service_template": self.vars["service_template"].get().strip(),
            "customs_item": self.vars["customs_item"].get().strip() or customs_level1,
            "customs_material": self.vars["customs_material"].get().strip() or customs_level2,
            "customs_process_mode": self.vars["customs_process_mode"].get().strip() or "按预设下拉选择",
            "customs_level1": customs_level1 or self.vars["customs_item"].get().strip(),
            "customs_level2": customs_level2 or self.vars["customs_material"].get().strip(),
            "customs_level3": customs_level3,
            "customs_level4": customs_level4,
            "tax_included": self.vars["tax_included"].get().strip(),
            "european_responsible": self.vars["european_responsible"].get().strip(),
            "brand_manufacturer": self.vars["brand_manufacturer"].get().strip(),
            "publish_action": self.vars["publish_action"].get().strip() or "立即发布",
            "translation_type": self.vars["translation_type"].get().strip(),
            "language_pair": self.vars["language_pair"].get().strip(),
            "max_items": int(self.vars["max_items"].get().strip()),
            "delay_between_actions": float(self.vars["delay_between_actions"].get().strip()),
            "draft_search_keyword": self.vars["draft_search_keyword"].get().strip(),
            "draft_search_type": self.vars["draft_search_type"].get().strip() or "标题",
            "product_video_action": self.vars["product_video_action"].get().strip() or "删除",
            "description_image_mode": self.vars["description_image_mode"].get().strip() or "保留前N张",
            "description_image_count": int(self.vars["description_image_count"].get().strip() or "5"),
            "enable_ai_text": self.vars["enable_ai_text"].get().strip(),
            "ai_text_api_url": self.vars["ai_text_api_url"].get().strip(),
            "ai_text_api_key": self.vars["ai_text_api_key"].get().strip(),
            "ai_text_model": self.vars["ai_text_model"].get().strip(),
            "ai_text_prompt": self.vars["ai_text_prompt"].get().strip(),
            "enable_ai_image": self.vars["enable_ai_image"].get().strip(),
            "ai_image_api_url": self.vars["ai_image_api_url"].get().strip(),
            "ai_image_api_key": self.vars["ai_image_api_key"].get().strip(),
            "ai_image_model": self.vars["ai_image_model"].get().strip(),
            "ai_image_prompt": self.vars["ai_image_prompt"].get().strip(),
            "ai_image_use_product_context": self.vars["ai_image_use_product_context"].get().strip() or "否",
            "ai_image_size": self.vars["ai_image_size"].get().strip(),
            "ai_image_count": int(self.vars["ai_image_count"].get().strip() or "1"),
            "ai_image_timeout_sec": int(self.vars["ai_image_timeout_sec"].get().strip() or "1800"),
            "ai_image_poll_interval_sec": int(self.vars["ai_image_poll_interval_sec"].get().strip() or "15"),
        }

        for key, var in self.skip_vars.items():
            data[f"skip_{key}"] = bool(var.get())

        return data

    def save_runtime_config(self):
        try:
            data = self._build_runtime_config_data()
            with open(RUNTIME_CONFIG, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self._append_log(f"[GUI] 参数已保存到 {RUNTIME_CONFIG}")
            messagebox.showinfo("提示", "参数已保存")
        except Exception as e:
            messagebox.showerror("错误", f"保存参数失败：{e}")

    def _apply_runtime_config_data(self, data: dict):
        if not isinstance(data, dict):
            raise ValueError("参数文件格式不正确，根节点必须是 JSON 对象")

        for key, var in self.vars.items():
            if key in data:
                value = data.get(key, "")
                if key == "ai_text_model" and value in ("deepseek-chat", "deepseek-reasoner"):
                    value = "deepseek-v4-flash"
                var.set("" if value is None else str(value))

        for key, var in self.skip_vars.items():
            var.set(bool(data.get(f"skip_{key}", False)))
            self._update_field_enabled_state(key)

    def import_runtime_config(self):
        try:
            path = filedialog.askopenfilename(
                title="选择旧版本参数文件 runtime_config.json",
                filetypes=[("JSON 参数文件", "*.json"), ("所有文件", "*.*")],
            )
            if not path:
                return

            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            self._apply_runtime_config_data(data)
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(RUNTIME_CONFIG, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            self._append_log(f"[GUI] 已导入参数文件: {path}")
            self._append_log(f"[GUI] 已保存到新版固定配置路径: {RUNTIME_CONFIG}")
            messagebox.showinfo("提示", f"参数已导入并保存到：\n{RUNTIME_CONFIG}")
        except Exception as e:
            messagebox.showerror("错误", f"导入参数文件失败：{e}")
    def load_runtime_config(self, silent: bool = False):
        try:
            config_path = RUNTIME_CONFIG
            if (not getattr(sys, "frozen", False)) and not os.path.exists(config_path) and os.path.exists(APP_DIR_RUNTIME_CONFIG):
                try:
                    with open(APP_DIR_RUNTIME_CONFIG, "r", encoding="utf-8") as src:
                        data = json.load(src)
                    with open(RUNTIME_CONFIG, "w", encoding="utf-8") as dst:
                        json.dump(data, dst, ensure_ascii=False, indent=2)
                    config_path = RUNTIME_CONFIG
                except Exception:
                    config_path = APP_DIR_RUNTIME_CONFIG

            if not os.path.exists(config_path):
                if not silent:
                    messagebox.showwarning("提示", f"未找到已保存参数文件：\n{RUNTIME_CONFIG}")
                return

            with open(config_path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)

            for key, var in self.vars.items():
                if key in data:
                    value = data.get(key, "")
                    if key == "ai_text_model" and value in ("deepseek-chat", "deepseek-reasoner"):
                        value = "deepseek-v4-flash"
                    var.set("" if value is None else str(value))

            for key, var in self.skip_vars.items():
                var.set(bool(data.get(f"skip_{key}", False)))
                self._update_field_enabled_state(key)

            self._append_log(f"[GUI] 已加载参数文件: {config_path}")
            if not silent:
                messagebox.showinfo("提示", "参数已加载到界面")
        except Exception as e:
            if silent:
                self._append_log(f"[GUI] 自动加载参数失败: {e}")
            else:
                messagebox.showerror("错误", f"加载参数失败：{e}")

    def _detect_chrome_path(self):
        candidates = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None

    def _chrome_debug_ready(self, timeout_sec: float = 2.0):
        endpoints = [
            f"http://127.0.0.1:{DEBUG_PORT}/json/version",
            f"http://localhost:{DEBUG_PORT}/json/version",
            f"http://[::1]:{DEBUG_PORT}/json/version",
        ]
        last_error = None
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            for url in endpoints:
                try:
                    with urllib.request.urlopen(url, timeout=0.8) as resp:
                        return True, url, resp.read(200).decode("utf-8", errors="ignore")
                except Exception as exc:
                    last_error = exc
            time.sleep(0.2)
        return False, "", str(last_error) if last_error else ""

    def auto_launch_browser(self):
        try:
            ready, url, _ = self._chrome_debug_ready(timeout_sec=1.0)
            if ready:
                self._append_log(f"[GUI] 已检测到可用调试浏览器: {url}")
                return

            chrome_path = self._detect_chrome_path()
            if not chrome_path:
                self._append_log("[GUI] 未找到 Chrome 可执行文件，请手动打开带调试端口的 Chrome")
                return

            os.makedirs(CHROME_PROFILE, exist_ok=True)

            # 直接拉起 Chrome（带远程调试端口 + 指定采集箱 URL）
            cmd = [
                chrome_path,
                f"--remote-debugging-port={DEBUG_PORT}",
                "--remote-debugging-address=127.0.0.1",
                f"--user-data-dir={CHROME_PROFILE}",
                "--no-first-run",
                "--no-default-browser-check",
                DRAFT_URL,
            ]

            self.browser_process = subprocess.Popen(cmd, cwd=BASE_DIR)
            self._append_log("[GUI] 已打开调试 Chrome，请先登录店小秘后点击“开始程序”")
            ready, url, err = self._chrome_debug_ready(timeout_sec=6.0)
            if ready:
                self._append_log(f"[GUI] 调试端口已就绪: {url}")
            else:
                self._append_log(f"[GUI] 调试端口暂未就绪，请稍等或重新点击打开浏览器: {err}")
        except Exception as e:
            self._append_log(f"[GUI] 打开浏览器失败: {e}")

    def fetch_dropdown_info(self, mode: str = "linked"):
        """
        登录后点击：从当前页面抓取下拉框信息并更新 GUI 可选项。
        mode=categories 只抓类目；mode=linked 按当前类目抓联动项；mode=customs 按当前类目和属性模板抓海关弹窗选项。
        """
        if self.process and self.process.poll() is None:
            messagebox.showwarning("提示", "自动化运行中，不能获取下拉框信息")
            return

        try:
            if mode in {"linked", "customs"}:
                self.save_runtime_config()
                category = self.vars.get("category").get().strip() if self.vars.get("category") else ""
                if not category:
                    messagebox.showwarning("提示", "请先选择或填写类目。")
                    return
                if mode == "customs":
                    template = self.vars.get("template").get().strip() if self.vars.get("template") else ""
                    if not template:
                        messagebox.showwarning("提示", "请先选择或填写属性信息模板，再获取海关监管选项。")
                        return
                    self._append_log(f"[GUI] 正在按类目和属性模板获取海关监管选项: {category} / {template}")
                else:
                    self._append_log(f"[GUI] 正在获取当前类目联动项: {category}")
            else:
                self._append_log("[GUI] 正在获取类目选项...")

            # 打包模式：走同 exe 的 worker 子进程，不依赖外部 py/main_automation.py 文件
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, "--worker-fetch-dropdowns", f"--fetch-mode={mode}"]
            else:
                if not os.path.exists(MAIN_SCRIPT):
                    messagebox.showerror("错误", f"找不到主脚本：{MAIN_SCRIPT}")
                    return

                py_cmd = self._detect_python_cmd()
                if not py_cmd:
                    messagebox.showerror("错误", "未检测到 Python 运行环境（python/py）。")
                    return
                cmd = py_cmd + [MAIN_SCRIPT, "--fetch-dropdowns", f"--fetch-mode={mode}"]

            p = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            out, _ = p.communicate(timeout=90)
            if out:
                for line in out.splitlines():
                    self._append_log(line)

            options_file = DROPDOWN_OPTIONS_FILE
            if not os.path.exists(options_file):
                self._append_log(f"[GUI] dropdown_options.json not found: {options_file}")
                self._append_log(f"[GUI] fetch worker exit code: {p.returncode}")
                messagebox.showwarning("提示", "未生成 dropdown_options.json，请确认已登录且页面已打开。")
                return

            with open(options_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            fetch_mode = data.get("mode") or mode
            items = data.get("items", [])
            special_options = data.get("special_options", {})

            # 关键词映射
            mapping = {
                "category": ["分类", "类目"],
                "template": ["模板", "引用模板"],
                "currency_template": ["运费模板", "币种模板", "售价运费"],
                "service_template": ["服务模板"],
                "tax_included": ["关税", "报价是否含关税"],
                "european_responsible": ["欧盟责任人"],
                "brand_manufacturer": ["品牌制造商", "制造商"],
                "translation_type": ["翻译方式", "翻译类型"],
                "language_pair": ["语言对", "翻译语言"],
                "customs_level1": ["海关监管1"],
                "customs_level2": ["海关监管2"],
                "customs_level3": ["海关监管3"],
                "customs_level4": ["海关监管4"],
                "customs_item": ["海关品名"],
                "customs_material": ["海关材质"],
            }

            # inputId 精准映射（你反馈的关键字段）
            input_id_mapping = {
                "form_item_freightTemplateId": "currency_template",
                "form_item_promiseTemplateId": "service_template",
                "form_item_msrEuId": "european_responsible",
                "form_item_manufactureId": "brand_manufacturer",
                "rc_select_1": "category",
            }

            if fetch_mode == "categories":
                target_keys = {"category"}
            elif fetch_mode == "linked":
                target_keys = set(mapping.keys()) - {"category", "customs_level1", "customs_level2", "customs_level3", "customs_level4", "customs_item", "customs_material"}
            elif fetch_mode == "customs":
                target_keys = {"customs_level1", "customs_level2", "customs_level3", "customs_level4", "customs_item", "customs_material"}
            else:
                target_keys = set(mapping.keys())

            collected = {k: set(self.dropdown_values.get(k, [])) for k in mapping.keys()}

            # 先合并 main_automation.py 专门采集的候选（最可靠）
            for key, arr in special_options.items():
                if key in collected and isinstance(arr, list):
                    for v in arr:
                        if isinstance(v, str) and v.strip():
                            collected[key].add(v.strip())

            for it in items:
                label = (it.get("label") or "").strip()
                current = (it.get("current") or "").strip()
                placeholder = (it.get("placeholder") or "").strip()
                input_id = (it.get("inputId") or "").strip()
                text = f"{label} {placeholder}"

                # 1) 先按 inputId 精准归类
                mapped_key = input_id_mapping.get(input_id)
                if mapped_key and current:
                    collected[mapped_key].add(current)

                # 2) 再按关键词兜底归类
                for key, kws in mapping.items():
                    if any(kw in text for kw in kws):
                        if current:
                            collected[key].add(current)

            # 回写 combobox 候选
            for key, values in collected.items():
                if key not in target_keys:
                    continue
                vals = [v for v in values if v]
                vals.sort()
                self.dropdown_values[key] = vals
                combo = self.combo_widgets.get(key)
                if combo:
                    combo["values"] = vals

            if fetch_mode == "categories":
                self._append_log("[GUI] 类目选项已更新。请先选择类目，再点击“② 获取当前类目联动项”。")
                messagebox.showinfo("提示", "类目选项获取完成。请选择类目后再获取联动项。")
            elif fetch_mode == "customs":
                self._append_log("[GUI] 海关监管选项已更新到界面可选项")
                messagebox.showinfo("提示", "海关监管选项获取完成，已更新到界面。")
            else:
                self._append_log("[GUI] 当前类目联动项已更新到界面可选项")
                messagebox.showinfo("提示", "当前类目联动项获取完成，已更新到界面。")
        except Exception as e:
            messagebox.showerror("错误", f"获取下拉框信息失败：{e}")

    def _detect_python_cmd(self):
        # 优先当前环境 python，再尝试 py
        for cmd in (["python"], ["py", "-3"]):
            try:
                p = subprocess.Popen(
                    cmd + ["-V"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                p.communicate(timeout=5)
                if p.returncode == 0:
                    return cmd
            except Exception:
                continue
        return None

    def _start_worker_process(self, mode_label: str, frozen_worker_arg: str, dev_args: list[str]):
        if self.process and self.process.poll() is None:
            messagebox.showwarning("提示", "程序已在运行")
            return

        try:
            ready, url, err = self._chrome_debug_ready(timeout_sec=2.0)
            if not ready:
                self._append_log("[GUI] 未检测到可用调试浏览器，正在重新打开...")
                self.auto_launch_browser()
                ready, url, err = self._chrome_debug_ready(timeout_sec=8.0)
            if not ready:
                messagebox.showerror("启动失败", f"Chrome 调试端口 9222 未就绪：{err}")
                return
            self.save_runtime_config()
            self.log_text.delete("1.0", "end")
            self._append_log(f"[GUI] 启动任务: {mode_label}")
            self._append_log(f"[GUI] 将连接调试浏览器: {url}")

            # 单文件纯客户端模式：启动“同一个 exe 的 worker 子进程”
            if getattr(sys, "frozen", False):
                cmd = [sys.executable, frozen_worker_arg]
                self._append_log(f"[GUI] Worker命令: {' '.join(cmd)}")
                env = os.environ.copy()
                env["SHOP_AUTOMATION_QUIET_STDOUT"] = "1"
                self.process = subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    bufsize=1,
                )
            else:
                # 开发模式（python 直接运行）
                if not os.path.exists(MAIN_SCRIPT):
                    messagebox.showerror(
                        "启动失败",
                        f"找不到主脚本：\n{MAIN_SCRIPT}"
                    )
                    return

                py_cmd = self._detect_python_cmd()
                if not py_cmd:
                    messagebox.showerror(
                        "启动失败",
                        "未检测到 Python 运行环境（python/py）。"
                    )
                    return

                cmd = py_cmd + [MAIN_SCRIPT] + list(dev_args)
                self._append_log(f"[GUI] Dev命令: {' '.join(cmd)}")
                env = os.environ.copy()
                env["SHOP_AUTOMATION_QUIET_STDOUT"] = "1"
                self.process = subprocess.Popen(
                    cmd,
                    cwd=BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    bufsize=1,
                )

            self.status_var.set("状态：运行中")
            self.start_btn.config(state="disabled")
            self.stop_btn.config(state="normal")

            self.log_watcher_running = True
            self.last_log_pos = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0
            self.recent_gui_log_lines = []
            threading.Thread(target=self._watch_process_exit, daemon=True).start()
            threading.Thread(target=self._watch_log_file, daemon=True).start()

        except Exception as e:
            messagebox.showerror("错误", f"启动失败：{e}")

    def start_automation(self):
        self._start_worker_process("完整自动化流程", "--worker", [])

    def start_publish_only(self):
        self._start_worker_process("仅执行发布当前页", "--worker-publish-only", ["--publish-only"])

    def stop_automation(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self._append_log("[GUI] 已发送停止信号")
        self.status_var.set("状态：已停止")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.log_watcher_running = False
        self._notify_finished()

    def _watch_process_exit(self):
        if not self.process:
            return
        try:
            code = self.process.wait()
        except Exception as e:
            self.root.after(0, self._append_log, f"[GUI] 进程监控异常: {e}")
            code = None

        self.root.after(0, self._append_log, f"[GUI] 脚本退出，返回码: {code}")
        self.root.after(0, self.status_var.set, "状态：未运行")
        self.root.after(0, self.start_btn.config, {"state": "normal"})
        self.root.after(0, self.stop_btn.config, {"state": "disabled"})
        self.root.after(0, self._notify_finished)
        self.log_watcher_running = False

    def _watch_process_output(self):
        if not self.process:
            return

        try:
            while True:
                if not self.process:
                    break

                line = self.process.stdout.readline()
                if line:
                    line = line.rstrip("\n")
                    if line:
                        self.root.after(0, self._append_log, line)
                    continue

                # readline 空串：可能真的退出，也可能只是暂时没输出
                code = self.process.poll()
                if code is None:
                    time.sleep(0.2)
                    continue
                break

        except Exception as e:
            self.root.after(0, self._append_log, f"[GUI] 输出监控异常: {e}")

        finally:
            code = self.process.poll() if self.process else None

            # 关键修复：code=None 不视为退出，避免误报“退出”
            if code is None:
                self.root.after(0, self._append_log, "[GUI] 输出流短暂中断，进程仍在运行，继续监控日志文件")
                return

            self.root.after(0, self._append_log, f"[GUI] 脚本退出，返回码: {code}")
            self.root.after(0, self.status_var.set, "状态：未运行")
            self.root.after(0, self.start_btn.config, {"state": "normal"})
            self.root.after(0, self.stop_btn.config, {"state": "disabled"})
            self.root.after(0, self._notify_finished)
            self.log_watcher_running = False

    def _watch_log_file(self):
        total = self.vars["max_items"].get().strip() or "0"
        try:
            total_int = int(total)
        except Exception:
            total_int = 0

        while self.log_watcher_running:
            try:
                if os.path.exists(LOG_FILE):
                    with open(LOG_FILE, "r", encoding="utf-8") as f:
                        f.seek(self.last_log_pos)
                        chunk = f.read()
                        self.last_log_pos = f.tell()

                    if chunk:
                        for line in chunk.splitlines():
                            if line and line not in self.recent_gui_log_lines:
                                self.recent_gui_log_lines.append(line)
                                self.recent_gui_log_lines = self.recent_gui_log_lines[-200:]
                                self.root.after(0, self._append_log, line)

                            if "开始处理第 " in line and " 个商品" in line:
                                # 解析进度
                                try:
                                    left = line.split("开始处理第 ")[1]
                                    idx = int(left.split(" 个商品")[0])
                                    self.root.after(0, self.progress_var.set, f"进度：{idx} / {total_int}")
                                except Exception:
                                    pass
            except Exception:
                pass

            time.sleep(0.5)


def run_worker_mode():
    """
    worker 子进程入口（用于单文件 exe 内部运行自动化主程序）
    """
    import asyncio
    import main_automation

    asyncio.run(main_automation.main())


def run_worker_fetch_dropdowns():
    """
    worker 子进程入口：采集下拉框信息（用于单文件 exe）
    """
    import asyncio
    import main_automation

    mode = "linked"
    for arg in sys.argv:
        if arg.startswith("--fetch-mode="):
            mode = arg.split("=", 1)[1].strip() or mode
    asyncio.run(main_automation.fetch_dropdown_info(mode))


def run_worker_publish_only():
    """
    worker 子进程入口：只执行当前编辑页发布步骤（用于单文件 exe）
    """
    import asyncio
    import main_automation

    asyncio.run(main_automation.publish_current_edit_page_only())


def main():
    root = tk.Tk()
    app = AutomationGUI(root)
    root.mainloop()


if __name__ == "__main__":
    if "--worker-fetch-dropdowns" in sys.argv:
        run_worker_fetch_dropdowns()
    elif "--worker-publish-only" in sys.argv:
        run_worker_publish_only()
    elif "--worker" in sys.argv:
        run_worker_mode()
    else:
        main()
