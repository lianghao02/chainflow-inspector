import sys


def main() -> None:
    try:
        from chain_fund_tracer.webview_app import launch
        launch()
    except Exception as exc:
        try:
            # 若 WebView2 啟動失敗，嘗試備援 Tkinter GUI
            from chain_fund_tracer.gui import launch as fallback_launch
            fallback_launch()
        except Exception as fb_exc:
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    "程式啟動錯誤",
                    f"HTML 工作台啟動失敗：{exc}\n\n備援 GUI 啟動亦失敗：{fb_exc}"
                )
                root.destroy()
            except Exception:
                pass
            sys.exit(1)


if __name__ == "__main__":
    main()
