import json
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.config import Settings
from chain_fund_tracer.exporters import export_agent_bundle
from chain_fund_tracer.models import (
    AnalysisResult,
    DataAvailability,
    FlowEvent,
    SubpoenaCandidate,
    TraceStep,
    Transfer,
)
from chain_fund_tracer.providers import (
    PolygonProvider,
    ProviderError,
    raw_internal_to_flow_event,
    raw_transfer_to_flow_event,
    raw_tx_to_flow_event,
)


class FakeCollectorProvider(PolygonProvider):
    def __init__(self):
        super().__init__(Settings())

    def transaction(self, tx_hash: str):
        if tx_hash == "0x" + "1" * 64:
            return {
                "hash": tx_hash,
                "from": "0x" + "a" * 40,
                "to": "0x" + "b" * 40,
                "value": "0xde0b6b3a7640000",  # 1 ETH/POL
                "blockNumber": "0x100",
            }
        return None

    def receipt(self, tx_hash: str):
        if tx_hash == "0x" + "1" * 64:
            return {
                "status": "0x1",
                "logs": [{
                    "address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",  # USDC
                    "topics": [
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                        "0x" + "0" * 24 + "a" * 40,
                        "0x" + "0" * 24 + "b" * 40,
                    ],
                    "data": hex(100_000_000),  # 100 USDC
                    "logIndex": "0x1",
                }],
            }
        return None

    def block_timestamp(self, block_number: str):
        return "0x66000000"


class AgentBundleAndCollectorTests(unittest.TestCase):
    def test_flow_event_adapters(self):
        raw_tx = {
            "hash": "0x" + "1" * 64,
            "from": "0x" + "a" * 40,
            "to": "0x" + "b" * 40,
            "value": "1000000000000000000",
            "blockNumber": "12345",
            "timestamp": "2026-09-30T12:00:00Z",
        }
        fe_tx = raw_tx_to_flow_event(raw_tx, chain_id=137, source_provider="TestRPC")
        self.assertEqual(fe_tx.event_type, "transaction")
        self.assertEqual(fe_tx.amount, "1.000000")
        self.assertEqual(fe_tx.chain_id, 137)
        self.assertEqual(fe_tx.from_address, "0x" + "a" * 40)

        raw_tr = {
            "transaction_hash": "0x" + "2" * 64,
            "from": {"hash": "0x" + "a" * 40},
            "to": {"hash": "0x" + "b" * 40},
            "token": {"address": "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359", "symbol": "USDC", "decimals": "6"},
            "total": {"value": "50000000"},
            "block_number": 12346,
            "timestamp": "2026-09-30T12:05:00Z",
        }
        fe_tr = raw_transfer_to_flow_event(raw_tr, chain_id=137)
        self.assertEqual(fe_tr.event_type, "token_transfer")
        self.assertEqual(fe_tr.amount, "50.000000")
        self.assertEqual(fe_tr.token_symbol, "USDC")

    def test_data_availability_differentiates_error_from_empty(self):
        # 1. 成功且確實無資料 (available=True, records=0)
        empty_avail = DataAvailability(
            query_type="transactions",
            available=True,
            status="NoResults",
            record_count=0,
            provider="Blockscout",
        )
        self.assertTrue(empty_avail.available)
        self.assertEqual(empty_avail.status, "NoResults")
        self.assertEqual(empty_avail.record_count, 0)

        # 2. 查詢失敗 (available=False, status=RateLimited)
        rate_limited_avail = DataAvailability(
            query_type="transactions",
            available=False,
            status="RateLimited",
            record_count=0,
            provider="Blockscout",
            error_message="HTTP 429 Too Many Requests",
        )
        self.assertFalse(rate_limited_avail.available)
        self.assertEqual(rate_limited_avail.status, "RateLimited")
        self.assertIn("429", rate_limited_avail.error_message)

    def test_export_agent_bundle_full_package(self):
        target = "0x" + "a" * 40
        result = AnalysisResult(query=target, network="Polygon")
        result.analysis_status = "complete"

        # 加入主鏈交易
        result.transactions.append({
            "hash": "0x" + "1" * 64,
            "from": target,
            "to": "0x" + "b" * 40,
            "value": "0.5 MATIC",
        })
        result.availabilities["transactions"] = DataAvailability(
            query_type="transactions", available=True, status="Success", record_count=1, provider="Blockscout"
        )

        # 加入代幣轉帳
        result.transfers.append(Transfer(
            tx_hash="0x" + "2" * 64,
            timestamp="2026-09-30 12:00:00 +0800",
            token="USDC",
            amount="100.000000",
            from_address="0x" + "c" * 40,
            to_address=target,
            token_type="ERC-20",
            token_contract="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        ))
        result.availabilities["token_transfers"] = DataAvailability(
            query_type="token_transfers", available=True, status="Success", record_count=1, provider="Blockscout"
        )

        # 標記 internal_transactions 為未支援 (available=False)
        result.availabilities["internal_transactions"] = DataAvailability(
            query_type="internal_transactions",
            available=False,
            status="UnsupportedProvider",
            record_count=0,
            error_message="公共端點未提供內部交易索引",
        )

        # 加入標籤與候選
        result.steps.append(TraceStep(
            direction="地址入金",
            hop=1,
            tx_hash="0x" + "2" * 64,
            timestamp="2026-09-30 12:00:00 +0800",
            token="USDC",
            amount="100.000000",
            from_address="0x" + "c" * 40,
            to_address=target,
            address="0x" + "c" * 40,
            classification="交易所",
            label="Binance: Hot Wallet",
            label_source="公開標籤",
            confidence="已確認",
            relation="僅資金關聯",
            token_contract="0x3c499c542cef5e3811e1192ce70d8cc03d5c3359",
        ))
        result.subpoena_candidates.append(SubpoenaCandidate(
            service_provider="Binance",
            service_type="中心化交易所",
            association_level="直接入金",
            chain="Polygon",
            from_address="0x" + "c" * 40,
            to_address=target,
            tx_hash="0x" + "2" * 64,
            datetime_tw="2026-09-30 12:00:00",
            asset="USDC",
            amount="100.000000",
            label_basis="公開標籤",
            inquiry_value="帳戶身分調證",
            limitations="需搭配帳號 UID",
        ))
        result.add_diagnostic_log("測試診斷訊息：完成初始化檢索")

        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = Path(tmp_dir) / "test_bundle.zip"
            export_agent_bundle(result, str(zip_path))
            self.assertTrue(zip_path.is_file())

            # 解壓縮並驗證 10 個核心檔案全部齊備
            extract_dir = Path(tmp_dir) / "extracted"
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(extract_dir)

            expected_files = [
                "README.txt",
                "PROMPT.txt",
                "summary.json",
                "transactions.json",
                "token_transfers.json",
                "internal_transactions.json",
                "traces_and_logs.json",
                "labels.json",
                "contracts.json",
                "diagnostic.log",
            ]
            for ef in expected_files:
                self.assertTrue((extract_dir / ef).is_file(), f"缺少必要分析包檔案：{ef}")

            # 驗證 summary.json 內容與真實狀態區分
            summary_json = json.loads((extract_dir / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary_json["target_address"], target)
            self.assertTrue(summary_json["data_availability"]["transactions"]["available"])
            self.assertFalse(summary_json["data_availability"]["internal_transactions"]["available"])
            self.assertEqual(
                summary_json["data_availability"]["internal_transactions"]["status"], "UnsupportedProvider"
            )

            # 驗證 PROMPT.txt 關鍵字
            prompt_text = (extract_dir / "PROMPT.txt").read_text(encoding="utf-8")
            self.assertIn("請分析附件中的鏈上法證資料包", prompt_text)
            self.assertIn("辨識附件中已有鏈上證據或公開標籤支持的交易所／服務商", prompt_text)
            self.assertIn("diagnostic.log", prompt_text)

    def test_diagnose_tx_pipeline(self):
        provider = FakeCollectorProvider()
        analyzer = Analyzer(provider)

        # 1. 存在且能完整解析的交易
        diag_ok = analyzer.diagnose_tx("0x" + "1" * 64)
        self.assertEqual(diag_ok["provider_raw"], "FOUND")
        self.assertEqual(diag_ok["parser"], "PASS")
        self.assertEqual(diag_ok["normalized"], "PASS")
        self.assertEqual(diag_ok["filter"], "PASS")

        # 2. 不存在的交易
        diag_missing = analyzer.diagnose_tx("0x" + "9" * 64)
        self.assertEqual(diag_missing["provider_raw"], "NOT FOUND")


class CollectorIntegrityTests(unittest.TestCase):
    def test_internal_pagination_limit_and_partial_failure(self):
        provider = PolygonProvider(Settings())
        page = {"items": [{"hash": "one"}], "next_page_params": {"index": 1}}
        with patch("chain_fund_tracer.providers.fetch_json", return_value=page):
            records, status = provider.query_internal_transactions_with_status("0x" + "a" * 40, 1)
        self.assertEqual(status.status, "IncompletePagination")
        self.assertFalse(status.is_complete)
        with patch("chain_fund_tracer.providers.fetch_json", side_effect=[page, ProviderError("逾時", error_type="Timeout")]):
            records, status = provider.query_internal_transactions_with_status("0x" + "a" * 40, 2)
        self.assertEqual(len(records), 1)
        self.assertEqual(status.record_count, 1)
        self.assertEqual(status.status, "Timeout")
        self.assertFalse(status.available)

    def test_malformed_response_is_not_empty(self):
        provider = PolygonProvider(Settings())
        for method in (provider.query_transactions_with_status, provider.query_internal_transactions_with_status):
            for malformed in ({"message": "error"}, None, {"items": [None]}):
                with self.subTest(method=method.__name__, response=malformed):
                    with patch("chain_fund_tracer.providers.fetch_json", return_value=malformed):
                        records, status = method("0x" + "a" * 40)
                    self.assertEqual(status.status, "ParseError")
                    self.assertFalse(status.available)

    def test_etherscan_error_and_pagination(self):
        provider = PolygonProvider(Settings(etherscan_api_key="test-only-placeholder", page_size=1))
        for method in (provider.query_transactions_with_status, provider.query_internal_transactions_with_status):
            with patch("chain_fund_tracer.providers.fetch_json", side_effect=[ProviderError("不可用"), {"status": "0", "message": "NOTOK", "result": "Max rate limit reached"}]):
                _, status = method("0x" + "a" * 40)
            self.assertEqual(status.status, "RateLimited")
            self.assertFalse(status.available)
            with patch("chain_fund_tracer.providers.fetch_json", side_effect=[ProviderError("不可用"), {"status": "1", "result": [{"hash": "one"}]}]):
                _, status = method("0x" + "a" * 40, 1)
            self.assertEqual(status.status, "IncompletePagination")
            self.assertFalse(status.is_complete)
            with patch("chain_fund_tracer.providers.fetch_json", side_effect=[ProviderError("不可用"), {"status": "0", "message": "No transactions found", "result": []}]):
                _, status = method("0x" + "a" * 40)
            self.assertEqual(status.status, "NoResults")
            self.assertTrue(status.available)

    def test_bundle_exports_collected_transfers_and_unknown_sources(self):
        result = AnalysisResult(query="0x" + "a" * 40)
        result.flow_events.append(raw_transfer_to_flow_event({
            "transaction_hash": "0x" + "1" * 64,
            "from": {"hash": "0x" + "b" * 40}, "to": {"hash": result.query},
            "token": {"address": "0x" + "c" * 40, "decimals": "6", "symbol": "USDC"},
            "total": {"value": "1000000"},
        }))
        result.availabilities["token_transfers"] = DataAvailability("token_transfers", True, "Success", 1)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bundle.zip"
            export_agent_bundle(result, str(path))
            with zipfile.ZipFile(path) as archive:
                summary = json.loads(archive.read("summary.json"))
                transfers = json.loads(archive.read("token_transfers.json"))
        self.assertEqual(len(transfers["records"]), 1)
        self.assertEqual(summary["counts"]["token_transfers_count"], 1)
        self.assertEqual(transfers["records"][0]["amount"], "1.000000")
        self.assertEqual(summary["data_availability"]["contract_logs"]["status"], "UnsupportedProvider")

    def test_collector_incompleteness_downgrades_summary(self):
        result = AnalysisResult(query="0x" + "a" * 40)
        result.availabilities["transactions"] = DataAvailability("transactions", True, "IncompletePagination", is_complete=False)
        Analyzer(FakeCollectorProvider()).finalize_analysis_result(result)
        self.assertEqual(result.analysis_status, "partial")
        self.assertIn("transactions", result.incomplete_tracks)


class HttpErrorTests(unittest.TestCase):
    def test_nonretryable_http_error_retains_status(self):
        import io
        from urllib.error import HTTPError
        from chain_fund_tracer.providers import fetch_json
        error = HTTPError("https://example.invalid", 400, "Bad Request", {}, io.BytesIO(b'{"message":"invalid request"}'))
        with patch("chain_fund_tracer.providers.urlopen", side_effect=error):
            with self.assertRaises(ProviderError) as raised:
                fetch_json("https://example.invalid")
        self.assertEqual(raised.exception.error_type, "ProviderUnavailable")
        self.assertIn("HTTP 400", str(raised.exception))
