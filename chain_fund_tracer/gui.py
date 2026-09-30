from __future__ import annotations

import os
import re
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .analysis import Analyzer
from .branding import PRODUCT_NAME, PRODUCT_NAME_EN, PRODUCT_NAME_ZH, PRODUCT_SUBTITLE
from .config import load_settings, save_settings
from .csv_loader import inspect_and_load_polygonscan_csv
from .exporters import export_csv, export_evidence_package, export_svg, export_text
from .flow_graph import (
    FlowEdge,
    FlowNode,
    ROLE_BRIDGE,
    ROLE_DEPOSIT_WALLET,
    ROLE_DEX,
    ROLE_EXCHANGE,
    ROLE_INTERMEDIATE,
    ROLE_POLYMARKET_INTERNAL,
    ROLE_RELAY_SOLVER,
    ROLE_RELAY_SOURCE,
    ROLE_UNCLASSIFIED,
    ROLE_ZERO_MINT,
    bridge_elapsed,
    build_case_summary,
    build_flow_graph,
    ordered_edges,
    short_address,
)
from .providers import PolygonProvider
from .explanations import explain_step, plain_summary
from .relay_evidence import explorer_url
from .flow_graph import infer_chain
from .history import (
    HistoryEntry,
    clear_history,
    list_history_entries,
    load_history_snapshot,
    save_history_entry,
)


class AnalysisCancelled(RuntimeError):
    pass


class App(ttk.Frame):
    THEMES = {
        "light": {
            "header_bg": "#0f172a",          # 頂欄深邃科技黑藍 (Slate-900)
            "header_text": "#ffffff",        # 頂欄純白標題
            "header_sub": "#94a3b8",         # 頂欄科技淺灰 (Slate-400)
            "header_badge_bg": "#1e293b",    # 頂欄徽章底色 (Slate-800)
            "header_badge_border": "#334155",# 頂欄徽章邊框
            "header_badge_text": "#38bdf8",  # 頂欄徽章文字 (Sky-400 科技藍)

            "background": "#e2e8f0",         # 工作台背板：有階層感的質感冷灰 (Slate-200)
            "well_bg": "#f1f5f9",            # 框內凹槽/槽底色 (Slate-100)，營造框中框層次！
            "surface": "#ffffff",            # 卡片純白容器 (Card Surface)
            "surface_subtle": "#f8fafc",     # 卡片次級底色 (Slate-50)
            "border": "#cbd5e1",             # 清晰主要邊框 (Slate-300)
            "border_strong": "#94a3b8",      # 實體強調邊框 (Slate-400)
            "text": "#0f172a",               # 主要文字 (Slate-900)
            "text_h1": "#0f172a",            # H1 核心大標題文字 (Slate-900)
            "text_h2": "#1d4ed8",            # H2 區塊次標題文字 (科技深藍 Blue-700)
            "secondary": "#334155",          # 次要文字 (Slate-700)
            "muted": "#64748b",              # 弱化/輔助文字 (Slate-500)

            "action": "#1d4ed8",             # 科技深藍 (Blue-700)
            "action_hover": "#1e40af",       # 懸停深藍 (Blue-800)
            "action_subtle": "#eff6ff",      # 淺藍高亮 (Blue-50)

            "canvas_bg": "#f8fafc",          # 畫布護眼微冷灰 (Slate-50)
            "canvas_card_bg": "#ffffff",     # 畫布節點白卡

            "success": "#059669",            # 翡翠綠
            "success_subtle": "#ecfdf5",
            "warning": "#d97706",            # 琥珀橘
            "warning_subtle": "#fffbeb",
            "error": "#dc2626",              # 警示紅
            "error_subtle": "#fef2f2",
            "info": "#4f46e5",               # 資訊靛藍
            "info_subtle": "#eef2ff",

            "exchange": "#fef3c7",           # VASP 琥珀金
            "exchange_border": "#d97706",
            "bridge": "#eef2ff",             # 跨鏈 靛藍紫
            "bridge_border": "#4f46e5",
            "polymarket": "#f5f3ff",         # Polymarket 紫色
            "polymarket_border": "#7c3aed",
            "dex": "#ecfdf5",                # DEX 翡翠綠
            "dex_border": "#059669",
            "unknown": "#f8fafc",
            "target": "#e0f2fe",             # TARGET 標的天藍
            "target_border": "#0284c7",
        },
        "dark": {
            "header_bg": "#030712",          # 頂欄深黑 (Gray-950)
            "header_text": "#ffffff",        # 頂欄標題
            "header_sub": "#9ca3af",         # 頂欄副標
            "header_badge_bg": "#111827",    # 頂欄徽章底色
            "header_badge_border": "#374151",# 頂欄徽章邊框
            "header_badge_text": "#38bdf8",  # 頂欄徽章文字

            "background": "#0b0f19",         # 暗黑工作台背板
            "well_bg": "#1e293b",            # 框內凹槽/槽底色 (Slate-800)，框體層次鮮明！
            "surface": "#111827",            # 卡片暗黑容器 (Gray-900)
            "surface_subtle": "#1f2937",     # 卡片次級底色 (Gray-800)
            "border": "#374151",             # 深色邊框 (Gray-700)
            "border_strong": "#4b5563",      # 深色強邊框 (Gray-600)
            "text": "#f9fafb",               # 白色主文字 (Gray-50)
            "text_h1": "#f9fafb",            # H1 核心大標題文字
            "text_h2": "#38bdf8",            # H2 區塊次標題文字 (Sky-400 亮藍)
            "secondary": "#cbd5e1",          # 淺灰次要文字 (Slate-300)
            "muted": "#94a3b8",              # 中灰弱化文字 (Slate-400)

            "action": "#2563eb",             # 科技藍
            "action_hover": "#3b82f6",       # 懸停亮藍
            "action_subtle": "#1e3a8a",      # 暗藍高亮

            "canvas_bg": "#0f172a",          # 畫布深邃冷藍黑 (Slate-900)
            "canvas_card_bg": "#1e293b",     # 畫布節點深卡 (Slate-800)

            "success": "#10b981",
            "success_subtle": "#064e3b",
            "warning": "#f59e0b",
            "warning_subtle": "#78350f",
            "error": "#ef4444",
            "error_subtle": "#7f1d1d",
            "info": "#6366f1",
            "info_subtle": "#312e81",

            "exchange": "#78350f",           # 暗色 VASP
            "exchange_border": "#f59e0b",
            "bridge": "#312e81",             # 暗色 跨鏈
            "bridge_border": "#818cf8",
            "polymarket": "#4c1d95",         # 暗色 Polymarket
            "polymarket_border": "#a78bfa",
            "dex": "#064e3b",                # 暗色 DEX
            "dex_border": "#34d399",
            "unknown": "#1e293b",
            "target": "#0c4a6e",             # 暗色 TARGET
            "target_border": "#38bdf8",
        },
    }
    COLORS = THEMES["light"]

    def __init__(self, root: tk.Tk, initial_query: str = "", auto_start: bool = False):
        self.root = root
        self.settings = load_settings()
        self.result = None
        self.graph = None
        self.selected_edge: FlowEdge | None = None
        self.selected_edge_index: int = -1
        self.current_edges: list[FlowEdge] = []
        self.edge_boxes: dict[str, tuple[float, float, float, float, float, float]] = {}
        self.history_entries: list[HistoryEntry] = []
        self.cancel_event = threading.Event()
        self.zoom = 1.0
        self.resolving = False
        self.running = False
        self.theme_name = "light"
        self.COLORS = dict(self.THEMES[self.theme_name])

        self._configure_style()
        super().__init__(root, padding=0, style="App.TFrame")

        root.title(f"{PRODUCT_NAME}｜資金流程圖")
        root.minsize(1080, 720)
        root.geometry("1280x820")
        root.configure(background=self.COLORS["background"])
        root.columnconfigure(0, weight=1)
        root.rowconfigure(0, weight=1)
        self.grid(sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=0)
        self.rowconfigure(1, weight=1)

        self.query = tk.StringVar(value=initial_query)
        self.hops = tk.IntVar(value=self.settings.max_hops)
        self.status = tk.StringVar(value="請輸入 Tx Hash 或 Wallet Address，再選擇分析模式。")
        self.show_inbound = tk.BooleanVar(value=True)
        self.show_outbound = tk.BooleanVar(value=True)
        self.show_internal = tk.BooleanVar(value=True)
        self.show_pool_inflow = tk.BooleanVar(value=True)
        self.show_gas_funding = tk.BooleanVar(value=True)
        self.show_technical_details = tk.BooleanVar(value=False)
        self.time_filter_var = tk.StringVar(value="")
        self.csv_path_var = tk.StringVar(value="")
        self.csv_display_var = tk.StringVar(value="（未選取）")
        self.advanced_visible = tk.BooleanVar(value=False)
        self.progress_caption = tk.StringVar(value="待命")
        self.progress_value = tk.DoubleVar(value=0)
        self._csv_inspect_after: str | None = None
        self.query_started_at: float | None = None
        self.csv_path_var.trace_add("write", self._on_csv_path_changed)

        self._build()
        self._refresh_history_combobox()
        self._render_empty_state()
        if auto_start and initial_query:
            self.root.after(150, lambda: self.start("polymarket"))

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        c = self.COLORS
        # 全域與容器
        style.configure(".", background=c["background"], font=("Microsoft JhengHei UI", 9))
        style.configure("App.TFrame", background=c["background"])
        style.configure("TFrame", background=c["background"])
        style.configure("TLabel", background=c["background"], foreground=c["text"], font=("Microsoft JhengHei UI", 9))
        style.configure("Title.TLabel", font=("Microsoft JhengHei UI", 15, "bold"), foreground=c["header_text"], background=c["header_bg"])
        style.configure("Subtitle.TLabel", font=("Microsoft JhengHei UI", 9), foreground=c["header_sub"], background=c["header_bg"])
        style.configure("Status.TLabel", font=("Microsoft JhengHei UI", 9), foreground=c["secondary"], background=c["background"])

        # 按鈕系統
        style.configure("TButton",
            font=("Microsoft JhengHei UI", 9),
            background=c["surface"],
            foreground=c["text"],
            borderwidth=1,
            bordercolor=c["border_strong"],
            lightcolor=c["surface"],
            darkcolor=c["surface_subtle"],
            focuscolor=c["action"],
            padding=(10, 5)
        )
        style.map("TButton",
            background=[("disabled", c["background"]), ("pressed", c["border"]), ("active", c["surface_subtle"])],
            foreground=[("disabled", c["muted"]), ("pressed", c["text"]), ("active", c["action"])],
            bordercolor=[("disabled", c["border"]), ("active", c["action"])]
        )

        style.configure("Primary.TButton",
            font=("Microsoft JhengHei UI", 9, "bold"),
            background="#1d4ed8",
            foreground="#ffffff",
            borderwidth=1,
            bordercolor="#1e40af",
            lightcolor="#2563eb",
            darkcolor="#1d4ed8",
            focuscolor="#1d4ed8",
            padding=(14, 6)
        )
        style.map("Primary.TButton",
            background=[("disabled", c["border"]), ("pressed", "#1e3a8a"), ("active", "#2563eb")],
            foreground=[("disabled", c["muted"]), ("pressed", "#ffffff"), ("active", "#ffffff")],
            bordercolor=[("disabled", c["border"]), ("active", "#1e3a8a")]
        )

        style.configure("Toolbar.TButton",
            font=("Microsoft JhengHei UI", 9),
            background=c["surface"],
            foreground=c["text"],
            borderwidth=1,
            bordercolor=c["border"],
            lightcolor=c["surface"],
            darkcolor=c["surface_subtle"],
            focuscolor=c["action"],
            padding=(9, 5)
        )
        style.map("Toolbar.TButton",
            background=[("disabled", c["surface_subtle"]), ("pressed", c["border"]), ("active", c["surface_subtle"])],
            foreground=[("disabled", c["muted"]), ("pressed", c["text"]), ("active", c["action"])],
            bordercolor=[("disabled", c["border"]), ("active", c["action"])]
        )

        # 歷史選單 Combobox
        style.configure("TCombobox",
            background=c["surface"],
            fieldbackground=c["surface"],
            foreground=c["text"],
            darkcolor=c["border"],
            lightcolor=c["surface"],
            bordercolor=c["border_strong"],
            arrowcolor=c["secondary"],
            arrowsize=13,
            padding=(8, 4)
        )
        style.map("TCombobox",
            fieldbackground=[("readonly", c["surface"]), ("disabled", c["background"])],
            foreground=[("readonly", c["text"]), ("disabled", c["muted"])],
            selectbackground=[("readonly", c["surface"])],
            selectforeground=[("readonly", c["text"])],
            bordercolor=[("focus", c["action"]), ("active", c["secondary"])]
        )
        self.root.option_add("*TCombobox*Listbox.background", c["surface"])
        self.root.option_add("*TCombobox*Listbox.foreground", c["text"])
        self.root.option_add("*TCombobox*Listbox.selectBackground", c["action_subtle"])
        self.root.option_add("*TCombobox*Listbox.selectForeground", c["action"])
        self.root.option_add("*TCombobox*Listbox.font", ("Cascadia Mono", 9))

        # 核取方塊
        style.configure("TCheckbutton",
            background=c["background"],
            foreground=c["text"],
            font=("Microsoft JhengHei UI", 9),
            indicatorbackground=c["surface"],
            indicatorcolor=c["action"],
            focusthickness=0
        )
        style.map("TCheckbutton",
            background=[("active", c["background"])],
            indicatorbackground=[("active", c["surface_subtle"])]
        )

        # 證據詳情面板
        style.configure("Evidence.TLabelframe",
            background=c["surface"],
            bordercolor=c["border_strong"],
            lightcolor=c["surface"],
            darkcolor=c["border"],
            borderwidth=1,
            padding=10
        )
        style.configure("Evidence.TLabelframe.Label",
            font=("Microsoft JhengHei UI", 10, "bold"),
            foreground=c["text"],
            background=c["surface"]
        )

        # 分頁籤 Notebook
        style.configure("TNotebook", background=c["background"], borderwidth=0, tabmargins=(4, 6, 2, 0))
        style.configure("TNotebook.Tab",
            background=c["border"],
            foreground=c["secondary"],
            padding=(20, 8),
            font=("Microsoft JhengHei UI", 9, "bold"),
            borderwidth=1,
            bordercolor=c["border_strong"],
            lightcolor=c["surface_subtle"],
            darkcolor=c["border"]
        )
        style.map("TNotebook.Tab",
            background=[("selected", c["surface"]), ("active", c["surface_subtle"])],
            foreground=[("selected", c["action"]), ("active", c["text"])],
            bordercolor=[("selected", c["border_strong"])]
        )

        # 捲軸與進度條
        style.configure("TScrollbar",
            background=c["surface_subtle"],
            troughcolor=c["background"],
            bordercolor=c["border"],
            arrowcolor=c["secondary"],
            borderwidth=0
        )
        style.configure("TProgressbar",
            background=c["action"],
            troughcolor=c["border"],
            borderwidth=0
        )
        style.configure("TPanedwindow", background=c["background"])
        style.configure("Sash", background=c["border"], bordercolor=c["border_strong"], sashthickness=5)

    def _build(self) -> None:
        c = self.COLORS

        # =========================================================================
        # 1. 頂部深色旗艦導航列 (Executive Header Bar) - 橫跨視窗全寬
        # =========================================================================
        self.header_bar = tk.Frame(self, bg=c["header_bg"], padx=20, pady=11)
        self.header_bar.grid(row=0, column=0, sticky="ew")
        self.header_bar.columnconfigure(0, weight=1)

        header_left = tk.Frame(self.header_bar, bg=c["header_bg"])
        header_left.grid(row=0, column=0, sticky="w")

        title_box = tk.Frame(header_left, bg=c["header_bg"])
        title_box.pack(side="top", anchor="w")

        self.header_icon_lbl = tk.Label(
            title_box, text="⛓️", font=("Segoe UI Emoji", 14),
            bg=c["header_bg"], fg=c["header_text"]
        )
        self.header_icon_lbl.pack(side="left", padx=(0, 8))

        self.header_title_lbl = tk.Label(
            title_box, text=f"{PRODUCT_NAME_ZH}  {PRODUCT_NAME_EN}  v{__version__}", font=("Microsoft JhengHei UI", 15, "bold"),
            bg=c["header_bg"], fg=c["header_text"]
        )
        self.header_title_lbl.pack(side="left")

        self.header_sub_lbl = tk.Label(
            header_left,
            text=f"{PRODUCT_SUBTITLE}・交易所標籤、地址與資金流不等於自然人身分或帳戶控制權",
            font=("Microsoft JhengHei UI", 9),
            bg=c["header_bg"], fg=c["header_sub"]
        )
        self.header_sub_lbl.pack(side="top", anchor="w", pady=(2, 0))

        header_right = tk.Frame(self.header_bar, bg=c["header_bg"])
        header_right.grid(row=0, column=1, sticky="e")

        self.header_badge = tk.Label(
            header_right,
            text="● 公開鏈上查核",
            font=("Microsoft JhengHei UI", 9, "bold"),
            bg=c["header_badge_bg"],
            fg=c["header_badge_text"],
            padx=10, pady=4,
            relief="solid", bd=1,
            highlightthickness=0
        )
        self.header_badge.pack(side="left", padx=(0, 10))

        self.theme_btn = tk.Button(
            header_right,
            text="🌙 深色模式",
            font=("Microsoft JhengHei UI", 9),
            bg=c["header_badge_bg"],
            fg=c["header_text"],
            activebackground=c["action"],
            activeforeground="#ffffff",
            relief="flat",
            bd=1,
            padx=8, pady=3,
            cursor="hand2",
            command=self._toggle_theme
        )
        self.theme_btn.pack(side="left")

        # =========================================================================
        # 2. 三欄工作台：左側查詢、中間流程、右側證據（Inspector）
        # =========================================================================
        self.main_content = ttk.Frame(self, padding=(16, 12, 16, 12), style="App.TFrame")
        self.main_content.grid(row=1, column=0, sticky="nsew")
        self.main_content.columnconfigure(0, weight=1)
        self.main_content.rowconfigure(0, weight=1)

        self.workspace_panes = ttk.Panedwindow(self.main_content, orient="horizontal")
        self.workspace_panes.grid(row=0, column=0, sticky="nsew")
        self.left_workspace = None
        self.left_panes = None

        # 左欄：查詢目標
        self.query_card = tk.Frame(
            self.workspace_panes,
            bg=c["surface"],
            highlightthickness=1,
            highlightbackground=c["border_strong"],
            padx=12, pady=10
        )
        self.query_card.columnconfigure(0, weight=1)

        card_header = tk.Frame(self.query_card, bg=c["surface"])
        card_header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        card_header.columnconfigure(0, weight=1)

        self.card_h2_lbl = tk.Label(
            card_header,
            text="查詢目標",
            font=("Microsoft JhengHei UI", 12, "bold"),
            bg=c["surface"],
            fg=c["text_h2"]
        )
        self.card_h2_lbl.pack(side="left")

        self.input_well = tk.Frame(
            self.query_card,
            bg=c["well_bg"],
            highlightthickness=0,
            padx=10, pady=8
        )
        self.input_well.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        self.input_well.columnconfigure(0, weight=1)

        self.query_lbl = tk.Label(
            self.input_well,
            text="錢包地址或 Tx Hash",
            bg=c["well_bg"],
            fg=c["text"],
            font=("Microsoft JhengHei UI", 10, "bold")
        )
        self.query_lbl.grid(row=0, column=0, sticky="w", pady=(0, 4))

        self.query_entry = tk.Entry(
            self.input_well,
            textvariable=self.query,
            font=("Cascadia Mono", 10),
            bg=c["surface"],
            fg=c["text"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=c["action"],
            highlightbackground=c["border_strong"],
        )
        self.query_entry.grid(row=1, column=0, sticky="ew", ipady=4)
        self.query_entry.bind("<Return>", lambda _event: self.start("polymarket"))

        self.query_options = tk.Frame(self.input_well, bg=c["well_bg"])
        self.query_options.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.hops_lbl = tk.Label(
            self.query_options,
            text="追蹤跳數：",
            bg=c["well_bg"],
            fg=c["secondary"],
            font=("Microsoft JhengHei UI", 9)
        )
        self.hops_lbl.pack(side="left")
        self.hops_spinbox = ttk.Spinbox(self.query_options, from_=1, to=5, textvariable=self.hops, width=4)
        self.hops_spinbox.pack(side="left", padx=(4, 0))
        self.advanced_toggle_btn = ttk.Button(
            self.query_options, text="資料範圍（選填） ▸", style="Toolbar.TButton", command=self._toggle_advanced
        )
        self.advanced_toggle_btn.pack(side="right")

        # 預設收合的資料範圍，避免首畫面被低頻條件占滿。
        self.advanced_frame = tk.Frame(self.input_well, bg=c["well_bg"])
        self.advanced_frame.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.advanced_frame.columnconfigure(0, weight=1)

        self.history_frame = tk.Frame(self.advanced_frame, bg=c["well_bg"])
        self.history_frame.grid(row=0, column=0, sticky="ew")
        self.history_frame.columnconfigure(0, weight=1)

        self.history_lbl = tk.Label(
            self.history_frame,
            text="本機查詢紀錄：",
            bg=c["well_bg"],
            fg=c["secondary"],
            font=("Microsoft JhengHei UI", 9)
        )
        self.history_lbl.grid(row=0, column=0, sticky="w")

        self.history_combobox = ttk.Combobox(self.history_frame, state="readonly", font=("Cascadia Mono", 9))
        self.history_combobox.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.history_combobox.bind("<<ComboboxSelected>>", self._on_history_selected)

        self.clear_history_btn = ttk.Button(self.history_frame, text="刪除紀錄…", style="Toolbar.TButton", command=self._confirm_clear_history)
        self.clear_history_btn.grid(row=0, column=1, sticky="e")

        self.time_frame = tk.Frame(self.advanced_frame, bg=c["well_bg"])
        self.time_frame.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.time_frame.columnconfigure(0, weight=1)

        self.time_lbl = tk.Label(
            self.time_frame,
            text="查詢截止時間（臺灣時間 UTC+8）：",
            bg=c["well_bg"],
            fg=c["secondary"],
            font=("Microsoft JhengHei UI", 9)
        )
        self.time_lbl.grid(row=0, column=0, sticky="w")

        self.time_entry = tk.Entry(
            self.time_frame,
            textvariable=self.time_filter_var,
            font=("Cascadia Mono", 10),
            bg=c["surface"],
            fg=c["text"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=c["action"],
            highlightbackground=c["border_strong"],
        )
        self.time_entry.grid(row=1, column=0, sticky="ew", ipady=2, pady=(4, 0))

        self.time_hint_lbl = tk.Label(
            self.time_frame,
            text="臺灣時間 YYYY-MM-DD 或 YYYY-MM-DD HH:MM",
            bg=c["well_bg"],
            fg=c["muted"],
            font=("Microsoft JhengHei UI", 9)
        )
        self.time_hint_lbl.grid(row=2, column=0, sticky="w", pady=(2, 0))

        self.csv_lbl = tk.Label(
            self.time_frame,
            text="PolygonScan CSV：",
            bg=c["well_bg"],
            fg=c["secondary"],
            font=("Microsoft JhengHei UI", 9)
        )
        self.csv_lbl.grid(row=3, column=0, sticky="w", pady=(8, 0))

        self.csv_entry = tk.Entry(
            self.time_frame,
            textvariable=self.csv_path_var,
            font=("Cascadia Mono", 9),
            bg=c["surface"],
            fg=c["text"],
            relief="solid",
            bd=1,
            highlightthickness=1,
            highlightcolor=c["action"],
            highlightbackground=c["border_strong"],
        )
        self.csv_entry.grid(row=4, column=0, sticky="ew", ipady=2, pady=(4, 0))

        self.csv_action_box = tk.Frame(self.time_frame, bg=c["well_bg"])
        self.csv_action_box.grid(row=5, column=0, sticky="ew", pady=(5, 0))

        self.select_csv_btn = ttk.Button(
            self.csv_action_box,
            text="選擇 CSV",
            style="Toolbar.TButton",
            command=self._select_csv_file
        )
        self.select_csv_btn.pack(side="left")

        self.csv_status_lbl = tk.Label(
            self.csv_action_box,
            text="（留空查最新）",
            bg=c["well_bg"],
            fg=c["muted"],
            font=("Microsoft JhengHei UI", 9),
            justify="left",
            wraplength=190,
        )
        self.csv_status_lbl.pack(side="left", padx=(6, 0))

        self.clear_csv_btn = ttk.Button(
            self.time_frame,
            text="清除條件",
            style="Toolbar.TButton",
            command=self._clear_conditions
        )
        self.clear_csv_btn.grid(row=6, column=0, sticky="e", pady=(6, 0))
        self.clear_time_btn = self.clear_csv_btn
        self.advanced_frame.grid_remove()

        self.actions_frame = tk.Frame(self.query_card, bg=c["surface"])
        self.actions_frame.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        self.actions_frame.columnconfigure(0, weight=1)
        self.actions_frame.columnconfigure(1, weight=1)

        self.polymarket_button = ttk.Button(self.actions_frame, text="追蹤 Polymarket 資金鏈", style="Primary.TButton", command=lambda: self.start("polymarket"))
        self.polymarket_button.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.analyze_button = ttk.Button(self.actions_frame, text="一般資金追蹤", style="Toolbar.TButton", command=lambda: self.start("general"))
        self.analyze_button.grid(row=1, column=0, sticky="ew", pady=(6, 0), padx=(0, 3))
        self.cancel_button = ttk.Button(self.actions_frame, text="停止查詢", style="Toolbar.TButton", command=self.cancel, state="disabled")
        self.cancel_button.grid(row=1, column=1, sticky="ew", pady=(6, 0), padx=(3, 0))

        self.utility_row = tk.Frame(self.query_card, bg=c["surface"])
        self.utility_row.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        self.settings_button = ttk.Button(self.utility_row, text="設定", style="Toolbar.TButton", command=self.open_settings)
        self.settings_button.pack(side="left")
        self.export_menu_button = ttk.Menubutton(self.utility_row, text="匯出 ▾", style="Toolbar.TButton", state="disabled")
        export_menu = tk.Menu(self.export_menu_button, tearoff=False)
        export_menu.add_command(label="證據包 ZIP", command=lambda: self.export("evidence"))
        export_menu.add_separator()
        export_menu.add_command(label="文字報告", command=lambda: self.export("text"))
        export_menu.add_command(label="CSV", command=lambda: self.export("csv"))
        export_menu.add_command(label="SVG 流程圖", command=lambda: self.export("svg"))
        self.export_menu_button.configure(menu=export_menu)
        self.export_menu_button.pack(side="right")
        # 保留既有屬性名稱，避免外部測試或擴充程式失效。
        self.export_text_button = self.export_menu_button
        self.export_csv_button = self.export_menu_button
        self.export_svg_button = self.export_menu_button
        self.export_evidence_button = self.export_menu_button

        # 中欄：資金流程圖與文字明細
        self.notebook = ttk.Notebook(self.workspace_panes)
        self.graph_tab = ttk.Frame(self.notebook, padding=8, style="TFrame")
        self.text_tab = ttk.Frame(self.notebook, padding=8, style="TFrame")
        self.notebook.add(self.graph_tab, text="資金流程圖")
        self.notebook.add(self.text_tab, text="文字明細")
        self._build_graph_tab()
        self._build_text_tab()

        # 右欄：證據詳情（Inspector 檢視面板）
        self.detail_frame = tk.Frame(
            self.workspace_panes, bg=c["surface"], highlightthickness=1, highlightbackground=c["border_strong"]
        )
        self._build_detail_panel()

        # 水平三欄配置：左欄查詢目標、中欄流程圖/明細、右欄全高證據詳情
        self.workspace_panes.add(self.query_card, weight=2)
        self.workspace_panes.add(self.notebook, weight=5)
        self.workspace_panes.add(self.detail_frame, weight=3)
        self._init_panes_sash()

        status_area = ttk.Frame(self.main_content, style="TFrame")
        status_area.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        status_area.columnconfigure(0, weight=1)
        self.status_lbl = ttk.Label(status_area, textvariable=self.status, style="Status.TLabel")
        self.status_lbl.grid(row=0, column=0, sticky="w")
        self.progress_caption_lbl = ttk.Label(status_area, textvariable=self.progress_caption, style="Status.TLabel")
        self.progress_caption_lbl.grid(row=0, column=1, sticky="e", padx=(8, 8))
        self.progress = ttk.Progressbar(status_area, mode="determinate", variable=self.progress_value, maximum=100, length=180)
        self.progress.grid(row=0, column=2, sticky="e")

    def _toggle_theme(self) -> None:
        self.theme_name = "dark" if self.theme_name == "light" else "light"
        self.COLORS = dict(self.THEMES[self.theme_name])
        c = self.COLORS
        self._configure_style()
        self.root.configure(background=c["background"])

        # 更新 Header Bar
        self.header_bar.configure(bg=c["header_bg"])
        self.header_icon_lbl.configure(bg=c["header_bg"], fg=c["header_text"])
        self.header_title_lbl.configure(bg=c["header_bg"], fg=c["header_text"])
        self.header_sub_lbl.configure(bg=c["header_bg"], fg=c["header_sub"])
        self.header_badge.configure(bg=c["header_badge_bg"], fg=c["header_badge_text"])
        self.theme_btn.configure(
            text="☀️ 淺色模式" if self.theme_name == "dark" else "🌙 深色模式",
            bg=c["header_badge_bg"], fg=c["header_text"]
        )

        # 更新 Query Card 與內部 Well
        self.query_card.configure(bg=c["surface"], highlightbackground=c["border_strong"])
        self.card_h2_lbl.configure(bg=c["surface"], fg=c["text_h2"])
        self.input_well.configure(bg=c["well_bg"], highlightbackground=c["border"])
        self.query_options.configure(bg=c["well_bg"])
        self.advanced_frame.configure(bg=c["well_bg"])
        self.query_lbl.configure(bg=c["well_bg"], fg=c["text"])
        self.query_entry.configure(bg=c["surface"], fg=c["text"], highlightcolor=c["action"], highlightbackground=c["border_strong"])
        self.hops_lbl.configure(bg=c["well_bg"], fg=c["secondary"])
        self.history_frame.configure(bg=c["well_bg"])
        self.history_lbl.configure(bg=c["well_bg"], fg=c["secondary"])
        if hasattr(self, "time_frame"):
            self.time_frame.configure(bg=c["well_bg"])
            self.time_lbl.configure(bg=c["well_bg"], fg=c["secondary"])
            self.time_entry.configure(bg=c["surface"], fg=c["text"], highlightcolor=c["action"], highlightbackground=c["border_strong"])
            self.time_hint_lbl.configure(bg=c["well_bg"], fg=c["muted"])
            if hasattr(self, "csv_lbl"):
                self.csv_lbl.configure(bg=c["well_bg"], fg=c["secondary"])
                self.csv_entry.configure(bg=c["surface"], fg=c["text"], highlightcolor=c["action"], highlightbackground=c["border_strong"])
                self.csv_action_box.configure(bg=c["well_bg"])
                self._on_csv_path_changed()
        self.actions_frame.configure(bg=c["surface"])
        self.utility_row.configure(bg=c["surface"])

        # 更新 Toolbar 與 Detail 面板
        if hasattr(self, "toolbar_container"):
            self.toolbar_container.configure(bg=c["well_bg"], highlightbackground=c["border"])
            self.toolbar_lbl.configure(bg=c["well_bg"], fg=c["text_h2"])
            self.toolbar_hint_lbl.configure(bg=c["well_bg"], fg=c["secondary"])
        if hasattr(self, "detail_frame"):
            self.detail_frame.configure(bg=c["surface"], highlightbackground=c["border_strong"])
            self.detail_header_bar.configure(bg=c["well_bg"], highlightbackground=c["border"])
            self.detail_h2_lbl.configure(bg=c["well_bg"], fg=c["text_h2"])
            self.detail_badge_lbl.configure(bg=c["well_bg"], fg=c["muted"])
            self.detail_content.configure(bg=c["surface"])
            if hasattr(self, "detail_text_box"):
                self.detail_text_box.configure(bg=c["surface"])

        # 更新 Canvas 與 Text
        self.canvas.configure(background=c["canvas_bg"], highlightbackground=c["border_strong"])
        self.detail_text.configure(background=c["surface"], foreground=c["text"])
        self.output.configure(background=c["surface"], foreground=c["text"])

        # 更新文字標籤顏色
        self.detail_text.tag_configure("section", foreground=c["text_h2"])
        self.detail_text.tag_configure("label", foreground=c["secondary"])
        self.detail_text.tag_configure("value", foreground=c["text"])
        self.detail_text.tag_configure("value_highlight", foreground=c["success"])
        self.detail_text.tag_configure("mono", foreground=c["text"])
        self.detail_text.tag_configure("trade", foreground=c["polymarket_border"])
        self.detail_text.tag_configure("disclaimer", foreground=c["muted"])

        if self.graph:
            self.render_graph()
        else:
            self._render_empty_state()

        if self.selected_edge:
            self._select_edge(self.selected_edge, focus_canvas=False)

    def _build_graph_tab(self) -> None:
        c = self.COLORS
        self.graph_tab.rowconfigure(1, weight=1)
        self.graph_tab.columnconfigure(0, weight=1)

        # 獨立工具槽框 (Toolbar Well Layer 2)
        self.toolbar_container = tk.Frame(
            self.graph_tab,
            bg=c["well_bg"],
            highlightthickness=1,
            highlightbackground=c["border"],
            padx=10, pady=6
        )
        self.toolbar_container.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self.toolbar_lbl = tk.Label(
            self.toolbar_container,
            text="顯示篩選：",
            font=("Microsoft JhengHei UI", 10, "bold"),
            bg=c["well_bg"],
            fg=c["text_h2"]
        )
        self.toolbar_lbl.pack(side="left")

        for text, variable in (
            ("入金主線", self.show_inbound),
            ("出金", self.show_outbound),
            ("平台內部", self.show_internal),
            ("資金池關聯", self.show_pool_inflow),
            ("原生幣供資", self.show_gas_funding),
        ):
            ttk.Checkbutton(self.toolbar_container, text=text, variable=variable, command=self.render_graph).pack(side="left", padx=(3, 6))
        ttk.Separator(self.toolbar_container, orient="vertical").pack(side="left", fill="y", padx=8)
        ttk.Button(self.toolbar_container, text="縮小", style="Toolbar.TButton", command=lambda: self._change_zoom(-0.1)).pack(side="left")
        ttk.Button(self.toolbar_container, text="100%", style="Toolbar.TButton", command=self._reset_zoom).pack(side="left", padx=4)
        ttk.Button(self.toolbar_container, text="放大", style="Toolbar.TButton", command=lambda: self._change_zoom(0.1)).pack(side="left")
        ttk.Button(self.toolbar_container, text="回到目標", style="Toolbar.TButton", command=self._scroll_target).pack(side="left", padx=(12, 0))

        self.toolbar_hint_lbl = tk.Label(
            self.toolbar_container,
            text="段內依時間排序｜線型僅區分事件；證據強度請看詳情",
            font=("Microsoft JhengHei UI", 9),
            bg=c["well_bg"],
            fg=c["secondary"]
        )
        self.toolbar_hint_lbl.pack(side="right")

        canvas_frame = ttk.Frame(self.graph_tab)
        canvas_frame.grid(row=1, column=0, sticky="nsew")

        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(
            canvas_frame,
            background=self.COLORS["canvas_bg"],
            highlightthickness=1,
            highlightbackground=self.COLORS["border_strong"],
            takefocus=True,
        )
        x_scroll = ttk.Scrollbar(canvas_frame, orient="horizontal", command=self.canvas.xview)
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")
        self.canvas.bind("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind("<Shift-MouseWheel>", self._on_shift_mousewheel)
        self.canvas.bind("<Control-MouseWheel>", self._on_ctrl_mousewheel)
        self.canvas.bind("<FocusIn>", lambda _event: self.canvas.configure(highlightbackground=self.COLORS["action"], highlightthickness=2))
        self.canvas.bind("<FocusOut>", lambda _event: self.canvas.configure(highlightbackground=self.COLORS["border_strong"], highlightthickness=1))
        self.canvas.bind("<Up>", self._on_key_up)
        self.canvas.bind("<Down>", self._on_key_down)
        self.canvas.bind("<Home>", self._on_key_home)
        self.canvas.bind("<End>", self._on_key_end)
        self.canvas.bind("<Return>", lambda _event: self._activate_selected())
        self.canvas.bind("<space>", lambda _event: self._activate_selected())
        self.canvas.bind("<Button-1>", lambda _event: self.canvas.focus_set())

    def _build_detail_panel(self) -> None:
        """建立右欄證據詳情（Inspector）；與中欄流程圖維持點選連動。"""
        c = self.COLORS
        self.detail_header_bar = tk.Frame(
            self.detail_frame,
            bg=c["well_bg"],
            padx=12, pady=7,
            highlightthickness=1,
            highlightbackground=c["border"]
        )
        self.detail_header_bar.pack(side="top", fill="x")

        self.detail_h2_lbl = tk.Label(
            self.detail_header_bar,
            text="證據詳情",
            font=("Microsoft JhengHei UI", 12, "bold"),
            bg=c["well_bg"],
            fg=c["text_h2"]
        )
        self.detail_h2_lbl.pack(side="left")

        self.detail_badge_lbl = tk.Label(
            self.detail_header_bar,
            text="點選流程圖即時連動",
            font=("Microsoft JhengHei UI", 9),
            bg=c["well_bg"],
            fg=c["muted"]
        )
        self.detail_badge_lbl.pack(side="right")

        self.detail_content = tk.Frame(self.detail_frame, bg=c["surface"], padx=8, pady=8)
        self.detail_content.pack(side="top", fill="both", expand=True)
        self.detail_content.rowconfigure(0, weight=1)
        self.detail_content.columnconfigure(0, weight=1)
        self.detail_content.columnconfigure(1, weight=1)

        self.detail_text_box = tk.Frame(self.detail_content, bg=c["surface"])
        self.detail_text_box.grid(row=0, column=0, columnspan=2, sticky="nsew")
        self.detail_text_box.rowconfigure(0, weight=1)
        self.detail_text_box.columnconfigure(0, weight=1)

        self.detail_text = tk.Text(
            self.detail_text_box,
            width=36,
            wrap="word",
            font=("Microsoft JhengHei UI", 10),
            relief="flat",
            background=self.COLORS["surface"],
            foreground=self.COLORS["text"],
            padx=12,
            pady=12,
            state="disabled",
        )
        self.detail_scroll = ttk.Scrollbar(self.detail_text_box, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=self.detail_scroll.set)
        self.detail_text.grid(row=0, column=0, sticky="nsew")
        self.detail_scroll.grid(row=0, column=1, sticky="ns")

        self.detail_text.tag_configure("section", font=("Microsoft JhengHei UI", 11, "bold"), foreground=self.COLORS["text_h2"], spacing1=12, spacing3=4)
        self.detail_text.tag_configure("label", font=("Microsoft JhengHei UI", 9), foreground=self.COLORS["secondary"])
        self.detail_text.tag_configure("value", font=("Microsoft JhengHei UI", 10, "bold"), foreground=self.COLORS["text"])
        self.detail_text.tag_configure("value_highlight", font=("Microsoft JhengHei UI", 10, "bold"), foreground=self.COLORS["success"])
        self.detail_text.tag_configure("mono", font=("Cascadia Mono", 9), foreground=self.COLORS["text"])
        self.detail_text.tag_configure("trade", font=("Microsoft JhengHei UI", 10, "bold"), foreground=self.COLORS["polymarket_border"])
        self.detail_text.tag_configure("disclaimer", font=("Microsoft JhengHei UI", 9), foreground=self.COLORS["muted"])

        self.copy_button = ttk.Button(self.detail_content, text="複製 Tx Hash", style="Toolbar.TButton", command=self.copy_selected_tx, state="disabled")
        self.copy_button.grid(row=1, column=0, sticky="ew", pady=(8, 0), padx=(0, 4))
        self.explorer_button = ttk.Button(self.detail_content, text="開啟 Explorer", style="Toolbar.TButton", command=self.open_selected_explorer, state="disabled")
        self.explorer_button.grid(row=1, column=1, sticky="ew", pady=(8, 0), padx=(4, 0))
        self.copy_from_button = ttk.Button(self.detail_content, text="複製發送地址", style="Toolbar.TButton", command=self.copy_selected_from, state="disabled")
        self.copy_from_button.grid(row=2, column=0, sticky="ew", pady=(6, 0), padx=(0, 4))
        self.copy_to_button = ttk.Button(self.detail_content, text="複製收款地址", style="Toolbar.TButton", command=self.copy_selected_to, state="disabled")
        self.copy_to_button.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(4, 0))
        self.resolve_button = ttk.Button(self.detail_content, text="讀取選取地址合約結構（Polygon）", style="Toolbar.TButton", command=self.resolve_selected, state="disabled")
        self.resolve_button.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.technical_details_button = ttk.Button(
            self.detail_content,
            text="顯示技術細節 ▸",
            style="Toolbar.TButton",
            command=self._toggle_technical_details,
            state="disabled",
        )
        self.technical_details_button.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    def _build_text_tab(self) -> None:
        self.text_tab.rowconfigure(0, weight=1)
        self.text_tab.columnconfigure(0, weight=1)
        self.output = tk.Text(self.text_tab, wrap="word", font=("Microsoft JhengHei UI", 10), padx=10, pady=10)
        scrollbar = ttk.Scrollbar(self.text_tab, orient="vertical", command=self.output.yview)
        self.output.configure(yscrollcommand=scrollbar.set)
        self.output.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

    def _toggle_advanced(self) -> None:
        visible = not self.advanced_visible.get()
        self.advanced_visible.set(visible)
        if visible:
            self.advanced_frame.grid()
            self.advanced_toggle_btn.configure(text="資料範圍（選填） ▾")
        else:
            self.advanced_frame.grid_remove()
            self.advanced_toggle_btn.configure(text="資料範圍（選填） ▸")
        self._init_panes_sash()

    def _clear_conditions(self) -> None:
        """清除非破壞性的查詢條件，保留地址、結果與本機紀錄。"""
        self.time_filter_var.set("")
        self.csv_path_var.set("")
        self.hops.set(self.settings.max_hops)
        self.status.set("已清除日期、CSV 與追蹤跳數條件；查詢地址及目前結果均已保留。")

    def _show_csv_metadata(self, path: str, info: dict) -> None:
        current = self.csv_path_var.get().strip().strip('"').strip("'")
        if current != path or not hasattr(self, "csv_status_lbl"):
            return
        time_range = str(info.get("time_range") or "未取得").replace(" 至 ", "～")
        self.csv_status_lbl.configure(
            text=f"已載入 {info.get('total_rows', 0)} 筆｜{time_range}",
            fg=self.COLORS["success"],
        )

    def _inspect_csv_metadata(self, path: str) -> None:
        target = self.query.get().strip()

        def worker() -> None:
            try:
                info = inspect_and_load_polygonscan_csv(path, target, max_candidates=1)
            except Exception:
                return
            self.root.after(0, lambda: self._show_csv_metadata(path, info))

        threading.Thread(target=worker, daemon=True).start()

    def _on_csv_path_changed(self, *_args) -> None:
        if not hasattr(self, "csv_status_lbl"):
            return
        raw = self.csv_path_var.get().strip().strip('"').strip("'")
        if not raw:
            self.csv_status_lbl.configure(text="（留空查最新）", fg=self.COLORS["muted"])
            return
        if os.path.isfile(raw):
            size_kb = os.path.getsize(raw) / 1024
            self.csv_status_lbl.configure(text=f"✓ 有效（{size_kb:.0f} KB）", fg=self.COLORS["success"])
            if self._csv_inspect_after:
                self.root.after_cancel(self._csv_inspect_after)
            self._csv_inspect_after = self.root.after(350, lambda path=raw: self._inspect_csv_metadata(path))
        else:
            self.csv_status_lbl.configure(text="⚠️ 檔案不存在", fg=self.COLORS["error"])

    def _select_csv_file(self) -> None:
        from tkinter import filedialog
        initial_dir = os.path.join(os.path.expanduser("~"), "Downloads")
        if not os.path.isdir(initial_dir):
            initial_dir = None
        path = filedialog.askopenfilename(
            parent=self.root,
            initialdir=initial_dir,
            title="選擇 PolygonScan Token Transfers CSV 檔案",
            filetypes=[("CSV 檔案", "*.csv"), ("所有檔案", "*.*")]
        )
        if path:
            clean_path = path.strip().strip('"').strip("'")
            self.csv_path_var.set(clean_path)
            self.status.set(f"已選取 PolygonScan CSV：{os.path.basename(clean_path)}。系統將先建立候選索引，再逐筆向鏈上核實。")

    def _clear_csv_file(self) -> None:
        self.csv_path_var.set("")
        self.status.set("已清除 PolygonScan CSV。")

    def start(self, mode: str) -> None:
        query = self.query.get().strip()
        if not query:
            self.status.set("請先輸入 Tx Hash 或錢包地址。")
            self.query_entry.focus_set()
            return
        time_raw = self.time_filter_var.get().strip()
        time_cutoff = None
        if time_raw:
            try:
                from .providers import parse_time_anchor
                time_cutoff = parse_time_anchor(time_raw, is_end_time=True)
            except ValueError as exc:
                messagebox.showwarning("時間格式提示", str(exc))
                return

        csv_path = self.csv_path_var.get().strip().strip('"').strip("'")
        if csv_path and not os.path.isfile(csv_path):
            messagebox.showerror("檔案不存在", f"找不到指定的 PolygonScan CSV：\n{csv_path}\n\n請確認路徑，或使用「清除條件」。")
            return

        self.cancel_event.clear()
        self.query_started_at = time.monotonic()
        self._set_running(True)
        if csv_path and mode != "polymarket":
            self.status.set("提示：歷史 CSV 索引僅適用 Polymarket 資金鏈；一般地址分析將查詢最新原生幣紀錄…")
        elif csv_path and mode == "polymarket":
            self.status.set(f"正在載入歷史 CSV 索引「{os.path.basename(csv_path)}」並由鏈上核實…")
        elif time_raw and mode == "polymarket":
            self.status.set(f"正在鎖定歷史時間「{time_raw}」並連線公開資料源…")
        elif time_raw and mode != "polymarket":
            self.status.set("時間錨定僅適用 Polymarket 資金鏈；一般地址分析將查詢最新紀錄…")
        else:
            self.status.set("正在連線公開資料源…目前結果會保留到新查詢成功完成。")
        self.progress.configure(mode="indeterminate")
        self.progress_value.set(0)
        self.progress.start(12)
        self.progress_caption.set("準備查詢")
        threading.Thread(target=self._analyze, args=(mode, query, self.hops.get(), time_cutoff, time_raw, csv_path), daemon=True).start()

    def cancel(self) -> None:
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self.status.set("正在安全停止；目前網路請求完成後即中止。")
        self.progress_caption.set("正在停止")

    def _set_running(self, running: bool) -> None:
        self.running = running
        state = "disabled" if running else "normal"
        self.analyze_button.configure(state=state)
        self.polymarket_button.configure(state=state)
        self.cancel_button.configure(state="normal" if running else "disabled")
        if hasattr(self, "select_csv_btn"):
            self.select_csv_btn.configure(state=state)
        if hasattr(self, "clear_csv_btn"):
            self.clear_csv_btn.configure(state=state)
        if hasattr(self, "clear_history_btn"):
            self.clear_history_btn.configure(state=state if self.history_entries else "disabled")
        if hasattr(self, "history_combobox"):
            self.history_combobox.configure(state="disabled" if running else "readonly")
        if hasattr(self, "clear_time_btn"):
            self.clear_time_btn.configure(state=state)
        if hasattr(self, "advanced_toggle_btn"):
            self.advanced_toggle_btn.configure(state=state)
        self.resolve_button.configure(state="normal" if not running and not self.resolving and self.selected_edge and self._infer_chain(self.selected_edge.step) == "Polygon" else "disabled")
        if not running:
            self.progress.stop()

    def _progress_status(self, message: str) -> None:
        if self.cancel_event.is_set():
            raise AnalysisCancelled("查詢已由使用者停止。")
        self.root.after(0, lambda value=message: self._apply_progress_status(value))

    def _apply_progress_status(self, message: str) -> None:
        """把既有後端進度訊息轉成不誤導的階段進度。"""
        self.status.set(message)
        match = re.search(r"第\s*(\d+)\s*/\s*(\d+)", message)
        current = int(match.group(1)) if match else 0
        total = int(match.group(2)) if match else 0

        if "CSV" in message:
            stage, base, span = "讀取 CSV", 6, 6
        elif "Receipt" in message or "底層 USDC" in message:
            stage, base, span = "核實底層資產", 25, 30
        elif "Relay" in message:
            stage, base, span = "追蹤 Relay", 58, 25
        elif "上游" in message or "來源錢包" in message:
            stage, base, span = "追蹤來源鏈上游", 84, 12
        elif "下注" in message or "pUSD" in message:
            stage, base, span = "解析 Polymarket 紀錄", 12, 12
        else:
            stage, base, span = "讀取公開鏈上資料", 8, 8

        if total > 0:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            ratio = min(1.0, max(0.0, current / total))
            self.progress_caption.set(f"{stage} {current}/{total}")
            self.progress_value.set(max(self.progress_value.get(), base + span * ratio))
        else:
            self.progress_caption.set(stage)
            self.progress_value.set(max(self.progress_value.get(), base))

    def _analyze(self, mode: str, query: str, hops: int, as_of_time: float | None = None, time_raw: str = "", csv_path: str = "") -> None:
        try:
            self.settings.max_hops = hops
            save_settings(self.settings)
            analyzer = Analyzer(PolygonProvider(self.settings), progress=self._progress_status)
            if mode == "polymarket":
                result = analyzer.analyze_polymarket_funding(
                    query, hops, as_of_time=as_of_time, time_filter_raw=time_raw, csv_path=csv_path
                )
            else:
                result = analyzer.analyze(
                    query, hops, as_of_time=as_of_time, time_filter_raw=time_raw
                )
            if self.cancel_event.is_set():
                raise AnalysisCancelled("查詢已由使用者停止。")
            self.root.after(0, lambda: self.show(result, mode=mode))
        except AnalysisCancelled as exc:
            self.root.after(0, lambda message=str(exc): self._show_cancelled(message))
        except Exception as exc:
            error_message = str(exc)
            self.root.after(0, lambda message=error_message: self._show_error(message))
        finally:
            self.root.after(0, lambda: self._set_running(False))

    def _show_error(self, message: str) -> None:
        self.progress.stop()
        self.progress_caption.set("查詢失敗")
        self.status.set(f"查詢失敗：{message} 可檢查網路或設定後重試；上一次結果已保留。")
        messagebox.showerror("分析失敗", f"{message}\n\n請檢查網路、RPC／Explorer 設定後再試；上一次成功結果不會被清除。")

    def _show_cancelled(self, message: str) -> None:
        self.progress.stop()
        self.progress_caption.set("已停止")
        self.status.set(f"{message} 上一次成功結果仍保留在畫面中。")

    def show(self, result, mode: str = "polymarket", from_history: bool = False) -> None:
        self.result = result
        self.graph = build_flow_graph(result)
        self.export_text_button.configure(state="normal")
        self.export_csv_button.configure(state="normal")
        self.export_evidence_button.configure(state="normal")
        self.export_svg_button.configure(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress_value.set(100)
        self.progress_caption.set("分析完成")
        self._render_text(result)
        self.render_graph()
        warning_count = len(result.warnings)
        if not from_history:
            try:
                save_history_entry(result, mode=mode)
                self._refresh_history_combobox()
            except Exception:
                pass
            relay_paths = len({step.relay_request_id for step in result.steps if step.relay_request_id})
            exchange_labels = len({step.label for step in result.steps if step.classification == "交易所" and step.label})
            parts = ["分析完成"]
            if getattr(result, "csv_index", None) and result.csv_index.get("total_rows") is not None:
                parts.append(f"CSV {result.csv_index.get('total_rows')} 筆")
            parts.extend([
                f"關聯步驟 {len(result.steps)} 筆",
                f"Relay 路徑 {relay_paths} 條",
                f"交易所標籤 {exchange_labels} 個",
                f"注意事項 {warning_count} 項",
            ])
            if self.query_started_at is not None:
                parts.append(f"耗時 {time.monotonic() - self.query_started_at:.1f} 秒")
            self.status.set("｜".join(parts) + "。已儲存至本機查詢紀錄。")
        else:
            self.status.set(f"已還原歷史快照：{len(result.steps)} 筆關聯步驟、{warning_count} 項注意事項。")

    def _refresh_history_combobox(self) -> None:
        self.history_entries = list_history_entries()
        if not hasattr(self, "history_combobox"):
            return
        if not self.history_entries:
            self.history_combobox["values"] = ["（尚無本機歷史快照）"]
            self.history_combobox.current(0)
            self.history_combobox.configure(state="readonly")
            self.clear_history_btn.configure(state="disabled")
        else:
            options = ["選擇過往紀錄秒開快照…"] + [f"[{i+1}] {e.display_title}" for i, e in enumerate(self.history_entries)]
            self.history_combobox.configure(state="readonly")
            self.history_combobox["values"] = options
            self.history_combobox.current(0)
            self.clear_history_btn.configure(state="normal")

    def _on_history_selected(self, _event=None) -> None:
        idx = self.history_combobox.current()
        if not self.history_entries or idx <= 0 or idx - 1 >= len(self.history_entries):
            return
        entry = self.history_entries[idx - 1]
        self.status.set(f"正在載入本機快照：{entry.query}…")
        result = load_history_snapshot(entry.id)
        if not result:
            self.status.set(f"載入失敗：找不到快照檔 {entry.snapshot_file}。")
            messagebox.showwarning("快照失效", f"無法讀取本機快照檔案：{entry.snapshot_file}\n可能檔案已被移動或移除。")
            self._refresh_history_combobox()
            return
        self.query.set(entry.query)
        self.show(result, mode=entry.mode, from_history=True)
        self.status.set(f"已秒開本機歷史快照：{entry.query}（快照時間：{entry.timestamp}，{len(result.steps)} 步）。")

    def _confirm_clear_history(self) -> None:
        if not self.history_entries:
            return
        ans = messagebox.askyesno("清空歷史紀錄", "確定要清空所有本機偵查歷史快照嗎？\n此動作將刪除快照 JSON 檔案，無法復原。")
        if ans:
            clear_history()
            self._refresh_history_combobox()
            self.status.set("已清空所有本機歷史紀錄與快照檔案。")

    def _render_text(self, result) -> None:
        self.output.configure(state="normal")
        self.output.delete("1.0", "end")
        self.output.insert("end", "\n".join(result.summary) + "\n\n")
        self.output.insert("end", plain_summary(result.steps) + "\n\n")
        for item in result.transfers:
            self.output.insert("end", f"[Transfer] {item.token} {item.amount}\n{item.from_address} → {item.to_address}\n\n")
        self.output.insert("end", "關聯追蹤（僅呈現資金關聯）\n" + "=" * 42 + "\n")
        for item in result.steps:
            evidence = "｜".join(filter(None, [item.chain, f"區塊 {item.block_number}" if item.block_number else "", f"Log {item.log_index}" if item.log_index else ""]))
            self.output.insert("end", f"[{item.direction} 第 {item.hop} 跳] {item.classification} {item.label}\n{item.from_address} → {item.to_address}\nTx：{item.tx_hash}\n時間：{item.timestamp or '未取得'}｜Token／金額：{item.token}／{item.amount or '未取得'}\n信心：{item.confidence}｜判定：{item.relation}｜路徑：{item.path_role}\n證據：{evidence or '未取得'}｜標籤來源：{item.label_source}\n備註：{item.notes}\n\n")
            self.output.insert("end", explain_step(item).text() + "\n\n")
        self.output.insert("end", "注意事項\n" + "\n".join(f"- {item}" for item in result.warnings))
        if result.sources:
            self.output.insert("end", "\n\n資料來源\n" + "\n".join(f"- {item}" for item in result.sources))
        self.output.configure(state="disabled")

    def _render_empty_state(self) -> None:
        self.canvas.delete("all")
        c = self.COLORS
        cx, cy, cw, ch = 48, 40, 640, 190
        # 純白/主題卡片底色
        self.canvas.create_rectangle(cx, cy, cx + cw, cy + ch, fill=c["surface"], outline=c["border_strong"], width=1)
        # 科技藍色指示條 (5px)
        self.canvas.create_rectangle(cx, cy, cx + 5, cy + ch, fill=c["action"], outline="")
        self.canvas.create_text(cx + 28, cy + 24, anchor="nw", text="尚無資金流程圖", font=("Microsoft JhengHei UI", 16, "bold"), fill=c["text"])
        self.canvas.create_text(
            cx + 28, cy + 64, anchor="nw", width=cw - 56,
            text="請由左側「查詢目標」貼上 Polygon / EVM 交易雜湊（Tx Hash）或錢包地址，\n再選擇「追蹤 Polymarket 資金鏈」或「一般資金追蹤」。",
            font=("Microsoft JhengHei UI", 10), fill=c["secondary"]
        )
        # 底部提示小標
        self.canvas.create_rectangle(cx + 28, cy + 134, cx + cw - 28, cy + 168, fill=c["action_subtle"], outline=c["border"], width=1)
        self.canvas.create_text(
            cx + 40, cy + 142, anchor="nw",
            text="提示：完成分析後可點選任一步驟，在右側「證據詳情」核對該筆證據與限制。",
            font=("Microsoft JhengHei UI", 9), fill=c["action"]
        )
        self.canvas.configure(scrollregion=(0, 0, 800, 320))
        self._set_detail("點選流程圖中的箭頭後，這裡會顯示完整證據。")

    def render_graph(self) -> None:
        if not self.graph:
            self._render_empty_state()
            return
        lanes = []
        if self.show_inbound.get():
            lanes.append("入金")
        if self.show_internal.get():
            lanes.append("內部")
        if self.show_outbound.get():
            lanes.append("出金")
        edges = ordered_edges(self.graph, lanes)
        filtered_edges = []
        for edge in edges:
            if getattr(edge.step, "line_style", "") == "dashed" and not self.show_pool_inflow.get():
                continue
            if getattr(edge.step, "line_style", "") == "dotted" and not self.show_gas_funding.get():
                continue
            filtered_edges.append(edge)
        edges = filtered_edges
        self.current_edges = edges
        self.edge_boxes = {}
        self.canvas.delete("all")
        if not edges:
            self.selected_edge = None
            self.selected_edge_index = -1
            self.canvas.create_text(48, 60, anchor="nw", text="目前篩選條件下沒有可顯示的路徑。", font=("Microsoft JhengHei UI", 13, "bold"), fill=self.COLORS["secondary"])
            self.canvas.configure(scrollregion=(0, 0, 780, 300))
            return

        scale = self.zoom
        node_width, node_height = 340 * scale, 72 * scale
        node_x = 44 * scale
        timeline_x = node_x + node_width / 2
        evidence_x, evidence_width = 416 * scale, 316 * scale
        banner_width = 752 * scale
        y = 30 * scale

        # 現代案件情報摘要卡
        summary = build_case_summary(self.graph, self.result.query if self.result else "")
        banner_x = 24 * scale
        banner_w = banner_width
        main_tx_disp = self._short_tx(summary.main_tx) if summary.main_tx != "無" else "無"
        summary_lines = [
            "【案件情報摘要（段內由舊到新）】",
            f"路徑特徵：{' → '.join(summary.path_steps)}",
            f"上游 VASP 關聯 Tx：{main_tx_disp}",
            f"{plain_summary(self.result.steps)}",
            f"{summary.disclaimer}",
        ]
        banner_text = self.canvas.create_text(
            banner_x + 20 * scale, y + 14 * scale, anchor="nw", width=banner_w - 36 * scale,
            text="\n".join(summary_lines),
            font=("Microsoft JhengHei UI", max(9, int(10 * scale))), fill=self.COLORS["text"], tags="summary_text")
        banner_h = self.canvas.bbox(banner_text)[3] - y + 16 * scale
        banner_rect = self.canvas.create_rectangle(banner_x, y, banner_x + banner_w, y + banner_h, fill=self.COLORS["surface"], outline=self.COLORS["border_strong"], width=1, tags="summary_box")
        accent_bar = self.canvas.create_rectangle(banner_x, y, banner_x + 4 * scale, y + banner_h, fill=self.COLORS["action"], outline="", tags="summary_accent")
        self.canvas.tag_lower(banner_rect, banner_text)
        self.canvas.tag_raise(accent_bar, banner_rect)
        y += banner_h + 24 * scale

        current_lane = None
        current_chain = None
        drawn_addrs: set[tuple[str, str]] = set()
        last_target_id: tuple[str, str] | None = None
        last_target_bottom: float = 0.0

        for edge in edges:
            if edge.lane != current_lane:
                if current_lane is not None:
                    y += 30 * scale
                current_lane = edge.lane
                current_chain = None
                last_target_id = None

                # Polymarket 協定內部加上「（非外部來源）」並弱化
                if edge.lane == "內部":
                    lane_title = "Polymarket 協定內部（非外部來源）"
                    lane_color = self.COLORS["secondary"]
                elif edge.lane == "出金":
                    lane_title = "資金出金路徑"
                    lane_color = self.COLORS["text"]
                else:
                    lane_title = "外部入金主路徑"
                    lane_color = self.COLORS["text"]

                self.canvas.create_text(24 * scale, y, anchor="w", text=lane_title, font=("Microsoft JhengHei UI", max(10, int(14 * scale)), "bold"), fill=lane_color)
                self.canvas.create_line(24 * scale, y + 22 * scale, 24 * scale + banner_width, y + 22 * scale, fill=self.COLORS["border_strong"], width=1)
                y += 44 * scale

            if edge.chain != current_chain:
                current_chain = edge.chain
                last_target_id = None
                self.canvas.create_rectangle(44 * scale, y, 400 * scale, y + 32 * scale, fill=self.COLORS["surface_subtle"], outline=self.COLORS["border"])
                self.canvas.create_text(58 * scale, y + 16 * scale, anchor="w", text=current_chain, font=("Microsoft JhengHei UI", max(9, int(11 * scale)), "bold"), fill=self.COLORS["info"])
                y += 44 * scale

            source = self.graph.nodes[edge.source]
            target = self.graph.nodes[edge.target]

            src_id = (edge.chain, source.address.lower())
            tgt_id = (edge.chain, target.address.lower())

            # 同鏈 + 同地址 預設合併，重用上一個 Target 節點
            reuse_source = (last_target_id is not None and last_target_id == src_id)
            if reuse_source:
                arrow_top = last_target_bottom + 4 * scale
                step_top = arrow_top - 6 * scale
            else:
                step_top = y
                is_src_revisit = src_id in drawn_addrs
                self._draw_node(node_x, y, node_width, node_height, source, edge.key, is_revisit=is_src_revisit)
                drawn_addrs.add(src_id)
                arrow_top = y + node_height + 6 * scale

            event_lines = [
                f"{edge.token}  {edge.amount or '金額未取得'}",
                edge.timestamp or "時間未取得",
                f"Tx：{self._short_tx(edge.tx_hash)}" if edge.tx_hash else "Tx：未取得",
                f"[{explain_step(edge.step).badge}]",
            ]
            elapsed = bridge_elapsed(edge, edges) if edge.step.relay_leg == "destination" else ""
            if elapsed:
                event_lines.append(f"跨鏈時間戳差：{elapsed}")
            event_text = self.canvas.create_text(evidence_x + 12 * scale, arrow_top + 8 * scale, anchor="nw", width=evidence_width - 24 * scale, text="\n".join(event_lines), font=("Microsoft JhengHei UI", max(8, int(9.5 * scale))), fill=self.COLORS["text"], tags=(edge.key, "interactive"))
            arrow_bottom = max(arrow_top + 96 * scale, self.canvas.bbox(event_text)[3] + 12 * scale)
            dash = {"bridge": (8, 4), "internal": (2, 3), "unknown": (6, 5), "dashed": (6, 4), "dotted": (2, 3)}.get(edge.style)
            color = {"bridge": self.COLORS["info"], "internal": self.COLORS["secondary"], "unknown": "#7a8793", "dashed": "#d97706", "dotted": "#7c3aed"}.get(edge.style, self.COLORS["success"])
            self.canvas.create_line(timeline_x, arrow_top, timeline_x, arrow_bottom, width=max(2, int(3 * scale)), fill=color, arrow=tk.LAST, arrowshape=(12 * scale, 14 * scale, 5 * scale), dash=dash, tags=(edge.key, "interactive"))

            # 每條資金邊只保留 4 個核心欄位 (資產、金額、時間、Tx Hash)
            ev_rect = (evidence_x, arrow_top - 2 * scale, evidence_x + evidence_width, arrow_bottom - 2 * scale)
            ev_fill = self.COLORS["surface_subtle"] if edge.lane == "內部" else self.COLORS["surface"]
            card = self.canvas.create_rectangle(*ev_rect, fill=ev_fill, outline=self.COLORS["border_strong"], tags=(edge.key, "interactive", f"box_{edge.key}"))
            self.canvas.tag_lower(card, event_text)

            # Target 節點
            target_y = arrow_bottom + 6 * scale
            is_tgt_revisit = tgt_id in drawn_addrs
            self._draw_node(node_x, target_y, node_width, node_height, target, edge.key, is_revisit=is_tgt_revisit)
            drawn_addrs.add(tgt_id)

            step_bottom = target_y + node_height
            last_target_id = tgt_id
            last_target_bottom = step_bottom

            self.edge_boxes[edge.key] = (*ev_rect, step_top, step_bottom)
            self.canvas.tag_bind(edge.key, "<Button-1>", lambda _event, selected=edge: self._select_edge(selected, focus_canvas=True))
            self.canvas.tag_bind(edge.key, "<Enter>", lambda _event: self.canvas.configure(cursor="hand2"))
            self.canvas.tag_bind(edge.key, "<Leave>", lambda _event: self.canvas.configure(cursor=""))
            y = step_bottom + 26 * scale
        if self.graph.truncated:
            self.canvas.create_text(24 * scale, y, anchor="w", text="路徑數量過多，流程圖僅顯示前 80 筆；完整內容請查看文字或 CSV。", fill=self.COLORS["warning"], font=("Microsoft JhengHei UI", 10, "bold"))
            y += 36 * scale
        self.canvas.configure(scrollregion=(0, 0, 780 * scale, max(y + 36 * scale, 360)))
        if self.selected_edge and self.selected_edge in self.current_edges:
            self._select_edge(self.selected_edge, focus_canvas=False)
        elif self.current_edges and self.selected_edge_index >= 0:
            idx = min(self.selected_edge_index, len(self.current_edges) - 1)
            self._select_edge(self.current_edges[idx], focus_canvas=False)

    def _short_tx(self, value: str) -> str:
        return f"{value[:10]}…{value[-8:]}" if len(value) > 22 else value

    def _draw_node(self, x, y, width, height, node: FlowNode, tag: str, is_revisit: bool = False) -> None:
        fill, outline, border_w, badge_text, badge_color = self._node_style(node)
        scale = self.zoom
        self.canvas.create_rectangle(x, y, x + width, y + height, fill=fill, outline=outline, width=border_w, tags=(tag, "interactive"))

        # 右上角角色標籤徽章 (Pill Badge)
        pill_w = 64 * scale
        pill_h = 18 * scale
        pill_x = x + width - pill_w - 10 * scale
        pill_y = y + 10 * scale
        self.canvas.create_rectangle(pill_x, pill_y, pill_x + pill_w, pill_y + pill_h, fill=outline, outline="", tags=(tag, "interactive"))
        self.canvas.create_text(pill_x + pill_w / 2, pill_y + pill_h / 2, text=badge_text, font=("Segoe UI", max(8, int(8.5 * scale)), "bold"), fill="#ffffff", tags=(tag, "interactive"))

        role_title = node.role
        if is_revisit:
            role_title += "（同地址再次出現）"

        self.canvas.create_text(x + 12 * scale, y + 12 * scale, anchor="nw", width=width - pill_w - 28 * scale, text=role_title, font=("Microsoft JhengHei UI", max(9, int(10.5 * scale)), "bold"), fill=self.COLORS["text"], tags=(tag, "interactive"))
        self.canvas.create_text(x + 12 * scale, y + 42 * scale, anchor="nw", text=short_address(node.address), font=("Cascadia Mono", max(8, int(9.5 * scale))), fill=self.COLORS["secondary"], tags=(tag, "interactive"))

    def _node_style(self, node: FlowNode) -> tuple[str, str, int, str, str]:
        scale = self.zoom
        w = max(1, int(1.5 * scale))
        if node.is_target:
            return (self.COLORS["target"], self.COLORS["target_border"], max(2, int(2.5 * scale)), "TARGET", self.COLORS["target_border"])
        if node.lane == "內部":
            return (self.COLORS["surface_subtle"], self.COLORS["border_strong"], w, "INTERNAL", self.COLORS["muted"])
        if node.role == ROLE_EXCHANGE:
            return (self.COLORS["exchange"], self.COLORS["exchange_border"], max(2, int(2.5 * scale)), "VASP", self.COLORS["exchange_border"])
        if node.role in (ROLE_BRIDGE, ROLE_RELAY_SOLVER, ROLE_RELAY_SOURCE):
            return (self.COLORS["bridge"], self.COLORS["bridge_border"], w, "BRIDGE", self.COLORS["bridge_border"])
        if node.role == ROLE_DEX:
            return (self.COLORS["dex"], self.COLORS["dex_border"], w, "DEX", self.COLORS["dex_border"])
        return (self.COLORS["surface"], self.COLORS["border_strong"], w, "NODE", self.COLORS["secondary"])

    def _select_edge(self, edge: FlowEdge, focus_canvas: bool = True) -> None:
        self.selected_edge = edge
        if edge in self.current_edges:
            self.selected_edge_index = self.current_edges.index(edge)
        step = edge.step
        node = self.graph.nodes.get(edge.source if step.address.lower() == step.from_address.lower() else edge.target)
        explorer = step.explorer_url or self._explorer_url(step)

        chain = step.chain or self._infer_chain(step)
        role = node.role if node else "中間地址"
        role_conf = step.role_confidence or (node.role_confidence if node else "已確認")
        rel_conf = step.relation_confidence or (node.relation_confidence if node else "僅資金關聯")

        # 預設先呈現承辦人判讀所需內容；底層欄位依需要展開。
        details = [
            "【查核結論】",
            f"節點角色：{role}",
            f"鏈別：{chain}",
            f"資產：{step.token}",
            f"金額：{step.amount or '未取得'}",
            f"時間：{step.timestamp or '未取得'}",
            "",
            "【鏈上紀錄】",
            f"發送地址（Transfer From）：{step.from_address or '未取得'}",
            f"收款地址（Transfer To）：{step.to_address or '未取得'}",
            f"Tx Hash：{step.tx_hash or '未取得'}",
            "",
            explain_step(step).text(),
            "",
            "【公開標籤與信心】",
            f"公開標籤：{step.label or '無'}",
            f"標籤來源：{step.label_source or '無'}",
            f"地址角色信心：{role_conf}",
            f"資金關聯信心：{rel_conf}",
            f"判定：{step.relation or '僅證明鏈上資金關聯，實際帳戶持有人須依法向服務商調取確認。'}",
        ]

        if self.show_technical_details.get():
            details.extend([
                "",
                "【技術細節】",
                f"完整地址：{step.address}",
                f"區塊：{step.block_number or '未取得'}｜Log Index：{step.log_index or '未取得'}",
                f"Token 合約：{step.token_contract or '未取得'}",
                f"資料依據：{step.evidence_source or '舊紀錄未註記，需查核'}",
                f"Relay Request ID：{step.relay_request_id or '未取得'}",
                f"精確配對：{'是（協定索引）' if step.pair_verified else '未確認'}",
                f"Explorer 連結：{explorer or '未取得'}",
            ])

        # 第 9 點：DepositWallet 資訊
        deposit_info = step.deposit_info or (node.deposit_info if node else {})
        if deposit_info:
            details.extend([
                "",
                "【合約結構探測（非控制權認定）】",
                *[f"{key}：{value}" for key, value in deposit_info.items()],
            ])

        # Polymarket 交易資訊（語意補強 + 鏈上直接解碼）
        trade_info = step.trade_info
        if trade_info:
            source = trade_info.get("enrichment_source") or "RPC Receipt 鏈上解碼"
            side = trade_info.get("action_label") or trade_info.get("action", "未知")
            outcome = trade_info.get("outcome", "")
            action_desc = f"{side} {outcome}".strip() if outcome else side
            mkt = trade_info.get("market_title")
            trader = trade_info.get("trader") or step.from_address
            val_raw = trade_info.get("value") or trade_info.get("collateral_amount", "0")
            val_clean = str(val_raw) if str(val_raw).startswith("$") else f"${val_raw}"
            fee = trade_info.get("fee", "0")
            shares = trade_info.get("shares", "0")
            price = trade_info.get("price_per_share", "0")
            ts = trade_info.get("timestamp") or step.timestamp or "未取得"

            trade_lines = [
                "",
                f"【Polymarket 交易資訊（來源：{source}）】",
                f"市場名稱：{mkt or '未取得（需經由 Orbscan/Data API 解析）'}",
                f"Trader：{trader}",
                f"角色：{role}",
                f"買賣／立場：{action_desc}",
                f"成交股數：{shares} Shares",
                f"成交單價：{price} USDC/股",
                f"交易總值：{val_clean}",
                f"手續費：{fee}",
                f"交易時間：{ts}",
            ]
            if trade_info.get("token_id"):
                trade_lines.append(f"標的 Token ID：#{trade_info.get('token_id')}")
            if trade_info.get("implied_probability"):
                trade_lines.append(f"隱含勝率：{trade_info.get('implied_probability')}")
            details.extend(trade_lines)

        details.extend([
            "",
            "【限制與待查事項】",
            f"備註：{step.notes or '無'}",
            "本結果僅表示鏈上資金關聯，不代表已確認目標地址與該交易所帳戶屬同一自然人。",
        ])

        self._set_detail("\n".join(details))
        has_tx = bool(step.tx_hash and step.tx_hash.strip())
        has_from = bool(step.from_address and step.from_address.strip())
        has_to = bool(step.to_address and step.to_address.strip())
        self.copy_button.configure(state="normal" if has_tx else "disabled")
        self.copy_from_button.configure(state="normal" if has_from else "disabled")
        self.copy_to_button.configure(state="normal" if has_to else "disabled")
        self.explorer_button.configure(state="normal" if explorer else "disabled")
        self.technical_details_button.configure(state="normal")
        self.resolve_button.configure(state="normal" if not self.running and not self.resolving and chain == "Polygon" and step.address.startswith("0x") else "disabled")
        self._highlight_selection(edge.key)
        if focus_canvas:
            self.canvas.focus_set()

    def _highlight_selection(self, key: str) -> None:
        self.canvas.delete("selection_ring")
        if key not in self.edge_boxes:
            return
        x1, y1, x2, y2, _top, _bot = self.edge_boxes[key]
        pad = 3 * self.zoom
        self.canvas.create_rectangle(
            x1 - pad, y1 - pad, x2 + pad, y2 + pad,
            outline=self.COLORS["action"],
            width=max(2, int(2.5 * self.zoom)),
            tags="selection_ring",
        )

    def _on_key_down(self, _event) -> str:
        if not self.current_edges:
            return "break"
        if self.selected_edge_index < 0:
            new_idx = 0
        else:
            new_idx = min(len(self.current_edges) - 1, self.selected_edge_index + 1)
        self._select_edge_by_index(new_idx)
        return "break"

    def _on_key_up(self, _event) -> str:
        if not self.current_edges:
            return "break"
        if self.selected_edge_index < 0:
            new_idx = 0
        else:
            new_idx = max(0, self.selected_edge_index - 1)
        self._select_edge_by_index(new_idx)
        return "break"

    def _on_key_home(self, _event) -> str:
        if self.current_edges:
            self._select_edge_by_index(0)
            self.canvas.yview_moveto(0)
        return "break"

    def _on_key_end(self, _event) -> str:
        if self.current_edges:
            self._select_edge_by_index(len(self.current_edges) - 1)
            self.canvas.yview_moveto(1.0)
        return "break"

    def _activate_selected(self) -> str:
        if 0 <= self.selected_edge_index < len(self.current_edges):
            edge = self.current_edges[self.selected_edge_index]
            self._select_edge(edge, focus_canvas=False)
        return "break"

    def _toggle_technical_details(self) -> None:
        visible = not self.show_technical_details.get()
        self.show_technical_details.set(visible)
        self.technical_details_button.configure(text="隱藏技術細節 ▾" if visible else "顯示技術細節 ▸")
        if self.selected_edge:
            self._select_edge(self.selected_edge, focus_canvas=False)

    def _select_edge_by_index(self, index: int) -> None:
        if 0 <= index < len(self.current_edges):
            edge = self.current_edges[index]
            self._select_edge(edge, focus_canvas=False)
            self._scroll_edge_into_view(edge.key)

    def _scroll_edge_into_view(self, key: str) -> None:
        if key not in self.edge_boxes:
            return
        _x1, _y1, _x2, _y2, top_y, bot_y = self.edge_boxes[key]
        scrollregion = self.canvas.cget("scrollregion")
        if not scrollregion:
            return
        parts = [float(v) for v in scrollregion.split()]
        total_h = parts[3] - parts[1]
        if total_h <= 0:
            return
        vis_h = self.canvas.winfo_height()
        if vis_h <= 1:
            return
        cur_top_frac, cur_bot_frac = self.canvas.yview()
        cur_top_px = cur_top_frac * total_h
        cur_bot_px = cur_bot_frac * total_h
        margin = 16 * self.zoom

        if top_y - margin < cur_top_px:
            new_top = max(0.0, (top_y - margin) / total_h)
            self.canvas.yview_moveto(new_top)
        elif bot_y + margin > cur_bot_px:
            target_top_px = (bot_y + margin) - vis_h
            new_top = min(1.0, max(0.0, target_top_px / total_h))
            self.canvas.yview_moveto(new_top)

    def _set_detail(self, value: str) -> None:
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        for line in value.split("\n"):
            if line.startswith("【") and line.endswith("】"):
                self.detail_text.insert("end", line + "\n", "section")
            elif "：" in line:
                key, rest = line.split("：", 1)
                self.detail_text.insert("end", key + "：", "label")
                if any(kw in key for kw in ("地址", "Tx Hash", "Token 合約", "區塊", "Token ID", "對手／合約", "Relay Request ID")):
                    self.detail_text.insert("end", rest + "\n", "mono")
                elif any(kw in key for kw in ("操作行為", "投入／換回資金", "成交均價", "隱含勝率", "合約份額")):
                    self.detail_text.insert("end", rest + "\n", "trade")
                elif any(kw in rest for kw in ("高度可能", "已確認", "是（協定索引）")):
                    self.detail_text.insert("end", rest + "\n", "value_highlight")
                else:
                    self.detail_text.insert("end", rest + "\n", "value")
            elif line.startswith("本結果僅表示") or "法律與證據" in line:
                self.detail_text.insert("end", line + "\n", "disclaimer")
            else:
                self.detail_text.insert("end", line + "\n")
        self.detail_text.configure(state="disabled")

    def _infer_chain(self, step) -> str:
        return infer_chain(step)

    def _explorer_url(self, step) -> str:
        if not step.tx_hash:
            return ""
        chain_id = step.chain_id or {"Polygon": 137, "BNB Chain": 56, "Ethereum": 1, "Base": 8453, "Optimism": 10, "Arbitrum One": 42161}.get(self._infer_chain(step), 0)
        return explorer_url(chain_id, step.tx_hash)

    def resolve_selected(self) -> None:
        if not self.selected_edge or self.running or self.resolving or self._infer_chain(self.selected_edge.step) != "Polygon":
            return
        edge = self.selected_edge
        self.resolving = True
        self.cancel_event.clear()
        self._set_running(True)
        self.progress.start(12)
        self.resolve_button.configure(state="disabled")
        self.status.set("正在讀取 Polygon 合約結構；不簽章、不送出交易…")

        def worker():
            from .wallet_resolver import resolve_wallet
            try:
                info = resolve_wallet(PolygonProvider(self.settings), edge.step.address, self._progress_status)
                if self.cancel_event.is_set():
                    raise AnalysisCancelled("合約結構查詢已停止，未保存未完成結果。")
                self.root.after(0, lambda: complete(info))
            except AnalysisCancelled as exc:
                self.root.after(0, lambda message=str(exc): self.status.set(message))
            except Exception as exc:
                self.root.after(0, lambda message=str(exc): self._show_error(message))
            finally:
                self.root.after(0, finished)

        def finished():
            self.resolving = False
            self._set_running(False)
            self.resolve_button.configure(state="normal" if self.selected_edge and self._infer_chain(self.selected_edge.step) == "Polygon" else "disabled")

        def complete(info):
            edge.step.deposit_info = info
            if self.result and any(step is edge.step for step in self.result.steps):
                self._render_text(self.result)
            if self.selected_edge is edge:
                self._select_edge(edge, focus_canvas=False)
            self.status.set("合約結構讀取完成；欄位回傳值不等於自然人控制權，詳見右側。")

        threading.Thread(target=worker, daemon=True).start()

    def _copy_to_clipboard(self, value: str, label: str) -> None:
        if not value:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.status.set(f"已複製{label}。")

    def copy_selected_tx(self) -> None:
        if not self.selected_edge or not self.selected_edge.tx_hash:
            return
        self._copy_to_clipboard(self.selected_edge.tx_hash, " Tx Hash")

    def copy_selected_from(self) -> None:
        if not self.selected_edge or not self.selected_edge.step.from_address:
            return
        self._copy_to_clipboard(self.selected_edge.step.from_address, "發送地址")

    def copy_selected_to(self) -> None:
        if not self.selected_edge or not self.selected_edge.step.to_address:
            return
        self._copy_to_clipboard(self.selected_edge.step.to_address, "收款地址")

    def open_selected_explorer(self) -> None:
        if not self.selected_edge:
            return
        url = self.selected_edge.step.explorer_url or self._explorer_url(self.selected_edge.step)
        if url:
            webbrowser.open(url)
            self.status.set("已在預設瀏覽器開啟 Explorer。")

    def _change_zoom(self, delta: float) -> None:
        self.zoom = min(1.5, max(0.8, round(self.zoom + delta, 1)))
        self.render_graph()
        self.status.set(f"流程圖縮放：{int(self.zoom * 100)}%。")

    def _reset_zoom(self) -> None:
        self.zoom = 1.0
        self.render_graph()

    def _scroll_home(self) -> None:
        self.canvas.xview_moveto(0)
        self.canvas.yview_moveto(0)

    def _scroll_target(self) -> None:
        if not self.graph or not self.current_edges:
            self._scroll_home()
            return
        for edge in reversed(self.current_edges):
            source = self.graph.nodes.get(edge.source)
            target = self.graph.nodes.get(edge.target)
            if (target and target.is_target) or (source and source.is_target):
                self._select_edge(edge, focus_canvas=False)
                self._scroll_edge_into_view(edge.key)
                return
        self._scroll_home()

    def _on_mousewheel(self, event) -> str:
        self.canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _on_shift_mousewheel(self, event) -> str:
        self.canvas.xview_scroll(-1 if event.delta > 0 else 1, "units")
        return "break"

    def _on_ctrl_mousewheel(self, event) -> str:
        self._change_zoom(0.1 if event.delta > 0 else -0.1)
        return "break"

    def export(self, kind: str) -> None:
        if not self.result:
            messagebox.showwarning("尚無結果", "請先完成一次分析。")
            return
        extensions = {"text": ".txt", "csv": ".csv", "evidence": ".zip", "svg": ".svg"}
        filetypes = {
            "text": [("文字檔", "*.txt")],
            "csv": [("CSV 檔", "*.csv")],
            "evidence": [("ZIP 證據包", "*.zip")],
            "svg": [("SVG 流程圖", "*.svg")],
        }
        path = filedialog.asksaveasfilename(defaultextension=extensions[kind], filetypes=filetypes[kind])
        if path:
            {"text": export_text, "csv": export_csv, "evidence": export_evidence_package, "svg": export_svg}[kind](self.result, path)
            self.status.set(f"已匯出：{path}")

    def open_settings(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("連線設定")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)
        values = {
            "rpc_url": tk.StringVar(value=self.settings.rpc_url),
            "blockscout_url": tk.StringVar(value=self.settings.blockscout_url),
            "etherscan_api_key": tk.StringVar(value=self.settings.etherscan_api_key),
            "relay_api_key": tk.StringVar(value=self.settings.relay_api_key),
            "orbscan_api_url": tk.StringVar(value=getattr(self.settings, "orbscan_api_url", "https://data-api.polymarket.com/trades")),
        }
        labels = {
            "rpc_url": "Polygon RPC URL",
            "blockscout_url": "Blockscout API URL",
            "etherscan_api_key": "Etherscan V2 API Key（跨鏈續追選填）",
            "relay_api_key": "Relay API Key（v3 選填）",
            "orbscan_api_url": "Orbscan / Polymarket API URL（語意解譯選填）",
        }
        for index, key in enumerate(values):
            ttk.Label(dialog, text=labels[key]).grid(row=index, column=0, sticky="w", padx=12, pady=8)
            ttk.Entry(dialog, textvariable=values[key], width=65, show="*" if key in {"etherscan_api_key", "relay_api_key"} else "").grid(row=index, column=1, sticky="ew", padx=12, pady=8)

        def save() -> None:
            for key, value in values.items():
                setattr(self.settings, key, value.get().strip())
            save_settings(self.settings)
            dialog.destroy()
            self.status.set("設定已儲存於程式同目錄 settings.json。")

        ttk.Button(dialog, text="儲存設定", style="Primary.TButton", command=save).grid(row=len(values), column=1, sticky="e", padx=12, pady=12)

    def _init_panes_sash(self) -> None:
        try:
            self.root.update_idletasks()
            total_w = self.workspace_panes.winfo_width()
            if total_w > 700:
                left_w = max(260, min(340, int(total_w * 0.22)))
                right_w = max(320, min(420, int(total_w * 0.28)))
                mid_x = total_w - right_w
                self.workspace_panes.sashpos(0, left_w)
                self.workspace_panes.sashpos(1, mid_x)
        except Exception:
            pass


def launch(initial_query: str = "", auto_start: bool = False) -> None:
    import sys
    root = tk.Tk()
    query = initial_query or (sys.argv[1].strip() if len(sys.argv) > 1 else "")
    App(root, initial_query=query, auto_start=auto_start or (len(sys.argv) > 1 and bool(query)))
    root.mainloop()
