from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TRANSFER_SINGLE_TOPIC = "0xc3d58168c5ae7397731d063d5bbf3d657854427343f4c083240f7aacaa2d0f62"
TRANSFER_BATCH_TOPIC = "0x4a3900ab02779c3829f7b0684c03d64205f4c1e7ea94fb2dbca4dfab03d577ae"

POLYMARKET_CONDITIONAL_TOKENS = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
PUSD = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
USDC = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def normalize(value: str | None) -> str:
    return value.lower() if value else ""


def hex_int(value: str | None) -> int:
    try:
        return int(value or "0x0", 16)
    except (ValueError, TypeError):
        return 0


@dataclass
class BetTrade:
    action: str  # "買進 (BUY)", "賣出 (SELL)", "勝選兌現 (REDEEM)", "部位調整 (SPLIT/MERGE)"
    collateral_token: str  # "pUSD" / "USDC.e" / "USDC"
    collateral_amount: str  # e.g. "8.685810"
    shares: str  # e.g. "15.000000"
    price_per_share: str  # e.g. "0.579054"
    implied_probability: str  # e.g. "57.91%"
    token_id: str  # 十進位字串
    token_id_hex: str  # "0x..."
    outcome_index: int  # 0 或 1 (二元選項序號)
    tx_hash: str = ""
    timestamp: str = ""
    log_index: str = ""
    market_title: str = ""
    outcome: str = ""
    trader_role: str = ""
    fee: str = ""
    value: str = ""
    enrichment_source: str = ""

    @property
    def action_label(self) -> str:
        return self.action

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BetTrade:
        valid_keys = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items() if k in valid_keys})

    def summary_text(self) -> str:
        if self.outcome and self.market_title:
            action_cn = "勝選兌現" if "REDEEM" in self.action else ("買入" if "BUY" in self.action or "買" in self.action else ("賣出" if "SELL" in self.action else self.action))
            try:
                p_float = float(self.price_per_share)
                cents_str = f"{p_float * 100:.1f}¢"
            except (ValueError, TypeError):
                cents_str = self.price_per_share
            val_str = self.value if self.value else f"${self.collateral_amount}"
            fee_part = f"、手續費 {self.fee}" if self.fee and self.fee != "未取得" and self.fee != "無" else ""
            market_part = f"（市場：{self.market_title}）" if self.market_title and "未取得" not in self.market_title else ""
            return f"{action_cn} {self.outcome}、{self.shares} Shares、價格 {cents_str}、交易價值 {val_str}{fee_part}{market_part}"

        if "REDEEM" in self.action:
            return (
                f"勝選兌現：銷毀 {self.shares} 股，收回 {self.collateral_amount} {self.collateral_token}（1:1 兌現）"
            )
        prob = f"，隱含勝率約 {self.implied_probability}" if self.implied_probability != "0.00%" else ""
        return (
            f"{self.action}：{self.shares} 股，金額 {self.collateral_amount} {self.collateral_token}"
            f"（均價 {self.price_per_share} USDC/股{prob}）"
        )


def decode_polymarket_trade(
    receipt: dict[str, Any],
    target_address: str,
    tx_hash: str = "",
    timestamp: str = "",
) -> BetTrade | None:
    """
    依 Net Delta（淨資產變化模型）解碼目標地址在該交易內的 Polymarket 投注行為。
    嚴格由 ERC-20 與 ERC-1155 原始 Logs 計算，不需外部 API。
    """
    target = normalize(target_address)
    if not target or not receipt:
        return None

    logs = receipt.get("logs", [])
    if not logs:
        return None

    collateral_delta: dict[str, Decimal] = {}
    token_deltas: dict[int, Decimal] = {}
    token_burned: dict[int, Decimal] = {}
    last_log_index = ""

    for log in logs:
        topics = log.get("topics", [])
        if not topics:
            continue
        topic0 = normalize(topics[0])
        contract = normalize(log.get("address"))

        # 1. ERC-20 抵押金變動 (pUSD, USDC.e, USDC)
        if len(topics) >= 3 and topic0 == TRANSFER_TOPIC:
            if contract in {PUSD, USDC_E, USDC}:
                symbol = "pUSD" if contract == PUSD else ("USDC.e" if contract == USDC_E else "USDC")
                sender = "0x" + topics[1][-40:].lower()
                receiver = "0x" + topics[2][-40:].lower()
                raw_val = hex_int(log.get("data"))
                val = Decimal(raw_val) / Decimal(10**6)

                if sender == target:
                    collateral_delta[symbol] = collateral_delta.get(symbol, Decimal(0)) - val
                    last_log_index = str(hex_int(log.get("logIndex", "")))
                if receiver == target:
                    collateral_delta[symbol] = collateral_delta.get(symbol, Decimal(0)) + val
                    last_log_index = str(hex_int(log.get("logIndex", "")))

        # 2. ERC-1155 條件代幣變動 (Polymarket CTF)
        elif contract == POLYMARKET_CONDITIONAL_TOKENS:
            if len(topics) >= 4 and topic0 == TRANSFER_SINGLE_TOPIC:
                sender = "0x" + topics[2][-40:].lower()
                receiver = "0x" + topics[3][-40:].lower()
                raw_data = log.get("data", "")
                if raw_data.startswith("0x"):
                    raw_data = raw_data[2:]
                if len(raw_data) >= 128:
                    tid = int(raw_data[0:64], 16)
                    val = Decimal(int(raw_data[64:128], 16)) / Decimal(10**6)

                    if sender == target:
                        token_deltas[tid] = token_deltas.get(tid, Decimal(0)) - val
                        last_log_index = str(hex_int(log.get("logIndex", "")))
                        if receiver == ZERO_ADDRESS:
                            token_burned[tid] = token_burned.get(tid, Decimal(0)) + val
                    if receiver == target:
                        token_deltas[tid] = token_deltas.get(tid, Decimal(0)) + val
                        last_log_index = str(hex_int(log.get("logIndex", "")))

            elif len(topics) >= 4 and topic0 == TRANSFER_BATCH_TOPIC:
                sender = "0x" + topics[2][-40:].lower()
                receiver = "0x" + topics[3][-40:].lower()
                raw_data = log.get("data", "")
                if raw_data.startswith("0x"):
                    raw_data = raw_data[2:]
                try:
                    # ABI 動態陣列解碼: word 0: ids offset, word 1: values offset
                    if len(raw_data) >= 128:
                        ids_offset = int(raw_data[0:64], 16) * 2
                        vals_offset = int(raw_data[64:128], 16) * 2
                        ids_len = int(raw_data[ids_offset:ids_offset + 64], 16)
                        vals_len = int(raw_data[vals_offset:vals_offset + 64], 16)
                        count = min(ids_len, vals_len)
                        for i in range(count):
                            id_start = ids_offset + 64 + i * 64
                            val_start = vals_offset + 64 + i * 64
                            tid = int(raw_data[id_start:id_start + 64], 16)
                            val = Decimal(int(raw_data[val_start:val_start + 64], 16)) / Decimal(10**6)

                            if sender == target:
                                token_deltas[tid] = token_deltas.get(tid, Decimal(0)) - val
                                last_log_index = str(hex_int(log.get("logIndex", "")))
                                if receiver == ZERO_ADDRESS:
                                    token_burned[tid] = token_burned.get(tid, Decimal(0)) + val
                            if receiver == target:
                                token_deltas[tid] = token_deltas.get(tid, Decimal(0)) + val
                                last_log_index = str(hex_int(log.get("logIndex", "")))
                except (ValueError, IndexError):
                    pass

    # 3. 依 Net Delta 綜合判定行為
    active_tokens = {tid: delta for tid, delta in token_deltas.items() if delta != 0}
    net_collateral = sum(collateral_delta.values()) if collateral_delta else Decimal(0)
    primary_token = next((k for k, v in collateral_delta.items() if v != 0), "pUSD")

    # 若完全沒有條件代幣變動，不判定為投注交易
    if not active_tokens and not token_burned:
        return None

    # 判定情境 A: 勝選兌現（代幣銷毀至 0x0 且收回本金）
    if token_burned and net_collateral > 0:
        action = "勝選兌現 (REDEEM)"
        main_tid = max(token_burned, key=token_burned.get)
        shares = token_burned[main_tid]
        collateral_amt = net_collateral
    # 判定情境 B: 買進（支出本金且獲得代幣）
    elif net_collateral < 0 and any(d > 0 for d in active_tokens.values()):
        action = "買進 (BUY)"
        main_tid = max(active_tokens, key=active_tokens.get)
        shares = active_tokens[main_tid]
        collateral_amt = abs(net_collateral)
    # 判定情境 C: 賣出（交出代幣且收回本金）
    elif net_collateral > 0 and any(d < 0 for d in active_tokens.values()):
        action = "賣出 (SELL)"
        main_tid = min(active_tokens, key=active_tokens.get)
        shares = abs(active_tokens[main_tid])
        collateral_amt = net_collateral
    # 判定情境 D: 部位調整 / 拆分合併
    else:
        action = "部位調整 (SPLIT/MERGE)"
        main_tid = max(active_tokens, key=lambda k: abs(active_tokens[k])) if active_tokens else (next(iter(token_burned)) if token_burned else 0)
        shares = abs(active_tokens.get(main_tid, Decimal(0))) or (token_burned.get(main_tid, Decimal(0)))
        collateral_amt = abs(net_collateral)

    # 4. 計算單價與勝率
    if shares > 0 and collateral_amt > 0:
        price = collateral_amt / shares
        price_str = f"{price:.6f}"
        prob_str = f"{float(price) * 100:.2f}%"
    elif "REDEEM" in action:
        price_str = "1.000000"
        prob_str = "100.00%"
    else:
        price_str = "0.000000"
        prob_str = "0.00%"

    token_id_str = str(main_tid)
    token_id_hex = hex(main_tid)
    outcome_index = 0 if (main_tid % 2 != 0) else 1

    return BetTrade(
        action=action,
        collateral_token=primary_token,
        collateral_amount=f"{collateral_amt:.6f}",
        shares=f"{shares:.6f}",
        price_per_share=price_str,
        implied_probability=prob_str,
        token_id=token_id_str,
        token_id_hex=token_id_hex,
        outcome_index=outcome_index,
        tx_hash=tx_hash,
        timestamp=timestamp,
        log_index=last_log_index,
    )
