from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import webview

from .analysis import Analyzer
from .branding import PRODUCT_NAME
from .config import Settings
from .csv_loader import inspect_and_load_polygonscan_csv
from .exporters import export_agent_bundle, export_csv, export_evidence_package, export_subpoena_csv, export_svg, export_text
from .history import delete_history_entry, list_history_entries, load_history_entry, save_history_entry
from .models import AnalysisResult
from .providers import PolygonProvider, ProviderError


class Controller:
    """PyWebView JavaScript API 協調控制器。
    負責前端事件呼叫、背景查詢執行緒、進度回報、取消與檔案對話框。
    """

    def __init__(self, window: webview.Window | None = None):
        self._window = window
        self._settings = Settings.load()
        self._provider = PolygonProvider(self._settings)
        self._current_result: AnalysisResult | None = None
        self._is_running = False
        self._cancel_requested = False
        self._analysis_thread: threading.Thread | None = None

    @property
    def settings(self) -> Settings:
        return self._settings

    @property
    def current_result(self) -> AnalysisResult | None:
        return self._current_result

    def set_window(self, window: webview.Window) -> None:
        self._window = window

    # ==========================
    # 初始資料與設定
    # ==========================

    def get_init_data(self) -> dict[str, Any]:
        """提供前端初始化所需之設定與歷史記錄。"""
        history_list = [entry.to_dict() for entry in list_history_entries()]
        core_tokens = getattr(self._settings, "core_inbound_tokens", [
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # Native USDC
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
            "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",  # pUSD
            "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",  # USDT
        ])
        return {
            "product_name": PRODUCT_NAME,
            "settings": {
                "rpc_url": self._settings.rpc_url,
                "blockscout_url": self._settings.blockscout_url,
                "has_etherscan_api_key": bool(self._settings.etherscan_api_key.strip()),
                "orbscan_api_url": getattr(self._settings, "orbscan_api_url", ""),
                "max_hops": self._settings.max_hops,
                "page_size": self._settings.page_size,
                "max_history_pages": getattr(self._settings, "max_history_pages", 15),
                "core_inbound_tokens": core_tokens,
            },
            "history": history_list,
        }

    def save_settings(self, new_settings: dict[str, Any]) -> dict[str, Any]:
        """儲存並套用使用者設定。"""
        try:
            for key, val in new_settings.items():
                if key == "etherscan_api_key":
                    val_str = str(val).strip()
                    if val_str:  # 僅在明確提供新金鑰時才覆寫
                        self._settings.etherscan_api_key = val_str
                elif hasattr(self._settings, key):
                    if key in ("max_hops", "page_size", "max_history_pages"):
                        setattr(self._settings, key, int(val))
                    elif key == "core_inbound_tokens" and isinstance(val, list):
                        setattr(self._settings, key, [str(t).strip().lower() for t in val if str(t).strip()])
                    else:
                        setattr(self._settings, key, str(val).strip())
            self._settings.save()
            self._provider = PolygonProvider(self._settings)
            return {"success": True, "message": "設定已更新"}
        except Exception as exc:
            return {"success": False, "message": f"設定儲存失敗：{exc}"}

    # ==========================
    # CSV 檔案對話框與預檢
    # ==========================

    def select_csv_file(self) -> str:
        """開啟系統原生檔案選擇對話框，選擇 PolygonScan CSV 檔案。"""
        if not self._window:
            return ""
        file_types = ("CSV 試算表檔案 (*.csv)", "所有檔案 (*.*)")
        result = self._window.create_file_dialog(
            webview.OPEN_DIALOG,
            allow_multiple=False,
            file_types=file_types,
        )
        if result and len(result) > 0:
            return str(result[0])
        return ""

    def inspect_csv(self, csv_path: str, target_address: str = "") -> dict[str, Any]:
        """對使用者選取的 CSV 進行法證規格與時間窗預檢。"""
        if not csv_path or not Path(csv_path).is_file():
            return {"success": False, "error": "CSV 檔案不存在"}
        try:
            info = inspect_and_load_polygonscan_csv(csv_path, target_address)
            return {"success": True, "data": info}
        except Exception as exc:
            return {"success": False, "error": f"讀取 CSV 失敗：{exc}"}

    # ==========================
    # 核心鏈上分析
    # ==========================

    def run_analysis(self, params: dict[str, Any]) -> dict[str, Any]:
        """執行資金追蹤分析（同步或從前端非同步呼叫）。"""
        if self._is_running:
            return {"success": False, "error": "已有分析任務正在執行中"}

        self._is_running = True
        self._cancel_requested = False

        query = str(params.get("query", "")).strip()
        mode = str(params.get("mode", "polymarket")).strip()
        hops = int(params.get("hops", self._settings.max_hops or 2))
        time_filter_raw = str(params.get("time_filter_raw", "")).strip()
        csv_path = str(params.get("csv_path", "")).strip()

        # 解析時間錨定
        as_of_time: float | None = None
        start_time: float | None = None
        end_time: float | None = None

        if time_filter_raw:
            try:
                from .providers import parse_user_datetime_input
                if "~" in time_filter_raw:
                    parts = time_filter_raw.split("~", 1)
                    start_time = parse_user_datetime_input(parts[0].strip(), False)
                    end_time = parse_user_datetime_input(parts[1].strip(), True)
                else:
                    as_of_time = parse_user_datetime_input(time_filter_raw, True)
            except Exception as exc:
                self._is_running = False
                return {"success": False, "error": f"時間篩選格式錯誤：{exc}"}

        def on_progress(msg: str) -> None:
            if self._cancel_requested:
                raise InterruptedError("使用者已手動停止查詢")
            if self._window:
                safe_msg = json.dumps(msg, ensure_ascii=False)
                self._window.evaluate_js(f"window.__onProgress && window.__onProgress({safe_msg})")

        analyzer = Analyzer(self._provider, progress=on_progress)

        try:
            on_progress("正在驗證輸入地址／交易雜湊…")
            if mode == "polymarket":
                result = analyzer.analyze_polymarket_funding(
                    tx_hash=query,
                    max_hops=hops,
                    as_of_time=as_of_time,
                    start_time=start_time,
                    end_time=end_time,
                    time_filter_raw=time_filter_raw,
                    csv_path=csv_path,
                )
            else:
                result = analyzer.analyze(
                    query=query,
                    max_hops=hops,
                    as_of_time=as_of_time,
                    start_time=start_time,
                    end_time=end_time,
                    time_filter_raw=time_filter_raw,
                )

            self._current_result = result
            # 儲存至本機歷史記錄
            save_history_entry(result, mode=mode)

            status_text = {
                "complete": "分析完成，正在呈現結果…",
                "partial": "分析部分完成，正在呈現可驗證結果…",
                "failed": "核心資產軌道查詢失敗，正在呈現錯誤與已取得資料…",
            }.get(result.analysis_status, "分析完成，正在呈現結果…")
            on_progress(status_text)
            return {
                "success": True,
                "data": result.to_dict(),
            }

        except InterruptedError:
            return {"success": False, "error": "查詢已手動取消"}
        except ProviderError as exc:
            return {"success": False, "error": f"區塊鏈查詢異常：{exc}"}
        except Exception as exc:
            tb = traceback.format_exc()
            return {"success": False, "error": f"系統發生未預期錯誤：{exc}", "traceback": tb}
        finally:
            self._is_running = False

    def cancel_analysis(self) -> dict[str, Any]:
        """發出停止信號。"""
        if self._is_running:
            self._cancel_requested = True
            return {"success": True, "message": "正在停止查詢…"}
        return {"success": False, "message": "目前無執行中任務"}

    # ==========================
    # 歷史紀錄管理
    # ==========================

    def get_history(self) -> list[dict[str, Any]]:
        """取得歷史紀錄清單。"""
        return [entry.to_dict() for entry in list_history_entries()]

    def load_history(self, entry_id: str) -> dict[str, Any]:
        """載入指定的歷史快照。"""
        result = load_history_entry(entry_id)
        if result:
            self._current_result = result
            return {"success": True, "data": result.to_dict()}
        return {"success": False, "error": "找不到此歷史快照"}

    def delete_history(self, entry_id: str) -> dict[str, Any]:
        """刪除指定歷史快照。"""
        success = delete_history_entry(entry_id)
        return {"success": success}

    # ==========================
    # 匯出報告與證據包
    # ==========================

    def export_report(self, export_type: str) -> dict[str, Any]:
        """開啟系統原生存檔對話框並匯出報告。"""
        if not self._current_result:
            return {"success": False, "error": "目前無可匯出的分析結果"}
        if not self._window:
            return {"success": False, "error": "無有效視窗環境"}

        query_slug = self._current_result.query.replace("0x", "")[:12]
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")

        configs = {
            "csv": (f"資金追蹤步驟_{query_slug}_{date_str}.csv", ("CSV 檔案 (*.csv)",)),
            "txt": (f"法證查核紀錄_{query_slug}_{date_str}.txt", ("文字報告 (*.txt)",)),
            "svg": (f"資金路徑圖_{query_slug}_{date_str}.svg", ("向量圖形 (*.svg)",)),
            "subpoena_csv": (f"函調候選清單_{query_slug}_{date_str}.csv", ("CSV 檔案 (*.csv)",)),
            "zip": (f"法證證據包_{query_slug}_{date_str}.zip", ("ZIP 壓縮檔 (*.zip)",)),
            "agent_bundle": (f"agent_analysis_bundle_{query_slug}_{date_str}.zip", ("Agent 分析包 (*.zip)",)),
        }

        if export_type not in configs:
            return {"success": False, "error": f"不支援的匯出格式：{export_type}"}

        default_filename, file_types = configs[export_type]
        save_path = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=default_filename,
            file_types=file_types,
        )

        if not save_path:
            return {"success": False, "cancelled": True}

        dest = str(save_path)
        try:
            if export_type == "csv":
                export_csv(self._current_result, dest)
            elif export_type == "txt":
                export_text(self._current_result, dest)
            elif export_type == "svg":
                export_svg(self._current_result, dest)
            elif export_type == "subpoena_csv":
                export_subpoena_csv(self._current_result, dest)
            elif export_type == "zip":
                export_evidence_package(self._current_result, dest)
            elif export_type == "agent_bundle":
                export_agent_bundle(self._current_result, dest)
            return {"success": True, "file_path": dest}
        except Exception as exc:
            return {"success": False, "error": f"匯出失敗：{exc}"}

    # ==========================
    # 外部工具輔助（嚴格白名單防護）
    # ==========================

    _ALLOWED_HOSTS = {
        "polygonscan.com",
        "etherscan.io",
        "bscscan.com",
        "arbiscan.io",
        "optimistic.etherscan.io",
        "basescan.org",
        "tronscan.org",
        "polymarket.com",
    }

    def open_external(self, url: str) -> bool:
        """以系統預設瀏覽器開啟合法的鏈上瀏覽器超連結（嚴格白名單與 HTTPS 協議驗證）。"""
        if not url:
            return False
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url.strip())
            if parsed.scheme.lower() != "https":
                return False
            hostname = (parsed.hostname or "").lower()
            # 檢查 hostname 是否屬於白名單網域或其子網域
            is_allowed = any(
                hostname == allowed or hostname.endswith("." + allowed)
                for allowed in self._ALLOWED_HOSTS
            )
            if is_allowed:
                webbrowser.open(url)
                return True
        except Exception:
            pass
        return False

    def open_explorer(self, chain_id: int | str, item_type: str, item_value: str) -> bool:
        """由後端依據鏈別與標的類型安全產生 Explorer 網址並開啟。"""
        val = str(item_value or "").strip()
        itype = str(item_type or "").strip().lower()
        if not val or itype not in ("tx", "address"):
            return False

        try:
            cid = int(chain_id)
        except (ValueError, TypeError):
            cid = 137

        base_urls = {
            1: "https://etherscan.io",
            56: "https://bscscan.com",
            137: "https://polygonscan.com",
            42161: "https://arbiscan.io",
            10: "https://optimistic.etherscan.io",
            8453: "https://basescan.org",
            728126428: "https://tronscan.org/#",
        }
        base = base_urls.get(cid, "https://polygonscan.com")
        path_part = "transaction" if cid == 728126428 and itype == "tx" else ("tx" if itype == "tx" else "address")
        safe_url = f"{base}/{path_part}/{val}"
        return self.open_external(safe_url)
