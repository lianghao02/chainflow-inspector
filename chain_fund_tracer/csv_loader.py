from __future__ import annotations
import csv
import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

from .models import timestamp_to_text

# 零地址與已核實之 Polymarket 核心內部/交易合約
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"

KNOWN_POLYMARKET_CONTRACTS = {
    "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",  # pUSD Token
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # USDC (Native)
    "0x4d97dcd97ec945f40cf65f87097ace5ea0476045",  # Conditional Tokens (CTF)
    "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e",  # CTF Exchange
    "0xc5d563a36ae78145c45a50134d48a1215220f80a",  # Neg Risk CTF Exchange
    "0xd91e80cf2e7be2e162c6513ced06f1dcc40e5296",  # Neg Risk Adapter
    "0x3a3bd7bb9528e159577f7c2e685cc81a765002e2",  # NegRisk Wrapped Collateral
    "0xe111180000d2663c0091e4f400237545b87b996b",  # CTF Exchange (舊/相容)
    "0xe2222d279d744050d28e00520010520000310f59",  # Neg Risk Exchange (舊/相容)
    "0x93070a847efef7f70739046a929d47a521f5b8ee",  # Collateral Onramp
    "0xc288480574783bd7615170660d71753378159c47",  # Reward Distributor
    "0xc417fd8e9661c0d2120b64a04bb3278c17e99db1",  # pUSD Settlement
    "0x4cd00e387622c35bddb9b4c962c136462338bc31",  # Relay Depository
}

REQUIRED_HEADERS = {"transaction hash", "from", "to", "tokenvalue"}


def normalize(val: str | None) -> str:
    return str(val or "").strip().lower()


def compute_file_sha256(file_path: str) -> str:
    """計算本機檔案之 SHA-256 雜湊值作為客觀稽核指紋。"""
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha256.update(chunk)
    return sha256.hexdigest()


def inspect_and_load_polygonscan_csv(
    file_path: str,
    target_address: str,
    max_candidates: int = 50,
) -> dict[str, Any]:
    """
    解析 PolygonScan ERC-20 Token Transfers CSV 檔案，進行保守分類並抽取入金候選交易。

    【法證定位】
    CSV 嚴格定位為「使用者提供之歷史索引，用來選出候選 Tx Hash」，
    不等於最終鏈上證據；最終結論仍須透過 RPC Receipt、原始 Logs 與 Relay 進行鏈上核實。
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"找不到指定的 CSV 檔案：{file_path}")

    sha256_hash = compute_file_sha256(file_path)
    norm_target = normalize(target_address)

    # 嘗試讀取編碼（優先處理含 BOM 之 UTF-8）
    content = ""
    for enc in ("utf-8-sig", "utf-8", "cp950", "latin-1"):
        try:
            with open(file_path, "r", encoding=enc) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if not content:
        raise ValueError("CSV 檔案為空或無法辨識文字編碼。")

    lines = content.splitlines()
    if not lines:
        raise ValueError("CSV 檔案無有效資料列。")

    reader = csv.reader(lines)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("CSV 檔案缺少欄位標頭（Header）。")

    # 建立標頭名稱與索引映射（忽略大小寫與空白）
    header_map: dict[str, int] = {}
    for idx, h in enumerate(raw_headers):
        clean_h = h.strip().lower()
        header_map[clean_h] = idx

    # 驗證必要欄位
    missing = [req for req in REQUIRED_HEADERS if req not in header_map]
    if missing:
        raise ValueError(
            f"CSV 格式不符 PolygonScan Token Transfers 標準；缺少必要欄位：{', '.join(missing)}"
        )

    idx_tx = header_map["transaction hash"]
    idx_from = header_map["from"]
    idx_to = header_map["to"]
    idx_val = header_map["tokenvalue"]
    idx_time = header_map.get("datetime (utc)")
    if idx_time is None:
        idx_time = header_map.get("datetime")
    if idx_time is None:
        idx_time = header_map.get("unixtimestamp")
    idx_symbol = header_map.get("tokensymbol")
    idx_block = header_map.get("blockno")

    total_rows = 0
    inbound_count = 0
    outbound_count = 0
    tokens_found: set[str] = set()
    timestamps: list[str] = []

    mints: list[dict[str, Any]] = []
    external_inflows: list[dict[str, Any]] = []
    internal_transfers: list[dict[str, Any]] = []
    betting_candidates: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    seen_betting_hashes: set[str] = set()

    for row_num, row in enumerate(reader, start=2):
        if not row or len(row) <= max(header_map.values()):
            continue

        tx_hash = normalize(row[idx_tx])
        if not tx_hash or not tx_hash.startswith("0x"):
            continue

        total_rows += 1
        frm = normalize(row[idx_from])
        to = normalize(row[idx_to])
        val_str = row[idx_val].replace(",", "").strip()
        dt_str = row[idx_time].strip() if idx_time is not None and idx_time < len(row) else ""
        symbol = row[idx_symbol].strip() if idx_symbol is not None and idx_symbol < len(row) else "未知代幣"
        block_no = row[idx_block].strip() if idx_block is not None and idx_block < len(row) else ""

        tokens_found.add(symbol)
        if dt_str:
            timestamps.append(dt_str)

        # 僅關注與目標地址有關的轉帳
        if to == norm_target:
            inbound_count += 1
            if tx_hash in seen_hashes:
                continue

            # 保守分類原則：
            # 1. 零地址鑄造候選
            # 2. 已知 Polymarket 內部合約
            # 3. 外部轉入候選（非零地址且非已知合約；待鏈上 Receipt 核實）
            if frm == ZERO_ADDRESS:
                category = "零地址鑄造候選"
                note = "由 CSV 索引識別為 pUSD 零地址鑄造；需讀取 Receipt Logs 核對同筆交易支付 USDC 的底層出資來源。"
                item = {
                    "hash": tx_hash,
                    "time": dt_str,
                    "from": frm,
                    "to": to,
                    "token": symbol,
                    "amount": val_str,
                    "block_number": block_no,
                    "category": category,
                    "note": note,
                }
                mints.append(item)
                seen_hashes.add(tx_hash)
            elif frm in KNOWN_POLYMARKET_CONTRACTS:
                category = "已知 Polymarket 內部合約"
                internal_transfers.append({
                    "hash": tx_hash, "time": dt_str, "from": frm, "to": to,
                    "token": symbol, "amount": val_str, "category": category
                })
            else:
                category = "外部轉入候選"
                note = "由 CSV 索引識別為外部轉入；需由鏈上 Receipt 確認是否為 Relay 跨鏈履約、合約或一般錢包。"
                item = {
                    "hash": tx_hash,
                    "time": dt_str,
                    "from": frm,
                    "to": to,
                    "token": symbol,
                    "amount": val_str,
                    "block_number": block_no,
                    "category": category,
                    "note": note,
                }
                external_inflows.append(item)
                seen_hashes.add(tx_hash)

        elif frm == norm_target:
            outbound_count += 1

        # CSV 只作為候選索引；是否真為投注仍須由同筆 Receipt 的
        # pUSD 與 ERC-1155 條件代幣變化共同確認。
        counterparty = to if frm == norm_target else frm
        if (
            (frm == norm_target or to == norm_target)
            and symbol.strip().lower() == "pusd"
            and counterparty in KNOWN_POLYMARKET_CONTRACTS
            and tx_hash not in seen_betting_hashes
        ):
            betting_candidates.append({
                "hash": tx_hash,
                "time": dt_str,
                "from": frm,
                "to": to,
                "token": symbol,
                "amount": val_str,
                "block_number": block_no,
            })
            seen_betting_hashes.add(tx_hash)

    # 排序與時間跨度計算（嚴謹取最小與最大時間，並換算為臺灣標準時間 +0800）
    def _to_timestamp(ts_str: str) -> float:
        if not ts_str:
            return 0.0
        try:
            if "T" in ts_str:
                return datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            return datetime.strptime(ts_str.replace(" UTC", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            try:
                return float(ts_str)
            except Exception:
                return 0.0

    valid_ts = sorted([ts for ts in timestamps if ts], key=_to_timestamp)
    start_raw = valid_ts[0] if valid_ts else "未知"
    end_raw = valid_ts[-1] if valid_ts else "未知"
    start_time_tw = timestamp_to_text(start_raw) or start_raw
    end_time_tw = timestamp_to_text(end_raw) or end_raw

    is_truncated = (total_rows >= 5000)

    def _parse_cand_time(item: dict[str, Any]) -> float:
        t = item.get("time", "")
        if not t:
            return 0.0
        try:
            if "T" in t:
                return datetime.fromisoformat(t.replace("Z", "+00:00")).timestamp()
            return datetime.strptime(t, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
        except Exception:
            return 0.0

    mints.sort(key=_parse_cand_time, reverse=True)
    external_inflows.sort(key=_parse_cand_time, reverse=True)
    betting_candidates.sort(key=_parse_cand_time, reverse=True)

    # 候選交易合併（零地址鑄造優先，次之為外部直接轉入；兩者皆按時間由新到舊倒序）
    combined_candidates = mints + external_inflows
    selected_candidates = combined_candidates[:max_candidates]

    import_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "file_name": os.path.basename(file_path),
        "file_path": file_path,
        "sha256": sha256_hash,
        "import_time": import_time_utc,
        "total_rows": total_rows,
        "is_truncated": is_truncated,
        "time_range": f"{start_time_tw} 至 {end_time_tw}" if start_raw != "未知" else "未取得",
        "tokens": sorted(list(tokens_found)),
        "target_address": target_address,
        "inbound_count": inbound_count,
        "outbound_count": outbound_count,
        "mint_candidates_count": len(mints),
        "external_candidates_count": len(external_inflows),
        "internal_count": len(internal_transfers),
        "betting_candidates_count": len(betting_candidates),
        "betting_candidates": betting_candidates[:max_candidates],
        "candidates": selected_candidates,
    }
