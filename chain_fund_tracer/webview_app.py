from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

from .branding import PRODUCT_NAME
from .controller import Controller


def launch() -> None:
    """啟動 PyWebView 本機桌面視窗應用程式。"""
    ui_dir = Path(__file__).resolve().parent / "ui"
    html_path = ui_dir / "index.html"

    if not html_path.is_file():
        raise FileNotFoundError(f"找不到前端 UI 檔案：{html_path}")

    controller = Controller()

    # 建立視窗並注入 Controller 作為 js_api
    window = webview.create_window(
        title=f"{PRODUCT_NAME} - 區塊鏈資金追蹤與反洗錢法證平台",
        url=str(html_path.as_uri()),
        js_api=controller,
        width=1280,
        height=860,
        min_size=(1024, 700),
        text_select=True,
    )

    controller.set_window(window)

    # 啟動 PyWebView（在 Windows 上優先使用 Edge Chromium / WebView2）
    webview.start(debug=False)


if __name__ == "__main__":
    launch()
