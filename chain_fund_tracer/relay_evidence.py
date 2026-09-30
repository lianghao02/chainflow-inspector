"""Relay 索引證據的精確配對；不以時間或金額相近補造跨鏈關係。"""
from decimal import Decimal, InvalidOperation, localcontext


def tx_hash(tx: dict) -> str:
    return str(tx.get("txHash") or tx.get("hash") or tx.get("transactionId") or "")


def select_request(requests: list[dict], query: str) -> dict | None:
    matches = []
    for request in requests:
        data = request.get("data") or {}
        hashes = {tx_hash(tx).lower() for key in ("inTxs", "outTxs") for tx in data.get(key, []) or []}
        if query.lower() in hashes and request.get("id"):
            matches.append(request)
    # 同筆批次交易涉及多個 Request 時，不任選第一筆。
    return matches[0] if len(matches) == 1 else None


def amount_text(raw, decimals) -> str:
    try:
        places = int(decimals)
        if not 0 <= places <= 36:
            return ""
        with localcontext() as ctx:
            ctx.prec = 100
            value = Decimal(str(raw))
            return format(value / (Decimal(10) ** places), "f") if value.is_finite() else ""
    except (ValueError, TypeError, InvalidOperation):
        return ""


def request_legs(matched: dict) -> tuple[list[dict], list[dict]]:
    request = matched.get("request") or {}
    data = request.get("data") or {}
    return data.get("inTxs") or [], data.get("outTxs") or []


def exact_pair(matched: dict, source_hash: str, destination_hash: str) -> bool:
    ins, outs = request_legs(matched)
    return bool(source_hash and destination_hash and (matched.get("request") or {}).get("id")) and (
        source_hash.lower() in {tx_hash(tx).lower() for tx in ins}
        and destination_hash.lower() in {tx_hash(tx).lower() for tx in outs}
    )


def destination_fills(matched: dict, source_hash: str) -> list[dict]:
    """只還原成功 Request 的已成功 outTx；餘額差是索引證據而非 Transfer Log。"""
    request = matched.get("request") or {}
    if request.get("status") != "success":
        return []
    ins, _outs = request_legs(matched)
    if len(ins) != 1 or ins[0].get("status") != "success":
        return []
    data = request.get("data") or {}
    if matched.get("version") == 3:
        asset = (((data.get("route") or {}).get("actual") or {}).get("destination") or {}).get("outputCurrency") or {}
    else:
        asset = (data.get("metadata") or {}).get("currencyOut") or {}
    currency = asset.get("currency") or {}
    recipient = request.get("recipient") or (data.get("metadata") or {}).get("recipient") or ""
    contract = currency.get("address", "")
    if not recipient or not contract or currency.get("decimals") is None:
        return []
    fills = []
    for tx in request_legs(matched)[1]:
        if tx.get("status") != "success" or not exact_pair(matched, source_hash, tx_hash(tx)):
            continue
        try:
            chain_id = int(tx.get("chainId") or 0)
            currency_chain = int(currency.get("chainId") or 0)
        except (ValueError, TypeError):
            continue
        if chain_id != currency_chain or chain_id not in EXPLORERS:
            continue
        credits, debits = [], []
        for entry in tx.get("stateChanges") or []:
            change = entry.get("change") or {}
            token = (change.get("data") or {}).get("tokenAddress", "")
            if token.lower() != contract.lower():
                continue
            try:
                diff = int(change.get("balanceDiff", "0"))
            except (ValueError, TypeError):
                continue
            if diff > 0 and entry.get("address", "").lower() == recipient.lower():
                credits.append(diff)
            elif diff < 0:
                debits.append((entry.get("address", ""), -diff))
        # 多對多資產變化不能由淨額推導唯一付款者。
        if len(credits) != 1 or len(debits) != 1 or credits[0] != debits[0][1]:
            continue
        amount = amount_text(credits[0], currency["decimals"])
        if not amount:
            continue
        fills.append({
            "request_id": request["id"], "hash": tx_hash(tx),
            "chain_id": int(tx["chainId"]), "time": tx.get("timestamp", ""),
            "block": str(tx.get("block", "")), "from": debits[0][0], "to": recipient,
            "contract": contract, "symbol": currency.get("symbol", "未知資產"),
            "amount": amount, "raw_amount": str(credits[0]), "decimals": currency["decimals"],
        })
    return fills


EXPLORERS = {1: "https://etherscan.io/tx/", 10: "https://optimistic.etherscan.io/tx/",
             56: "https://bscscan.com/tx/", 137: "https://polygonscan.com/tx/",
             8453: "https://basescan.org/tx/", 42161: "https://arbiscan.io/tx/"}


def explorer_url(chain_id: int, value: str) -> str:
    if chain_id == 728126428 and value:
        return "https://tronscan.org/#/transaction/" + value
    return EXPLORERS[chain_id] + value if chain_id in EXPLORERS and value else ""


def same_chain_request_match(
    matched: dict,
    query_tx_hash: str,
    expected_recipient: str,
    expected_output_token: str = "",
    receipt_transfers: list | None = None,
) -> dict | None:
    """核對同鏈 Relay Request 證據，不假定輸入與輸出金額絕對相等（容許換匯與手續費差額）。

    核對項目：
    - Request 狀態為 success，且具備有效 Request ID。
    - query_tx_hash 存在於 inTxs 或 outTxs 之一。
    - origin_chain_id 與 destination_chain_id 相同且有效。
    - Request recipient 與 expected_recipient 吻合。
    - 若指定 expected_output_token，合約地址必須吻合。
    - 若提供 receipt_transfers，核對是否有相符的 recipient 與 token 撥付事件。
    """
    if not isinstance(matched, dict):
        return None
    request = matched.get("request") or {}
    if request.get("status") != "success":
        return None
    req_id = request.get("id")
    if not req_id:
        return None

    data = request.get("data") or {}
    metadata = data.get("metadata") or {}
    route = data.get("route") or {}
    actual = route.get("actual") or {}

    ins, outs = request_legs(matched)
    all_tx_hashes = {tx_hash(tx).lower() for tx in ins + outs if tx_hash(tx)}
    if not query_tx_hash or query_tx_hash.lower() not in all_tx_hashes:
        return None

    # Recipient 比對
    recipient = (
        request.get("recipient")
        or metadata.get("recipient")
        or actual.get("destination", {}).get("recipient")
        or ""
    )
    if not recipient or recipient.lower() != expected_recipient.lower():
        return None

    # Currency In / Out
    if matched.get("version") == 3:
        origin_asset = (actual.get("origin") or {}).get("inputCurrency") or metadata.get("currencyIn") or {}
        dest_asset = (actual.get("destination") or {}).get("outputCurrency") or metadata.get("currencyOut") or {}
    else:
        origin_asset = metadata.get("currencyIn") or (actual.get("origin") or {}).get("inputCurrency") or {}
        dest_asset = metadata.get("currencyOut") or (actual.get("destination") or {}).get("outputCurrency") or {}

    in_curr = origin_asset.get("currency") or {}
    out_curr = dest_asset.get("currency") or {}

    try:
        origin_chain = int(in_curr.get("chainId") or (ins[0].get("chainId") if ins else 0) or 0)
        dest_chain = int(out_curr.get("chainId") or (outs[0].get("chainId") if outs else 0) or 0)
    except (ValueError, TypeError):
        return None

    if origin_chain == 0 or dest_chain == 0 or origin_chain != dest_chain:
        return None

    # Input amount and symbol
    in_symbol = in_curr.get("symbol") or origin_asset.get("symbol") or "USDC"
    in_token = in_curr.get("address") or origin_asset.get("address") or ""
    in_amount = origin_asset.get("amountFormatted") or amount_text(origin_asset.get("amount"), in_curr.get("decimals"))

    # Output amount and symbol
    out_symbol = out_curr.get("symbol") or dest_asset.get("symbol") or "pUSD"
    out_token = out_curr.get("address") or dest_asset.get("address") or ""
    out_amount = dest_asset.get("amountFormatted") or amount_text(dest_asset.get("amount"), out_curr.get("decimals"))

    if expected_output_token:
        if not out_token or expected_output_token.lower() != out_token.lower():
            return None

    # Sender / User
    sender = request.get("user") or request.get("sender") or metadata.get("sender") or ""

    # Receipt transfer verification (若提供則進行鏈上 Transfer 事件雙重核對)
    if receipt_transfers is not None:
        matched_transfer = False
        for t in receipt_transfers:
            to_addr = getattr(t, "to_address", "") or (t.get("to") if isinstance(t, dict) else "")
            token_sym = getattr(t, "token", "") or (t.get("token") if isinstance(t, dict) else "")
            if to_addr and to_addr.lower() == expected_recipient.lower():
                if token_sym.lower() == out_symbol.lower() or token_sym.lower() in ("pusd", "usdc", "usdc.e"):
                    matched_transfer = True
                    break
        if not matched_transfer:
            return None

    in_tx_hash = tx_hash(ins[0]) if ins else query_tx_hash
    out_tx_hash = tx_hash(outs[0]) if outs and tx_hash(outs[0]) else in_tx_hash

    return {
        "matched": True,
        "request_id": req_id,
        "version": matched.get("version", 2),
        "origin_chain_id": origin_chain,
        "destination_chain_id": dest_chain,
        "input_token": in_token,
        "input_symbol": in_symbol,
        "input_amount": in_amount,
        "output_token": out_token,
        "output_symbol": out_symbol,
        "output_amount": out_amount,
        "sender": sender,
        "recipient": recipient,
        "origin_tx_hash": in_tx_hash,
        "destination_tx_hash": out_tx_hash,
        "status": "success",
        "timestamp": request.get("createdAt") or request.get("updatedAt") or "",
        "source": f"Relay Requests API v{matched.get('version', 2)}",
    }
