from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .betting import BetTrade, decode_polymarket_trade


@dataclass
class OrbscanTradeInfo:
    market_title: str  # 市場名稱
    trader: str  # 交易者地址
    role: str  # "Taker (吃單方)" 或 "Maker (掛單方)"
    side: str  # "買進 (BUY)", "賣出 (SELL)", "勝選兌現 (REDEEM)"
    outcome: str  # "Yes", "No" 或自訂標的
    shares: str  # 份額字串
    price_cents: str  # "86.2¢"
    price_usd: str  # "$0.862000"
    fee: str  # "$0.952" 或 "無"
    value: str  # 交易價值 (如 "$172.40")
    timestamp: str  # 時間戳
    tx_hash: str  # 交易雜湊
    source: str  # 資料來源說明

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OrbscanTradeInfo:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    def summary_line(self) -> str:
        """
        產出高價值白話摘要：
        買入 No、200 Shares、價格 86.2¢、交易價值 $172.40、手續費 $0.952。
        """
        if "REDEEM" in self.side.upper() or "勝選兌現" in self.side:
            action_cn = "勝選兌現"
        elif "BUY" in self.side.upper() or "買" in self.side:
            action_cn = "買入"
        elif "SELL" in self.side.upper() or "賣" in self.side:
            action_cn = "賣出"
        else:
            action_cn = self.side

        outcome_part = f" {self.outcome}" if self.outcome and self.outcome != "未取得" else ""
        fee_part = f"、手續費 {self.fee}" if self.fee and self.fee != "未取得" and self.fee != "無" else ""
        market_part = f"（市場：{self.market_title}）" if self.market_title and "未取得" not in self.market_title else ""

        return (
            f"{action_cn}{outcome_part}、{self.shares} Shares、價格 {self.price_cents}、"
            f"交易價值 {self.value}{fee_part}{market_part}"
        )


def format_price_display(price_val: float | Decimal | str) -> tuple[str, str]:
    try:
        p = float(price_val)
        cents = f"{p * 100:.1f}¢"
        usd = f"${p:.6f}"
        return cents, usd
    except (ValueError, TypeError):
        return "未取得", "未取得"


def parse_orbscan_response(data: Any, target_address: str, tx_hash: str) -> OrbscanTradeInfo | None:
    """解析 Orbscan 或 Polymarket Data API 回傳之交易資料結構。"""
    if not data:
        return None

    items: list[dict[str, Any]] = []
    if isinstance(data, list):
        items = [x for x in data if isinstance(x, dict)]
    elif isinstance(data, dict):
        if "trades" in data and isinstance(data["trades"], list):
            items = [x for x in data["trades"] if isinstance(x, dict)]
        else:
            items = [data]

    if not items:
        return None

    target_lower = target_address.lower().strip()
    tx_lower = tx_hash.lower().strip()

    # 尋找匹配該 Tx Hash 與目標地址的交易
    matched = None
    for item in items:
        item_tx = str(item.get("transactionHash") or item.get("txHash") or item.get("tx_hash") or "").lower().strip()
        if tx_lower and item_tx and item_tx != tx_lower:
            continue
        # 匹配目標地址 (可能是 maker, taker, proxyWallet, user, trader)
        addrs = [
            str(item.get("maker") or "").lower(),
            str(item.get("taker") or "").lower(),
            str(item.get("proxyWallet") or "").lower(),
            str(item.get("user") or "").lower(),
            str(item.get("trader") or "").lower(),
        ]
        if not target_lower or any(target_lower == a for a in addrs if a):
            matched = item
            break

    if not matched:
        # 不任取 API 的第一筆，以免將其他地址或其他交易的投注語意誤套本案。
        return None

    # 提取市場名稱
    market_title = (
        matched.get("title")
        or matched.get("market")
        or matched.get("question")
        or matched.get("marketTitle")
        or "Polymarket 預測合約"
    )

    # 交易方向 (Buy / Sell)
    raw_side = str(matched.get("side") or matched.get("type") or "BUY").upper()
    side = "買進 (BUY)" if "BUY" in raw_side else ("賣出 (SELL)" if "SELL" in raw_side else raw_side)

    # Outcome (Yes / No)
    raw_outcome = matched.get("outcome")
    outcome_idx = matched.get("outcomeIndex")
    if raw_outcome is not None:
        outcome = str(raw_outcome)
    elif outcome_idx is not None:
        outcome = "Yes" if str(outcome_idx) == "0" else "No"
    else:
        outcome = "未取得"

    # 角色 (Taker / Maker)
    taker_addr = str(matched.get("taker") or "").lower()
    role = "Taker (吃單方)" if (target_lower and taker_addr == target_lower) else "Maker (掛單方)"

    # 份額與價格
    size_num = matched.get("size") or matched.get("shares") or matched.get("amount") or 0
    try:
        shares_str = f"{float(size_num):.6f}"
    except (ValueError, TypeError):
        shares_str = str(size_num)

    price_num = matched.get("price") or 0
    price_cents, price_usd = format_price_display(price_num)

    # 手續費
    raw_fee = matched.get("fee") or matched.get("transactionFee")
    if raw_fee is not None:
        try:
            fee_str = f"${float(raw_fee):.3f}"
        except (ValueError, TypeError):
            fee_str = str(raw_fee)
    else:
        fee_str = "未取得"

    # 交易價值
    val_num = matched.get("value") or matched.get("totalValue") or matched.get("collateralAmount")
    if val_num is not None:
        try:
            val_str = f"${float(val_num):.2f}"
        except (ValueError, TypeError):
            val_str = str(val_num)
    else:
        try:
            val_calc = float(size_num) * float(price_num)
            val_str = f"${val_calc:.2f}"
        except Exception:
            val_str = "未取得"

    timestamp = str(matched.get("timestamp") or matched.get("time") or "")

    return OrbscanTradeInfo(
        market_title=market_title,
        trader=target_address,
        role=role,
        side=side,
        outcome=outcome,
        shares=shares_str,
        price_cents=price_cents,
        price_usd=price_usd,
        fee=fee_str,
        value=val_str,
        timestamp=timestamp,
        tx_hash=tx_hash,
        source="Orbscan / Polymarket API 解譯",
    )


def fallback_from_receipt(
    receipt: dict[str, Any] | None,
    target_address: str,
    tx_hash: str = "",
    timestamp: str = "",
) -> OrbscanTradeInfo | None:
    """當外部語意端點未回應時，自動降級為由原始 Receipt Logs 本地推估。"""
    if not receipt:
        return None

    trade = decode_polymarket_trade(receipt, target_address, tx_hash=tx_hash, timestamp=timestamp)
    if not trade:
        return None

    # 由鏈上資料推估語意
    price_cents, price_usd = format_price_display(trade.price_per_share)
    try:
        val_float = float(trade.collateral_amount)
        val_str = f"${val_float:.2f}"
    except (ValueError, TypeError):
        val_str = f"${trade.collateral_amount}"

    outcome_label = f"待解析（Token ID {trade.token_id}）"
    if "REDEEM" in trade.action:
        outcome_label = "勝選份額"
        fee_str = "無（合約原生銷毀兌現）"
    else:
        fee_str = "未取得（鏈上原生）"

    return OrbscanTradeInfo(
        market_title="題目待解析（僅確認鏈上投注）",
        trader=target_address,
        role="Taker / 直連合約",
        side=trade.action,
        outcome=outcome_label,
        shares=trade.shares,
        price_cents=price_cents,
        price_usd=price_usd,
        fee=fee_str,
        value=val_str,
        timestamp=trade.timestamp,
        tx_hash=trade.tx_hash,
        source="鏈上 Receipt Logs 原生解碼（外部語意未連上）",
    )


def parse_polygonscan_meta(
    html: str,
    target_address: str,
    tx_hash: str,
    timestamp: str = "",
) -> OrbscanTradeInfo | None:
    """從 Polygonscan 頁面之 Meta Description 中提取 Orbscan 預測市場官方交易語意。"""
    if not html:
        return None

    # 匹配 Meta Description
    m = re.search(r'<meta\s+(?:name|property)=["\'](?:Description|description|og:description)["\']\s+content=["\'](.*?)["\']', html, re.I)
    if not m:
        return None
    desc = m.group(1).strip()
    if "Polymarket" not in desc and "Orbscan" not in desc:
        return None

    # 匹配範例：... (bought|sold) 200 No shares for $ 173.47 in Will Puma Shen win the next Taipei Mayor election? via Polymarket View on Orbscan ...
    pattern = r'(?:bought|sold)\s+([\d\.,]+)\s+(Yes|No)\s+shares\s+for\s+\$\s*([\d\.,]+)\s+in\s+(.*?)\s+via\s+Polymarket'
    m_trade = re.search(pattern, desc, re.I)
    if not m_trade:
        return None

    shares_str, outcome, cost_str, market = m_trade.groups()
    is_buy = "bought" in desc.lower()
    side = "買進 (BUY)" if is_buy else "賣出 (SELL)"

    try:
        shares_f = float(shares_str.replace(",", ""))
        cost_f = float(cost_str.replace(",", ""))
        unit_price = cost_f / shares_f if shares_f > 0 else 0.0
        price_cents, price_usd = format_price_display(unit_price)
        val_str = f"${cost_f:.2f}"
        formatted_shares = f"{shares_f:.6f}"
    except (ValueError, ZeroDivisionError):
        price_cents, price_usd = "未取得", "未取得"
        val_str = f"${cost_str}"
        formatted_shares = shares_str

    return OrbscanTradeInfo(
        market_title=market.strip(),
        trader=target_address,
        role="Taker (吃單方)",
        side=side,
        outcome=outcome.strip(),
        shares=formatted_shares,
        price_cents=price_cents,
        price_usd=price_usd,
        fee="未取得（鏈上原生）",
        value=val_str,
        timestamp=timestamp,
        tx_hash=tx_hash,
        source="PolygonScan + Orbscan 語意解譯",
    )


def fetch_gamma_market_by_token_id(token_id: str, timeout: int = 3) -> dict[str, Any] | None:
    """透過 Polymarket Gamma API 查詢指定 clob_token_id 之市場題目與選項。"""
    if not token_id or str(token_id) == "0":
        return None
    url = f"https://gamma-api.polymarket.com/markets?clob_token_ids={token_id}"
    req = Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if not data or not isinstance(data, list):
                return None
            market = data[0]
            if not isinstance(market, dict):
                return None
            question = market.get("question") or market.get("title") or ""
            if not question:
                return None

            raw_outcomes = market.get("outcomes")
            if isinstance(raw_outcomes, str):
                try:
                    outcomes_list = json.loads(raw_outcomes)
                except Exception:
                    outcomes_list = [raw_outcomes]
            elif isinstance(raw_outcomes, list):
                outcomes_list = raw_outcomes
            else:
                outcomes_list = []

            raw_clob_tokens = market.get("clobTokenIds")
            if isinstance(raw_clob_tokens, str):
                try:
                    clob_list = json.loads(raw_clob_tokens)
                except Exception:
                    clob_list = [raw_clob_tokens]
            elif isinstance(raw_clob_tokens, list):
                clob_list = raw_clob_tokens
            else:
                clob_list = []

            matched_outcome = "未取得"
            str_tid = str(token_id).strip().lower()
            for idx, cid in enumerate(clob_list):
                if str(cid).strip().lower() == str_tid and idx < len(outcomes_list):
                    matched_outcome = str(outcomes_list[idx])
                    break

            return {
                "question": question.strip(),
                "outcome": matched_outcome,
                "market_slug": market.get("slug", ""),
                "condition_id": market.get("conditionId", ""),
            }
    except Exception:
        # 防禦性捕獲所有連線錯誤（如公務內網 WinError 10054、DNS 逾時等）
        return None


def fetch_orbscan_trade(
    tx_hash: str,
    target_address: str,
    api_url: str = "",
    receipt: dict[str, Any] | None = None,
    timestamp: str = "",
    timeout: int = 4,
) -> OrbscanTradeInfo | None:
    """
    綜合查詢 Polymarket 交易語意：
    1. 嘗試由外部端點 (Polymarket Data API / Orbscan) 依 Tx Hash 查詢語意。
    2. 若有 Receipt 且提取到 Token ID，嘗試由 Polymarket Gamma API 查詢題目與選項。
    3. 若遇網路阻斷 (如 Windows WinError 10054)，嘗試由 Polygonscan 頁面提取內建 Orbscan Meta。
    4. 若皆無法取得，自動降級為本地 Receipt Logs 原生解碼（保留金額與份額，標註題目待解析）。
    """
    # 1. 嘗試呼叫外部 Data API (依 Tx Hash)
    if tx_hash:
        endpoint = api_url.strip() or "https://data-api.polymarket.com/trades"
        query_url = f"{endpoint}?transactionHash={tx_hash}"
        try:
            req = Request(
                query_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json",
                },
            )
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                parsed = parse_orbscan_response(data, target_address, tx_hash)
                if parsed:
                    return parsed
        except Exception:
            pass

    # 2. 本地 Receipt 解碼以提取 Token ID
    trade = decode_polymarket_trade(receipt, target_address, tx_hash=tx_hash, timestamp=timestamp) if receipt else None

    # 3. 嘗試由 Polymarket Gamma API (依 CLOB Token ID) 查詢市場題目與選項
    if trade and trade.token_id and trade.token_id != "0":
        try:
            gamma_info = fetch_gamma_market_by_token_id(trade.token_id, timeout=timeout)
            if gamma_info and gamma_info.get("question"):
                price_cents, price_usd = format_price_display(trade.price_per_share)
                try:
                    val_float = float(trade.collateral_amount)
                    val_str = f"${val_float:.2f}"
                except (ValueError, TypeError):
                    val_str = f"${trade.collateral_amount}"
                fee_str = "未取得（鏈上原生）"
                return OrbscanTradeInfo(
                    market_title=gamma_info["question"],
                    trader=target_address,
                    role="Taker / 直連合約",
                    side=trade.action,
                    outcome=gamma_info.get("outcome") or "未取得",
                    shares=trade.shares,
                    price_cents=price_cents,
                    price_usd=price_usd,
                    fee=fee_str,
                    value=val_str,
                    timestamp=trade.timestamp,
                    tx_hash=trade.tx_hash,
                    source="Polymarket Gamma API",
                )
        except Exception:
            pass

    # 4. 嘗試由 Polygonscan Meta Description 提取 Orbscan 官方語意（備援層）
    if tx_hash:
        try:
            pscan_url = f"https://polygonscan.com/tx/{tx_hash}"
            req_pscan = Request(
                pscan_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml",
                },
            )
            with urlopen(req_pscan, timeout=timeout) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
                parsed_meta = parse_polygonscan_meta(html, target_address, tx_hash, timestamp)
                if parsed_meta:
                    return parsed_meta
        except Exception:
            pass

    # 5. 無縫降級：本地 Receipt 原生解碼
    return fallback_from_receipt(receipt, target_address, tx_hash, timestamp)
