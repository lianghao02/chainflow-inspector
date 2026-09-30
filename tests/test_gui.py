import tkinter as tk
import unittest

from chain_fund_tracer.gui import App
from chain_fund_tracer.models import AnalysisResult, TraceStep


def has_display() -> bool:
    try:
        r = tk.Tk()
        r.withdraw()
        r.destroy()
        return True
    except Exception:
        return False


@unittest.skipIf(not has_display(), "無 GUI 視窗顯示環境，安全略過 Tkinter 介面測試")
class GuiFlowTests(unittest.TestCase):
    def test_vertical_evidence_chain_shows_time_and_bridge_elapsed(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            target = "0x" + "a" * 40
            wallet = "0x" + "b" * 40
            relay = "0x" + "c" * 40
            result = AnalysisResult(query=target, steps=[
                TraceStep("來源鏈原生幣入金", 5, "0x" + "1" * 64, "2026-09-23 08:03:46 +0800", "BNB（BNB Chain）", "0.09276721", relay, wallet, relay, "交易所", "Binance: Withdrawals 7", "公開標籤", "高度可能", "僅資金關聯"),
                TraceStep("Relay 來源鏈", 3, "0x" + "2" * 64, "2026-09-23 08:07:44 +0800", "USDT（BNB Chain）", "72.9", wallet, relay, wallet, "外部錢包", "Relay來源鏈入金者", "Relay", "已確認", "僅資金關聯"),
                TraceStep("Relay 目的鏈補款", 3, "0x" + "3" * 64, "2026-09-23 08:07:47 +0800", "USDC.e", "72.748693", relay, target, relay, "Bridge", "Relay Solver", "Explorer", "高度可能", "僅資金關聯"),
            ])
            for step, leg in zip(result.steps[1:], ("source", "destination")):
                step.relay_request_id, step.relay_leg, step.pair_verified = "request-1", leg, True
            app.show(result)
            root.update_idletasks()
            canvas_text = "\n".join(
                app.canvas.itemcget(item, "text")
                for item in app.canvas.find_all()
                if app.canvas.type(item) == "text"
            )
            self.assertIn("Binance: Withdrawals 7", canvas_text)
            self.assertIn("2026-09-23 08:03:46 +0800", canvas_text)
            self.assertIn("跨鏈時間戳差：約 3 秒", canvas_text)
            self.assertIn("跨鏈索引配對", canvas_text)
            self.assertIn("由舊到新", canvas_text)
        finally:
            root.destroy()

    def test_keyboard_navigation_and_selection_ring(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            target = "0x" + "a" * 40
            wallet = "0x" + "b" * 40
            relay = "0x" + "c" * 40
            result = AnalysisResult(query=target, steps=[
                TraceStep("來源鏈原生幣入金", 5, "0x" + "1" * 64, "2026-09-23 08:03:46 +0800", "BNB（BNB Chain）", "0.09276721", relay, wallet, relay, "交易所", "Binance: Withdrawals 7", "公開標籤", "高度可能", "僅資金關聯"),
                TraceStep("Relay 來源鏈", 3, "0x" + "2" * 64, "2026-09-23 08:07:44 +0800", "USDT（BNB Chain）", "72.9", wallet, relay, wallet, "外部錢包", "Relay來源鏈入金者", "Relay", "已確認", "僅資金關聯"),
                TraceStep("Relay 目的鏈補款", 3, "0x" + "3" * 64, "2026-09-23 08:07:47 +0800", "USDC.e", "72.748693", relay, target, relay, "Bridge", "Relay Solver", "Explorer", "高度可能", "僅資金關聯"),
            ])
            app.show(result)
            root.update_idletasks()

            # 初始狀態未選取
            self.assertEqual(app.selected_edge_index, -1)
            self.assertEqual(len(app.canvas.find_withtag("selection_ring")), 0)

            # 鍵盤向下鍵：選取第 0 筆
            app._on_key_down(None)
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 0)
            self.assertIsNotNone(app.selected_edge)
            self.assertEqual(len(app.canvas.find_withtag("selection_ring")), 1)
            self.assertIn("Binance: Withdrawals 7", app.detail_text.get("1.0", "end"))
            self.assertIn("發送地址（Transfer From）：" + relay, app.detail_text.get("1.0", "end"))
            self.assertIn("收款地址（Transfer To）：" + wallet, app.detail_text.get("1.0", "end"))
            self.assertNotIn("完整地址：", app.detail_text.get("1.0", "end"))

            app._toggle_technical_details()
            self.assertIn("完整地址：", app.detail_text.get("1.0", "end"))
            self.assertNotIn("\nFrom：", app.detail_text.get("1.0", "end"))
            self.assertNotIn("\nTo：", app.detail_text.get("1.0", "end"))
            self.assertIn("Relay Request ID：", app.detail_text.get("1.0", "end"))

            # 鍵盤向下鍵：選取第 1 筆
            app._on_key_down(None)
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 1)
            self.assertIn("USDT（BNB Chain）", app.detail_text.get("1.0", "end"))

            # 鍵盤向上鍵：回到第 0 筆
            app._on_key_up(None)
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 0)

            # End 鍵：跳到最後一筆 (第 2 筆)
            app._on_key_end(None)
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 2)

            # Home 鍵：跳回第 0 筆
            app._on_key_home(None)
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 0)

            app._scroll_target()
            root.update_idletasks()
            self.assertEqual(app.selected_edge_index, 2)
        finally:
            root.destroy()

    def test_zoom_scaling_and_evidence_bounds(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            target = "0x" + "a" * 40
            wallet = "0x" + "b" * 40
            relay = "0x" + "c" * 40
            result = AnalysisResult(query=target, steps=[
                TraceStep("來源鏈原生幣入金", 5, "0x" + "1" * 64, "2026-09-23 08:03:46 +0800", "BNB（BNB Chain）", "0.09276721", relay, wallet, relay, "交易所", "Binance: Withdrawals 7", "公開標籤", "高度可能", "僅資金關聯"),
                TraceStep("Relay 來源鏈", 3, "0x" + "2" * 64, "2026-09-23 08:07:44 +0800", "USDT（BNB Chain）", "72.9", wallet, relay, wallet, "外部錢包", "Relay來源鏈入金者", "Relay", "已確認", "僅資金關聯"),
                TraceStep("Relay 目的鏈補款", 3, "0x" + "3" * 64, "2026-09-23 08:07:47 +0800", "USDC.e", "72.748693", relay, target, relay, "Bridge", "Relay Solver", "Explorer", "高度可能", "僅資金關聯"),
            ])
            app.show(result)
            root.update_idletasks()

            result.steps[2].timestamp = "2026-09-23 08:07:43 +0800"
            for item, leg in zip(result.steps[1:], ("source", "destination")):
                item.relay_request_id, item.relay_leg, item.pair_verified = "request-1", leg, True
            app.show(result)
            for zoom in (0.8, 0.9, 1.0, 1.25, 1.5):
                app.zoom = zoom
                app.render_graph()
                root.update_idletasks()
                # 檢查每筆 edge 的證據卡片矩形與文字都在邊界內
                for edge in app.current_edges:
                    box_tag = f"box_{edge.key}"
                    rects = app.canvas.find_withtag(box_tag)
                    self.assertTrue(len(rects) > 0)
                    r_bbox = app.canvas.bbox(rects[0])
                    # 找出該卡片內的文字
                    ev_texts = [
                        t for t in app.canvas.find_withtag(edge.key)
                        if app.canvas.type(t) == "text" and app.canvas.coords(t)[0] >= r_bbox[0]
                    ]
                    self.assertTrue(len(ev_texts) > 0)
                    t_bbox = app.canvas.bbox(ev_texts[0])
                    # 文字右界與下界不得超出卡片矩形
                    self.assertLessEqual(t_bbox[2], r_bbox[2] + 2)
                    self.assertLessEqual(t_bbox[3], r_bbox[3] + 2)
                summary_box = app.canvas.bbox(app.canvas.find_withtag("summary_box")[0])
                summary_text = app.canvas.bbox(app.canvas.find_withtag("summary_text")[0])
                self.assertLessEqual(summary_text[3], summary_box[3])
        finally:
            root.destroy()

    def test_history_combobox_integration(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            with patch("chain_fund_tracer.history.get_history_dir", return_value=tmp_path):
                root = tk.Tk()
                root.withdraw()
                try:
                    app = App(root)
                    root.update_idletasks()
                    # 初始無歷史紀錄
                    self.assertEqual(str(app.history_combobox.cget("state")), "readonly")
                    self.assertEqual(len(app.history_entries), 0)
                    self.assertEqual(str(app.clear_history_btn.cget("state")), "disabled")

                    # 分析完成顯示結果，觸發自動存檔
                    target = "0x" + "a" * 40
                    wallet = "0x" + "b" * 40
                    result = AnalysisResult(query=target, steps=[
                        TraceStep("外部入金", 1, "0x" + "1" * 64, "2026-09-26 12:00:00 +0800", "USDC", "100", wallet, target, wallet, "外部錢包", "入金者", "公開標籤", "高度可能", "僅資金關聯"),
                    ])
                    app.show(result, mode="polymarket")
                    root.update_idletasks()

                    # 驗證 Combobox 已經更新為有紀錄
                    self.assertEqual(str(app.history_combobox.cget("state")), "readonly")
                    self.assertEqual(str(app.clear_history_btn.cget("state")), "normal")
                    self.assertEqual(len(app.history_entries), 1)
                    values = list(app.history_combobox.cget("values"))
                    self.assertGreaterEqual(len(values), 2)
                    self.assertIn(target[:8], values[1])

                    # 變更 query 後，選取歷史紀錄並觸發切換
                    app.query.set("0x" + "9" * 40)
                    app.history_combobox.current(1)
                    app._on_history_selected()
                    root.update_idletasks()

                    # 驗證 query 與 result 還原
                    self.assertEqual(app.query.get(), target)
                    self.assertEqual(app.result.query, target)
                    self.assertEqual(len(app.result.steps), 1)

                    # 清空歷史
                    from chain_fund_tracer.history import clear_history
                    clear_history()
                    app._refresh_history_combobox()
                    root.update_idletasks()
                    self.assertEqual(str(app.history_combobox.cget("state")), "readonly")
                    self.assertEqual(len(app.history_entries), 0)
                    self.assertEqual(str(app.clear_history_btn.cget("state")), "disabled")
                finally:
                    root.destroy()

    def test_theme_toggle(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            root.update_idletasks()
            self.assertEqual(app.theme_name, "light")
            self.assertEqual(app.COLORS["header_bg"], "#0f172a")
            self.assertEqual(app.COLORS["background"], "#e2e8f0")
            self.assertEqual(app.theme_btn.cget("text"), "🌙 深色模式")

            # 切換至深色模式
            app._toggle_theme()
            root.update_idletasks()
            self.assertEqual(app.theme_name, "dark")
            self.assertEqual(app.COLORS["header_bg"], "#030712")
            self.assertEqual(app.COLORS["background"], "#0b0f19")
            self.assertEqual(app.theme_btn.cget("text"), "☀️ 淺色模式")

            # 再次切換回淺色模式
            app._toggle_theme()
            root.update_idletasks()
            self.assertEqual(app.theme_name, "light")
            self.assertEqual(app.COLORS["header_bg"], "#0f172a")
            self.assertEqual(app.theme_btn.cget("text"), "🌙 深色模式")
        finally:
            root.destroy()

    def test_csv_entry_and_validation_status(self):
        import tempfile
        import os
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            root.update_idletasks()
            # 初始狀態
            self.assertIn("留空查最新", app.csv_status_lbl.cget("text"))

            # 輸入不存在之路徑
            app.csv_path_var.set("C:/non_existent_folder/fake.csv")
            root.update_idletasks()
            self.assertIn("檔案不存在", app.csv_status_lbl.cget("text"))

            # 建立暫存 CSV 檔案測試有效狀態
            with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False) as tf:
                tf.write("test,content\n1,2\n")
                temp_csv = tf.name
            try:
                # 測試帶引號字串（Windows 複製路徑常見）
                app.csv_path_var.set(f'"{temp_csv}"')
                root.update_idletasks()
                self.assertIn("有效", app.csv_status_lbl.cget("text"))

                # 測試清空
                app._clear_csv_file()
                root.update_idletasks()
                self.assertEqual(app.csv_path_var.get(), "")
                self.assertIn("留空查最新", app.csv_status_lbl.cget("text"))
            finally:
                if os.path.exists(temp_csv):
                    os.unlink(temp_csv)
        finally:
            root.destroy()

    def test_three_zone_workspace_and_collapsible_conditions(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            root.update_idletasks()
            self.assertIn("鏈流查核", root.title())
            self.assertEqual(len(app.workspace_panes.panes()), 3)
            self.assertIsNone(app.left_panes)
            self.assertTrue(hasattr(app, "detail_scroll"))
            self.assertFalse(app.advanced_visible.get())
            self.assertEqual(app.advanced_frame.winfo_manager(), "")

            app._toggle_advanced()
            root.update_idletasks()
            self.assertTrue(app.advanced_visible.get())
            self.assertEqual(app.advanced_frame.winfo_manager(), "grid")

            app.query.set("0x" + "a" * 40)
            app.time_filter_var.set("2026-09-20")
            app.csv_path_var.set("C:/missing.csv")
            app.hops.set(2)
            app._clear_conditions()
            self.assertEqual(app.query.get(), "0x" + "a" * 40)
            self.assertEqual(app.time_filter_var.get(), "")
            self.assertEqual(app.csv_path_var.get(), "")
            self.assertEqual(app.hops.get(), app.settings.max_hops)
        finally:
            root.destroy()

    def test_stage_progress_is_determinate_and_non_decreasing(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            app._apply_progress_status("正在核對第 5/20 筆 pUSD 鑄造 Receipt…")
            first = app.progress_value.get()
            self.assertIn("5/20", app.progress_caption.get())
            self.assertGreater(first, 25)

            app._apply_progress_status("正在比對 Relay 跨鏈紀錄…")
            self.assertEqual(app.progress_caption.get(), "追蹤 Relay")
            self.assertGreaterEqual(app.progress_value.get(), first)
        finally:
            root.destroy()

    def test_evidence_panel_from_to_and_copy_buttons(self):
        root = tk.Tk()
        root.withdraw()
        try:
            app = App(root)
            from_vasp = "0xe2fc31f816a9b94326492132018c3aecc4a93ae1"
            to_relay = "0xdd81cb8ccc1376063a8435e05b007587f7eddec2"
            tx_vasp = "0xf058f48" + "0" * 57
            zero_addr = "0x" + "0" * 40
            normal_addr = "0x" + "9" * 40

            step_vasp = TraceStep(
                "來源鏈轉入", 4, tx_vasp, "2026-07-17 14:00:00 +0800", "USDC", "400",
                from_vasp, to_relay, from_vasp, "交易所", "Binance: Withdrawals 7", "公開標籤", "高度可能", "已確認"
            )
            step_vasp.block_number = 40123456
            step_vasp.log_index = 88
            step_vasp.token_contract = "0x" + "5" * 40
            step_vasp.relay_request_id = "0xreq123"

            step_zero = TraceStep(
                "零地址鑄造", 1, "0x" + "a" * 64, "2026-07-17 14:01:00 +0800", "pUSD", "400",
                zero_addr, normal_addr, zero_addr, "合約", "pUSD Mint", "合約", "已確認", "已確認"
            )

            step_missing_tx = TraceStep(
                "內部兌換", 1, "", "2026-07-17 14:02:00 +0800", "USDC", "10",
                normal_addr, normal_addr, normal_addr, "DEX", "Uniswap", "無", "已確認", "僅資金關聯"
            )

            result = AnalysisResult(query=to_relay, steps=[step_vasp, step_zero, step_missing_tx])
            app.show(result)
            root.update_idletasks()

            # 1. 初始未選取，按鈕應為 disabled
            self.assertEqual(str(app.copy_button.cget("state")), "disabled")
            self.assertEqual(str(app.copy_from_button.cget("state")), "disabled")
            self.assertEqual(str(app.copy_to_button.cget("state")), "disabled")

            # 2. 選取 step_vasp (index 0)
            app._select_edge_by_index(0)
            root.update_idletasks()

            detail = app.detail_text.get("1.0", "end")
            self.assertIn("發送地址（Transfer From）：" + from_vasp, detail)
            self.assertIn("收款地址（Transfer To）：" + to_relay, detail)
            self.assertIn("Tx Hash：" + tx_vasp, detail)
            # 未展開技術細節前，不應有完整地址標籤
            self.assertNotIn("完整地址：", detail)

            # 按鈕應全部啟用
            self.assertEqual(str(app.copy_button.cget("state")), "normal")
            self.assertEqual(str(app.copy_from_button.cget("state")), "normal")
            self.assertEqual(str(app.copy_to_button.cget("state")), "normal")
            self.assertEqual(str(app.explorer_button.cget("state")), "normal")

            # 測試複製發送地址
            app.copy_selected_from()
            self.assertEqual(root.clipboard_get(), from_vasp)
            self.assertEqual(app.status.get(), "已複製發送地址。")

            # 測試複製收款地址
            app.copy_selected_to()
            self.assertEqual(root.clipboard_get(), to_relay)
            self.assertEqual(app.status.get(), "已複製收款地址。")

            # 測試複製 Tx Hash
            app.copy_selected_tx()
            self.assertEqual(root.clipboard_get(), tx_vasp)
            self.assertEqual(app.status.get(), "已複製 Tx Hash。")

            # 測試展開技術細節
            app._toggle_technical_details()
            detail_tech = app.detail_text.get("1.0", "end")
            self.assertIn("完整地址：" + from_vasp, detail_tech)
            self.assertIn("區塊：40123456", detail_tech)
            self.assertIn("Log Index：88", detail_tech)
            self.assertIn("Token 合約：" + "0x" + "5" * 40, detail_tech)
            self.assertIn("Relay Request ID：0xreq123", detail_tech)
            self.assertNotIn("\nFrom：", detail_tech)
            self.assertNotIn("\nTo：", detail_tech)

            # 3. 選取零地址步驟 (step_zero, index 1)
            app._select_edge_by_index(1)
            root.update_idletasks()

            detail_zero = app.detail_text.get("1.0", "end")
            self.assertIn("發送地址（Transfer From）：" + zero_addr, detail_zero)
            self.assertEqual(str(app.copy_from_button.cget("state")), "normal")
            app.copy_selected_from()
            self.assertEqual(root.clipboard_get(), zero_addr)
            self.assertEqual(app.status.get(), "已複製發送地址。")

            # 4. 選取缺少 Tx Hash 的步驟 (step_missing_tx, index 2)
            app._select_edge_by_index(2)
            root.update_idletasks()

            detail_missing_tx = app.detail_text.get("1.0", "end")
            self.assertIn("發送地址（Transfer From）：" + normal_addr, detail_missing_tx)
            self.assertIn("收款地址（Transfer To）：" + normal_addr, detail_missing_tx)
            self.assertIn("Tx Hash：未取得", detail_missing_tx)
            self.assertEqual(str(app.copy_button.cget("state")), "disabled")
            self.assertEqual(str(app.copy_from_button.cget("state")), "normal")
            self.assertEqual(str(app.copy_to_button.cget("state")), "normal")

            # 5. 測試缺少發送/收款地址時按鈕停用與顯示未取得
            from chain_fund_tracer.flow_graph import FlowEdge
            step_no_addr = TraceStep(
                "缺地址步驟", 1, "0x" + "b" * 64, "2026-07-17 14:03:00 +0800", "USDC", "10",
                "", "", normal_addr, "未知", "", "無", "未知", "僅資金關聯"
            )
            edge_no_addr = FlowEdge(
                key="edge-no-addr", source="s", target="t", token="USDC", amount="10",
                tx_hash="0x" + "b" * 64, timestamp="2026-07-17 14:03:00 +0800",
                direction="缺地址", lane="入金", style="unknown", step=step_no_addr
            )
            app._select_edge(edge_no_addr, focus_canvas=False)
            root.update_idletasks()

            detail_no_addr = app.detail_text.get("1.0", "end")
            self.assertIn("發送地址（Transfer From）：未取得", detail_no_addr)
            self.assertIn("收款地址（Transfer To）：未取得", detail_no_addr)
            self.assertIn("Tx Hash：" + "0x" + "b" * 64, detail_no_addr)
            self.assertEqual(str(app.copy_button.cget("state")), "normal")
            self.assertEqual(str(app.copy_from_button.cget("state")), "disabled")
            self.assertEqual(str(app.copy_to_button.cget("state")), "disabled")
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
