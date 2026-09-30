from __future__ import annotations
from datetime import datetime, timezone, timedelta
import json
import time
from typing import Any
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from .config import Settings
from .relay_evidence import select_request


class ProviderError(RuntimeError):
    def __init__(self, message: str, *, attempts: int = 1, retryable: bool = False):
        super().__init__(message)
        self.attempts = attempts
        self.retryable = retryable

TAIWAN_TZ = timezone(timedelta(hours=8))


def parse_time_anchor(time_str: str, is_end_time: bool = True) -> float | None:
    """
    解析使用者輸入的日期時間字串（支援 YYYY-MM-DD、YYYY/MM/DD、YYYY-MM-DD HH:MM 等）。
    預設轉換為臺灣時間（UTC+8）之 UNIX 時間戳（秒）。
    若僅有日期：
      - is_end_time=True 時預設為當日 23:59:59（適合作為回溯基準日/結束時間）
      - is_end_time=False 時預設為當日 00:00:00（適合作為起始時間）
    若輸入空白或 None，回傳 None。
    若格式不符，拋出 ValueError。
    """
    if not time_str or not str(time_str).strip():
        return None
    raw = str(time_str).strip().replace("/", "-").replace(".", "-")
    formats = [
        ("%Y-%m-%d %H:%M:%S", False),
        ("%Y-%m-%d %H:%M", False),
        ("%Y-%m-%dT%H:%M:%S", False),
        ("%Y-%m-%dT%H:%M", False),
        ("%Y-%m-%d", True),
    ]
    for fmt, is_date_only in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if is_date_only:
                if is_end_time:
                    dt = dt.replace(hour=23, minute=59, second=59)
                else:
                    dt = dt.replace(hour=0, minute=0, second=0)
            dt_with_tz = dt.replace(tzinfo=TAIWAN_TZ)
            return dt_with_tz.timestamp()
        except ValueError:
            continue
    raise ValueError(f"無法解析時間格式「{time_str}」；請使用 YYYY-MM-DD 或 YYYY-MM-DD HH:MM（例如 2024-05-15 或 2024-05-15 14:30）。")

TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
TOKEN_SYMBOLS = {
    "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb": "pUSD",
    "0x2791bca1f2de4661ed88a30c99a7a9449aa84174": "USDC.e",
    "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359": "USDC",
    "0xc2132d05d31c914a87c6611c10748aeb04b58e8f": "USDT",
}
BNB_TOKEN_METADATA = {
    "0x55d398326f99059ff775485246999027b3197955": ("USDT", 18),
    "0x8ac76a51cc950d9822d68b83fe1ad97b32cd580d": ("USDC", 18),
}
POLYGON_RPC_FALLBACKS = (
    "https://polygon.drpc.org",
    "https://tenderly.rpc.polygon.community",
    "https://polygon.publicnode.com",
)
CHAIN_RPC_URLS = {
    1: ("https://ethereum-rpc.publicnode.com",),
    10: ("https://optimism-rpc.publicnode.com",),
    56: ("https://bsc-dataseed.bnbchain.org", "https://bsc-rpc.publicnode.com"),
    8453: ("https://base-rpc.publicnode.com",),
    42161: ("https://arbitrum-one-rpc.publicnode.com",),
}
TRON_CHAIN_ID = 728126428
TRONSCAN_API = "https://apilist.tronscanapi.com/api"
def fetch_json(
    url: str,
    payload: dict[str, Any] | list[dict[str, Any]] | None = None,
    timeout: int = 25,
    headers: dict[str, str] | None = None,
    max_retries: int = 2,
    request_audit: dict[str, Any] | None = None,
) -> Any:
    request_headers = {"Content-Type": "application/json", "User-Agent": "ChainFundTracer/0.2"}
    request_headers.update(headers or {})
    request_data = json.dumps(payload).encode("utf-8") if payload else None

    last_exc: Exception | None = None
    audit = request_audit if request_audit is not None else {}
    audit.update({"attempts": 0, "retryable": False, "error_message": "", "errors": []})
    for attempt in range(max_retries + 1):
        audit["attempts"] = attempt + 1
        request = Request(url, data=request_data, headers=request_headers)
        try:
            with urlopen(request, timeout=timeout) as response:
                audit["error_message"] = ""
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            retryable = exc.code in (408, 429) or 500 <= exc.code < 600
            audit["retryable"] = retryable
            audit["errors"].append(f"第 {attempt + 1} 次：HTTP {exc.code}")
            if not retryable:
                try:
                    detail = json.loads(exc.read().decode("utf-8")).get("message", "")
                except Exception:
                    detail = ""
                hint = f"；{detail}" if detail else ""
                message = f"公開資料服務回應 HTTP {exc.code}{hint}"
                audit["error_message"] = message
                raise ProviderError(message, attempts=attempt + 1, retryable=False) from exc
            last_exc = exc
            audit["error_message"] = f"公開資料服務回應 HTTP {exc.code}"
            if attempt < max_retries:
                time.sleep(float(2 ** attempt))
                continue
            message = f"公開資料服務在 {attempt + 1} 次嘗試後仍回應 HTTP {exc.code}"
            audit["error_message"] = message
            raise ProviderError(message, attempts=attempt + 1, retryable=True) from exc
        except (URLError, TimeoutError, OSError) as exc:
            last_exc = exc
            audit["retryable"] = True
            audit["error_message"] = str(exc)
            audit["errors"].append(f"第 {attempt + 1} 次：{exc}")
            if attempt < max_retries:
                time.sleep(float(2 ** attempt))
                continue
            hint = "；目前端點拒絕未授權請求，請在「設定」更換 Polygon RPC URL。" if "401" in str(exc) else ""
            message = f"已重試 {attempt + 1} 次後仍無法取得公開鏈上資料：{exc}{hint}"
            audit["error_message"] = message
            raise ProviderError(message, attempts=attempt + 1, retryable=True) from exc
        except Exception as exc:
            hint = "；目前端點拒絕未授權請求，請在「設定」更換 Polygon RPC URL。" if "401" in str(exc) else ""
            message = f"無法取得公開鏈上資料：{exc}{hint}"
            audit["error_message"] = message
            audit["errors"].append(f"第 {attempt + 1} 次：{exc}")
            raise ProviderError(message, attempts=attempt + 1, retryable=False) from exc

    message = f"公開鏈上資料請求逾時或連線失敗：{last_exc}"
    audit["error_message"] = message
    raise ProviderError(message, attempts=max_retries + 1, retryable=True)
class PolygonProvider:
    _serializable = False
    def __init__(self, settings: Settings):
        self.settings, self._rpc_id = settings, 0
        self.token_history_truncated = False
        self.token_history_scanned_count = 0
        self.token_history_min_block: int | None = None
        self.token_history_max_block: int | None = None
        self.last_scanned_pages = 0
        self.targeted_track_audit: dict[str, dict[str, Any]] = {}
        self.last_request_attempts = 0
        self.last_request_retryable = False
        self.last_request_error_message = ""
        self.last_explorer_url = ""
        self.last_request_errors: list[str] = []
    def rpc(self, method: str, params: list[Any]) -> Any:
        self._rpc_id += 1
        payload = {"jsonrpc":"2.0","id":self._rpc_id,"method":method,"params":params}
        errors: list[str] = []
        urls = dict.fromkeys((self.settings.rpc_url, *POLYGON_RPC_FALLBACKS))
        for url in urls:
            try:
                result = fetch_json(url, payload)
                if isinstance(result, dict) and "error" in result:
                    raise ProviderError(result["error"].get("message", "RPC 回應錯誤"))
                if not isinstance(result, dict):
                    raise ProviderError(f"RPC 回應格式不符：{type(result).__name__}")
                return result.get("result")
            except ProviderError as exc:
                errors.append(f"{url}：{exc}")
        raise ProviderError("Polygon RPC皆無法回應；" + "｜".join(errors))
    def transaction(self, tx_hash: str): return self.rpc("eth_getTransactionByHash", [tx_hash])
    def receipt(self, tx_hash: str): return self.rpc("eth_getTransactionReceipt", [tx_hash])
    def chain_receipt(self, tx_hash: str, chain_id: int):
        """讀取目的 EVM 鏈原始 Receipt；僅用於核對既有 Relay 配對。"""
        if chain_id == 137:
            return self.receipt(tx_hash)
        urls = CHAIN_RPC_URLS.get(chain_id)
        if not urls:
            raise ProviderError(f"chainId {chain_id} 尚無可用的 Receipt RPC。")
        errors = []
        for url in urls:
            self._rpc_id += 1
            try:
                response = fetch_json(url, {
                    "jsonrpc": "2.0", "id": self._rpc_id,
                    "method": "eth_getTransactionReceipt", "params": [tx_hash],
                })
                if isinstance(response, dict) and response.get("error"):
                    raise ProviderError(response["error"].get("message", "目的鏈 RPC 回應錯誤"))
                if not isinstance(response, dict):
                    raise ProviderError("目的鏈 Receipt RPC 回應格式不符")
                return response.get("result")
            except ProviderError as exc:
                errors.append(f"{url}：{exc}")
        raise ProviderError("目的鏈 Receipt RPC 皆無法回應；" + "｜".join(errors))

    def _chain_rpc_batch(self, chain_id: int, calls: list[tuple[str, list[Any]]]) -> list[dict[str, Any]]:
        """在指定 EVM 鏈執行 JSON-RPC 批次查詢。"""
        urls = CHAIN_RPC_URLS.get(chain_id)
        if not urls:
            raise ProviderError(f"chainId {chain_id} 尚無可用的公開 RPC。")
        payload: list[dict[str, Any]] = []
        for method, params in calls:
            self._rpc_id += 1
            payload.append({"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params})
        errors: list[str] = []
        for url in urls:
            try:
                response = fetch_json(url, payload)
                if not isinstance(response, list):
                    raise ProviderError("RPC 未回傳批次結果。")
                if any(item.get("error") for item in response if isinstance(item, dict)):
                    message = next(
                        (item["error"].get("message", "RPC 回應錯誤") for item in response if item.get("error")),
                        "RPC 回應錯誤",
                    )
                    raise ProviderError(message)
                return response
            except ProviderError as exc:
                errors.append(f"{url}：{exc}")
        raise ProviderError("來源鏈 RPC 批次查詢失敗；" + "｜".join(errors))

    def chain_inbound_token_transfers_before(
        self,
        address: str,
        chain_id: int,
        contract: str,
        before_tx_hash: str,
        lookback_blocks: int = 300,
        batch_size: int = 50,
    ) -> list[dict[str, Any]]:
        """當 Explorer 漏索引時，由錨點交易向前掃描原始區塊 Receipt。"""
        anchor = self.chain_receipt(before_tx_hash, chain_id) or {}
        anchor_block = int(anchor.get("blockNumber", "0x0"), 16)
        if not anchor_block:
            return []
        recipient_topic = "0x" + "0" * 24 + address.lower().removeprefix("0x")
        contract = contract.lower()
        metadata = BNB_TOKEN_METADATA.get(contract, ("ERC-20", 18))
        lower_bound = max(0, anchor_block - lookback_blocks)
        cursor = anchor_block - 1
        while cursor >= lower_bound:
            blocks = list(range(cursor, max(lower_bound - 1, cursor - batch_size), -1))
            responses = self._chain_rpc_batch(chain_id, [("eth_getBlockReceipts", [hex(block)]) for block in blocks])
            found: list[dict[str, Any]] = []
            for response in responses:
                for receipt in response.get("result") or []:
                    for log in receipt.get("logs") or []:
                        topics = log.get("topics") or []
                        if (log.get("address", "").lower() != contract or len(topics) < 3
                                or topics[0].lower() != TRANSFER_TOPIC or topics[2].lower() != recipient_topic):
                            continue
                        found.append({
                            "token": {"address": contract, "symbol": metadata[0], "decimals": str(metadata[1])},
                            "from": {"hash": "0x" + topics[1][-40:]},
                            "to": {"hash": "0x" + topics[2][-40:]},
                            "total": {"value": str(int(log.get("data", "0x0"), 16))},
                            "timestamp": log.get("blockTimestamp", ""),
                            "transaction_hash": log.get("transactionHash", ""),
                            "block_number": log.get("blockNumber"),
                        })
            if found:
                return sorted(found, key=lambda item: int(item.get("block_number", "0x0"), 16), reverse=True)
            cursor = blocks[-1] - 1
        return []

    def chain_activity_transactions_before(
        self,
        address: str,
        chain_id: int,
        before_tx_hash: str,
        lookback_blocks: int = 1500,
        batch_size: int = 50,
    ) -> list[dict[str, Any]]:
        """由錨點交易向前尋找目標地址發起或收取的原始交易。"""
        anchor = self.chain_receipt(before_tx_hash, chain_id) or {}
        anchor_block = int(anchor.get("blockNumber", "0x0"), 16)
        if not anchor_block:
            return []
        address = address.lower()
        lower_bound = max(0, anchor_block - lookback_blocks)
        cursor = anchor_block - 1
        while cursor >= lower_bound:
            blocks = list(range(cursor, max(lower_bound - 1, cursor - batch_size), -1))
            responses = self._chain_rpc_batch(
                chain_id, [("eth_getBlockByNumber", [hex(block), True]) for block in blocks]
            )
            found: list[dict[str, Any]] = []
            for response in responses:
                block = response.get("result") or {}
                for tx in block.get("transactions") or []:
                    if str(tx.get("from") or "").lower() != address and str(tx.get("to") or "").lower() != address:
                        continue
                    found.append({
                        **tx,
                        "fromAddress": tx.get("from", ""),
                        "toAddress": tx.get("to", ""),
                        "timestamp": block.get("timestamp", ""),
                    })
            if found:
                return sorted(found, key=lambda item: int(item.get("blockNumber", "0x0"), 16), reverse=True)
            cursor = blocks[-1] - 1
        return []

    def chain_token_transfers_from_prior_activity(
        self,
        address: str,
        chain_id: int,
        contract: str,
        before_tx_hash: str,
    ) -> list[dict[str, Any]]:
        """尋找地址上一筆操作，並從 Receipt 取得實際收到的 Token。"""
        contract = contract.lower()
        metadata = BNB_TOKEN_METADATA.get(contract, ("ERC-20", 18))
        recipient_topic = "0x" + "0" * 24 + address.lower().removeprefix("0x")
        events: list[dict[str, Any]] = []
        for tx in self.chain_activity_transactions_before(address, chain_id, before_tx_hash):
            receipt = self.chain_receipt(tx.get("hash", ""), chain_id) or {}
            for log in receipt.get("logs") or []:
                topics = log.get("topics") or []
                if (log.get("address", "").lower() != contract or len(topics) < 3
                        or topics[0].lower() != TRANSFER_TOPIC or topics[2].lower() != recipient_topic):
                    continue
                events.append({
                    "token": {"address": contract, "symbol": metadata[0], "decimals": str(metadata[1])},
                    "from": {"hash": "0x" + topics[1][-40:]},
                    "to": {"hash": "0x" + topics[2][-40:]},
                    "total": {"value": str(int(log.get("data", "0x0"), 16))},
                    "timestamp": tx.get("timestamp", ""),
                    "transaction_hash": log.get("transactionHash", tx.get("hash", "")),
                    "block_number": log.get("blockNumber", tx.get("blockNumber")),
                })
        return events
    def block_info(self, block_number: str | int) -> dict[str, Any]:
        """取得指定區塊之高度、時間戳與雜湊；包含記憶體快取。"""
        blk_num = int(block_number, 16) if str(block_number).startswith("0x") else int(block_number)
        if not hasattr(self, "_block_info_cache"):
            self._block_info_cache: dict[int, dict[str, Any]] = {}
        if blk_num in self._block_info_cache:
            return self._block_info_cache[blk_num]

        ts_str = self.block_timestamp(hex(blk_num))
        ts = float(int(ts_str, 16) if str(ts_str).startswith("0x") else ts_str or 0.0)
        block = self.rpc("eth_getBlockByNumber", [hex(blk_num), False]) or {}
        info = {
            "number": blk_num,
            "timestamp": ts,
            "hash": block.get("hash", "") if isinstance(block, dict) else "",
        }
        self._block_info_cache[blk_num] = info
        return info

    def block_timestamp(self, block_number: str):
        block = self.rpc("eth_getBlockByNumber", [block_number, False])
        return block.get("timestamp", "") if block else ""

    def timestamp_to_block_number(self, target_timestamp: float) -> int:
        """
        將目標時間戳（UNIX timestamp，秒）轉換為對應之 Polygon 區塊高度。
        採用嚴格單調二分逼近演算法，保證回傳 block_timestamp <= target_timestamp 之最大區塊。
        """
        if not hasattr(self, "_timestamp_block_cache"):
            self._timestamp_block_cache: dict[int, tuple[int, float, str]] = {}

        target_int = int(target_timestamp)
        if target_int in self._timestamp_block_cache:
            return self._timestamp_block_cache[target_int][0]

        latest_hex = self.rpc("eth_blockNumber", [])
        if not latest_hex:
            raise ProviderError("無法透過 RPC 取得最新區塊高度。")
        latest_block = int(latest_hex, 16) if isinstance(latest_hex, str) and latest_hex.startswith("0x") else int(latest_hex)
        latest_info = self.block_info(latest_block)
        latest_time = latest_info.get("timestamp", target_timestamp)

        if target_timestamp >= latest_time:
            self._timestamp_block_cache[target_int] = (latest_block, latest_time, latest_info.get("hash", ""))
            return latest_block

        genesis_time = 1590858000.0  # Polygon 創世約 2020-05-30
        if target_timestamp <= genesis_time:
            self._timestamp_block_cache[target_int] = (1, genesis_time, "")
            return 1

        diff_seconds = latest_time - target_timestamp
        estimated_block = max(1, latest_block - int(diff_seconds / 2.15))
        window = max(200_000, int(diff_seconds * 0.20))

        low = max(1, estimated_block - window)
        high = min(latest_block, estimated_block + window)

        low_info = self.block_info(low)
        low_time = low_info.get("timestamp", 0.0)
        if low_time > target_timestamp:
            low = 1
            low_time = genesis_time

        high_info = self.block_info(high)
        high_time = high_info.get("timestamp", latest_time)
        if high_time < target_timestamp:
            high = latest_block
            high_time = latest_time

        best_block = low

        # 純二分搜尋會在有限區塊範圍內必然收斂；不以平均出塊時間推定終止位置。
        # 目標是找出滿足 block_timestamp <= target_timestamp 的最大區塊。
        while low <= high:
            mid = (low + high) // 2

            mid_info = self.block_info(mid)
            mid_time = mid_info.get("timestamp")
            if mid_time is None:
                raise ProviderError(f"無法取得 Polygon 區塊 {mid} 的時間戳。")

            if mid_time <= target_timestamp:
                best_block = mid
                low = mid + 1
                low_time = mid_time
            else:
                high = mid - 1
                high_time = mid_time

        final_info = self.block_info(best_block)
        self._timestamp_block_cache[target_int] = (
            best_block,
            final_info.get("timestamp", 0.0),
            final_info.get("hash", "")
        )
        return best_block

    def address_transactions(self, address: str) -> list[dict[str, Any]]:
        url = f"{self.settings.blockscout_url.rstrip('/')}/addresses/{address}/transactions?{urlencode({'items_count':self.settings.page_size})}"
        try: return fetch_json(url).get("items", [])
        except ProviderError:
            if not self.settings.etherscan_api_key: raise
            query = urlencode({"chainid":137,"module":"account","action":"txlist","address":address,"sort":"desc","page":1,"offset":self.settings.page_size,"apikey":self.settings.etherscan_api_key})
            data = fetch_json(f"https://api.etherscan.io/v2/api?{query}"); return data.get("result", []) if isinstance(data.get("result"), list) else []

    def _etherscan_token_transfers(
        self,
        address: str,
        token: str | None = None,
        start_block: int | None = None,
        end_block: int | None = None,
        page: int = 1,
        offset: int = 50,
    ) -> list[dict[str, Any]]:
        """透過 Etherscan v2 API (PolygonScan) 查詢 ERC-20 轉帳。"""
        if not getattr(self.settings, "etherscan_api_key", ""):
            return []
        query: dict[str, Any] = {
            "chainid": 137,
            "module": "account",
            "action": "tokentx",
            "address": address,
            "sort": "desc",
            "page": page,
            "offset": offset,
            "apikey": self.settings.etherscan_api_key,
        }
        if token:
            query["contractaddress"] = token
        if start_block is not None:
            query["startblock"] = start_block
        if end_block is not None:
            query["endblock"] = end_block

        url = f"https://api.etherscan.io/v2/api?{urlencode(query)}"
        data = fetch_json(url)
        items = data.get("result", []) if isinstance(data, dict) and isinstance(data.get("result"), list) else []
        normalized: list[dict[str, Any]] = []
        for it in items:
            ts_raw = it.get("timeStamp", "0")
            try:
                ts_iso = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc).isoformat()
            except (ValueError, TypeError):
                ts_iso = ""
            normalized.append({
                "token": {
                    "address": it.get("contractAddress", token or ""),
                    "symbol": it.get("tokenSymbol", ""),
                    "decimals": str(it.get("tokenDecimal", "6")),
                    "name": it.get("tokenName", ""),
                },
                "from": {"hash": it.get("from", "")},
                "to": {"hash": it.get("to", "")},
                "total": {"value": str(it.get("value", "0"))},
                "timestamp": ts_iso,
                "transaction_hash": it.get("hash", ""),
                "block_number": int(it.get("blockNumber", 0)) if str(it.get("blockNumber", "")).isdigit() else it.get("blockNumber"),
            })
        return normalized

    def address_token_transfers(
        self,
        address: str,
        start_block: int | None = None,
        end_block: int | None = None,
        token: str | None = None,
        filter_dir: str | None = None,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """讀取 Explorer 已索引的 ERC-20 轉帳；支援指定區塊高度範圍、代幣合約與方向（to/from）。
        具備三層防禦韌性架構：
        1. 主端點定向索引查詢
        2. Etherscan v2 API 自動備援
        3. 代幣索引逾時自動降級（去除特定 token 條件，以 address filter 查詢後於本地篩選）
        """
        limit_pages = max_pages if max_pages is not None else getattr(self.settings, "max_history_pages", 15)
        explorer_urls = [self.settings.blockscout_url, *getattr(self.settings, "explorer_fallback_urls", [])]
        explorer_urls = list(dict.fromkeys(url.rstrip("/") for url in explorer_urls if str(url).strip()))
        
        # 注意：Blockscout v2 之 block_number 係游標參數需搭配 index，初次查詢不傳遞 block_number
        params: dict[str, Any] = {"type": "ERC-20", "items_count": 50}
        if token:
            params["token"] = token
        if filter_dir:
            params["filter"] = filter_dir

        events: list[dict[str, Any]] = []
        self.token_history_truncated = False
        self.token_history_scanned_count = 0
        self.token_history_min_block: int | None = None
        self.token_history_max_block: int | None = None
        self.last_scanned_pages = 0
        self.last_request_attempts = 0
        self.last_request_retryable = False
        self.last_request_error_message = ""
        self.last_explorer_url = explorer_urls[0] if explorer_urls else ""
        self.last_request_errors = []

        seen_blocks: list[int] = []
        active_endpoint = 0
        downgraded_to_unfiltered = False

        for _ in range(limit_pages):
            self.last_scanned_pages += 1
            data: dict[str, Any] | None = None
            last_error: ProviderError | None = None
            
            for endpoint_index in range(active_endpoint, len(explorer_urls)):
                base = f"{explorer_urls[endpoint_index]}/addresses/{address}/token-transfers"
                request_audit: dict[str, Any] = {}
                try:
                    data = fetch_json(
                        f"{base}?{urlencode(params)}",
                        max_retries=2 if endpoint_index == 0 else 0,
                        request_audit=request_audit,
                    )
                    self.last_request_attempts += int(request_audit.get("attempts", 1))
                    self.last_request_errors.extend(str(item) for item in request_audit.get("errors", []))
                    self.last_request_retryable = bool(request_audit.get("retryable", False))
                    self.last_request_error_message = ""
                    self.last_explorer_url = explorer_urls[endpoint_index]
                    active_endpoint = endpoint_index
                    break
                except ProviderError as exc:
                    self.last_request_attempts += int(request_audit.get("attempts", exc.attempts))
                    self.last_request_errors.extend(str(item) for item in request_audit.get("errors", []))
                    self.last_request_retryable = exc.retryable
                    self.last_request_error_message = str(exc)
                    last_error = exc

            # 若特定 token 查詢失敗/逾時，依序觸發 Etherscan 與降級策略
            if data is None and token and not downgraded_to_unfiltered:
                # 嘗試 1：Etherscan v2 API 備援
                if getattr(self.settings, "etherscan_api_key", ""):
                    try:
                        eth_items = self._etherscan_token_transfers(
                            address=address, token=token, start_block=start_block, end_block=end_block,
                        )
                        if eth_items:
                            self.last_request_errors.append("主端點逾時，已透過 Etherscan v2 備援取得代幣轉帳。")
                            self.last_request_error_message = ""
                            data = {"items": eth_items}
                    except Exception as eth_exc:
                        self.last_request_errors.append(f"Etherscan 備援查詢失敗：{eth_exc}")

                # 嘗試 2：Blockscout 代幣專屬索引逾時，降級為不帶 token 的地址聚合轉帳查詢
                if data is None:
                    downgraded_to_unfiltered = True
                    params_fallback = {"type": "ERC-20", "items_count": 50}
                    if filter_dir:
                        params_fallback["filter"] = filter_dir
                    base = f"{explorer_urls[0]}/addresses/{address}/token-transfers"
                    request_audit = {}
                    try:
                        data = fetch_json(
                            f"{base}?{urlencode(params_fallback)}",
                            max_retries=1,
                            request_audit=request_audit,
                        )
                        self.last_request_errors.append("Blockscout 代幣索引逾時，已自動降級為地址轉入聚合掃描並於本地記憶體篩選。")
                        self.last_request_error_message = ""
                        # 將後續分頁切換為不帶 token 模式
                        params = params_fallback
                    except Exception as fb_exc:
                        last_error = ProviderError(f"降級聚合查詢亦失敗：{fb_exc}")

            if data is None:
                if last_error is None:
                    raise ProviderError("未設定可用的 Explorer 歷史索引端點", attempts=0, retryable=False)
                raise ProviderError(
                    self.last_request_error_message or str(last_error),
                    attempts=self.last_request_attempts,
                    retryable=self.last_request_retryable,
                ) from last_error

            items = data.get("items", [])
            self.token_history_scanned_count += len(items)
            for item in items:
                # 若處於降級模式，在本地篩選 token
                if downgraded_to_unfiltered and token:
                    item_tok = str(item.get("token", {}).get("address") or item.get("token_address") or "").lower()
                    if item_tok != token.lower():
                        continue

                blk_num = item.get("block_number")
                if blk_num is not None:
                    try:
                        blk_int = int(blk_num)
                        seen_blocks.append(blk_int)
                        if end_block is not None and blk_int > end_block:
                            continue
                        if start_block is not None and blk_int < start_block:
                            continue
                    except (ValueError, TypeError):
                        pass
                events.append(item)

            next_page = data.get("next_page_params")
            if not next_page:
                if seen_blocks:
                    self.token_history_min_block = min(seen_blocks)
                    self.token_history_max_block = max(seen_blocks)
                return events

            if start_block is not None and items:
                last_blk = items[-1].get("block_number")
                if last_blk is not None:
                    try:
                        if int(last_blk) < start_block:
                            if seen_blocks:
                                self.token_history_min_block = min(seen_blocks)
                                self.token_history_max_block = max(seen_blocks)
                            return events
                    except (ValueError, TypeError):
                        pass

            params = {"type": "ERC-20", **next_page}
            if not downgraded_to_unfiltered and token and "token" not in params:
                params["token"] = token
            if filter_dir and "filter" not in params:
                params["filter"] = filter_dir

        self.token_history_truncated = True
        if seen_blocks:
            self.token_history_min_block = min(seen_blocks)
            self.token_history_max_block = max(seen_blocks)
        return events

    def targeted_inbound_token_transfers(
        self,
        address: str,
        tokens: list[str] | None = None,
        start_block: int | None = None,
        end_block: int | None = None,
        max_pages_per_token: int = 5,
    ) -> list[dict[str, Any]]:
        """針對核心儲備代幣清單執行定向入金（filter=to）打撈，
        以避免大量合約撮合與無關空投代幣干擾查詢效率。
        代幣清冊由 Settings.core_inbound_tokens 管理，具可擴充性。
        """
        if tokens is None:
            tokens = getattr(self.settings, "core_inbound_tokens", [
                "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # Native USDC
                "0x2791bca1f2de4661ed88a30c99a7a9449aa84174",  # USDC.e
                "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb",  # pUSD
                "0xc2132d05d31c914a87c6611c10748aeb04b58e8f",  # USDT
            ])
        all_events: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()
        self.targeted_track_audit = {}

        for tok in tokens:
            tok_norm = tok.lower()
            sym = TOKEN_SYMBOLS.get(tok_norm, "ERC-20")
            try:
                tok_events = self.address_token_transfers(
                    address=address,
                    start_block=start_block,
                    end_block=end_block,
                    token=tok,
                    filter_dir="to",
                    max_pages=max_pages_per_token,
                )
                self.targeted_track_audit[tok_norm] = {
                    "token": tok,
                    "symbol": sym,
                    "status": "truncated" if self.token_history_truncated else ("success" if tok_events else "empty"),
                    "attempts": self.last_request_attempts,
                    "retryable": self.last_request_retryable,
                    "pages_scanned": self.last_scanned_pages,
                    "items_count": len(tok_events),
                    "min_block": self.token_history_min_block,
                    "max_block": self.token_history_max_block,
                    "is_truncated": self.token_history_truncated,
                    "error_message": "",
                    "explorer_url": self.last_explorer_url,
                    "errors": list(self.last_request_errors),
                }
                for ev in tok_events:
                    tx_h = str(ev.get("transaction_hash") or ev.get("tx_hash") or ev.get("hash") or "").lower()
                    log_i = str(ev.get("log_index") or ev.get("index") or "")
                    key = (tx_h, log_i)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        all_events.append(ev)
            except Exception as exc:
                attempts = int(getattr(exc, "attempts", getattr(self, "last_request_attempts", 0)))
                retryable = bool(getattr(exc, "retryable", getattr(self, "last_request_retryable", False)))
                self.targeted_track_audit[tok_norm] = {
                    "token": tok,
                    "symbol": sym,
                    "status": "error",
                    "attempts": attempts,
                    "retryable": retryable,
                    "pages_scanned": getattr(self, "last_scanned_pages", 0),
                    "items_count": 0,
                    "min_block": None,
                    "max_block": None,
                    "is_truncated": False,
                    "error_message": str(exc),
                    "explorer_url": getattr(self, "last_explorer_url", ""),
                    "errors": list(getattr(self, "last_request_errors", [])),
                }

        return all_events

    def inbound_token_logs(self, address: str, contracts: list[str], to_block: int, lookback_blocks: int = 50_000) -> list[dict[str, Any]]:
        """Explorer漏索引時，直接以RPC Logs反查近期ERC-20入帳。"""
        recipient_topic = "0x" + "0" * 24 + address.lower().removeprefix("0x")
        from_block = max(0, to_block - lookback_blocks)
        events: list[dict[str, Any]] = []
        timestamp_cache: dict[str, str] = {}
        for contract in contracts:
            logs = self.rpc("eth_getLogs", [{
                "address": contract,
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "topics": [TRANSFER_TOPIC, None, recipient_topic],
            }]) or []
            for log in logs:
                topics = log.get("topics", [])
                if len(topics) < 3: continue
                block_number = log.get("blockNumber", "0x0")
                if block_number not in timestamp_cache:
                    timestamp_cache[block_number] = self.block_timestamp(block_number)
                events.append({
                    "token": {"address": contract, "symbol": TOKEN_SYMBOLS.get(contract.lower(), "ERC-20"), "decimals": "6"},
                    "from": {"hash": "0x" + topics[1][-40:]},
                    "to": {"hash": "0x" + topics[2][-40:]},
                    "total": {"value": str(int(log.get("data", "0x0"), 16))},
                    "timestamp": timestamp_cache[block_number],
                    "transaction_hash": log.get("transactionHash", ""),
                })
        return sorted(events, key=lambda item: int(item.get("timestamp", "0x0"), 16), reverse=True)

    def relay_request_by_hash(self, tx_hash: str) -> dict[str, Any] | None:
        """以目的鏈或來源鏈 Tx Hash 查詢 Relay 對應請求。"""
        base = "https://api.relay.link"
        if self.settings.relay_api_key:
            try:
                data = fetch_json(
                    f"{base}/requests/v3?{urlencode({'term': tx_hash, 'limit': 5})}",
                    headers={"x-api-key": self.settings.relay_api_key},
                )
                requests = data.get("requests", [])
                selected = select_request(requests, tx_hash)
                if selected:
                    return {"version": 3, "request": selected}
                if requests:
                    raise ProviderError("Relay 回傳多筆或未精確命中的 Request，無法唯一配對。")
            except ProviderError:
                pass
        # v2 在 2026-11-24 前提供免金鑰相容；停用後會清楚回報，絕不猜測來源鏈。
        data = fetch_json(f"{base}/requests/v2?{urlencode({'hash': tx_hash})}")
        if not isinstance(data, dict):
            return None
        requests = data.get("requests", [])
        selected = select_request(requests, tx_hash)
        if requests and not selected:
            raise ProviderError("Relay 回傳多筆或未精確命中的 Request，無法唯一配對。")
        return {"version": 2, "request": selected, "deprecation": data.get("deprecation")} if selected else None

    def chain_token_transfers(self, address: str, chain_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """查詢來源鏈的 ERC-20／TRC-20 紀錄，統一轉成 Explorer 相容格式。"""
        if chain_id == TRON_CHAIN_ID:
            data = fetch_json(
                f"{TRONSCAN_API}/token_trc20/transfers?{urlencode({'limit':min(limit, 100),'start':0,'relatedAddress':address})}"
            )
            output: list[dict[str, Any]] = []

            def tag(item: dict[str, Any], field: str) -> str:
                value = item.get(field, "")
                if isinstance(value, dict):
                    return str(value.get(field, "") or value.get("tag", ""))
                return str(value or "")

            for item in data.get("token_transfers", []):
                token = item.get("tokenInfo") or {}
                decimals = int(item.get("decimals") or token.get("tokenDecimal") or 6)
                timestamp = item.get("block_ts", item.get("block_timestamp", ""))
                try:
                    timestamp = int(timestamp) // 1000 if int(timestamp) > 10_000_000_000 else int(timestamp)
                except (TypeError, ValueError):
                    pass
                output.append({
                    "token": {
                        "address": item.get("contract_address", token.get("tokenId", "")),
                        "symbol": item.get("symbol", token.get("tokenAbbr", "TRC-20")),
                        "decimals": str(decimals),
                    },
                    "from": {"hash": item.get("from_address", ""), "name": tag(item, "from_address_tag")},
                    "to": {"hash": item.get("to_address", ""), "name": tag(item, "to_address_tag")},
                    "total": {"value": str(item.get("quant", item.get("amount_str", "0")))},
                    "timestamp": timestamp,
                    "transaction_hash": item.get("transaction_id", ""),
                    "block_number": item.get("block", item.get("block_number")),
                })
            return output

        if chain_id == 56:
            data = fetch_json(
                "https://bnbscan.com/api/v1/query",
                {
                    "entity": "token_transfers",
                    "filter": {"address": address},
                    "limit": min(limit, 100),
                    "orderBy": "desc",
                },
            )
            if not isinstance(data, dict):
                return []
            output: list[dict[str, Any]] = []
            for item in data.get("data", []):
                contract = str(item.get("tokenAddress", "")).lower()
                symbol, decimals = BNB_TOKEN_METADATA.get(contract, ("ERC-20", 18))
                output.append({
                    "token": {"address": contract, "symbol": symbol, "decimals": str(decimals)},
                    "from": {"hash": item.get("fromAddress", "")},
                    "to": {"hash": item.get("toAddress", "")},
                    "total": {"value": str(item.get("value", "0"))},
                    "timestamp": item.get("timestamp", ""),
                    "transaction_hash": item.get("txHash", ""),
                    "block_number": item.get("blockNumber"),
                })
            return output

        blockscout_urls = {
            1: "https://eth.blockscout.com/api/v2",
            10: "https://optimism.blockscout.com/api/v2",
            137: self.settings.blockscout_url.rstrip("/"),
            8453: "https://base.blockscout.com/api/v2",
            42161: "https://arbitrum.blockscout.com/api/v2",
        }
        if chain_id in blockscout_urls:
            url = f"{blockscout_urls[chain_id]}/addresses/{address}/token-transfers?{urlencode({'type':'ERC-20','items_count':min(limit, 50)})}"
            return fetch_json(url).get("items", [])

        if self.settings.etherscan_api_key:
            query = urlencode({
                "chainid": chain_id,
                "module": "account",
                "action": "tokentx",
                "address": address,
                "sort": "desc",
                "page": 1,
                "offset": min(limit, 100),
                "apikey": self.settings.etherscan_api_key,
            })
            data = fetch_json(f"https://api.etherscan.io/v2/api?{query}")
            if isinstance(data.get("result"), list):
                return data["result"]
            raise ProviderError(f"Etherscan未回傳chainId {chain_id}的Token紀錄：{data.get('message', '未知錯誤')}")

        raise ProviderError(
            f"來源鏈 chainId {chain_id} 沒有可用的免金鑰 Explorer；請在設定填入 Etherscan V2 API Key 後繼續追蹤。"
        )

    def chain_transactions(self, address: str, chain_id: int, limit: int = 100) -> list[dict[str, Any]]:
        """查詢來源鏈原生幣交易；目前 BNB Chain 可免金鑰使用。"""
        if chain_id == 56:
            data = fetch_json(
                "https://bnbscan.com/api/v1/query",
                {
                    "entity": "transactions",
                    "filter": {"address": address},
                    "limit": min(limit, 100),
                    "orderBy": "desc",
                },
            )
            return data.get("data", []) if isinstance(data, dict) else []
        return []

    def transaction_details(self, tx_hash: str) -> dict[str, Any] | None:
        """取得 Explorer 交易詳情（含 Open Labels Initiative metadata.tags）。"""
        if not tx_hash:
            return None
        url = f"{self.settings.blockscout_url.rstrip('/')}/transactions/{tx_hash}"
        try:
            return fetch_json(url)
        except ProviderError:
            return None

    def polygon_token_transfers_before(
        self,
        address: str,
        before_block: int | None = None,
        max_pages: int = 12,
        stop_condition: Any = None,
    ) -> list[dict[str, Any]]:
        """讀取 Polygon Explorer 的 ERC-20 轉帳；支援受限分頁（最多 max_pages 頁）並支援提前停止條件。"""
        base = f"{self.settings.blockscout_url.rstrip('/')}/addresses/{address}/token-transfers"
        params: dict[str, Any] = {"type": "ERC-20", "items_count": 50}
        if before_block is not None:
            params["block_number"] = before_block

        events: list[dict[str, Any]] = []
        for _ in range(max_pages):
            try:
                data = fetch_json(f"{base}?{urlencode(params)}")
            except ProviderError:
                break
            items = data.get("items", [])
            stopped = False
            for item in items:
                blk_num = item.get("block_number")
                if blk_num is not None and before_block is not None:
                    try:
                        if int(blk_num) > before_block:
                            continue
                    except (ValueError, TypeError):
                        pass
                events.append(item)
                if stop_condition and stop_condition(item):
                    stopped = True
                    break
            if stopped:
                break

            next_page = data.get("next_page_params")
            if not next_page:
                break
            params = {"type": "ERC-20", **next_page}

        return events

    def address_native_transfers_before(
        self,
        address: str,
        before_block: int | None = None,
        max_items: int = 50,
    ) -> list[dict[str, Any]]:
        """讀取目標地址接收原生代幣（如 POL）之交易紀錄（filter=to）。"""
        base = f"{self.settings.blockscout_url.rstrip('/')}/addresses/{address}/transactions"
        params: dict[str, Any] = {"filter": "to", "items_count": min(max_items, 50)}
        if before_block is not None:
            params["block_number"] = before_block
        try:
            data = fetch_json(f"{base}?{urlencode(params)}")
        except ProviderError:
            return []
        items = data.get("items", [])
        output: list[dict[str, Any]] = []
        for item in items:
            blk_num = item.get("block_number")
            if blk_num is not None and before_block is not None:
                try:
                    if int(blk_num) > before_block:
                        continue
                except (ValueError, TypeError):
                    pass
            val_wei = item.get("value", "0")
            try:
                val_pol = f"{int(str(val_wei)) / 10**18:.4f}"
            except (ValueError, TypeError):
                val_pol = str(val_wei)
            output.append({
                "hash": item.get("hash", ""),
                "from": item.get("from", {}),
                "to": item.get("to", {}),
                "value": val_pol,
                "raw_value": str(val_wei),
                "timestamp": item.get("timestamp", ""),
                "block_number": item.get("block_number"),
            })
        return output
