import json
import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from chain_fund_tracer.analysis import Analyzer
from chain_fund_tracer.config import Settings
from chain_fund_tracer.exporters import export_csv, export_text
from chain_fund_tracer.models import AnalysisResult, TraceStep
from chain_fund_tracer.providers import PolygonProvider, ProviderError, fetch_json


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class QueryRetryTests(unittest.TestCase):
    def test_timeout_then_retry_success(self):
        audit = {}
        with patch("chain_fund_tracer.providers.urlopen", side_effect=[TimeoutError("逾時"), _Response({"ok": True})]), patch(
            "chain_fund_tracer.providers.time.sleep"
        ) as sleeper:
            data = fetch_json("https://example.invalid", request_audit=audit)
        self.assertEqual(data, {"ok": True})
        self.assertEqual(audit["attempts"], 2)
        self.assertTrue(audit["retryable"])
        sleeper.assert_called_once_with(1.0)

    def test_three_timeouts_are_auditable_error(self):
        audit = {}
        with patch("chain_fund_tracer.providers.urlopen", side_effect=TimeoutError("The read operation timed out")), patch(
            "chain_fund_tracer.providers.time.sleep"
        ) as sleeper:
            with self.assertRaises(ProviderError) as caught:
                fetch_json("https://example.invalid", request_audit=audit)
        self.assertEqual(caught.exception.attempts, 3)
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(audit["attempts"], 3)
        self.assertEqual(len(audit["errors"]), 3)
        self.assertIn("已重試 3 次", str(caught.exception))
        self.assertEqual([call.args[0] for call in sleeper.call_args_list], [1.0, 2.0])

    def test_explorer_fallback_is_attempted_once(self):
        settings = Settings(explorer_fallback_urls=["https://backup.example/api/v2"])
        provider = PolygonProvider(settings)
        with patch(
            "chain_fund_tracer.providers.fetch_json",
            side_effect=[ProviderError("主端點逾時", attempts=3, retryable=True), {"items": [], "next_page_params": None}],
        ) as fetch:
            events = provider.address_token_transfers("0x" + "a" * 40)
        self.assertEqual(events, [])
        self.assertIn("backup.example", fetch.call_args_list[1].args[0])
        self.assertEqual(fetch.call_args_list[1].kwargs["max_retries"], 0)


class QueryTrackStateTests(unittest.TestCase):
    TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"

    def test_zero_items_is_empty_not_error(self):
        provider = PolygonProvider(Settings(core_inbound_tokens=[self.TOKEN]))
        with patch.object(provider, "address_token_transfers", return_value=[]):
            provider.targeted_inbound_token_transfers("0x" + "a" * 40)
        track = provider.targeted_track_audit[self.TOKEN]
        self.assertEqual(track["status"], "empty")
        self.assertFalse(track["is_truncated"])

    def test_page_limit_is_truncated(self):
        provider = PolygonProvider(Settings(core_inbound_tokens=[self.TOKEN]))

        def truncated(*_args, **_kwargs):
            provider.token_history_truncated = True
            provider.last_scanned_pages = 5
            provider.last_request_attempts = 5
            return [{"transaction_hash": "0x1", "log_index": "0"}]

        with patch.object(provider, "address_token_transfers", side_effect=truncated):
            provider.targeted_inbound_token_transfers("0x" + "a" * 40)
        track = provider.targeted_track_audit[self.TOKEN]
        self.assertEqual(track["status"], "truncated")
        self.assertTrue(track["is_truncated"])
        self.assertEqual(track["pages_scanned"], 5)


class EvidenceCompletenessTests(unittest.TestCase):
    def _step(self):
        return TraceStep(
            "地址入金", 1, "0x" + "1" * 64, "2026-01-01 00:00:00 +0800", "USDC", "100",
            "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "a" * 40,
            "交易所", "Binance Hot Wallet", "Explorer", "高度可能", "僅資金關聯",
            path_category="交易所直提", line_style="solid", event_role="補款", pair_verified=True,
        )

    def test_error_or_truncation_makes_result_partial_and_downgrades_wording(self):
        provider = PolygonProvider(Settings())
        provider.targeted_track_audit = {
            "usdc": {"symbol": "USDC", "status": "success", "is_truncated": False},
            "usdce": {"symbol": "USDC.e", "status": "error", "is_truncated": False, "attempts": 3, "error_message": "逾時"},
            "pusd": {"symbol": "pUSD", "status": "truncated", "is_truncated": True, "pages_scanned": 5, "items_count": 250},
        }
        result = AnalysisResult(query="0x" + "b" * 40, summary=["逐筆本金主線命中"], steps=[self._step()])
        finalized = Analyzer(provider).finalize_analysis_result(result)
        self.assertEqual(finalized.analysis_status, "partial")
        self.assertEqual(finalized.incomplete_tracks, ["USDC.e", "pUSD"])
        self.assertNotIn("逐筆本金主線", " ".join(finalized.summary))
        self.assertEqual(finalized.subpoena_candidates[0].association_level, "待驗證資金關聯")

    def test_all_complete_tracks_allow_verified_principal_wording(self):
        provider = PolygonProvider(Settings())
        provider.targeted_track_audit = {
            "usdc": {"symbol": "USDC", "status": "success", "is_truncated": False},
            "usdce": {"symbol": "USDC.e", "status": "empty", "is_truncated": False},
        }
        result = AnalysisResult(query="0x" + "b" * 40, summary=["逐筆本金主線命中"], steps=[self._step()])
        finalized = Analyzer(provider).finalize_analysis_result(result)
        self.assertEqual(finalized.analysis_status, "complete")
        self.assertIn("逐筆本金主線", " ".join(finalized.summary))
        self.assertEqual(finalized.subpoena_candidates[0].association_level, "逐筆本金")

    def test_all_error_tracks_make_result_failed(self):
        provider = PolygonProvider(Settings())
        provider.targeted_track_audit = {
            "usdc": {"symbol": "USDC", "status": "error", "is_truncated": False, "attempts": 3, "error_message": "逾時"},
            "usdce": {"symbol": "USDC.e", "status": "error", "is_truncated": False, "attempts": 3, "error_message": "逾時"},
        }
        finalized = Analyzer(provider).finalize_analysis_result(AnalysisResult(query="0x" + "b" * 40))
        self.assertEqual(finalized.analysis_status, "failed")
        self.assertEqual(finalized.incomplete_tracks, ["USDC", "USDC.e"])

    def test_html_layer_handles_partial_without_claiming_completion(self):
        app_js = Path("chain_fund_tracer/ui/app.js").read_text(encoding="utf-8")
        graph_js = Path("chain_fund_tracer/ui/graph.js").read_text(encoding="utf-8")
        self.assertIn("updateStatus('分析部分完成'", app_js)
        self.assertIn("⚠️ 暫定資金事件", app_js)
        self.assertIn("t.status === 'empty'", app_js)
        self.assertIn("this.filter = 'verified'", graph_js)
        self.assertIn("step.pair_verified === true", graph_js)

    def test_partial_status_is_preserved_in_text_csv_and_snapshot(self):
        result = AnalysisResult(
            query="0x" + "b" * 40,
            steps=[self._step()],
            analysis_status="partial",
            incomplete_tracks=["USDC.e", "pUSD"],
        )
        with tempfile.TemporaryDirectory() as folder:
            text_path = Path(folder) / "analysis.txt"
            csv_path = Path(folder) / "steps.csv"
            export_text(result, str(text_path))
            export_csv(result, str(csv_path))
            self.assertIn("分析狀態：部分完成", text_path.read_text(encoding="utf-8"))
            with csv_path.open("r", encoding="utf-8-sig", newline="") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row["analysis_status"], "partial")
            self.assertEqual(row["incomplete_tracks"], "USDC.e、pUSD")
        snapshot = result.to_dict()
        self.assertEqual(snapshot["analysis_status"], "partial")
        self.assertEqual(snapshot["incomplete_tracks"], ["USDC.e", "pUSD"])


    def test_maker_rebates_and_fee_recipient_flagged_as_internal(self):
        analyzer = Analyzer(PolygonProvider(Settings()))
        target = "0x" + "a" * 40
        events = [
            {
                "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "decimals": "6"},
                "from": {"hash": "0xfdb1b8dc7f5789a0c9a398026585b8b10fba5507"}, # Maker Rebates
                "to": {"hash": target},
                "total": {"value": "19840600"},
                "timestamp": "2026-09-30T08:45:05Z",
                "transaction_hash": "0x" + "1" * 64,
            },
            {
                "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "decimals": "6"},
                "from": {"hash": "0x115f48dc2a731aa16251c6d6e1befc42f92accc9"}, # Fee Recipient
                "to": {"hash": target},
                "total": {"value": "5000000"},
                "timestamp": "2026-09-30T08:00:00Z",
                "transaction_hash": "0x" + "2" * 64,
            }
        ]
        candidates = analyzer._funding_candidates(events, target, 0)
        self.assertEqual(len(candidates), 2)
        self.assertIn("平台內部／Polymarket 造市回饋金批次撥付", candidates[0]["note"])
        self.assertIn("平台內部／Polymarket 造市回饋金批次撥付", candidates[1]["note"])

    def test_token_timeout_falls_back_to_unfiltered_inbound_query(self):
        provider = PolygonProvider(Settings())
        address = "0x" + "a" * 40
        token_usdc_e = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
        
        # 第一次帶 token 拋出逾時異常；降級查詢不帶 token 成功回傳多種代幣
        side_effects = [
            ProviderError("已重試 3 次後仍無法取得公開鏈上資料：The read operation timed out", attempts=3, retryable=True),
            {
                "items": [
                    {
                        "token": {"address": "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb", "symbol": "pUSD"},
                        "from": {"hash": "0x1"}, "to": {"hash": address}, "total": {"value": "1000"},
                        "block_number": 9000,
                    },
                    {
                        "token": {"address": token_usdc_e, "symbol": "USDC.e"},
                        "from": {"hash": "0x2"}, "to": {"hash": address}, "total": {"value": "2000"},
                        "block_number": 8990,
                    },
                ],
                "next_page_params": None,
            }
        ]
        with patch("chain_fund_tracer.providers.fetch_json", side_effect=side_effects) as fetch:
            events = provider.address_token_transfers(address, token=token_usdc_e, filter_dir="to")
        
        # 本地記憶體精準過濾出 USDC.e
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["token"]["address"], token_usdc_e)
        self.assertTrue(any("自動降級" in err for err in provider.last_request_errors))

    def test_initial_query_does_not_send_bare_block_number_cursor(self):
        provider = PolygonProvider(Settings())
        address = "0x" + "a" * 40
        with patch("chain_fund_tracer.providers.fetch_json", return_value={"items": [], "next_page_params": None}) as mock_fetch:
            provider.address_token_transfers(address, end_block=94600000, filter_dir="to")
            called_url = mock_fetch.call_args[0][0]
            self.assertNotIn("block_number=", called_url)

    def test_subpoena_candidates_relay_eoa_and_dex_classifications(self):
        from chain_fund_tracer.analysis import build_subpoena_candidates
        from chain_fund_tracer.models import AnalysisResult, TraceStep

        s_relay = TraceStep(
            "Relay 跨鏈入金", 2, "0xrelay_tx", "2026-09-28 10:00:00", "USDC", "1000",
            "0xsolver", "0xtarget", "0xsolver", "Bridge", "Relay Solver", "Relay", "已確認", "跨鏈",
            path_category="跨鏈橋／Relay", line_style="solid", pair_verified=True, relay_request_id="0xreq123",
        )
        s_eoa = TraceStep(
            "個人錢包轉帳", 1, "0xeoa_tx", "2026-09-28 09:00:00", "USDC", "500",
            "0xeoa_sender", "0xtarget", "0xeoa_sender", "非託管個人錢包", "", "無公開標籤", "未知", "轉帳",
            path_category="外部錢包轉入", line_style="solid", pair_verified=False,
        )
        s_dex = TraceStep(
            "DEX 兌換", 1, "0xdex_tx", "2026-09-28 08:00:00", "pUSD", "300",
            "0xdex_router", "0xtarget", "0xdex_router", "DEX", "Uniswap V3 Router", "公開標籤", "高度可能", "兌換",
            path_category="DEX 兌換", line_style="solid", pair_verified=False,
        )
        res = AnalysisResult(query="0xtarget", steps=[s_relay, s_eoa, s_dex])
        candidates = build_subpoena_candidates(res)

        by_prov = {c.service_provider: c for c in candidates}
        self.assertIn("Relay Protocol (Relay.link)", by_prov)
        self.assertEqual(by_prov["Relay Protocol (Relay.link)"].inquiry_value, "可函調跨鏈發起IP與路由紀錄")
        self.assertIn("Relay Request ID", by_prov["Relay Protocol (Relay.link)"].limitations)

        self.assertIn("非託管個人錢包 (EOA)", by_prov)
        self.assertEqual(by_prov["非託管個人錢包 (EOA)"].inquiry_value, "無中心化開戶資料（不可直接函調）")
        self.assertIn("開戶手續費（Gas）", by_prov["非託管個人錢包 (EOA)"].limitations)

        self.assertIn("Uniswap V3 Router", by_prov)
        self.assertEqual(by_prov["Uniswap V3 Router"].service_type, "DEX 兌換")
        self.assertEqual(by_prov["Uniswap V3 Router"].inquiry_value, "不可作 KYC 終點")
        self.assertIn("去中心化撮合合約", by_prov["Uniswap V3 Router"].limitations)


if __name__ == "__main__":
    unittest.main()
