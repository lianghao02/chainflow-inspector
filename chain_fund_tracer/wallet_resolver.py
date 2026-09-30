"""唯讀介面探測；標準 Proxy 特徵不等於 Polymarket 身分或自然人控制權。"""
import re
from datetime import datetime, timezone
from .providers import ProviderError

IMPLEMENTATION_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
WORD = re.compile(r"^0x[0-9a-fA-F]{64}$")
MINIMAL_PROXY = re.compile(r"^0x363d3d373d3d3d363d73([0-9a-f]{40})5af43d82803e903d91602b57fd5bf3$")


def word_address(value):
    if isinstance(value, str) and WORD.fullmatch(value) and value[2:26] == "0" * 24:
        return "0x" + value[-40:]
    return "未取得"


def resolve_wallet(provider, address, progress=None):
    def read(method, params):
        if progress:
            progress(f"正在讀取合約結構：{method}…")
        return provider.rpc(method, params)

    chain_id_hex = read("eth_chainId", [])
    try:
        chain_id_val = int(chain_id_hex, 16) if chain_id_hex else 0
    except (ValueError, TypeError):
        chain_id_val = 0
    if chain_id_val != 137:
        raise ProviderError("RPC 不是 Polygon；停止讀取，避免跨鏈誤認。")
    block = read("eth_getBlockByNumber", ["latest", False]) or {}
    number, block_hash = block.get("number"), block.get("hash")
    if not number or not block_hash:
        raise ProviderError("無法固定查詢區塊，未讀取合約結構。")
    info = {"Contract": address, "鏈別": "Polygon", "查詢區塊": number, "區塊 Hash": block_hash,
            "擷取時間 UTC": datetime.now(timezone.utc).isoformat(), "owner()": "未取得", "factory()": "未取得",
            "id()": "未取得", "是否 Proxy": "未確認", "Implementation": "未取得",
            "定性限制": "僅探測合約介面與儲存特徵，尚未驗證 Polymarket 工廠來源／ABI；owner 回傳地址不是自然人身分或交易當時控制權。"}
    code = read("eth_getCode", [address, number])
    if code in (None, "0x", "0x0"):
        info["程式碼"] = "此查詢區塊無程式碼，未確認為智能合約錢包。"
        return info
    info["程式碼"] = "此查詢區塊有程式碼；不單憑此認定為 DepositWallet。"
    for method in ("owner()", "factory()", "id()"):
        try:
            digest = read("web3_sha3", ["0x" + method.encode("ascii").hex()])
            if not isinstance(digest, str) or not WORD.fullmatch(digest):
                continue
            raw = read("eth_call", [{"to": address, "data": digest[:10]}, number])
            info[method + " 原始回傳"] = str(raw)
            info[method] = raw if method == "id()" and isinstance(raw, str) and WORD.fullmatch(raw) else word_address(raw)
        except ProviderError:
            info[method] = "未取得（介面不支援或 RPC 失敗）"
    match = MINIMAL_PROXY.fullmatch(str(code).lower())
    if match:
        info["是否 Proxy"] = "符合 ERC-1167 標準最小代理碼"
        info["Implementation"] = "0x" + match.group(1)
    else:
        try:
            raw = read("eth_getStorageAt", [address, IMPLEMENTATION_SLOT, number])
            info["ERC-1967 原始儲存值"] = str(raw)
            implementation = word_address(raw)
            if implementation not in {"未取得", "0x" + "0" * 40}:
                info["是否 Proxy"] = "具有 ERC-1967 implementation 儲存特徵（仍須核對代理碼）"
                info["Implementation"] = implementation
        except ProviderError:
            pass
    end_block = read("eth_getBlockByNumber", [number, False]) or {}
    if end_block.get("hash") != block_hash:
        raise ProviderError("查詢期間區塊改變，請重試；未保存可能混合的結構資訊。")
    return info
