import sys
from chain_fund_tracer.gui import launch


if __name__ == "__main__":
    try:
        launch()
    except Exception as exc:
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("程式啟動錯誤", f"應用程式發生未預期錯誤：\n{exc}")
            root.destroy()
        except Exception:
            pass
        sys.exit(1)
