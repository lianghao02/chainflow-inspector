import sys


def main() -> None:
    # 1. 檢查核心依賴 pywebview 是否存在
    try:
        import webview
    except ImportError:
        err_msg = (
            "【執行環境提示】尚未安裝 HTML 工作台所需之依賴套件 (pywebview)。\n"
            "請先於終端機執行下列指令完成安裝：\n\n"
            "    py -3 -m pip install -r requirements.txt\n"
        )
        print(f"\n{err_msg}", file=sys.stderr)

        # 若環境具備 GUI 視窗，提供清楚的錯誤提示或選擇性切換
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            use_fallback = messagebox.askyesno(
                "HTML 介面依賴未安裝",
                "偵測到尚未安裝 pywebview 套件。\n\n"
                "請先於終端機執行：\n"
                "py -3 -m pip install -r requirements.txt\n\n"
                "是否要暫時以舊版 Tkinter 備援介面啟動？"
            )
            root.destroy()
            if use_fallback:
                from chain_fund_tracer.gui import launch as fallback_launch
                fallback_launch()
                return
        except Exception:
            pass
        sys.exit(1)

    # 2. 正式啟動 PyWebView 工作台
    try:
        from chain_fund_tracer.webview_app import launch
        launch()
    except Exception as exc:
        print(f"[錯誤] HTML 工作台啟動失敗：{exc}", file=sys.stderr)
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "程式啟動錯誤",
                f"HTML 工作台啟動異常：{exc}"
            )
            root.destroy()
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()

