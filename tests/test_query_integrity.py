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


if __name__ == "__main__":
    unittest.main()
