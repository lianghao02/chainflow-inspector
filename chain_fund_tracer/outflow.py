"""增量式出金追蹤；僅延伸精確配對的 Relay 結果，不改寫入金引擎。"""
from collections import deque
from decimal import Decimal

from .models import TraceStep, timestamp_to_text
from .providers import ProviderError
from .relay_evidence import amount_text, destination_fills, explorer_url
from .flow_graph import is_vasp

MAX_REQUESTS = 5
MAX_ADDRESSES = 8
MAX_BRANCHES = 5
HISTORY_LIMIT = 100
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def _receipt_transfer_log(receipt, fill):
    """回傳與 Relay 目的鏈淨額完全一致的唯一 ERC-20 Transfer Log。"""
    matches = []
    for log in (receipt or {}).get("logs", []):
        topics = log.get("topics") or []
        if (len(topics) < 3 or str(topics[0]).lower() != TRANSFER_TOPIC
                or str(log.get("address", "")).lower() != fill["contract"].lower()):
            continue
        sender = "0x" + str(topics[1])[-40:]
        recipient = "0x" + str(topics[2])[-40:]
        try:
            raw = int(str(log.get("data", "0x0")), 16)
        except ValueError:
            continue
        if (sender.lower() == fill["from"].lower() and recipient.lower() == fill["to"].lower()
                and raw == int(fill["raw_amount"])):
            matches.append(log)
    return matches[0] if len(matches) == 1 else None


def append_relay_outflows(analyzer, result, max_hops):
    from .analysis import CHAIN_NAMES
    origins = {s.tx_hash: s for s in result.steps if s.direction == "Relay 出金" and s.path_role == "出金"}
    if len(origins) > MAX_REQUESTS:
        result.warnings.append(f"出金 Relay 查詢限 {MAX_REQUESTS} 筆，尚有分支未查。")
    for origin in list(origins.values())[:MAX_REQUESTS]:
        if max_hops < 2:
            result.warnings.append("出金追蹤深度不足：尚未查詢 Relay 目的鏈。")
            continue
        analyzer.progress("正在精確配對出金 Relay Request 與目的鏈入帳…")
        try:
            matched = analyzer.provider.relay_request_by_hash(origin.tx_hash)
        except ProviderError as exc:
            result.warnings.append(f"出金 Relay 查詢失敗，已保留原轉帳：{exc}")
            continue
        fills = destination_fills(matched or {}, origin.tx_hash)
        if not fills:
            result.warnings.append(f"出金 {origin.tx_hash} 未取得唯一付款／收款餘額配對；可能未完成、退款、批次或索引欄位不足，不推測目的鏈。")
            continue
        origin.relay_request_id = matched["request"]["id"]
        origin.relay_leg, origin.pair_verified = "source", True
        origin.event_role = "跨鏈轉出"
        result.sources.append(f"Relay Requests v{matched['version']}：https://api.relay.link/requests/v{matched['version']}（Request {origin.relay_request_id}）")
        for fill in fills:
            chain = CHAIN_NAMES.get(fill["chain_id"], f"chainId {fill['chain_id']}")
            receipt_log = None
            try:
                receipt = analyzer.provider.chain_receipt(fill["hash"], fill["chain_id"])
                if receipt:
                    result.add_evidence("relay_destination_receipt", f"{chain} RPC Receipt：{fill['hash']}", receipt)
                    receipt_log = _receipt_transfer_log(receipt, fill)
            except ProviderError as exc:
                result.warnings.append(f"出金目的鏈 Receipt 核對失敗（{fill['hash']}）：{exc}")
            if not receipt_log:
                result.warnings.append(
                    f"出金目的鏈 {fill['hash']} 尚未取得唯一且金額一致的原始 Transfer Log；保留 Relay 淨額索引，但不提升為逐筆轉帳證據。"
                )
            # 目前內建地址清冊屬 BNB Chain，不能套用到另一條鏈的同地址。
            classification = analyzer.classify(fill["to"]) if fill["chain_id"] == 56 else ("未知地址", "", "無公開標籤", "未知")
            step = TraceStep(
                "Relay 出金目的鏈入帳", 2, fill["hash"], timestamp_to_text(fill["time"]),
                fill["symbol"], fill["amount"], fill["from"], fill["to"], fill["to"],
                *classification, "僅資金關聯",
                "同一 Relay Request 的目的鏈資產淨額變化；箭頭表示索引中的減少／增加關係，未以 Receipt 獨立核對逐筆 Transfer。",
                chain=chain, chain_id=fill["chain_id"], block_number=fill["block"],
                log_index=str(int(receipt_log.get("logIndex", "0x0"), 16)) if receipt_log else "",
                path_role="出金", event_role="跨鏈入帳", explorer_url=explorer_url(fill["chain_id"], fill["hash"]),
                relay_request_id=fill["request_id"], relay_leg="destination", pair_verified=True,
                token_contract=fill["contract"],
                evidence_source=("目的鏈 RPC Receipt Transfer Log／Relay Request 精確配對"
                                 if receipt_log else "Relay stateChanges 淨額索引（尚未逐筆核對 Transfer Log）"),
            )
            result.steps.append(step)
            result.summary.append(f"出金 Relay 目的鏈：{chain}；索引入帳 {fill['amount']} {fill['symbol']} 至 {fill['to']}。")
            if not is_vasp(step):
                _follow_recipient(analyzer, result, fill, max_hops)


def _follow_recipient(analyzer, result, fill, max_hops):
    from .analysis import event_address, event_label, event_timestamp, CHAIN_NAMES
    chain_id, contract = fill["chain_id"], fill["contract"].lower()
    start_time = event_timestamp(fill["time"])
    if not start_time:
        result.warnings.append("目的鏈入帳缺少時間，停止續追以免混入較早轉帳。")
        return
    frontier = deque([(fill["to"], start_time, 3)])
    visited, seen = set(), set()
    while frontier and len(visited) < MAX_ADDRESSES:
        address, cutoff, hop = frontier.popleft()
        if hop > max_hops:
            result.warnings.append("出金目的鏈已達追蹤深度；未查分支不代表沒有交易所關聯。")
            continue
        key = (chain_id, address.lower())
        if key in visited:
            continue
        visited.add(key)
        analyzer.progress(f"正在查看出金目的鏈收款地址 {address[:12]}… 的後續同資產轉帳")
        try:
            history = analyzer.provider.chain_token_transfers(address, chain_id, HISTORY_LIMIT)
        except ProviderError as exc:
            result.warnings.append(f"出金目的鏈 {address} 查詢中斷：{exc}")
            continue
        candidates = []
        for event in history:
            token = event.get("token") or {}
            token_address = token.get("address") or token.get("address_hash") or event.get("contractAddress", "")
            sender, recipient = event_address(event.get("from")), event_address(event.get("to"))
            when = event.get("timestamp", event.get("timeStamp", ""))
            tx = event.get("transaction_hash") or event.get("tx_hash") or event.get("hash", "")
            if (token_address.lower() != contract or sender.lower() != address.lower()
                    or event_timestamp(when) <= cutoff or not recipient or not tx):
                continue
            raw = (event.get("total") or {}).get("value") if isinstance(event.get("total"), dict) else event.get("value")
            amount = amount_text(raw, fill["decimals"])
            if not amount or not Decimal(amount).is_finite() or Decimal(amount) <= 0:
                continue
            candidates.append((event_timestamp(when), tx, sender, recipient, amount, when, event))
        candidates.sort(key=lambda item: (item[0], item[1]))
        if len(candidates) > MAX_BRANCHES:
            result.warnings.append(f"出金 {address} 分支超過 {MAX_BRANCHES} 筆，僅顯示查得範圍內較早的轉出。")
        if not candidates:
            result.warnings.append(f"出金 {address}：本次索引範圍未找到時間較晚的同合約轉出；不代表沒有出金或交易所關聯。")
        for when_num, tx, sender, recipient, amount, when, event in candidates[:MAX_BRANCHES]:
            event_key = (chain_id, tx, str(event.get("log_index", event.get("index", ""))), sender.lower(), recipient.lower(), amount)
            if event_key in seen:
                continue
            seen.add(event_key)
            public_label = event_label(event.get("to"))
            classification = analyzer.classify(recipient, public_label) if chain_id == 56 else analyzer.classify("", public_label)
            step = TraceStep(
                "出金目的鏈後續轉出候選", hop, tx, timestamp_to_text(when), fill["symbol"], amount,
                sender, recipient, recipient, *classification, "僅資金關聯",
                "僅為收款地址較晚的同資產轉帳候選；可能與既有餘額混合，未證明全部或部分款項來自該筆 Relay。",
                chain=CHAIN_NAMES.get(chain_id, f"chainId {chain_id}"), chain_id=chain_id,
                block_number=str(event.get("block_number") or event.get("blockNumber") or ""),
                log_index=str(event.get("log_index", event.get("index", ""))), path_role="出金",
                token_contract=contract, evidence_source="Explorer Token Transfers 索引／時間順序關聯",
                explorer_url=explorer_url(chain_id, tx),
            )
            result.steps.append(step)
            if is_vasp(step):
                result.summary.append(f"出金候選命中公開交易所標籤：{step.label}；不是款項逐筆歸屬或身分認定。")
            elif step.classification in {"Bridge", "DEX", "Polymarket"}:
                result.warnings.append(f"出金至 {recipient} 命中協定節點；本輪停止該分支，未把協定庫存當作使用者後續款項。")
            else:
                frontier.append((recipient, when_num, hop + 1))
    if frontier:
        result.warnings.append(f"出金目的鏈達 {MAX_ADDRESSES} 個地址查詢上限，仍有分支未查。")
    result.warnings.append(f"目的鏈續追只檢查每地址近期最多 {HISTORY_LIMIT} 筆同資產索引；未完整掃描歷史、不處理同秒先後及再次跨鏈／兌換。")
