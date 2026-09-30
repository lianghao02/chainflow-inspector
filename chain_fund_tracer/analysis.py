from __future__ import annotations
import re
from collections import deque
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Callable
from .models import AnalysisResult, TraceStep, Transfer, timestamp_to_text
from .providers import PolygonProvider, ProviderError
from .relay_evidence import amount_text, exact_pair, explorer_url, same_chain_request_match
ADDRESS = re.compile(r"^0x[a-fA-F0-9]{40}$")
TX_HASH = re.compile(r"^0x[a-fA-F0-9]{64}$")
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
POLYMARKET_CONDITIONAL_TOKENS = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"; USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
USDT = "0xc2132d05d31c914a87c6611c10748aeb04b58e8f"
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
CORE_INBOUND_RESERVES = [USDC, USDC_E, PUSD, USDT]
CTF_EXCHANGE = "0xe111180000d2663c0091e4f400237545b87b996b"
NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310f59"
COLLATERAL_ONRAMP = "0x93070a847efef7f70739046a929d47a521f5b8ee"
REWARD_DISTRIBUTOR = "0xc288480574783bd7615170660d71753378159c47"
PUSD_SETTLEMENT = "0xc417fd8e9661c0d2120b64a04bb3278c17e99db1"
RELAY_DEPOSITORY = "0x4cd00e387622c35bddb9b4c962c136462338bc31"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"
POLYMARKET_INTERNAL = {PUSD, CTF_EXCHANGE, NEG_RISK_EXCHANGE, COLLATERAL_ONRAMP, POLYMARKET_CONDITIONAL_TOKENS, REWARD_DISTRIBUTOR, PUSD_SETTLEMENT}
PUBLIC_ADDRESS_LABELS = {
    "0xe2fc31f816a9b94326492132018c3aecc4a93ae1": (
        "交易所", "Binance: Withdrawals 7", "Blockscan／BscScan 公開標籤（2026-09-23 查核）", "高度可能"
    ),
    "0xb300000b72deaeb607a12d5f54773d1c19c7028d": (
        "DEX", "Binance DEX Router", "BNB Chain 公開合約標籤", "已確認"
    ),
}
CHAIN_NAMES = {
    1: "Ethereum",
    10: "Optimism",
    56: "BNB Chain",
    137: "Polygon",
    8453: "Base",
    42161: "Arbitrum One",
    728126428: "TRON",
}
def normalize(value: str) -> str: return value.lower() if value else ""
def hex_int(value: str | None) -> int:
    try: return int(value or "0x0", 16)
    except ValueError: return 0
def event_address(value: Any) -> str:
    return value.get("hash", "") if isinstance(value, dict) else (value or "")
def event_label(value: Any) -> str:
    if not isinstance(value, dict): return ""
    tags = value.get("public_tags", []) or []
    tag_names = [item.get("display_name", item.get("name", "")) for item in tags if isinstance(item, dict)]
    meta_tags = value.get("metadata", {}).get("tags", []) if isinstance(value.get("metadata"), dict) else []
    for m in meta_tags:
        if isinstance(m, dict) and m.get("name"):
            tag_names.append(m["name"])
    explicit_name = str(value.get("name", "") or "").strip()
    if explicit_name:
        return explicit_name
    ignored = {"exchange", "bridge", "contract", "token", "wallet", "address"}
    cleaned: list[str] = []
    for name in tag_names:
        text = str(name or "").strip()
        if not text or re.fullmatch(r"note[_ -]?\d+", text, re.I):
            continue
        if text.lower() in ignored:
            continue
        if text not in cleaned:
            cleaned.append(text)
    return "、".join(cleaned)
def event_timestamp(value: Any) -> float:
    try:
        if value is None or value == "":
            return 0.0
        if isinstance(value, str):
            val_clean = value.strip()
            if "T" in val_clean:
                return datetime.fromisoformat(val_clean.replace("Z", "+00:00")).timestamp()
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z", "%Y/%m/%d %H:%M:%S"):
                try:
                    dt = datetime.strptime(val_clean, fmt)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    return dt.timestamp()
                except ValueError:
                    pass
        return float(int(value, 16) if str(value).startswith("0x") else value)
    except (ValueError, TypeError):
        return 0.0

class Analyzer:
    def __init__(self, provider: PolygonProvider, progress: Callable[[str], None] | None = None):
        self.provider = provider
        self.progress = progress or (lambda _message: None)
    def validate(self, query: str) -> str:
        query = query.strip()
        if not (ADDRESS.fullmatch(query) or TX_HASH.fullmatch(query)): raise ValueError("請輸入有效的 EVM 錢包地址（42 字元）或交易雜湊（66 字元）。")
        return query
    def classify(self, address: str, public_label: str = "") -> tuple[str, str, str, str]:
        value = normalize(address); custom = self.provider.settings.custom_labels.get(value)
        if custom: return (custom.get("classification", "未知地址"), custom.get("label", "自訂標籤"), "使用者設定", custom.get("confidence", "已確認"))
        if value in PUBLIC_ADDRESS_LABELS: return PUBLIC_ADDRESS_LABELS[value]
        label_lower = public_label.lower()
        if public_label and any(word in label_lower for word in ("dex", "router", "swap")):
            return ("DEX", public_label, "Explorer 公開標籤", "高度可能")
        exchange_words = ("binance", "okx", "bitget", "bybit", "coinbase", "kraken", "mexc", "gate.io", "max exchange")
        if public_label and any(word in label_lower for word in exchange_words):
            return ("交易所", public_label, "Explorer 公開標籤", "高度可能")
        vasp_words = ("moonpay", "simplex", "transak", "banxa", "ramp network")
        if public_label and any(word in label_lower for word in vasp_words):
            return ("入金服務商", public_label, "Explorer 公開標籤", "高度可能")
        if public_label and any(word in label_lower for word in ("relay", "bridge", "solver")):
            return ("Bridge", public_label, "Explorer 公開標籤", "高度可能")
        if value == POLYMARKET_CONDITIONAL_TOKENS: return ("Polymarket", "Polymarket Conditional Tokens", "內建公開合約清冊", "已確認")
        if value == PUSD: return ("Polymarket", "Polymarket pUSD", "內建公開合約清冊", "已確認")
        if value in (CTF_EXCHANGE, NEG_RISK_EXCHANGE): return ("Polymarket", "Polymarket Exchange", "內建公開合約清冊", "已確認")
        if value == COLLATERAL_ONRAMP: return ("Polymarket", "Polymarket Collateral Onramp", "內建公開合約清冊", "已確認")
        if value == PUSD_SETTLEMENT: return ("Polymarket", "Polymarket pUSD Settlement", "內建公開合約清冊", "已確認")
        if value == RELAY_DEPOSITORY: return ("Bridge", "Relay Depository", "Relay 公開索引", "已確認")
        if value in (USDC_E, USDC): return ("Token 合約", "USDC", "內建公開合約清冊", "已確認")
        if value == USDT: return ("Token 合約", "USDT", "內建公開合約清冊", "已確認")
        return ("未知地址", "", "無公開標籤", "未知")
    def analyze(
        self,
        query: str,
        max_hops: int | None = None,
        as_of_time: float | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        time_filter_raw: str = "",
    ) -> AnalysisResult:
        query = self.validate(query); result = AnalysisResult(query=query); hops = max(1, min(max_hops or self.provider.settings.max_hops, 5))
        result.sources = [f"Polygon RPC：{self.provider.settings.rpc_url}", f"Explorer：{self.provider.settings.blockscout_url}"]
        if TX_HASH.fullmatch(query):
            tx = self.provider.transaction(query)
            if not tx: raise ProviderError("找不到此交易，請確認網路為 Polygon 且雜湊正確。")
            receipt = self.provider.receipt(query) or {}; timestamp = timestamp_to_text(self.provider.block_timestamp(tx.get("blockNumber", "0x0"))) if tx.get("blockNumber") else "待確認"
            result.transactions.append({"hash":tx.get("hash", ""),"time":timestamp,"from":tx.get("from", ""),"to":tx.get("to", ""),"value_matic":f"{hex_int(tx.get('value'))/10**18:.8f}"})
            result.transfers.extend(self._parse_receipt(query, receipt, timestamp)); seeds = [tx.get("from", ""), tx.get("to", "")]
            result.summary.append(f"交易：{query}；狀態：{'成功' if receipt.get('status') == '0x1' else '未確認或失敗'}")
        else: seeds = [query]; result.summary.append(f"地址：{query}；追蹤深度：{hops} 跳")
        if as_of_time or time_filter_raw:
            result.warnings.append("時間錨定目前僅適用於 Polymarket 資金鏈分析模式；本次一般地址追蹤係以最新公開鏈上紀錄展開。")
        result.steps = self._trace(seeds, hops)
        if not result.steps: result.warnings.append("未取得可延伸的公開交易紀錄。公共 API 可能限流、資料尚未索引，或地址沒有近期交易。")
        result.warnings.append("本工具僅呈現公開鏈上關聯；地址、資金流與交易所標籤均不等於自然人身分或帳戶控制權。")
        return result

    def analyze_polymarket_funding(
        self,
        tx_hash: str,
        max_hops: int | None = None,
        as_of_time: float | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        time_filter_raw: str = "",
        csv_path: str = "",
    ) -> AnalysisResult:
        """由一筆下注交易或錢包地址反推 pUSD 扣款地址及其可見的 USDC／pUSD 補款。"""
        tx_hash = self.validate(tx_hash)
        hops = max(1, min(max_hops or self.provider.settings.max_hops, 5))
        if ADDRESS.fullmatch(tx_hash):
            return self._analyze_polymarket_address(
                tx_hash,
                hops,
                as_of_time=as_of_time,
                start_time=start_time,
                end_time=end_time,
                time_filter_raw=time_filter_raw,
                csv_path=csv_path,
            )
        self.progress("正在解析下注交易與 pUSD 扣款…")
        tx = self.provider.transaction(tx_hash)
        if not tx: raise ProviderError("找不到此交易，請確認為 Polygon 交易雜湊。")
        receipt = self.provider.receipt(tx_hash) or {}; raw_time = self.provider.block_timestamp(tx.get("blockNumber", "0x0")); timestamp = timestamp_to_text(raw_time)
        result = AnalysisResult(query=tx_hash); result.sources = [f"Polygon RPC：{self.provider.settings.rpc_url}", f"Explorer：{self.provider.settings.blockscout_url}"]
        result.add_evidence("polygon_target_transaction", f"Polygon RPC Transaction：{tx_hash}", tx)
        result.add_evidence("polygon_target_receipt", f"Polygon RPC Receipt：{tx_hash}", receipt)
        transfers = self._parse_receipt(tx_hash, receipt, timestamp); result.transfers = transfers
        debits = [item for item in transfers if item.token == "pUSD" and normalize(item.from_address) not in POLYMARKET_INTERNAL | {ZERO_ADDRESS}]
        if not debits:
            result.warnings.append("此交易 Receipt 中未找到可辨識的目標 pUSD 扣款；可能是不同代幣版本、批次事件或 Explorer 尚未完整解碼。")
            return result
        payer_amounts: dict[str, float] = {}
        payer_display: dict[str, str] = {}
        for debit in debits:
            key = normalize(debit.from_address)
            try: payer_amounts[key] = payer_amounts.get(key, 0) + float(debit.amount)
            except ValueError: payer_amounts.setdefault(key, 0)
            payer_display[key] = debit.from_address
        payers = sorted(payer_amounts, key=payer_amounts.get, reverse=True)[:10]
        result.summary = [f"目標下注 Tx：{tx_hash}", f"下注時間：{timestamp or '未取得'}", f"偵測到 {len(payers)} 個實際 pUSD 扣款候選（批次撮合會同時包含多名交易者）："]
        result.summary.extend(f"- {payer_display[key]}｜扣款合計 {payer_amounts[key]:.6f} pUSD" for key in payers)
        from .betting import decode_polymarket_trade
        from .orbscan import fetch_orbscan_trade
        for key in payers:
            payer = payer_display[key]
            trade = decode_polymarket_trade(receipt, payer, tx_hash, timestamp)
            if trade:
                orb_info = fetch_orbscan_trade(
                    tx_hash=tx_hash,
                    target_address=payer,
                    api_url=getattr(self.provider.settings, "orbscan_api_url", ""),
                    receipt=receipt,
                    timestamp=timestamp,
                )
                if orb_info:
                    trade.market_title = orb_info.market_title
                    trade.outcome = orb_info.outcome
                    trade.trader_role = orb_info.role
                    trade.fee = orb_info.fee
                    trade.value = orb_info.value
                    trade.enrichment_source = orb_info.source
                result.steps.insert(0, TraceStep(
                    "Polymarket 投注", 0, tx_hash, timestamp,
                    trade.collateral_token, trade.collateral_amount,
                    payer, POLYMARKET_CONDITIONAL_TOKENS, payer,
                    "Polymarket", "Polymarket 投注", "內建公開合約清冊", "已確認", "直接交易",
                    trade.summary_text(), chain="Polygon", block_number=str(hex_int(tx.get("blockNumber"))),
                    log_index=trade.log_index, path_role="內部", event_role="投注買賣",
                    explorer_url=f"https://polygonscan.com/tx/{tx_hash}", chain_id=137,
                    evidence_source=orb_info.source if orb_info else "RPC Receipt 條件代幣解碼",
                    trade_info=trade.to_dict(),
                ))
                result.summary.insert(2, f"下注行為解碼：{payer} 執行 {trade.summary_text()}")
        result.summary.append("以下逐一追查各扣款候選的下注前補款；不得在未比對目標錢包前任選其中一人。")
        cutoff = event_timestamp(raw_time); cutoff_block = hex_int(tx.get("blockNumber"))
        relay_found = False
        relay_attempts = 0
        relay_matches = 0
        any_candidates = False
        any_underlying = False
        history_count = 0
        candidate_count = 0
        underlying_count = 0
        for index, payer_key in enumerate(payers, start=1):
            payer = payer_display[payer_key]
            self.progress(f"正在追查第 {index}/{len(payers)} 個 pUSD 扣款候選…")
            try: history = self.provider.address_token_transfers(payer)
            except ProviderError as exc:
                result.warnings.append(f"無法取得扣款地址 {payer} 的 Token Transfers：{exc}"); continue
            history_count += len(history)
            result.add_evidence("polygon_address_token_transfers", f"Explorer Token Transfers：{payer}", history)
            if self.provider.token_history_truncated:
                page_limit = getattr(getattr(self.provider, "settings", None), "max_history_pages", 6)
                event_limit = max(1, int(page_limit)) * 50
                result.warnings.append(
                    f"地址 {payer} 已達公開 Explorer 一般索引查詢上限（最多約 {event_limit} 筆）；更早補款可能未納入。"
                )
            candidates = self._funding_candidates(history, payer, cutoff)[:20]
            candidate_count += len(candidates)
            # 大量批次撮合可能含有多名高頻交易者。先以Explorer快速掃過全部候選，
            # 僅在最後仍未命中Relay時啟用較慢的RPC Logs備援，避免介面長時間無回應。
            if not candidates and cutoff_block and index == len(payers) and relay_matches == 0:
                try:
                    rpc_history = self.provider.inbound_token_logs(payer, [PUSD, USDC_E, USDC], cutoff_block)
                    candidates = self._funding_candidates(rpc_history, payer, cutoff)[:20]
                    if candidates:
                        result.warnings.append(f"Explorer未收錄地址 {payer} 的近期補款；本次已改由Polygon RPC Logs補足。")
                except ProviderError as exc:
                    result.warnings.append(f"RPC Logs備援查詢失敗（{payer}）：{exc}")
            any_candidates = any_candidates or bool(candidates)
            for candidate in candidates:
                kind, label, source, confidence = self.classify(candidate["from"], candidate.get("label", ""))
                note = f"扣款候選：{payer}。{candidate['note']}"
                result.steps.append(TraceStep("下注前補款", 1, candidate["hash"], timestamp_to_text(candidate["time"]), candidate["token"], candidate["amount"], candidate["from"], payer, candidate["from"], kind, label, source, confidence, "僅資金關聯", note))
            self.progress("正在解析 pUSD 鑄造交易中的底層 USDC…")
            underlying = self._pusd_underlying_sources(candidates, cutoff, result)
            underlying_count += len(underlying)
            any_underlying = any_underlying or bool(underlying)
            for item in underlying:
                kind, label, label_source, confidence = self.classify(item["from"], item.get("label", ""))
                confirmed = item.get("attribution_confirmed") == "true"
                note = (f"對應扣款候選 {payer}；已依同筆交易的目標鑄造地址、金額及 Log 順序唯一配對。"
                        if confirmed else f"對應扣款候選 {payer}；同筆批次交易存在多筆可能來源，歸屬待確認，不向上延伸。")
                result.steps.append(TraceStep("pUSD 底層入金", 2, item["hash"], timestamp_to_text(item["time"]), item["token"], item["amount"], item["from"], item["to"], item["from"], kind, label, label_source, confidence if confirmed else "未知", "僅資金關聯" if confirmed else "關聯不足", note))
            for item in [value for value in underlying if value.get("attribution_confirmed") == "true"]:
                if relay_attempts >= 10:
                    break
                relay_attempts += 1
                if self._append_relay_path(result, item, hops):
                    relay_matches += 1
            external_sources = [item["from"] for item in candidates if normalize(item["from"]) not in POLYMARKET_INTERNAL | {ZERO_ADDRESS}][:5]
            if not underlying:
                result.steps.extend(self._trace_token_upstream(external_sources, cutoff, hops))
        relay_found = relay_matches > 0
        result.summary.append(
            f"查詢範圍：共讀取 {history_count} 筆近期 Token Transfer、辨識 {candidate_count} 筆補款候選與 "
            f"{underlying_count} 筆底層資產候選；已嘗試 {relay_attempts} 筆並展開 {relay_matches} 條 Relay 路徑。"
        )
        if relay_attempts >= 10 and underlying_count > relay_attempts:
            result.warnings.append("底層入金候選超過本次 10 筆 Relay 查詢上限；尚有候選未展開，不代表其沒有跨鏈或交易所關聯。")
        if not any_candidates: result.warnings.append("在 Explorer 回傳的近期 Token Transfers 中，沒有找到下注前可辨識的 pUSD／USDC 補款；請增加 API 頁數或匯入 USDC 明細。")
        result.warnings.append("Polymarket Exchange、Onramp、Reward Distributor、零地址鑄造均屬平台內部或協定事件，不可直接當成外部入金或交易所來源。")
        if any_underlying and not relay_found:
            result.warnings.append("已找到pUSD底層資金地址，但未在Relay公開索引中命中跨鏈請求；將其保留為外部資金候選，不推測來源鏈。")
        result.warnings.append("命中交易所公開標籤只代表資金關聯；KYC、提幣與登入資料必須依正式程序向服務商調取。")
        return result

    def _analyze_polymarket_address(
        self,
        address: str,
        hops: int,
        as_of_time: float | None = None,
        start_time: float | None = None,
        end_time: float | None = None,
        time_filter_raw: str = "",
        csv_path: str = "",
    ) -> AnalysisResult:
        """由 Polymarket 地址的近期或歷史指定時間 pUSD 入金反查鑄造、Relay 與來源鏈。"""
        self.progress("正在查詢地址 pUSD／USDC 入金…")
        result = AnalysisResult(query=address)
        result.sources = [
            f"Polygon RPC：{self.provider.settings.rpc_url}",
            f"Explorer：{self.provider.settings.blockscout_url}",
        ]

        cutoff = as_of_time or end_time or 0.0
        start_block = None
        end_block = None

        if cutoff > 0:
            try:
                end_block = self.provider.timestamp_to_block_number(cutoff)
            except Exception as exc:
                raise ProviderError(f"歷史時間轉區塊失敗（{exc}）；為維護證據真實性，已終止查詢，不自動改查最新資料。") from exc

        if start_time and start_time > 0:
            try:
                start_block = self.provider.timestamp_to_block_number(start_time)
            except Exception as exc:
                raise ProviderError(f"起始時間轉區塊失敗（{exc}）；已終止查詢。") from exc

        end_info = self.provider.block_info(end_block) if end_block else {}
        end_block_hash = end_info.get("hash", "")
        end_block_timestamp = end_info.get("timestamp", 0.0)

        if cutoff > 0 or (start_time and start_time > 0):
            result.time_filter = {
                "raw_input": time_filter_raw,
                "timezone": "Asia/Taipei (UTC+8)",
                "cutoff_time": cutoff,
                "start_time": start_time or 0,
                "cutoff_text": timestamp_to_text(cutoff) if cutoff else "",
                "start_text": timestamp_to_text(start_time) if start_time else "",
                "end_block": end_block,
                "end_block_hash": end_block_hash,
                "end_block_timestamp": end_block_timestamp,
                "start_block": start_block,
                "resolution_method": "strict_floor_binary_search",
            }

        csv_data: dict[str, Any] = {}
        if csv_path:
            from .csv_loader import inspect_and_load_polygonscan_csv
            self.progress(f"正在讀取歷史 CSV 索引：{csv_path}…")
            csv_data = inspect_and_load_polygonscan_csv(csv_path, address)
            result.csv_index = csv_data
            result.sources.append(
                f"歷史索引：使用者提供之 PolygonScan CSV（檔名：{csv_data['file_name']}，SHA-256：{csv_data['sha256'][:16]}…）"
            )
            result.summary.append(
                f"【歷史 CSV 索引】已載入 {csv_data['file_name']}（共 {csv_data['total_rows']} 筆，時間跨度 {csv_data['time_range']}）；"
                f"保守篩選出 {csv_data['mint_candidates_count']} 筆零地址鑄造候選與 {csv_data['external_candidates_count']} 筆外部轉入候選。"
            )
            if csv_data.get("is_truncated"):
                result.warnings.append(
                    f"匯入之 CSV 記錄達 {csv_data['total_rows']} 筆（疑似觸及 PolygonScan 單次 5,000 筆匯出上限）；"
                    "較早或較晚的歷史金流可能未完整包含，建議在區塊鏈瀏覽器指定日期區間分段下載。"
                )
            result.warnings.append(
                "【法證定位】本案採用「使用者提供之歷史 CSV 索引 ＋ Polygon RPC 鏈上即時核實」；"
                "CSV 僅作為歷史索引以選取候選雜湊；各步驟是否完成 Receipt、原始 Logs 或 Relay 核對，"
                "應以該步驟的「證據來源」與「配對狀態」個別判讀。"
            )
            all_candidates = csv_data.get("candidates", [])
            has_valid_reserve = any(str(c.get("token", "")).strip().lower() in {"pusd", "usdc", "usdc.e", "usdt"} for c in all_candidates)
            if csv_data.get("is_truncated") or not has_valid_reserve:
                result.warnings.append(
                    "【歷史 CSV 限制補強】匯入之 CSV 記錄達單次匯出上限（5,000 筆），時間跨度可能未涵蓋全部歷史記錄；系統已自動啟用核心儲備代幣定向檢索進行歷史入金補強。"
                )
                try:
                    targeted = self.provider.targeted_inbound_token_transfers(address)
                    if targeted:
                        targeted_cands = self._funding_candidates(targeted, address, cutoff)
                        seen_cand_hashes = {normalize(c.get("hash", "")) for c in all_candidates}
                        for tc in targeted_cands:
                            h_norm = normalize(tc.get("hash", ""))
                            if h_norm not in seen_cand_hashes:
                                seen_cand_hashes.add(h_norm)
                                all_candidates.append(tc)
                except Exception:
                    pass

            sorted_candidates = self._prioritize_candidates(all_candidates)
            if cutoff > 0:
                candidates = [c for c in sorted_candidates if not c.get("time") or event_timestamp(c["time"]) < cutoff][:20]
            else:
                candidates = sorted_candidates[:20]
            history = []
            redemption_hashes = set()
            history_truncated = csv_data.get("is_truncated", False)
            scanned_count = csv_data.get("total_rows", 0)
            min_block = None
            max_block = None
        else:
            try:
                if start_block is not None or end_block is not None:
                    try:
                        history = self.provider.address_token_transfers(address, start_block=start_block, end_block=end_block)
                    except TypeError:
                        history = self.provider.address_token_transfers(address)
                else:
                    history = self.provider.address_token_transfers(address)
            except ProviderError as exc:
                raise ProviderError(f"無法取得此地址的 Token Transfers：{exc}") from exc

            # 保存一般歷史查詢的覆蓋範圍。後續每種代幣的定向查詢會更新
            # Provider 的暫存統計，不可讓它覆寫本次一般查詢的稽核資料。
            history_truncated = getattr(self.provider, "token_history_truncated", False)
            scanned_count = getattr(self.provider, "token_history_scanned_count", len(history))
            min_block = getattr(self.provider, "token_history_min_block", None)
            max_block = getattr(self.provider, "token_history_max_block", None)

            # 依設定清冊並行查詢核心儲備代幣，避免高頻撮合或無關代幣事件
            # 將較早的本金入金排除在一般歷史查詢範圍之外。
            try:
                targeted = self.provider.targeted_inbound_token_transfers(address, start_block=start_block, end_block=end_block)
                if targeted:
                    seen_keys = {
                        (str(h.get("transaction_hash") or h.get("tx_hash") or h.get("hash") or "").lower(),
                         str(h.get("log_index") or h.get("index") or ""))
                        for h in history
                    }
                    for t_ev in targeted:
                        t_key = (
                            str(t_ev.get("transaction_hash") or t_ev.get("tx_hash") or t_ev.get("hash") or "").lower(),
                            str(t_ev.get("log_index") or t_ev.get("index") or "")
                        )
                        if t_key not in seen_keys:
                            seen_keys.add(t_key)
                            history.append(t_ev)
            except Exception:
                pass

            if result.time_filter:
                result.time_filter["scanned_transfer_count"] = scanned_count
                result.time_filter["is_truncated"] = history_truncated
                result.time_filter["min_block_scanned"] = min_block
                result.time_filter["max_block_scanned"] = max_block
                if history_truncated and min_block:
                    result.time_filter["unscanned_range"] = f"1 ~ {min_block - 1}"

            if not history and end_block:
                try:
                    self.progress("Explorer 未收錄該歷史區段，啟動 RPC Logs 深度打撈…")
                    history = self.provider.inbound_token_logs(address, [PUSD, USDC_E, USDC], to_block=end_block)
                    if history:
                        result.warnings.append("該歷史區段資料已改由 Polygon RPC Logs 深度打撈取得。")
                except Exception as exc:
                    result.warnings.append(f"RPC Logs 深度打撈失敗：{exc}")

            result.add_evidence("polygon_address_token_transfers", f"Explorer Token Transfers：{address}", history)
            redemption_hashes = self._redemption_tx_hashes(history, address)
            all_candidates = self._funding_candidates(history, address, cutoff)
            prioritized_candidates = self._prioritize_candidates(all_candidates)
            candidates = [item for item in prioritized_candidates if normalize(item["hash"]) not in redemption_hashes][:20]

        summary_header = f"Polymarket 地址：{address}"
        if cutoff > 0:
            date_label = result.time_filter.get("cutoff_text") or time_filter_raw
            blk_label = f"（區塊 <= {end_block}）" if end_block else ""
            summary_header += f" [時間錨定：{date_label} 之前 {blk_label}]"
            result.summary.append(f"【歷史時間錨定】已鎖定 {date_label} 之前發生的資金流；排除該日之後的無關金流。")

        result.summary.append(summary_header)
        result.summary.append(f"找到 {len(candidates)} 筆入金候選；將由指定時間紀錄反查鑄造與 Relay 來源。")
        if redemption_hashes:
            result.summary.append(f"另辨識 {len(redemption_hashes)} 筆 pUSD 贖回／出金交易，已與入金候選分開。")
        for candidate in candidates:
            kind, label, source, confidence = self.classify(candidate["from"], candidate.get("label", ""))
            ev_source = "使用者提供之 CSV 歷史索引（待鏈上核實）" if csv_path else "Explorer Token Transfers 索引"
            result.steps.append(TraceStep(
                "地址入金", 1, candidate["hash"], timestamp_to_text(candidate["time"]),
                candidate["token"], candidate["amount"], candidate["from"], address,
                candidate["from"], kind, label, source, confidence, "僅資金關聯", candidate["note"],
                chain="Polygon", block_number=candidate.get("block_number", ""), log_index=candidate.get("log_index", ""),
                path_role="入金", event_role="補款", explorer_url=f"https://polygonscan.com/tx/{candidate['hash']}",
                chain_id=137, evidence_source=ev_source,
            ))
        self.progress("正在解析 pUSD 鑄造交易中的底層 USDC…")
        underlying = self._pusd_underlying_sources(candidates, cutoff, result)
        for item in underlying:
            kind, label, source, confidence = self.classify(item["from"], item.get("label", ""))
            confirmed = item.get("attribution_confirmed") == "true"
            confirmed_note = (
                f"地址 {address} 的 pUSD 鑄造已依目標地址、金額及 Log 順序唯一配對到底層資產（可確認同筆交易中支付底層 USDC.e 的鏈上來源地址，但不等於確認自然人或帳戶控制者）。"
                if confirmed else "同筆批次交易存在多筆可能底層來源；歸屬待確認，本工具不向上延伸此候選。"
            )
            ev_decoding_source = "RPC Receipt Transfer 解碼（鏈上核實）" if csv_path else "RPC Receipt Transfer 解碼"
            result.steps.append(TraceStep(
                "pUSD 底層入金", 2, item["hash"], timestamp_to_text(item["time"]),
                item["token"], item["amount"], item["from"], item["to"], item["from"],
                kind, label, source, confidence if confirmed else "未知", "僅資金關聯" if confirmed else "關聯不足",
                confirmed_note,
                chain="Polygon", block_number=item.get("block_number", ""), log_index=item.get("log_index", ""),
                path_role="入金", event_role="底層資產投入", explorer_url=f"https://polygonscan.com/tx/{item['hash']}",
                chain_id=137, evidence_source=ev_decoding_source, token_contract=USDC_E if item["token"] == "USDC.e" else USDC,
            ))
        relay_matches = 0
        confirmed_underlying = [item for item in underlying if item.get("attribution_confirmed") == "true"]
        relay_targets = confirmed_underlying[:10]
        for idx, item in enumerate(relay_targets, start=1):
            self.progress(f"正在檢索第 {idx}/{len(relay_targets)} 筆 Relay 跨鏈路徑與來源鏈（{item.get('amount', '')} {item.get('token', '')}）…")
            if self._append_relay_path(result, item, hops):
                relay_matches += 1

        # 針對直接由外部轉入目標地址的候選（非平台內部轉帳或零地址鑄造），嘗試穿透跨鏈或同鏈 Relay 來源
        direct_inbound_candidates = [
            candidate for candidate in candidates
            if normalize(candidate["from"]) not in POLYMARKET_INTERNAL | {ZERO_ADDRESS}
        ]
        matched_direct_hashes: set[str] = set()
        for item in direct_inbound_candidates[:10]:
            # 先核對 Polygon 同鏈 Relay，避免跨鏈查詢先寫入不適用的失敗警告。
            if self._append_same_chain_relay_path(result, item, address, hops):
                relay_matches += 1
                matched_direct_hashes.add(item["hash"])
            elif self._append_relay_path(result, item, hops):
                relay_matches += 1
                matched_direct_hashes.add(item["hash"])

        if matched_direct_hashes:
            # 若直接入金已被確認為 Relay 目的鏈補款，移除前面未分類的同筆「地址入金」步驟，避免重複
            result.steps = [
                step for step in result.steps
                if not (step.direction == "地址入金" and step.tx_hash in matched_direct_hashes)
            ]

        relay_found = relay_matches > 0
        result.summary.append(
            f"查詢範圍：取得 {len(history)} 筆近期 Token Transfer、辨識 {len(candidates)} 筆入金候選；"
            f"{len(confirmed_underlying)} 筆底層資產可唯一配對，已展開 {relay_matches} 條 Relay 路徑。"
        )
        if len(confirmed_underlying) > 10:
            result.warnings.append(f"可唯一配對的底層入金共 {len(confirmed_underlying)} 筆，本次僅展開前 10 筆 Relay 路徑。")
        if history_truncated:
            unscanned_text = f"（已掃描區塊 {min_block}～{max_block}，區塊 1～{min_block - 1} 尚未翻閱）" if min_block else ""
            page_limit = getattr(getattr(self.provider, "settings", None), "max_history_pages", 6)
            event_limit = max(1, int(page_limit)) * 50
            result.warnings.append(
                f"地址 Token Transfer 已達一般索引查詢上限（最多約 {event_limit} 筆；實際讀取 {scanned_count} 筆）"
                f"{unscanned_text}；較早的入金或出金可能未完整納入。"
            )
        result.steps.extend(self._address_outflow_steps(history, address, redemption_hashes))
        betting_steps = self._address_betting_steps(
            history,
            address,
            redemption_hashes,
            csv_data.get("betting_candidates", []) if csv_data else None,
        )
        result.steps.extend(betting_steps)
        if betting_steps:
            result.summary.append(f"另辨識 {len(betting_steps)} 筆 Polymarket 投注交易；題目與選項僅在語意資料可精確配對時顯示。")
            for step in betting_steps[:10]:
                info = step.trade_info
                result.summary.append(
                    f"投注明細：{info.get('market_title') or '題目待解析'}｜"
                    f"{info.get('action') or '行為待解析'} {info.get('outcome') or '選項待解析'}｜"
                    f"投入 {info.get('collateral_amount') or step.amount} {info.get('collateral_token') or step.token}｜"
                    f"份額 {info.get('shares') or '待解析'}｜"
                    f"Tx：{step.tx_hash}"
                )
        from .outflow import append_relay_outflows
        append_relay_outflows(self, result, hops)
        has_pusd = any(normalize(c["from"]) in POLYMARKET_INTERNAL | {ZERO_ADDRESS} for c in candidates)
        if not candidates:
            result.warnings.append("近期公開 Token Transfers 中未找到此地址的 pUSD／USDC 入金；可能超出索引範圍或地址並非交易用錢包。")
        elif has_pusd and not underlying:
            result.warnings.append("已找到 pUSD 入金，但尚未從同筆交易辨識到底層 USDC／USDC.e。")
        elif not relay_found:
            result.warnings.append("已找到入金候選，但未命中 Relay 公開索引；不推測來源鏈。")
        if redemption_hashes:
            result.warnings.append("已將同筆交易內的 pUSD 贖回、穩定幣入帳及 Relay 轉出整組判讀為出金，未列為外部補款。")
        result.warnings.append("Polymarket 合約、零地址鑄造、Relay Solver 均屬協定流程，不可直接認定為交易所來源。")
        result.warnings.append("命中交易所公開標籤只代表資金關聯；KYC、提幣與登入資料必須依正式程序向服務商調取。")
        principal_vasp = [
            step for step in result.steps
            if step.path_role == "入金" and step.line_style == "solid"
            and step.classification in {"交易所", "入金服務商", "VASP"}
            and step.event_role != "手續費供資"
        ]
        auxiliary_vasp = [
            step for step in result.steps
            if step.path_role == "入金" and step.line_style in {"dashed", "dotted"}
            and step.classification in {"交易所", "入金服務商", "VASP"}
        ]
        if principal_vasp:
            labels = "、".join(dict.fromkeys(step.label for step in principal_vasp if step.label))
            result.summary.append(
                f"【入金來源結論】逐筆本金主線命中公開交易所／VASP 標籤：{labels}；"
                "這證明資金路徑直接關聯，不等於直接確認特定自然人身分。"
            )
        else:
            auxiliary_labels = "、".join(dict.fromkeys(step.label for step in auxiliary_vasp if step.label))
            relay_note = "（本金主線主要經由跨鏈協議或兌換合約中繼）；" if relay_found else ""
            suffix = (
                f"另命中 {auxiliary_labels}，但均屬較早資金池或原生幣供資輔助線索，不是本案本金的逐筆唯一來源。"
                if auxiliary_labels else "目前亦無可列為交易所來源的輔助標籤紀錄。"
            )
            result.summary.append(f"【入金來源結論】逐筆本金主線尚未命中可確認的交易所／VASP 公開標籤；{relay_note}{suffix}")
        result.warnings = list(dict.fromkeys(result.warnings))
        result.sources = list(dict.fromkeys(result.sources))
        return result
    def _prioritize_candidates(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """針對入金候選進行三層法證優先級排序：
        - 第一層：已確認之中心化交易所／VASP 公開出金標籤
        - 第二層：核心儲備代幣（Native USDC, USDT, USDC.e 等）之外部直接轉入
        - 第三層：未具公開標籤之外部個人／中繼錢包轉入
        - 備選層：平台內部撮合合約結算
        同層級內依時間由新至舊倒序。
        """
        core_tokens = getattr(self.provider.settings, "core_inbound_tokens", [
            "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
            "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",
            "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",
            "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",
        ])
        core_token_set = {normalize(t) for t in core_tokens}

        def _cand_prio(item: dict[str, Any]) -> tuple[int, float]:
            frm = normalize(item.get("from", ""))
            lbl = (item.get("label") or "").lower()
            token = (item.get("token") or "").upper()
            contract = normalize(item.get("contract") or "")
            is_internal = frm in POLYMARKET_INTERNAL or frm == ZERO_ADDRESS or "ctfexchange" in lbl or "negrisk" in lbl
            is_exchange = (not is_internal) and any(x in lbl for x in ("binance", "okx", "bitget", "bybit", "coinbase", "kraken", "mexc", "gate.io", "max exchange", "hot wallet", "bito"))
            is_reserve = (token in {"USDC", "USDT", "USDC.E"} or contract in core_token_set) and not is_internal
            if is_exchange:
                prio = 0
            elif is_reserve:
                prio = 1
            elif not is_internal:
                prio = 2
            else:
                prio = 3
            return (prio, -event_timestamp(item.get("time", "")))

        return sorted(items, key=_cand_prio)

    def _funding_candidates(self, events: list[dict[str, Any]], recipient: str, cutoff: float) -> list[dict[str, str]]:
        found = []
        core_tokens = getattr(self.provider.settings, "core_inbound_tokens", [PUSD, USDC, USDC_E, USDT])
        valid_contracts = {normalize(t) for t in core_tokens} | {PUSD, USDC, USDC_E, USDT}
        for event in events:
            token_data = event.get("token", {}) or {}; contract = normalize(token_data.get("address") or token_data.get("address_hash") or event.get("token_address", ""))
            sender, target = event_address(event.get("from")), event_address(event.get("to")); when = event.get("timestamp", event.get("timeStamp", ""))
            if normalize(target) != normalize(recipient) or contract not in valid_contracts: continue
            if cutoff and event_timestamp(when) >= cutoff: continue
            amount_raw = event.get("total", {}).get("value", "") if isinstance(event.get("total"), dict) else event.get("value", "")
            decimals = int(token_data.get("decimals", 6) or 6); amount = f"{int(str(amount_raw) or '0') / 10**decimals:.6f}" if str(amount_raw).isdigit() else str(amount_raw)
            token = "pUSD" if contract == PUSD else ("USDC.e" if contract == USDC_E else ("USDT" if contract == USDT else "USDC"))
            internal = normalize(sender) in POLYMARKET_INTERNAL or normalize(sender) == ZERO_ADDRESS
            note = "平台內部／鑄造事件，已排除為外部來源；應查看同筆 Tx 的 USDC Logs。" if internal else "外部補款候選；需再追此地址的上游 USDC 來源。"
            found.append({"hash": event.get("transaction_hash", event.get("tx_hash", event.get("hash", ""))), "time": str(when), "from": sender, "to": target, "token": token, "contract": contract, "amount": amount, "note": note, "label": event_label(event.get("from")), "block_number": str(event.get("block_number", "")), "log_index": str(event.get("log_index", event.get("index", "")))})
        return sorted(found, key=lambda item: event_timestamp(item["time"]), reverse=True)

    def _redemption_tx_hashes(self, events: list[dict[str, Any]], address: str) -> set[str]:
        """辨識同筆包含 pUSD 轉出、穩定幣入帳與穩定幣轉出的贖回／出金交易。"""
        grouped: dict[str, dict[str, bool]] = {}
        target = normalize(address)
        for event in events:
            tx_hash = normalize(event.get("transaction_hash", event.get("tx_hash", event.get("hash", ""))))
            if not tx_hash:
                continue
            token_data = event.get("token", {}) or {}
            contract = normalize(token_data.get("address") or token_data.get("address_hash") or event.get("token_address", ""))
            sender, recipient = normalize(event_address(event.get("from"))), normalize(event_address(event.get("to")))
            flags = grouped.setdefault(tx_hash, {"pusd_out": False, "stable_in": False, "stable_out": False})
            if contract == PUSD and sender == target:
                flags["pusd_out"] = True
            if contract in {USDC, USDC_E} and recipient == target:
                flags["stable_in"] = True
            if contract in {USDC, USDC_E} and sender == target:
                flags["stable_out"] = True
        return {tx_hash for tx_hash, flags in grouped.items() if all(flags.values())}

    def _address_outflow_steps(self, events: list[dict[str, Any]], address: str, tx_hashes: set[str]) -> list[TraceStep]:
        output: list[TraceStep] = []
        target = normalize(address)
        for event in events:
            tx_hash = normalize(event.get("transaction_hash", event.get("tx_hash", event.get("hash", ""))))
            if tx_hash not in tx_hashes:
                continue
            token_data = event.get("token", {}) or {}
            contract = normalize(token_data.get("address") or token_data.get("address_hash") or event.get("token_address", ""))
            sender, recipient = event_address(event.get("from")), event_address(event.get("to"))
            sender_key, recipient_key = normalize(sender), normalize(recipient)
            if not ((contract == PUSD and sender_key == target) or (contract in {USDC, USDC_E} and sender_key == target)):
                continue
            raw = event.get("total", {}).get("value", "") if isinstance(event.get("total"), dict) else event.get("value", "")
            decimals = int(token_data.get("decimals", 6) or 6)
            try:
                amount = f"{int(str(raw)) / 10**decimals:.6f}"
            except (TypeError, ValueError):
                amount = str(raw)
            token = "pUSD" if contract == PUSD else ("USDC.e" if contract == USDC_E else "USDC")
            is_redeem = contract == PUSD
            classification, label, source, confidence = self.classify(recipient)
            output.append(TraceStep(
                "pUSD 贖回" if is_redeem else ("Relay 出金" if recipient_key == RELAY_DEPOSITORY else "穩定幣轉出"), 1, tx_hash,
                timestamp_to_text(event.get("timestamp", event.get("timeStamp", ""))), token, amount,
                sender, recipient, recipient, classification, label, source, confidence,
                "僅資金關聯", "同筆交易整組 Logs 顯示為 pUSD 贖回後轉出，不列為外部補款。",
                chain="Polygon", block_number=str(event.get("block_number", "")),
                log_index=str(event.get("log_index", event.get("index", ""))), path_role="出金",
                event_role="贖回" if is_redeem else "轉帳",
                explorer_url=f"https://polygonscan.com/tx/{tx_hash}",
                chain_id=137, token_contract=contract, evidence_source="Explorer Token Transfers 索引",
            ))
        return output

    def _address_betting_steps(
        self,
        events: list[dict[str, Any]],
        address: str,
        redemption_hashes: set[str],
        indexed_candidates: list[dict[str, Any]] | None = None,
    ) -> list[TraceStep]:
        """從地址事件中辨識 Polymarket 買入／賣出／兌現交易，並解碼其投注方向、股數與單價。"""
        output: list[TraceStep] = []
        target = normalize(address)
        candidate_hashes: list[tuple[str, str, str]] = []
        seen_hashes: set[str] = set()

        for event in events:
            tx_hash = normalize(event.get("transaction_hash", event.get("tx_hash", event.get("hash", ""))))
            if not tx_hash or tx_hash in redemption_hashes or tx_hash in seen_hashes:
                continue
            token_data = event.get("token", {}) or {}
            contract = normalize(token_data.get("address") or token_data.get("address_hash") or event.get("token_address", ""))
            sender = normalize(event_address(event.get("from")))
            recipient = normalize(event_address(event.get("to")))

            is_pusd_trade = (contract == PUSD and (
                (sender == target and recipient in POLYMARKET_INTERNAL) or
                (recipient == target and sender in POLYMARKET_INTERNAL)
            ))
            is_ctf_event = (contract == POLYMARKET_CONDITIONAL_TOKENS and (sender == target or recipient == target))

            if is_pusd_trade or is_ctf_event:
                seen_hashes.add(tx_hash)
                when = event.get("timestamp", event.get("timeStamp", ""))
                block_num = str(event.get("block_number", ""))
                candidate_hashes.append((tx_hash, str(when), block_num))

        for item in indexed_candidates or []:
            tx_hash = normalize(item.get("hash", ""))
            if not tx_hash or tx_hash in redemption_hashes or tx_hash in seen_hashes:
                continue
            seen_hashes.add(tx_hash)
            candidate_hashes.append((tx_hash, str(item.get("time", "")), str(item.get("block_number", ""))))

        from .betting import decode_polymarket_trade
        from .orbscan import fetch_orbscan_trade

        for tx_hash, when, block_num in candidate_hashes[:10]:
            try:
                receipt = self.provider.receipt(tx_hash) or {}
            except ProviderError:
                continue
            if not receipt:
                continue
            trade = decode_polymarket_trade(receipt, target, tx_hash, timestamp_to_text(when))
            if not trade or trade.action == "UNKNOWN":
                continue
            orb_info = fetch_orbscan_trade(
                tx_hash=tx_hash,
                target_address=target,
                api_url=getattr(self.provider.settings, "orbscan_api_url", ""),
                receipt=receipt,
                timestamp=timestamp_to_text(when),
            )
            if orb_info:
                trade.market_title = orb_info.market_title
                trade.outcome = orb_info.outcome
                trade.trader_role = orb_info.role
                trade.fee = orb_info.fee
                trade.value = orb_info.value
                trade.enrichment_source = orb_info.source
            trade_dict = trade.to_dict()
            is_buy_side = "BUY" in trade.action or "SPLIT" in trade.action or "買" in trade.action
            output.append(TraceStep(
                "Polymarket 投注", 1, tx_hash, timestamp_to_text(trade.timestamp or when),
                trade.collateral_token, trade.collateral_amount,
                target if is_buy_side else POLYMARKET_CONDITIONAL_TOKENS,
                POLYMARKET_CONDITIONAL_TOKENS if is_buy_side else target,
                target, "Polymarket", f"Polymarket {trade.action_label}", "內建公開合約清冊",
                "已確認", "直接交易", trade.summary_text(),
                chain="Polygon", block_number=block_num, log_index=trade.log_index,
                path_role="內部", event_role="投注買賣",
                explorer_url=f"https://polygonscan.com/tx/{tx_hash}",
                chain_id=137,
                evidence_source=orb_info.source if orb_info else "RPC Receipt 條件代幣解碼",
                trade_info=trade_dict,
            ))
        return output

    def _pusd_underlying_sources(self, candidates: list[dict[str, str]], cutoff: float, result: AnalysisResult | None = None) -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        seen: set[tuple[str, str, str, str]] = set()
        mint_candidates = [c for c in candidates if normalize(c["from"]) in POLYMARKET_INTERNAL | {ZERO_ADDRESS} and TX_HASH.fullmatch(c.get("hash") or "")]
        for idx, candidate in enumerate(mint_candidates, start=1):
            tx_hash = candidate["hash"]
            self.progress(f"正在核對第 {idx}/{len(mint_candidates)} 筆 pUSD 鑄造 Receipt（{tx_hash[:10]}…）…")
            try:
                receipt = self.provider.receipt(tx_hash) or {}
            except ProviderError:
                continue
            if result is not None:
                result.add_evidence("polygon_mint_receipt", f"Polygon RPC Receipt：{tx_hash}", receipt)
            timestamp = timestamp_to_text(candidate["time"])
            transfers = self._parse_receipt(tx_hash, receipt, timestamp)
            stable_inputs = [transfer for transfer in transfers
                             if transfer.token in {"USDC", "USDC.e"}
                             and normalize(transfer.to_address) in {PUSD, COLLATERAL_ONRAMP}
                             and normalize(transfer.from_address) not in POLYMARKET_INTERNAL | {ZERO_ADDRESS}]
            target = normalize(candidate.get("to", ""))
            mint_matches = [transfer for transfer in transfers
                            if transfer.token == "pUSD" and normalize(transfer.from_address) == ZERO_ADDRESS
                            and normalize(transfer.to_address) == target]
            if candidate.get("log_index"):
                exact_log = [transfer for transfer in mint_matches if transfer.log_index == candidate["log_index"]]
                if exact_log:
                    mint_matches = exact_log
            try:
                candidate_amount = Decimal(candidate["amount"])
            except (InvalidOperation, ValueError):
                candidate_amount = None
            amount_matches = [transfer for transfer in stable_inputs
                              if candidate_amount is not None and Decimal(transfer.amount) == candidate_amount]
            if len(mint_matches) == 1:
                mint_log = int(mint_matches[0].log_index or -1)
                ordered = [transfer for transfer in amount_matches if int(transfer.log_index or -1) < mint_log]
                if ordered:
                    amount_matches = ordered
            confirmed = len(mint_matches) == 1 and len(amount_matches) == 1
            possible = amount_matches if amount_matches else stable_inputs
            for transfer in possible:
                key = (normalize(transfer.from_address), tx_hash, target, transfer.log_index)
                if key in seen:
                    continue
                seen.add(key)
                found.append({"hash": tx_hash, "time": candidate["time"], "from": transfer.from_address,
                              "to": transfer.to_address, "token": transfer.token, "amount": transfer.amount,
                              "label": "", "block_number": candidate.get("block_number", ""),
                              "log_index": transfer.log_index,
                              "attribution_confirmed": "true" if confirmed else "false"})
        return found

    def _append_relay_path(self, result: AnalysisResult, underlying: dict[str, str], max_hops: int) -> bool:
        """尋找底層資金地址的目的鏈補款，並以Relay索引還原來源鏈交易。"""
        # 1. 優先將當前傳入的交易本身加入候選清單（支援直接透過 Relay 收到穩定幣或該 Tx 本身即為出款的情境）
        inbound: list[dict[str, str]] = [underlying]
        # Relay Router 可能在同一筆交易內先把資產撥入暫存合約，再立即鑄造 pUSD。
        # 直接核對該筆 Receipt，可避免高流量暫存合約的 300 筆歷史上限漏掉目標事件。
        try:
            receipt = self.provider.receipt(underlying["hash"]) or {}
            transfers = self._parse_receipt(underlying["hash"], receipt, timestamp_to_text(underlying["time"]))
            for transfer in transfers:
                same_token = transfer.token.lower().replace(".", "") == underlying["token"].lower().replace(".", "")
                if (normalize(transfer.to_address) == normalize(underlying["from"])
                        and same_token and transfer.amount == underlying["amount"]):
                    inbound.append({
                        "hash": underlying["hash"], "time": underlying["time"],
                        "from": transfer.from_address, "to": transfer.to_address,
                        "token": transfer.token, "amount": transfer.amount,
                        "label": "RelayRouterV3",
                    })
        except ProviderError:
            pass
        try:
            history = self.provider.address_token_transfers(underlying["from"])
        except ProviderError as exc:
            if len(inbound) <= 1:
                result.warnings.append(f"無法查詢底層資金地址 {underlying['from']}：{exc}")
                return False
            history = []
        history_inbound = self._generic_inbound_candidates(
            history, underlying["from"], event_timestamp(underlying["time"]),
            token_symbol=underlying["token"],
        )
        seen_candidates = {(item["hash"], normalize(item["from"]), normalize(item["to"]), item["amount"]) for item in inbound}
        for item in history_inbound:
            key = (item["hash"], normalize(item["from"]), normalize(item["to"]), item["amount"])
            if key not in seen_candidates:
                inbound.append(item)
                seen_candidates.add(key)
        inbound = inbound[:10]
        for candidate in inbound:
            self.progress(f"正在比對 Relay 跨鏈紀錄：{candidate['hash'][:14]}…")
            try:
                matched = self.provider.relay_request_by_hash(candidate["hash"])
            except ProviderError as exc:
                result.warnings.append(f"Relay公開索引查詢失敗：{exc}")
                return False
            if not matched:
                continue
            result.add_evidence("relay_request", f"Relay Request：{candidate['hash']}", matched)
            details = self._relay_details(matched)
            if (not details or matched.get("request", {}).get("status") != "success"
                    or not exact_pair(matched, details["tx_hash"], candidate["hash"])):
                result.warnings.append(f"Relay {candidate['hash']} 未取得唯一且成功的來源／目的配對，保留斷點。")
                continue
            kind, label, source, confidence = self.classify(candidate["from"], candidate.get("label", "") or "Relay: Solver")
            result.steps.append(TraceStep("Relay 目的鏈補款", 3, candidate["hash"], timestamp_to_text(candidate["time"]), candidate["token"], candidate["amount"], candidate["from"], candidate["to"], candidate["from"], kind, label or "Relay Solver", source if label else "Relay公開索引", confidence, "僅資金關聯", "Relay Solver在Polygon目的鏈提供資金；此地址不是原始入金者。"))
            destination = result.steps[-1]
            destination.relay_request_id = details["request_id"]
            destination.relay_leg = "destination"
            destination.pair_verified = True
            destination.chain, destination.chain_id = "Polygon", 137
            destination.evidence_source = "Explorer Token Transfers／Relay Request 精確配對"
            destination.explorer_url = explorer_url(137, candidate["hash"])
            chain_name = CHAIN_NAMES.get(details["chain_id"], f"chainId {details['chain_id']}")
            result.summary.extend([
                f"Relay 來源鏈：{chain_name}",
                f"Relay 來源地址：{details['depositor']}",
                f"Relay 來源資產：{details['amount']} {details['symbol']}；來源Tx：{details['tx_hash']}",
            ])
            result.sources.append(f"Relay Requests API v{matched['version']}：https://api.relay.link")
            result.steps.append(TraceStep("Relay 來源鏈", 3, details["tx_hash"], timestamp_to_text(details["timestamp"]), f"{details['symbol']}（{chain_name}）", details["amount"], details["depositor"], details["depository"], details["depositor"], "外部錢包", "Relay來源鏈入金者", "Relay公開索引", "已確認", "僅資金關聯", f"Relay請求 {details['request_id']} 對應的來源鏈交易；此鏈上地址不等於自然人身分。"))
            origin = result.steps[-1]
            origin.relay_request_id, origin.relay_leg = details["request_id"], "source"
            origin.pair_verified = True
            origin.chain, origin.chain_id = chain_name, details["chain_id"]
            origin.token_contract = details["contract"]
            origin.evidence_source = "Relay Request 精確配對（協定索引）"
            origin.explorer_url = explorer_url(details["chain_id"], details["tx_hash"])
            if matched["version"] == 2:
                result.warnings.append("Relay免金鑰v2介面預定於2026-11-24停用；請於設定填入Relay API Key以改用v3。")
            if max_hops >= 3:
                self.progress(f"正在追蹤{chain_name}來源錢包的上游Token入帳…")
                self._append_source_chain_upstream(result, details, max_hops)
            return True
        return False

    def _append_same_chain_relay_path(
        self,
        result: AnalysisResult,
        candidate: dict[str, str],
        recipient_address: str,
        max_hops: int,
    ) -> bool:
        """比對並展開 Polygon 同鏈 Relay 轉換路徑（如 USDC 經由 RelayRouterV3 轉為 pUSD 撥付）。"""
        tx_hash = candidate.get("hash", "")
        if not tx_hash:
            return False
        self.progress(f"正在核對同鏈 Relay Request：{tx_hash[:14]}…")
        try:
            matched = self.provider.relay_request_by_hash(tx_hash)
        except ProviderError as exc:
            result.warnings.append(f"同鏈 Relay 查詢失敗：{exc}")
            return False
        if not matched:
            return False

        try:
            receipt = self.provider.receipt(tx_hash) or {}
        except ProviderError:
            receipt = {}
        receipt_transfers = self._parse_receipt(tx_hash, receipt, timestamp_to_text(candidate.get("time", "")))
        sc_info = same_chain_request_match(
            matched,
            tx_hash,
            recipient_address,
            expected_output_token=PUSD,
            receipt_transfers=receipt_transfers,
        )
        if not sc_info:
            return False

        result.add_evidence("relay_request", f"Relay Request（同鏈）：{tx_hash}", matched)
        result.add_evidence("polygon_same_chain_relay_receipt", f"Polygon RPC Receipt：{tx_hash}", receipt)
        req_id = sc_info["request_id"]
        sender = sc_info["sender"]
        in_amount = sc_info["input_amount"]
        in_symbol = sc_info["input_symbol"]
        out_amount = sc_info["output_amount"]
        out_symbol = sc_info["output_symbol"]
        dest_tx = sc_info["destination_tx_hash"]
        origin_tx = sc_info["origin_tx_hash"]
        when_text = timestamp_to_text(sc_info["timestamp"] or candidate.get("time"))

        router_addr = candidate.get("from", "")
        router_kind, router_label, router_source, router_conf = self.classify(router_addr, candidate.get("label", "") or "RelayRouterV3")

        # 1. 目的端同鏈撥付（實線）
        dest_note = f"Relay 請求 {req_id} 於 Polygon 同鏈轉換撥付 {out_amount} {out_symbol} 至目標地址；已由 Request 資料核實。"
        dest_step = TraceStep(
            "Relay 目的鏈補款", 2, dest_tx, when_text,
            out_symbol, out_amount, router_addr, recipient_address, router_addr,
            router_kind, router_label or "RelayRouterV3", router_source or "Relay公開索引", router_conf,
            "僅資金關聯", dest_note,
            chain="Polygon", block_number=candidate.get("block_number", ""), log_index=candidate.get("log_index", ""),
            path_role="入金", event_role="補款", explorer_url=f"https://polygonscan.com/tx/{dest_tx}",
            chain_id=137, evidence_source="Relay Request 精確配對（Polygon 同鏈）",
            line_style="solid",
        )
        dest_step.relay_request_id = req_id
        dest_step.relay_leg = "destination"
        dest_step.pair_verified = True
        result.steps.append(dest_step)

        # 2. 來源端底層投入（實線）
        sender_kind, sender_label, sender_source, sender_conf = self.classify(sender)
        src_note = f"Relay 請求 {req_id} 使用者地址投入 {in_amount} {in_symbol} 底層資產（Polygon 同鏈轉換）；不等於確認自然人身分。"
        src_step = TraceStep(
            "Relay 來源鏈", 3, origin_tx, when_text,
            in_symbol, in_amount, sender, router_addr, sender,
            "外部錢包" if sender_kind == "未知地址" else sender_kind,
            sender_label or "Relay 使用者地址", sender_source or "Relay公開索引", sender_conf,
            "僅資金關聯", src_note,
            chain="Polygon", block_number=candidate.get("block_number", ""), log_index="",
            path_role="入金", event_role="底層資產投入", explorer_url=f"https://polygonscan.com/tx/{origin_tx}",
            chain_id=137, evidence_source="Relay Request 精確配對（Polygon 同鏈）",
            line_style="solid",
        )
        src_step.relay_request_id = req_id
        src_step.relay_leg = "source"
        src_step.pair_verified = True
        result.steps.append(src_step)

        result.sources.append(f"{sc_info['source']}：https://api.relay.link")
        result.summary.extend([
            "Relay 來源鏈：Polygon（同鏈轉換）",
            f"Relay 來源地址：{sender}",
            f"Relay 來源資產：{in_amount} {in_symbol}；撥付資產：{out_amount} {out_symbol}；Tx：{origin_tx}",
        ])

        if max_hops >= 3 and sender:
            self._append_same_chain_upstream(
                result,
                sender,
                event_timestamp(sc_info["timestamp"] or candidate.get("time")),
                max_hops,
                expected_token=in_symbol,
                expected_amount=in_amount,
            )

        return True

    def _append_same_chain_upstream(
        self,
        result: AnalysisResult,
        sender: str,
        cutoff: float,
        max_hops: int,
        expected_token: str = "USDC",
        expected_amount: str = "",
    ) -> None:
        """追蹤同鏈 Relay 使用者錢包的上游直接轉帳（實線）與中間資金池關聯（虛線／點線）。"""
        self.progress(f"正在追蹤 Relay 使用者錢包 {sender[:10]}… 的直接上游入金…")
        try:
            history = self.provider.address_token_transfers(sender)
        except ProviderError as exc:
            result.warnings.append(f"無法查詢 Relay 使用者地址 {sender} 的轉帳：{exc}")
            return

        inbound = self._generic_inbound_candidates(history, sender, cutoff, token_symbol=expected_token)
        if not inbound:
            inbound = self._generic_inbound_candidates(history, sender, cutoff)

        try:
            expected_value = Decimal(str(expected_amount))
        except (InvalidOperation, ValueError, TypeError):
            expected_value = None
        exact_amount = []
        if expected_value is not None:
            for item in inbound:
                try:
                    if abs(Decimal(str(item["amount"])) - expected_value) <= Decimal("0.000001"):
                        exact_amount.append(item)
                except (InvalidOperation, ValueError, TypeError):
                    continue

        uniquely_matched = len(exact_amount) == 1
        selected = exact_amount if exact_amount else inbound[:3]
        for item in selected[:3]:
            intermediate_addr = item["from"]
            item_hash = item["hash"]
            item_time = item["time"]
            item_token = item["token"]
            item_amount = item["amount"]
            item_block = item.get("block_number", "")

            source_kind, source_label, source_origin, source_conf = self.classify(intermediate_addr, item.get("label", ""))
            if uniquely_matched:
                direct_note = (
                    f"此筆 {item_amount} {item_token} 與 Relay 投入金額唯一吻合，列為逐筆本金上游；"
                    "地址控制者與自然人身分仍待服務商資料確認。"
                )
                line_style = "solid"
                relation = "僅資金關聯"
            else:
                direct_note = (
                    f"此筆 {item_amount} {item_token} 僅為 Relay 前入金候選；未能依幣別、金額與時間唯一配對，"
                    "不得視為該筆本金的確定來源。"
                )
                line_style = "dashed"
                relation = "關聯不足"
            step_direct = TraceStep(
                "來源鏈上游" if uniquely_matched else "來源鏈上游候選", 4, item_hash, timestamp_to_text(item_time),
                item_token, item_amount, intermediate_addr, sender, intermediate_addr,
                source_kind if source_kind != "未知地址" else "中間地址",
                source_label or "未分類中間地址", source_origin, source_conf,
                relation, direct_note,
                chain="Polygon", block_number=str(item_block), log_index="",
                path_role="入金", event_role="轉帳", explorer_url=f"https://polygonscan.com/tx/{item_hash}",
                chain_id=137, evidence_source="Explorer Token Transfers 索引",
                line_style=line_style,
            )
            result.steps.append(step_direct)

            if uniquely_matched and source_kind == "交易所":
                result.summary.append(
                    f"逐筆本金上游命中交易所公開標籤：{source_label}；"
                    f"{item_amount} {item_token}；Tx：{item_hash}"
                )

            if uniquely_matched and max_hops >= 4 and source_kind != "交易所":
                self._inspect_intermediate_pool(result, intermediate_addr, event_timestamp(item_time), item_block)

        if inbound and not uniquely_matched:
            result.warnings.append(
                f"Relay 前共找到 {len(inbound)} 筆上游入金，但沒有唯一一筆同時符合 "
                f"{expected_amount} {expected_token}；已改列候選虛線，不認定為本金來源。"
            )

    def _inspect_intermediate_pool(self, result: AnalysisResult, pool_address: str, cutoff: float, before_block: Any) -> None:
        """查核中間資金池之較早資金池關聯（虛線）與原生 POL 供資關聯（點線）。"""
        self.progress(f"正在分析中間資金池 {pool_address[:10]}… 之資金來源…")
        blk_int = None
        if before_block:
            try:
                blk_int = int(str(before_block), 16) if str(before_block).startswith("0x") else int(before_block)
            except (ValueError, TypeError):
                pass

        # 1. 較早資金池入金（MoonPay 等 VASP，虛線）
        try:
            pool_transfers = self.provider.polygon_token_transfers_before(pool_address, before_block=blk_int, max_pages=12)
        except ProviderError as exc:
            result.warnings.append(f"無法查詢中間資金池 Token 記錄：{exc}")
            pool_transfers = []

        service_relations: list[str] = []
        seen_vasp_senders: set[str] = set()
        for pt in pool_transfers:
            p_sender = event_address(pt.get("from"))
            p_recipient = event_address(pt.get("to"))
            if normalize(p_recipient) != normalize(pool_address):
                continue
            p_time = pt.get("timestamp", pt.get("timeStamp", ""))
            if cutoff and event_timestamp(p_time) >= cutoff:
                continue

            lbl = event_label(pt.get("from"))
            p_hash = pt.get("transaction_hash", pt.get("tx_hash", pt.get("hash", "")))
            if not lbl and p_hash:
                tx_dtl = self.provider.transaction_details(p_hash)
                if tx_dtl:
                    lbl = event_label(tx_dtl.get("from"))

            p_tok_data = pt.get("token", {}) or {}
            decimals = int(p_tok_data.get("decimals", 6) or 6)
            raw_val = pt.get("total", {}).get("value", "") if isinstance(pt.get("total"), dict) else pt.get("value", "")
            try:
                amt = f"{int(str(raw_val)) / 10**decimals:.6f}" if str(raw_val).isdigit() else str(raw_val)
            except (ValueError, TypeError):
                amt = str(raw_val)
            sym = p_tok_data.get("symbol", "USDC")

            p_kind, p_label, p_src, p_conf = self.classify(p_sender, lbl)
            is_fiat_vasp = p_kind == "入金服務商" or any(kw in lbl.lower() for kw in ("moonpay", "simplex", "transak", "banxa"))
            is_exchange = p_kind == "交易所" or any(kw in lbl.lower() for kw in ("okx", "binance", "bybit"))

            if (is_fiat_vasp or is_exchange) and normalize(p_sender) not in seen_vasp_senders:
                seen_vasp_senders.add(normalize(p_sender))
                service_relations.append(f"{p_label or lbl}：{amt} {sym}（Tx {p_hash}）")
                pool_note = (
                    f"較早資金池入金（非逐筆歸屬）：公開標籤地址曾向中間資金池轉入大額穩定幣；"
                    f"因進入混合資金池，非逐筆唯一對應，不能確認其中哪筆資金後續用於本案。"
                )
                step_pool = TraceStep(
                    "較早資金池入金", 5, p_hash, timestamp_to_text(p_time),
                    sym, amt, p_sender, pool_address, p_sender,
                    "入金服務商" if is_fiat_vasp else "交易所",
                    p_label or lbl or ("MoonPay" if is_fiat_vasp else "交易所"),
                    p_src or "Explorer 公開標籤", p_conf or "高度可能",
                    "僅資金關聯", pool_note,
                    chain="Polygon", block_number=str(pt.get("block_number", "")), log_index="",
                    path_role="入金", event_role="資金池入金", explorer_url=f"https://polygonscan.com/tx/{p_hash}",
                    chain_id=137, evidence_source="Explorer Token Transfers 索引（Open Labels Initiative）",
                    line_style="dashed",
                )
                result.steps.append(step_pool)
                result.summary.append(f"較早資金池入金：{p_label or lbl} 向中間資金池轉入 {amt} {sym}（非逐筆歸屬，以虛線表示）")
                if len(seen_vasp_senders) >= 2:
                    break

        # 2. 原生 POL 供資關聯（OKX 180 等，點線）
        try:
            native_transfers = self.provider.address_native_transfers_before(pool_address, before_block=blk_int, max_items=50)
        except ProviderError as exc:
            result.warnings.append(f"無法查詢中間資金池原生代幣記錄：{exc}")
            native_transfers = []

        native_relations: list[str] = []
        for nt in native_transfers:
            n_sender = event_address(nt.get("from"))
            n_time = nt.get("timestamp", "")
            if cutoff and event_timestamp(n_time) >= cutoff:
                continue
            n_lbl = event_label(nt.get("from"))
            n_hash = nt.get("hash", "")
            if not n_lbl and n_hash:
                tx_dtl = self.provider.transaction_details(n_hash)
                if tx_dtl:
                    n_lbl = event_label(tx_dtl.get("from"))

            n_kind, n_label, n_src, n_conf = self.classify(n_sender, n_lbl)
            if n_kind == "交易所" or "okx" in (n_lbl or "").lower():
                native_relations.append(f"{n_label or n_lbl}：{nt['value']} POL（Tx {n_hash}）")
                gas_note = (
                    f"原生 POL 供資關聯（非本案本金）：{n_label or n_lbl} 曾向中間資金池轉入原生 POL 作為燃料手續費；"
                    f"帳戶制餘額混合，無法證明本案轉帳手續費必定消耗該筆代幣，非逐筆對應。"
                )
                step_gas = TraceStep(
                    "原生 POL 供資", 5, n_hash, timestamp_to_text(n_time),
                    "POL", nt["value"], n_sender, pool_address, n_sender,
                    "交易所", n_label or n_lbl or "OKX", n_src or "Explorer 公開標籤", n_conf or "高度可能",
                    "僅資金關聯", gas_note,
                    chain="Polygon", block_number=str(nt.get("block_number", "")), log_index="",
                    path_role="入金", event_role="手續費供資", explorer_url=f"https://polygonscan.com/tx/{n_hash}",
                    chain_id=137, evidence_source="Explorer Native Transactions（Open Labels Initiative）",
                    line_style="dotted",
                )
                result.steps.append(step_gas)
                result.summary.append(f"原生 POL 供資關聯：{n_label or n_lbl} 向中間資金池轉入 {nt['value']} POL（原生幣供資關聯／非本案本金，以點線表示）")
                break

        # 3. 依實際命中內容組合客觀結論，不硬編碼服務商、次數或金額。
        if service_relations or native_relations:
            short_pool = f"{pool_address[:6]}...{pool_address[-4:]}"
            parts = []
            if service_relations:
                parts.append("較早穩定幣關聯：" + "；".join(service_relations))
            if native_relations:
                parts.append("原生 POL 供資關聯：" + "；".join(native_relations))
            result.summary.append(
                f"【資金池服務商線索】{short_pool} 的" + "；".join(parts) +
                "。這些是較早資金池或手續費供資紀錄，非本案本金的逐筆唯一來源；"
                "不足以確認各地址由同一自然人控制，也不能單憑公開標籤確認特定客戶身分。"
            )

    def _relay_details(self, matched: dict[str, Any]) -> dict[str, Any] | None:
        request = matched.get("request", {})
        protocol_origin = (((request.get("protocol") or {}).get("deposit") or {}).get("origin") or {})
        data = request.get("data") or {}
        if len(data.get("inTxs") or []) != 1:
            return None
        if matched.get("version") == 3:
            route_origin = (((data.get("route") or {}).get("actual") or {}).get("origin") or {}).get("inputCurrency") or {}
            tx = (data.get("inTxs") or [{}])[0]
            currency = route_origin.get("currency") or {}
            tx_hash = tx.get("txHash") or protocol_origin.get("transactionId", "")
        else:
            route_origin = ((data.get("metadata") or {}).get("currencyIn") or {})
            tx = (data.get("inTxs") or [{}])[0]
            currency = route_origin.get("currency") or {}
            tx_hash = tx.get("hash") or protocol_origin.get("transactionId", "")
        chain_id = int(currency.get("chainId") or protocol_origin.get("chainId") or tx.get("chainId") or 0)
        if not tx_hash or not chain_id:
            return None
        return {
            "request_id": request.get("id", ""),
            "chain_id": chain_id,
            "tx_hash": tx_hash,
            "timestamp": tx.get("timestamp", ""),
            "depositor": protocol_origin.get("depositor") or request.get("sender") or request.get("user", ""),
            "depository": protocol_origin.get("depository", ""),
            "symbol": currency.get("symbol", "未知資產"),
            "contract": currency.get("address") or protocol_origin.get("currency", ""),
            "amount": route_origin.get("amountFormatted") or amount_text(protocol_origin.get("amount"), currency.get("decimals")),
        }

    def _append_source_chain_upstream(self, result: AnalysisResult, details: dict[str, Any], max_hops: int) -> None:
        depositor = str(details.get("depositor") or "").strip()
        if not depositor:
            return
        if details["chain_id"] == 56:
            self._append_bnb_upstream(result, details, max_hops)
            return
        if details["chain_id"] == 728126428:
            result.sources.append("Tronscan 公開 TRC-20 API：https://apilist.tronscanapi.com/api")
        frontier = [(depositor, 4, event_timestamp(details["timestamp"]))]
        seen: set[str] = set()
        while frontier:
            address, hop, cutoff = frontier.pop(0)
            # TRON Base58 地址區分大小寫；只有 EVM 0x 地址可安全轉為小寫。
            lookup_address = normalize(address) if str(address).startswith("0x") else address
            seen_key = normalize(address) if str(address).startswith("0x") else address
            if seen_key in seen or hop > max_hops: continue
            seen.add(seen_key)
            try:
                events = self.provider.chain_token_transfers(lookup_address, details["chain_id"])
            except ProviderError as exc:
                result.warnings.append(str(exc))
                return
            candidates = self._generic_inbound_candidates(events, lookup_address, cutoff, details["contract"], details["symbol"])
            for item in candidates[:5]:
                kind, label, label_source, confidence = self.classify(item["from"], item.get("label", ""))
                chain_name = CHAIN_NAMES.get(details["chain_id"], f"chainId {details['chain_id']}")
                result.steps.append(TraceStep("來源鏈上游", hop, item["hash"], timestamp_to_text(item["time"]), f"{item['token']}（{chain_name}）", item["amount"], item["from"], address, item["from"], kind, label, label_source, confidence, "僅資金關聯" if kind != "未知地址" else "未知", "Relay跨鏈前的來源鏈Token入帳；命中交易所標籤仍須依法調取KYC及提幣資料。"))
                step = result.steps[-1]
                step.chain, step.chain_id = chain_name, details["chain_id"]
                step.token_contract = details["contract"]
                step.explorer_url = explorer_url(details["chain_id"], item["hash"])
                step.evidence_source = "Tronscan 公開 TRC-20 索引" if details["chain_id"] == 728126428 else "來源鏈 Explorer Token Transfer 索引"
                if kind == "交易所":
                    result.summary.append(
                        f"上游命中交易所公開標籤：{label}；來源資產：{item['amount']} {item['token']}；Tx：{item['hash']}"
                    )
                frontier.append((item["from"], hop + 1, event_timestamp(item["time"])))

    def _append_bnb_upstream(self, result: AnalysisResult, details: dict[str, Any], max_hops: int) -> None:
        """以免金鑰 BNBScan 還原 Relay 前的穩定幣兌換與原生 BNB 入金。"""
        relay_depositor = normalize(details.get("depositor", ""))
        if not relay_depositor:
            return
        cutoff = event_timestamp(details["timestamp"])
        try:
            token_events = self.provider.chain_token_transfers(relay_depositor, 56)
        except ProviderError as exc:
            result.warnings.append(f"BNBScan Token 索引查詢失敗，已改用原始 RPC 備援：{exc}")
            token_events = []
        relay_inputs = self._generic_inbound_candidates(
            token_events, relay_depositor, cutoff, details.get("contract", ""), details.get("symbol", "")
        )
        result.sources.append("BNBScan 公開 REST API：https://bnbscan.com/api/v1/query")
        if not relay_inputs:
            fallback = getattr(self.provider, "chain_inbound_token_transfers_before", None)
            if fallback:
                try:
                    token_events = fallback(
                        relay_depositor, 56, details.get("contract", ""), details["tx_hash"]
                    )
                    relay_inputs = self._generic_inbound_candidates(
                        token_events, relay_depositor, cutoff, details.get("contract", ""), details.get("symbol", "")
                    )
                    if relay_inputs:
                        result.sources.append("BNB Chain 原始區塊 Receipt RPC（Explorer 漏索引備援）")
                except ProviderError as exc:
                    result.warnings.append(f"BNB Chain 原始 Receipt 備援查詢失敗：{exc}")
        for item in relay_inputs[:5]:
            kind, label, source, confidence = self.classify(item["from"], item.get("label", ""))
            result.steps.append(TraceStep(
                "Relay 前穩定幣轉入", 4, item["hash"], timestamp_to_text(item["time"]),
                f"{item['token']}（BNB Chain）", item["amount"], item["from"], relay_depositor,
                item["from"], kind, label, source, confidence, "僅資金關聯",
                "Relay 來源交易前轉入穩定幣的資金錢包；此中間地址仍須續追其資產取得方式。",
                chain="BNB Chain", chain_id=56, block_number=str(item.get("block_number", "")),
                explorer_url=explorer_url(56, item["hash"]), evidence_source="BNBScan Token Transfers 索引",
            ))
            if kind == "交易所":
                result.summary.append(
                    f"上游命中交易所公開標籤：{label}（BNB Chain）；來源資產：{item['amount']} {item['token']}；Tx：{item['hash']}"
                )
        if not relay_inputs:
            result.warnings.append("BNB Chain 上未找到 Relay 來源地址在跨鏈前的穩定幣入帳。")
            return

        funding_address = normalize(relay_inputs[0]["from"])
        funding_cutoff = event_timestamp(relay_inputs[0]["time"])
        try:
            funding_events = self.provider.chain_token_transfers(funding_address, 56)
        except ProviderError as exc:
            result.warnings.append(f"BNBScan 中間資金錢包索引失敗，已改用原始 RPC 備援：{exc}")
            funding_events = []
        swap_candidates = self._generic_inbound_candidates(
            funding_events, funding_address, funding_cutoff,
            details.get("contract", ""), details.get("symbol", ""),
        )
        if not swap_candidates:
            fallback = getattr(self.provider, "chain_token_transfers_from_prior_activity", None)
            if fallback:
                try:
                    funding_events = fallback(
                        funding_address, 56, details.get("contract", ""), relay_inputs[0]["hash"]
                    )
                    swap_candidates = self._generic_inbound_candidates(
                        funding_events, funding_address, funding_cutoff,
                        details.get("contract", ""), details.get("symbol", ""),
                    )
                except ProviderError as exc:
                    result.warnings.append(f"BNB Chain DEX 前置交易備援查詢失敗：{exc}")
        for item in swap_candidates[:5]:
            kind, label, source, confidence = self.classify(item["from"], item.get("label", ""))
            result.steps.append(TraceStep(
                "來源鏈兌換入帳", 4, item["hash"], timestamp_to_text(item["time"]),
                f"{item['token']}（BNB Chain）", item["amount"], item["from"], funding_address,
                item["from"], kind, label, source, confidence, "僅資金關聯",
                "中間資金錢包在 Relay 前取得穩定幣；若來源為 DEX Router，須續查支付兌換的原生 BNB。",
                chain="BNB Chain", chain_id=56, block_number=str(item.get("block_number", "")),
                explorer_url=explorer_url(56, item["hash"]), evidence_source="BNBScan DEX 兌換 Token Transfers 索引",
            ))
        if max_hops < 5:
            return
        native_cutoff = event_timestamp(swap_candidates[0]["time"]) if swap_candidates else funding_cutoff
        try:
            transactions = self.provider.chain_transactions(funding_address, 56)
        except ProviderError as exc:
            result.warnings.append(f"BNBScan 原生幣索引失敗，已改用原始 RPC 備援：{exc}")
            transactions = []
        if not transactions:
            fallback = getattr(self.provider, "chain_activity_transactions_before", None)
            if fallback:
                try:
                    anchor_hash = swap_candidates[0]["hash"] if swap_candidates else relay_inputs[0]["hash"]
                    transactions = fallback(funding_address, 56, anchor_hash)
                except ProviderError as exc:
                    result.warnings.append(f"BNB Chain 原生幣交易備援查詢失敗：{exc}")
        native_inbound: list[dict[str, Any]] = []
        for tx in transactions:
            if normalize(tx.get("toAddress", tx.get("to", ""))) != funding_address:
                continue
            when = tx.get("timestamp", tx.get("timeStamp", ""))
            if native_cutoff and event_timestamp(when) >= native_cutoff:
                continue
            try:
                value_text = str(tx.get("value", "0"))
                raw_value = Decimal(int(value_text, 16)) if value_text.startswith("0x") else Decimal(value_text)
                amount = raw_value / Decimal(10**18) if raw_value >= Decimal(10**12) else raw_value
            except (InvalidOperation, ValueError):
                continue
            if amount <= 0:
                continue
            native_inbound.append({**tx, "time": when, "amount": f"{amount:.8f}"})
        native_inbound.sort(key=lambda item: event_timestamp(item["time"]), reverse=True)
        for tx in native_inbound[:5]:
            sender = tx.get("fromAddress", tx.get("from", ""))
            kind, label, source, confidence = self.classify(sender)
            tx_h = tx.get("hash", tx.get("txHash", ""))
            result.steps.append(TraceStep(
                "來源鏈原生幣入金", 5, tx_h,
                timestamp_to_text(tx["time"]), "BNB（BNB Chain）", tx["amount"], sender, funding_address,
                sender, kind, label, source, confidence,
                "僅資金關聯" if kind != "未知地址" else "未知",
                "兌換穩定幣前的原生 BNB 入金；命中交易所提幣標籤仍不等於已確認帳戶持有人。",
                chain="BNB Chain", chain_id=56, block_number=str(tx.get("blockNumber", "")),
                explorer_url=explorer_url(56, tx_h), evidence_source="BNBScan 原生交易公開索引",
            ))
            if kind == "交易所":
                result.summary.append(
                    f"上游命中交易所公開標籤：{label}；來源資產：{tx['amount']} BNB；Tx：{tx.get('hash', tx.get('txHash', ''))}"
                )

    def _generic_inbound_candidates(self, events: list[dict[str, Any]], recipient: str, cutoff: float, token_contract: str = "", token_symbol: str = "") -> list[dict[str, str]]:
        found: list[dict[str, str]] = []
        for event in events:
            token_data = event.get("token", {}) or {}
            contract = normalize(token_data.get("address") or token_data.get("address_hash") or event.get("contractAddress", event.get("token_address", "")))
            symbol = token_data.get("symbol", event.get("tokenSymbol", "未知Token")) or "未知Token"
            sender, target = event_address(event.get("from")), event_address(event.get("to"))
            when = event.get("timestamp", event.get("timeStamp", ""))
            if normalize(target) != normalize(recipient): continue
            # Relay Router 可能在鑄造 pUSD 的同一筆交易、同一秒先行入帳；
            # 僅排除真正晚於目標事件的紀錄，後續仍須以 Request ID 精確配對。
            if cutoff and event_timestamp(when) > cutoff: continue
            if token_contract and contract and contract != normalize(token_contract): continue
            if not token_contract and token_symbol and symbol.lower().replace(".", "") != token_symbol.lower().replace(".", ""): continue
            raw = event.get("total", {}).get("value", "") if isinstance(event.get("total"), dict) else event.get("value", "")
            decimals = int(token_data.get("decimals", event.get("tokenDecimal", 0)) or 0)
            try: amount = f"{int(str(raw)) / 10**decimals:.6f}" if decimals else str(raw)
            except (TypeError, ValueError): amount = str(raw)
            found.append({"hash": event.get("transaction_hash", event.get("tx_hash", event.get("hash", ""))), "time": str(when), "from": sender, "to": target, "token": symbol, "amount": amount, "label": event_label(event.get("from"))})
        return sorted(found, key=lambda item: event_timestamp(item["time"]), reverse=True)
    def _trace_token_upstream(self, sources: list[str], cutoff: float, max_hops: int) -> list[TraceStep]:
        output=[]; seen=set(); frontier=[(source, 2, cutoff) for source in sources]
        while frontier:
            address, hop, before = frontier.pop(0); address=normalize(address)
            if address in seen or hop > max_hops: continue
            seen.add(address)
            try: events=self.provider.address_token_transfers(address)
            except ProviderError: continue
            for item in self._funding_candidates(events, address, before)[:5]:
                source=item["from"]
                if normalize(source) in POLYMARKET_INTERNAL | {ZERO_ADDRESS}: continue
                kind,label,label_source,confidence=self.classify(source)
                output.append(TraceStep("USDC 上游",hop,item["hash"],timestamp_to_text(item["time"]),item["token"],item["amount"],source,address,source,kind,label,label_source,confidence,"僅資金關聯",item["note"]))
                frontier.append((source, hop+1, event_timestamp(item["time"])))
        return output
    def _parse_receipt(self, tx_hash: str, receipt: dict[str, Any], timestamp: str) -> list[Transfer]:
        transfers = []
        logs = receipt.get("logs", []) if isinstance(receipt, dict) and isinstance(receipt.get("logs"), list) else []
        for log in logs:
            topics = log.get("topics", [])
            if len(topics) >= 3 and normalize(topics[0]) == TRANSFER_TOPIC:
                sender, recipient, contract = "0x"+topics[1][-40:], "0x"+topics[2][-40:], log.get("address", "")
                token = "pUSD" if normalize(contract) == PUSD else ("USDC.e" if normalize(contract) == USDC_E else ("USDC" if normalize(contract) == USDC else f"ERC-20 合約 {contract}"))
                raw_amount = hex_int(log.get("data"))
                amount = f"{raw_amount / 10**6:.6f}" if token in {"pUSD", "USDC", "USDC.e"} else str(raw_amount)
                transfers.append(Transfer(tx_hash, timestamp, token, amount, sender, recipient, "ERC-20", "RPC receipt logs", contract, str(hex_int(log.get("logIndex")))))
            elif len(topics) >= 4 and normalize(log.get("address")) == POLYMARKET_CONDITIONAL_TOKENS:
                transfers.append(Transfer(tx_hash, timestamp, "Polymarket Outcome Token", "請以 Explorer 解碼確認", "0x"+topics[2][-40:], "0x"+topics[3][-40:], "ERC-1155", "Polymarket Conditional Tokens 事件"))
        return transfers
    def _trace(self, seeds: list[str], max_hops: int) -> list[TraceStep]:
        steps: list[TraceStep] = []; seen: set[tuple[str, str]] = set()
        for direction in ("上游", "下游"):
            queue = deque((address, 1) for address in seeds if ADDRESS.fullmatch(address or "")); visited: set[str] = set()
            while queue:
                address, hop = queue.popleft(); address = normalize(address)
                if address in visited or hop > max_hops: continue
                visited.add(address)
                try: transactions = self.provider.address_transactions(address)
                except ProviderError: continue
                for tx in transactions:
                    sender = tx.get("from", {}).get("hash", "") if isinstance(tx.get("from"), dict) else tx.get("from", "")
                    recipient = tx.get("to", {}).get("hash", "") if isinstance(tx.get("to"), dict) else tx.get("to", "")
                    related = sender if direction == "上游" else recipient
                    matches = normalize(recipient) == address if direction == "上游" else normalize(sender) == address
                    key = (direction, tx.get("hash", ""))
                    if not sender or not recipient or not matches or normalize(related) == address or key in seen: continue
                    seen.add(key); kind, label, source, confidence = self.classify(related); timestamp = tx.get("timestamp", tx.get("timeStamp", "")); amount = tx.get("value", "")
                    notes = "此列為地址交易紀錄；Token 金流須另查交易 Logs。"
                    if isinstance(amount, str) and amount.isdigit():
                        numeric_amount = int(amount) / 10**18; amount = f"{numeric_amount:.8f} MATIC"
                        if 0 < numeric_amount < 0.001: notes = "極小額原生幣轉入，可能為灑幣或干擾交易；不宜當成主要資金來源。"
                    steps.append(TraceStep(direction, hop, tx.get("hash", ""), timestamp_to_text(timestamp) if timestamp else "", "原生幣／請再查 Logs", str(amount), sender, recipient, related, kind, label, source, confidence, "僅資金關聯" if kind != "未知地址" else "未知", notes))
                    if hop < max_hops: queue.append((related, hop + 1))
        return steps
